
import logging
import datetime
from src.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

class MomentumBuyStrategy(BaseStrategy):
    def __init__(self, kite_client, trade_manager, expiry_stamp, candle_size=50, interval="15minute", trailing_points=20, quantity=50, end_time=None):
        """
        expiry_stamp: e.g. "23OCT"
        candle_size: Minimum points difference between Open and Close.
        interval: Candle interval str (default "15minute")
        trailing_points: Points to trail SL by
        end_time: datetime.time object for auto-exit time (e.g., 15:20)
        """
        super().__init__(kite_client, trade_manager)
        self.expiry_stamp = expiry_stamp
        self.candle_size = candle_size
        self.interval = interval
        self.trailing_points = trailing_points
        self.quantity = quantity
        self.end_time = end_time
        
        self.symbol = "NSE:NIFTY 50"
        self.instrument_token = 256265 # Token for Nifty 50. Ideally fetch this dynamically.
        
        self.state = "IDLE" # IDLE, IN_TRADE
        self.current_trade = None # {order_id, symbol, entry_price, sl_price, type}
        self.last_candle_time = None
        self.last_check_minute = -1 # Track minute to avoid multiple checks in same minute boundary

    def get_strike_symbol(self, strike, option_type):
        # Example: NIFTY23OCT19500CE
        return f"NIFTY{self.expiry_stamp}{int(strike)}{option_type}"

    def on_tick(self):
        now = datetime.datetime.now().time()

        # 0. AUTO-EXIT LOGIC
        if self.end_time and now >= self.end_time:
            if self.state == "IN_TRADE":
                logger.info(f"End time {self.end_time} reached. Exiting trade.")
                self.exit_trade()
            elif self.state != "EXITED":
                self.state = "EXITED"
                logger.info(f"End time {self.end_time} reached. Stopping strategy.")
            return

        if self.state == "EXITED":
            return

        # 1. Manage Active Trade
        if self.state == "IN_TRADE":
            self.manage_trade()
            return

        # 2. Check for New Entry
        if self.state == "IDLE":
            # Only check at 15-minute boundaries (e.g., 00, 15, 30, 45)
            # We add a small delay (10s) to ensure the candle is formed on the server
            now_dt = datetime.datetime.now()
            if now_dt.minute % 15 == 0 and now_dt.second >= 10:
                if now_dt.minute != self.last_check_minute:
                    self.check_entry()
                    self.last_check_minute = now_dt.minute

    def check_entry(self):
        # Calculate time range for last completed candle
        now = datetime.datetime.now()
        # End time should be now, start time should be enough to get last few candles
        from_date = now - datetime.timedelta(minutes=60)
        to_date = now

        # Fetch historical data
        # Note: We hardcoded token 256265 for Nifty 50. 
        # In prod, we should map 'NSE:NIFTY 50' to token via instrument dump.
        data = self.kite_client.get_historical_data(self.instrument_token, from_date, to_date, self.interval)
        
        if not data:
            return

        last_candle = data[-1]
        candle_time = last_candle['date']
        
        # Ensure we only process a candle once
        if self.last_candle_time == candle_time:
            return

        self.last_candle_time = candle_time
        
        open_p = last_candle['open']
        close_p = last_candle['close']
        high_p = last_candle['high']
        low_p = last_candle['low']
        
        body_size = abs(close_p - open_p)
        
        logger.info(f"Momentum Check: Time={candle_time}, O={open_p}, C={close_p}, Size={body_size}")

        if body_size >= self.candle_size:
            # Check Direction and Momentum Strength
            
            # Green Candle
            if close_p > open_p:
                # Momentum Check: Close near High, Open near Low (Strong body)
                # Let's say wicks should be small relative to body or just pure body check
                # User asked: open is high/ low, and cloase is low/ high respectively
                # Wait, for GREEN: Open should be Low, Close should be High.
                # For RED: Open should be High, Close should be Low.
                
                # Allow some buffer (e.g. 10% of body size)
                buffer = body_size * 0.2 
                is_strong_green = (open_p - low_p <= buffer) and (high_p - close_p <= buffer)
                
                if is_strong_green:
                    self.enter_trade("BUY_CE", close_p, low_p) # SL at Low of candle

            # Red Candle
            elif open_p > close_p:
                # Strong Red
                buffer = body_size * 0.2
                is_strong_red = (high_p - open_p <= buffer) and (close_p - low_p <= buffer)
                
                if is_strong_red:
                    self.enter_trade("BUY_PE", close_p, high_p) # SL at High of candle

    def enter_trade(self, trade_type, spot_price, sl_level):
        atm_strike = round(spot_price / 50) * 50
        option_type = "CE" if trade_type == "BUY_CE" else "PE"
        symbol = self.get_strike_symbol(atm_strike, option_type)
        
        logger.info(f"Momentum Signal! {trade_type} {symbol}. Spot: {spot_price}, SL Level: {sl_level}")

        order_id = self.trade_manager.place_order(
            symbol=symbol,
            exchange="NFO",
            transaction_type="BUY",
            quantity=self.quantity,
            order_type="MARKET",
            product="MIS",
            tag="MomentumBuy"
        )

        if order_id:
            # We need to track the OPTION PRICE for trailing SL, not the Spot SL blindly.
            # But the strategy says "trailing stoploss".
            # Usually we trail the option premium.
            # Let's get entry price of option.
            quote = self.kite_client.get_quote([f"NFO:{symbol}"])
            entry_price = 0
            if quote and f"NFO:{symbol}" in quote:
                entry_price = quote[f"NFO:{symbol}"]["last_price"]
            
            # Initial SL for Option:
            # Since we based signal on Spot Candle, implementing precise Spot SL on Option is triggered by Spot Price usually.
            # BUT, standard practice for simple algo: Trail Option Premium.
            # Let's set initial SL at X points below entry.
            # Or use the user requirement: "buy ATM... with trailing stoploss"
            # I will implement Point-based trailing on the Option Premium.
            
            initial_sl = entry_price - 20 # Arbitrary or calculated?
            # User didn't specify SL amount, just "trailing stoploss". 
            # I'll use `self.trailing_points` (default 20) as initial risk.
            initial_sl = entry_price - self.trailing_points

            self.current_trade = {
                "symbol": symbol,
                "order_id": order_id,
                "entry_price": entry_price,
                "sl_price": initial_sl,
                "quantity": self.quantity,
                "highest_ltp": entry_price
            }
            self.state = "IN_TRADE"
            logger.info(f"Entered {symbol} at {entry_price}. Initial SL: {initial_sl}")

    def manage_trade(self):
        if not self.current_trade:
            return

        symbol = self.current_trade["symbol"]
        quote_key = f"NFO:{symbol}"
        quote = self.kite_client.get_quote([quote_key])
        
        if not quote or quote_key not in quote:
            return

        ltp = quote[quote_key]["last_price"]
        sl_price = self.current_trade["sl_price"]
        
        # 1. Check SL Hit
        if ltp <= sl_price:
            logger.info(f"SL Hit for {symbol} at {ltp}. Exiting...")
            self.exit_trade()
            return

        # 2. Trail SL
        # Logic: If LTP moves up, drag SL up.
        # Fixed point trailing: SL = High - Trailing_Gap
        if ltp > self.current_trade["highest_ltp"]:
            self.current_trade["highest_ltp"] = ltp
            new_sl = ltp - self.trailing_points
            
            if new_sl > sl_price:
                self.current_trade["sl_price"] = new_sl
                logger.info(f"Trailing SL Updated for {symbol}: {new_sl} (LTP: {ltp})")

    def exit_trade(self):
        if not self.current_trade:
            return

        self.trade_manager.place_order(
            symbol=self.current_trade["symbol"],
            exchange="NFO",
            transaction_type="SELL",
            quantity=self.current_trade["quantity"],
            order_type="MARKET",
            product="MIS",
            tag="MomentumBuy"
        )
        
        self.current_trade = None
        self.state = "IDLE"
        logger.info("Momentum Trade Exited.")
