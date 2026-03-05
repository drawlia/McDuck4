import logging
import datetime
from src.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

class OpeningRangeBreakoutStrategy(BaseStrategy):
    def __init__(self, kite_client, trade_manager, base_symbol, instrument_token, expiry_stamp,
                 interval="5minute", orb_minutes=30, volume_mult=1.5,
                 confirm_bars=2, atr_stop_mult=1.5, end_time=None, itm_offset=100, quantity=65, profit_target=800):
        """
        base_symbol: The chart to track e.g. "NSE:NIFTY 50" or "NFO:NIFTY24MARFUT"
        instrument_token: Token for the base chart
        expiry_stamp: e.g. "26310" for the options
        itm_offset: Distance from ATM to buy ITM options
        interval: Candle interval string (default "5minute")
        orb_minutes: Number of minutes from market open to define the opening range
        volume_mult: Volume multiplier vs VolMA to confirm breakout
        confirm_bars: Number of consecutive bars required beyond ORB to confirm signal
        atr_stop_mult: Multiplier for ATR trailing stop
        end_time: datetime.time object for auto-exit time (e.g., 15:15)
        """
        super().__init__(kite_client, trade_manager)
        self.base_symbol = base_symbol
        self.instrument_token = instrument_token
        self.expiry_stamp = expiry_stamp
        self.interval = interval
        self.orb_minutes = orb_minutes
        self.volume_mult = volume_mult
        self.confirm_bars = confirm_bars
        self.atr_stop_mult = atr_stop_mult
        self.end_time = end_time
        self.itm_offset = itm_offset
        self.profit_target = profit_target

        self.state = "IDLE"  # IDLE, IN_TRADE, EXITED
        self.current_trade = None  # {order_id, option_symbol, spot_entry_price, sl_price, trade_type, quantity, max_favorable_price}
        self.quantity = quantity  # Default quantity for Options

        self.orb_high = None
        self.orb_low = None
        
        self.consecutive_long_breaks = 0
        self.consecutive_short_breaks = 0
        self.last_candle_time = None
        
        self.market_start_time = datetime.time(9, 15)

        # Assuming we only trade once per day per direction or once overall?
        # Let's assume one trade per day for ORB.
        self.has_traded_today = False

        self.restore_state()

    def get_strike_symbol(self, strike, option_type):
        return f"NIFTY{self.expiry_stamp}{int(strike)}{option_type}"

    def restore_state(self):
        try:
            open_trades = self.trade_manager.get_open_trades_from_csv()
            if "ORBStrategy" in open_trades and open_trades["ORBStrategy"]:
                logger.info("Restoring ORB position from log...")
                trade_data = open_trades["ORBStrategy"][0]
                option_symbol = trade_data["symbol"]
                trade_type = "LONG" if option_symbol.endswith("CE") else "SHORT"
                
                self.current_trade = {
                    "option_symbol": option_symbol,
                    "order_id": "RESTORED",
                    "spot_entry_price": trade_data["entry_price"], # Assuming restored data is underlying based
                    "sl_price": 0, # Dummy SL for now since we lost historical context
                    "trade_type": trade_type,
                    "quantity": trade_data["quantity"],
                    "max_favorable_price": 0,
                    "atr14_at_entry": 40,
                    "entry_premium": 0  # Missing historical premium entry point
                }
                self.state = "IN_TRADE"
                self.has_traded_today = True
        except Exception as e:
            logger.error(f"Error restoring ORB state: {e}")

    def on_tick(self):
        now = datetime.datetime.now().time()

        # 0. AUTO-EXIT LOGIC
        if self.end_time and now >= self.end_time:
            if self.state == "IN_TRADE":
                logger.info(f"End time {self.end_time} reached. Exiting trade.")
                self.exit_trade()
            elif self.state != "EXITED":
                self.state = "EXITED"
                logger.info(f"End time {self.end_time} reached. Stopping ORB strategy for the day.")
            return

        if self.state == "EXITED":
            return

        # 1. Manage Active Trade
        if self.state == "IN_TRADE":
            self.manage_trade()
            return

        # 2. Check for New Entry
        if self.state == "IDLE" and not self.has_traded_today:
            # Check market opened and ORB period is over
            now_dt = datetime.datetime.now()
            market_open_dt = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
            
            # ORB end time
            orb_end_time = market_open_dt + datetime.timedelta(minutes=self.orb_minutes)
            
            if now_dt < orb_end_time:
                return # Wait for ORB to form

            # Strategy usually checked on candle close.
            interval_mins = 5
            if self.interval == "15minute":
                interval_mins = 15
            elif self.interval == "5minute":
                interval_mins = 5

            # Simple logic: check a few seconds after the candle closes
            if now_dt.minute % interval_mins == 0 and now_dt.second >= 10:
                self.check_entry(now_dt)

    def check_entry(self, current_dt):
        # Fetch data for today to calculate ORB, VWAP, VolMA, and ATR
        market_open_dt = current_dt.replace(hour=9, minute=15, second=0, microsecond=0)
        
        # We need historical data to calculate ATR(14). So fetch data from a few days ago.
        from_date = current_dt - datetime.timedelta(days=3)
        to_date = current_dt
        
        data = self.kite_client.get_historical_data(self.instrument_token, from_date, to_date, self.interval)
        
        if not data or len(data) < 15:
            return
            
        # Get today's data only for VWAP and ORB
        todays_data = [d for d in data if d['date'].date() == current_dt.date()]
        if not todays_data:
            return

        # 1. Calculate ORB High / Low
        orb_candles_count = self.orb_minutes // 5 # Assuming 5min candles for calculation if interval is 5min
        if self.interval == "15minute":
            orb_candles_count = self.orb_minutes // 15
            
        if len(todays_data) < orb_candles_count:
            return # Haven't finished ORB candles yet
            
        orb_candles = todays_data[:orb_candles_count]
        self.orb_high = max([c['high'] for c in orb_candles])
        self.orb_low = min([c['low'] for c in orb_candles])
        
        last_candle = data[-2] # Current completed candle
        candle_time = last_candle['date']
        
        if self.last_candle_time == candle_time:
            return
            
        self.last_candle_time = candle_time
        
        # 2. Calculate daily VWAP up to the last completed candle
        cumulative_tp_vol = 0
        cumulative_vol = 0
        
        # Recalculate VWAP for today up to last_candle
        for c in todays_data:
            tp = (c['high'] + c['low'] + c['close']) / 3
            vol = c['volume']
            cumulative_tp_vol += tp * vol
            cumulative_vol += vol
            if c['date'] == candle_time:
                break
                
        vwap_t = cumulative_tp_vol / cumulative_vol if cumulative_vol > 0 else last_candle['close']
        
        # 3. Calculate VolMA (5)
        # We use the previous 5 bars for Volume MA
        vol_bars = data[-7:-2] if len(data) >= 7 else data[:-2]
        volma_t = sum([c['volume'] for c in vol_bars]) / len(vol_bars) if vol_bars else 1
        
        # 4. Calculate ATR(14)
        atr_candles = data[-16:-2]
        atr14 = sum([(c['high'] - c['low']) for c in atr_candles]) / 14 if len(atr_candles) > 0 else 50
        
        close_t = last_candle['close']
        volume_t = last_candle['volume']
        
        logger.info(f"ORB Check [{candle_time.time()}]: C={close_t}, ORB_H={self.orb_high}, ORB_L={self.orb_low}, VWAP={vwap_t:.2f}, VolMA(5)={volma_t:.2f}, Vol={volume_t}, ATR14={atr14:.2f}")

        # Signal Logic
        long_break = (close_t > self.orb_high) and (close_t > vwap_t) and (volume_t > self.volume_mult * volma_t)
        short_break = (close_t < self.orb_low) and (close_t < vwap_t) and (volume_t > self.volume_mult * volma_t)

        if long_break:
            self.consecutive_long_breaks += 1
            self.consecutive_short_breaks = 0
        elif short_break:
            self.consecutive_short_breaks += 1
            self.consecutive_long_breaks = 0
        else:
            self.consecutive_long_breaks = 0
            self.consecutive_short_breaks = 0
            
        if self.consecutive_long_breaks >= self.confirm_bars:
            self.enter_trade("LONG", close_t, atr14)
        elif self.consecutive_short_breaks >= self.confirm_bars:
            self.enter_trade("SHORT", close_t, atr14)

    def enter_trade(self, trade_type, spot_price, atr14):
        logger.info(f"ORB Signal Confirmed! {trade_type} signal at spot {spot_price}")

        # Calculate ITM Option Strike
        atm_strike = round(spot_price / 50) * 50
        if trade_type == "LONG":
            target_strike = atm_strike - self.itm_offset
            option_type = "CE"
        else:
            target_strike = atm_strike + self.itm_offset
            option_type = "PE"
            
        option_symbol = self.get_strike_symbol(target_strike, option_type)

        order_id = self.trade_manager.place_order(
            symbol=option_symbol,
            exchange="NFO",
            transaction_type="BUY",
            quantity=self.quantity,
            order_type="MARKET",
            product="MIS",
            tag="ORBStrategy"
        )
        
        if order_id:
            # We assume MARKET fill is close to current spot_price.
            # Calculate hard SL based on ATR on the SPOT chart.
            if trade_type == "LONG":
                initial_sl = spot_price - (self.atr_stop_mult * atr14)
            else:
                initial_sl = spot_price + (self.atr_stop_mult * atr14)

            # Get entry Option Premium for profit calculation
            entry_premium = 0
            quote = self.kite_client.get_quote([f"NFO:{option_symbol}"])
            if quote and f"NFO:{option_symbol}" in quote:
                entry_premium = quote[f"NFO:{option_symbol}"]["last_price"]
                
            self.current_trade = {
                "option_symbol": option_symbol,
                "order_id": order_id,
                "spot_entry_price": spot_price,
                "sl_price": initial_sl,
                "trade_type": trade_type,
                "quantity": self.quantity,
                "max_favorable_price": spot_price,
                "atr14_at_entry": atr14,  # Store for trailing calculation
                "entry_premium": entry_premium
            }
            self.state = "IN_TRADE"
            self.has_traded_today = True
            
            logger.info(f"Entered BUY {option_symbol} at spot ~{spot_price}. Initial Spot SL: {initial_sl:.2f}")

    def manage_trade(self):
        if not self.current_trade:
            return
            
        # Track the underlying chart (Future) to determine SL
        quote_key = self.base_symbol if ":" in self.base_symbol else f"NFO:{self.base_symbol}"
        option_symbol = self.current_trade["option_symbol"]
        
        quote = self.kite_client.get_quote([quote_key, f"NFO:{option_symbol}"])
        
        if not quote or quote_key not in quote:
            return
            
        spot_ltp = quote[quote_key]["last_price"]
        sl_price = self.current_trade["sl_price"]
        trade_type = self.current_trade["trade_type"]
        atr14 = self.current_trade["atr14_at_entry"]
        entry_premium = self.current_trade.get("entry_premium", 0)
        quantity = self.current_trade["quantity"]

        # 0. Check Profit Target
        if entry_premium > 0 and f"NFO:{option_symbol}" in quote:
            option_ltp = quote[f"NFO:{option_symbol}"]["last_price"]
            current_mtm = (option_ltp - entry_premium) * quantity
            if current_mtm >= self.profit_target:
                logger.info(f"Profit Target Hit for ORB! {option_symbol} MTM: {current_mtm} >= {self.profit_target}. Exiting...")
                self.exit_trade()
                return
        
        # 1. Check SL Hit
        if trade_type == "LONG" and spot_ltp <= sl_price:
            logger.info(f"SL Hit for LONG ORB (Spot: {spot_ltp} <= SL: {sl_price}). Exiting Option {option_symbol}...")
            self.exit_trade()
            return
        elif trade_type == "SHORT" and spot_ltp >= sl_price:
            logger.info(f"SL Hit for SHORT ORB (Spot: {spot_ltp} >= SL: {sl_price}). Exiting Option {option_symbol}...")
            self.exit_trade()
            return
            
        # 2. Trail SL (Step ATR Trial)
        if trade_type == "LONG":
            if spot_ltp > self.current_trade["max_favorable_price"]:
                self.current_trade["max_favorable_price"] = spot_ltp
                
                potential_new_sl = spot_ltp - (self.atr_stop_mult * atr14)
                if potential_new_sl > sl_price:
                    self.current_trade["sl_price"] = potential_new_sl
                    logger.info(f"Trailing SL Updated for LONG ORB: {potential_new_sl:.2f} (Spot LTP: {spot_ltp})")
                    
        else: # SHORT
            if spot_ltp < self.current_trade["max_favorable_price"]:
                self.current_trade["max_favorable_price"] = spot_ltp
                
                potential_new_sl = spot_ltp + (self.atr_stop_mult * atr14)
                if potential_new_sl < sl_price:
                    self.current_trade["sl_price"] = potential_new_sl
                    logger.info(f"Trailing SL Updated for SHORT ORB: {potential_new_sl:.2f} (Spot LTP: {spot_ltp})")

    def exit_trade(self):
        if not self.current_trade:
            return
            
        # We always BUY options to enter, so SELL to exit
        self.trade_manager.place_order(
            symbol=self.current_trade["option_symbol"],
            exchange="NFO",
            transaction_type="SELL",
            quantity=self.current_trade["quantity"],
            order_type="MARKET",
            product="MIS",
            tag="ORBStrategy"
        )
        
        self.current_trade = None
        self.state = "EXITED"
        logger.info("ORB Trade Exited.")

