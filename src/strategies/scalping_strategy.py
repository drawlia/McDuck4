import logging
import datetime
from src.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class ScalpingStrategy(BaseStrategy):
    def __init__(
        self,
        kite_client,
        trade_manager,
        expiry_stamp,
        start_time=None,
        interval="5minute",
        quantity=65,
        end_time=None,
        profit_target=3000,
        trailing_points=30,
        small_candle_threshold=15,  # Max body size to consider a candle "small"
        min_candles=3,  # Minimum consecutive small candles required
    ):
        """
        Scalping Strategy: Detect consecutive small candles in one direction.

        Args:
            expiry_stamp: e.g. "23OCT"
            start_time: datetime.time object for allowing new entries (e.g., 09:45)
            interval: Candle interval str (default "5minute")
            quantity: Quantity to trade
            end_time: datetime.time object for auto-exit time (e.g., 15:20)
            profit_target: MTM profit target to exit trade (default 3000)
            trailing_points: Points to trail SL by (default 30)
            small_candle_threshold: Max body size to consider a candle "small"
            min_candles: Minimum consecutive small candles in one direction
        """
        super().__init__(kite_client, trade_manager)
        self.expiry_stamp = expiry_stamp
        self.start_time = start_time
        self.interval = interval
        self.quantity = quantity
        self.end_time = end_time
        self.profit_target = profit_target
        self.trailing_points = trailing_points
        self.small_candle_threshold = small_candle_threshold
        self.min_candles = min_candles

        self.symbol = "NSE:NIFTY 50"
        self.instrument_token = 256265  # Token for Nifty 50

        self.state = "IDLE"  # IDLE, IN_TRADE, EXITED
        self.current_trade = None  # {order_id, symbol, entry_price, sl_price, type}
        self.last_candle_time = None
        self.last_check_minute = -1

        # Restore positions from CSV if any
        self.restore_state()

    def restore_state(self):
        try:
            open_trades = self.trade_manager.get_open_trades_from_csv()
            if "ScalpingStrategy" in open_trades and open_trades["ScalpingStrategy"]:
                logger.info("Restoring Scalping position from log...")
                trade_data = open_trades["ScalpingStrategy"][0]
                self.current_trade = {
                    "symbol": trade_data["symbol"],
                    "order_id": "RESTORED",
                    "entry_price": trade_data["entry_price"],
                    "sl_price": trade_data["entry_price"] - self.trailing_points,
                    "mtm_sl": -self.trailing_points * trade_data["quantity"],
                    "initial_mtm_risk": self.trailing_points
                    * trade_data["quantity"],
                    "max_mtm_reached": 0,
                    "quantity": trade_data["quantity"],
                    "highest_ltp": trade_data["entry_price"],
                }
                self.state = "IN_TRADE"
        except Exception as e:
            logger.error(f"Error restoring Scalping state: {e}")

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
            if self.start_time and now < self.start_time:
                return

            # Check if new trades cutoff time has been reached (14:50)
            new_trades_cutoff = datetime.time(14, 50)
            if now >= new_trades_cutoff:
                logger.info(
                    f"New trades cutoff time {new_trades_cutoff} reached. No new entries allowed."
                )
                self.state = "EXITED"
                return

            # Only check at candle boundaries (e.g., every 5 minutes)
            now_dt = datetime.datetime.now()
            if now_dt.minute % 5 == 0 and now_dt.second >= 10:
                if now_dt.minute != self.last_check_minute:
                    self.check_entry()
                    self.last_check_minute = now_dt.minute

    def check_entry(self):
        # Check overall profit threshold
        overall_profit = self.trade_manager.calculate_overall_profit()
        if overall_profit > 0:
            logger.info(f"Scalping: Current overall profit: {overall_profit:.2f}")

        # Fetch historical data
        now = datetime.datetime.now()
        from_date = now - datetime.timedelta(days=2)
        to_date = now

        data = self.kite_client.get_historical_data(
            self.instrument_token, from_date, to_date, self.interval
        )

        if not data or len(data) < self.min_candles + 1:
            logger.warning(
                f"Insufficient data for Scalping check. Need {self.min_candles + 1} candles, got {len(data) if data else 0}"
            )
            return

        # Use data[:-1] as it might contain incomplete current candle
        completed_candles = data[:-1]
        last_candles = completed_candles[-self.min_candles :]

        if len(last_candles) < self.min_candles:
            return

        # Get last candle time to avoid reprocessing
        last_candle_time = completed_candles[-1]["date"]
        if self.last_candle_time == last_candle_time:
            return

        self.last_candle_time = last_candle_time

        # Check for pattern: consecutive small candles in one direction
        pattern_result = self.check_small_candle_pattern(last_candles)

        if pattern_result:
            direction, avg_high, avg_low, entry_price = pattern_result
            self.enter_trade(direction, entry_price, avg_high, avg_low)

    def check_small_candle_pattern(self, candles):
        """
        Check if candles form a small candle pattern.
        Returns: (direction, avg_high, avg_low, spot_price) or None

        Direction: 'BUY_CE' for uptrend, 'BUY_PE' for downtrend
        """
        # Candle properties
        bodies = []
        highs = []
        lows = []
        closes = []
        directions = []  # 1 for green, -1 for red

        for candle in candles:
            open_p = candle["open"]
            close_p = candle["close"]
            high_p = candle["high"]
            low_p = candle["low"]

            body_size = abs(close_p - open_p)
            bodies.append(body_size)
            highs.append(high_p)
            lows.append(low_p)
            closes.append(close_p)

            # Determine direction (1 for green/up, -1 for red/down)
            direction = 1 if close_p > open_p else -1
            directions.append(direction)

        # Check 1: All candles are "small"
        if any(body > self.small_candle_threshold for body in bodies):
            logger.info(
                f"Scalping: Not all candles are small. Bodies: {bodies}, Threshold: {self.small_candle_threshold}"
            )
            return None

        # Check 2: All candles move in the same direction (all green or all red)
        if not (all(d > 0 for d in directions) or all(d < 0 for d in directions)):
            logger.info(
                f"Scalping: Not all candles in same direction. Directions: {directions}"
            )
            return None

        # Pattern found!
        is_uptrend = all(d > 0 for d in directions)
        pattern_direction = "BUY_CE" if is_uptrend else "BUY_PE"

        # Calculate SL level: Use the extreme point across all candles
        avg_high = max(highs)
        avg_low = min(lows)
        entry_price = closes[-1]  # Entry at close of last candle

        logger.info(
            f"Scalping Pattern Found! Direction: {pattern_direction}, "
            f"Bodies: {bodies}, Entry: {entry_price}, High: {avg_high}, Low: {avg_low}"
        )

        return (pattern_direction, avg_high, avg_low, entry_price)

    def enter_trade(self, trade_type, entry_price, avg_high, avg_low):
        """
        Enter trade based on scalping signal.
        trade_type: 'BUY_CE' or 'BUY_PE'
        entry_price: Spot price at entry
        avg_high: Highest point in the pattern
        avg_low: Lowest point in the pattern
        """
        atm_strike = round(entry_price / 50) * 50
        option_type = "CE" if trade_type == "BUY_CE" else "PE"
        symbol = self.get_strike_symbol(atm_strike, option_type)

        # Calculate SL based on candle extremes
        # For BUY_CE: SL is the difference between entry and the low
        # For BUY_PE: SL is the difference between entry and the high
        if trade_type == "BUY_CE":
            sl_level = avg_low
            sl_distance = entry_price - avg_low
        else:
            sl_level = avg_high
            sl_distance = avg_high - entry_price

        logger.info(
            f"Scalping Signal! {trade_type} {symbol}. Entry Spot: {entry_price}, SL Level: {sl_level}, SL Distance: {sl_distance}"
        )

        order_id = self.trade_manager.place_order(
            symbol=symbol,
            exchange="NFO",
            transaction_type="BUY",
            quantity=self.quantity,
            order_type="MARKET",
            product="MIS",
            tag="ScalpingStrategy",
        )

        if order_id:
            # Get entry price of option
            quote = self.kite_client.get_quote([f"NFO:{symbol}"])
            entry_option_price = 0
            if quote and f"NFO:{symbol}" in quote:
                entry_option_price = quote[f"NFO:{symbol}"]["last_price"]

            # Set initial SL for the option based on candle distance
            # We'll trail it from the entry price
            initial_sl = entry_option_price - sl_distance
            initial_mtm_sl = (initial_sl - entry_option_price) * self.quantity

            self.current_trade = {
                "symbol": symbol,
                "order_id": order_id,
                "entry_price": entry_option_price,
                "sl_price": initial_sl,
                "mtm_sl": initial_mtm_sl,
                "initial_mtm_risk": abs(initial_mtm_sl),
                "max_mtm_reached": 0,
                "quantity": self.quantity,
                "highest_ltp": entry_option_price,
                "trade_type": trade_type,
            }
            self.state = "IN_TRADE"
            logger.info(
                f"Entered Scalping {symbol} at {entry_option_price}. Initial SL: {initial_sl}, Distance: {sl_distance}"
            )

    def manage_trade(self):
        if not self.current_trade:
            return

        symbol = self.current_trade["symbol"]
        quote_key = f"NFO:{symbol}"
        quote = self.kite_client.get_quote([quote_key])

        if not quote or quote_key not in quote:
            return

        ltp = quote[quote_key]["last_price"]
        entry_price = self.current_trade["entry_price"]
        quantity = self.current_trade["quantity"]

        # 0. Check Profit Target
        current_mtm = (ltp - entry_price) * quantity

        mtm_sl = self.current_trade.get("mtm_sl")
        if mtm_sl is None:
            mtm_sl = (self.current_trade["sl_price"] - entry_price) * quantity
            self.current_trade["mtm_sl"] = mtm_sl

        initial_mtm_risk = self.current_trade.get("initial_mtm_risk", abs(mtm_sl))
        max_mtm_reached = self.current_trade.get("max_mtm_reached", 0)

        if current_mtm > max_mtm_reached:
            self.current_trade["max_mtm_reached"] = current_mtm
            new_mtm_sl = current_mtm - initial_mtm_risk

            if new_mtm_sl > mtm_sl:
                self.current_trade["mtm_sl"] = new_mtm_sl
                mtm_sl = new_mtm_sl
                logger.info(
                    f"Scalping MTM SL Updated for {symbol}: MTM SL={mtm_sl:.2f}, "
                    f"Max MTM={current_mtm:.2f}"
                )

        sl_price = entry_price + (mtm_sl / quantity)
        self.current_trade["sl_price"] = sl_price

        logger.info(
            f"Strategy MTM: Scalping ({symbol}): {current_mtm:.2f} | "
            f"Max MTM: {self.current_trade['max_mtm_reached']:.2f} | "
            f"MTM SL: {mtm_sl:.2f} | LTP: {ltp} | SL Price: {sl_price:.2f}"
        )

        if current_mtm >= self.profit_target:
            logger.info(
                f"Profit Target Hit for {symbol}! MTM: {current_mtm} >= {self.profit_target}. Exiting..."
            )
            self.exit_trade()
            return

        # 1. Check SL Hit
        if current_mtm <= mtm_sl:
            logger.info(
                f"Scalping MTM SL Hit for {symbol}. MTM={current_mtm:.2f} <= SL={mtm_sl:.2f}. Exiting..."
            )
            self.exit_trade()
            return

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
            tag="ScalpingStrategy",
        )

        self.current_trade = None
        self.state = "IDLE"
        logger.info("Scalping Trade Exited.")
