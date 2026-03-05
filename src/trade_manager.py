import logging
import time
import csv
import os
import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TradeManager:
    def __init__(self, kite_client, base_log_dir="logs"):
        self.kite_client = kite_client
        self.active_trades = (
            []
        )  # List of dictionaries: {symbol, order_id, entry_price, sl_price, quantity, trail_gap}

        # Create daily logging directory
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        self.log_dir = os.path.join(base_log_dir, today_str)
        os.makedirs(self.log_dir, exist_ok=True)

        self.log_file = os.path.join(self.log_dir, "trades.csv")

        # Initialize log file with headers if it doesn't exist
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "Timestamp",
                        "Strategy",
                        "Symbol",
                        "Side",
                        "Quantity",
                        "Price",
                        "OrderID",
                    ]
                )

    def _log_to_csv(self, strategy_name, symbol, side, qty, price, order_id):
        """
        Appends a trade record to the CSV file.
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [timestamp, strategy_name, symbol, side, qty, price, order_id]
                )
            logger.info(
                f"Trade logged to {self.log_file}: {strategy_name} {side} {symbol}"
            )
        except Exception as e:
            logger.error(f"Error logging to CSV: {e}")

    def get_open_trades_from_csv(self):
        """
        Parses the today's CSV log and returns a list of currently open positions.
        Returns: { 'StrategyName': [{'symbol': '...', 'quantity': ..., 'entry_price': ...}] }
        """
        if not os.path.exists(self.log_file):
            return {}

        open_positions = {}  # (strategy, symbol) -> {'qty': ..., 'price': ... (avg)}
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        try:
            with open(self.log_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Only process today's trades
                    timestamp = row["Timestamp"][
                        :10
                    ]  # Extract YYYY-MM-DD from timestamp
                    if timestamp != today_str:
                        continue

                    strategy = row["Strategy"]
                    symbol = row["Symbol"]
                    side = row["Side"]
                    qty = int(row["Quantity"])
                    price = float(row["Price"])

                    key = (strategy, symbol)
                    if key not in open_positions:
                        open_positions[key] = {"qty": 0, "price": 0}

                    if side == "BUY":
                        # Simplistic average price tracking for entry
                        total_cost = (
                            open_positions[key]["qty"] * open_positions[key]["price"]
                        ) + (qty * price)
                        open_positions[key]["qty"] += qty
                        if open_positions[key]["qty"] > 0:
                            open_positions[key]["price"] = (
                                total_cost / open_positions[key]["qty"]
                            )
                    else:  # SELL
                        open_positions[key]["qty"] -= qty

            # Refined logic: Net Quantity.
            # If Strategy is IronFly, initial orders are SELL (Short), so negative is Open.
            # If Strategy is MomentumBuy, initial orders are BUY (Long), so positive is Open.

            # Let's just return all non-zero net positions grouped by strategy.
            result = {}
            for (strategy, symbol), data in open_positions.items():
                if data["qty"] != 0:
                    if strategy not in result:
                        result[strategy] = []
                    result[strategy].append(
                        {
                            "symbol": symbol,
                            "quantity": abs(data["qty"]),
                            "entry_price": data["price"],
                            "side": "SELL" if data["qty"] < 0 else "BUY",
                        }
                    )

            return result
        except Exception as e:
            logger.error(f"Error reading open trades from CSV: {e}")
            return {}

    def place_order(
        self,
        symbol,
        transaction_type,
        quantity,
        order_type="MARKET",
        exchange="NSE",
        price=None,
        trigger_price=None,
        variety="regular",
        product="MIS",
        tag=None,
    ):
        """
        Generic method to place an order.
        """
        order_id = self.kite_client.place_order(
            tradingsymbol=symbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            product=product,
            price=price,
            trigger_price=trigger_price,
            variety=variety,
        )

        if order_id:
            logger.info(
                f"Order Placed: {transaction_type} {symbol} Qty={quantity} ID={order_id}"
            )

            # Log the trade
            # In MARKET orders, 'price' might be None, so we might need LTP for the log
            log_price = price if price else 0
            if not log_price:
                # Try to fetch LTP for logging purposes if price is None
                try:
                    quote = self.kite_client.get_quote([f"{exchange}:{symbol}"])
                    if quote and f"{exchange}:{symbol}" in quote:
                        log_price = quote[f"{exchange}:{symbol}"]["last_price"]
                except:
                    pass

            self._log_to_csv(
                tag if tag else "Unknown",
                symbol,
                transaction_type,
                quantity,
                log_price,
                order_id,
            )
            return order_id
        return None

    def place_buy_order(self, symbol, quantity, price, sl_price, trail_gap=None):
        """
        Places a Limit Buy order and tracks it for trailing SL.
        """
        # Place the main entry order
        order_id = self.place_order(
            symbol=symbol,
            transaction_type="BUY",
            quantity=quantity,
            order_type="LIMIT",
            price=price,
        )

        if order_id:  # Only track if order was successfully placed
            # In a real scenario, we wait for the order to be FILLED before tracking it.
            # For this simple app, we assume immediate fill or just track the intent.
            trade = {
                "symbol": symbol,
                "order_id": order_id,
                "entry_price": price,
                "sl_price": sl_price,
                "quantity": quantity,
                "trail_gap": trail_gap,
                "status": "OPEN",
            }
            self.active_trades.append(trade)
            logger.info(f"Tracking trade for {symbol} with SL: {sl_price}")

        return order_id

    def check_and_trail_sl(self):
        """
        Polls current prices and adjusts SL if price moves in favor.
        """
        if not self.active_trades:
            return

        symbols = [t["symbol"] for t in self.active_trades]
        # Adding NSE: prefix
        api_symbols = [f"NSE:{s}" for s in symbols]

        quotes = self.kite_client.get_quote(api_symbols)

        for trade in self.active_trades:
            symbol = trade["symbol"]
            api_symbol = f"NSE:{symbol}"

            if api_symbol not in quotes:
                continue

            ltp = quotes[api_symbol]["last_price"]
            sl_price = trade["sl_price"]
            trail_gap = trade["trail_gap"]

            logger.info(f"Monitoring {symbol}: LTP={ltp}, SL={sl_price}")

            # Check for Stoploss Hit
            if ltp <= sl_price:
                logger.warning(f"Stoploss HIT for {symbol} at {ltp}. Exiting...")
                self.exit_trade(trade, ltp)
                continue

            # Trailing Logic
            if trail_gap:
                # If LTP moves up, we want to maintain the gap.
                # New potential SL is LTP - trail_gap
                # We only move SL UP for Long trades.
                potential_new_sl = ltp - trail_gap
                if potential_new_sl > sl_price:
                    trade["sl_price"] = potential_new_sl
                    logger.info(
                        f"Trailing SL Updated for {symbol}: Old={sl_price}, New={trade['sl_price']}"
                    )

    def exit_trade(self, trade, exit_price=None):
        """
        Exits the trade (sells position).
        """
        # Close the position
        order_id = self.place_order(
            symbol=trade["symbol"],
            transaction_type="SELL",  # Assuming long exit
            quantity=trade["quantity"],
            order_type="MARKET",
        )

        if order_id:
            logger.info(f"Exit Order Placed for {trade['symbol']} at Market")
            if trade in self.active_trades:
                self.active_trades.remove(trade)
