from src.strategies.base import BaseStrategy
import logging

logger = logging.getLogger(__name__)


class SimpleStrategy(BaseStrategy):
    def __init__(self, kite_client, trade_manager, symbol, quantity):
        super().__init__(kite_client, trade_manager)
        self.symbol = symbol
        self.quantity = quantity
        self.has_traded = False  # Simple flag to trade once for demo

    def on_tick(self):
        if self.has_traded:
            return

        # Example Logic: Just fetch quote and buy if valid
        # In real life, check indicators, etc.
        quote = self.kite_client.get_quote([f"NSE:{self.symbol}"])
        if not quote:
            return

        ltp = quote[f"NSE:{self.symbol}"]["last_price"]
        logger.info(f"Strategy {self.symbol}: LTP = {ltp}")

        # DUMMY CONDITION: Buy if price > 0 (Always enter for testing if not traded)
        if ltp > 0:
            logger.info("Signal Generated: BUY")

            # Entry Price: Last Traded Price
            entry_price = ltp
            # Stop Loss: 1% below entry
            sl_price = entry_price * 0.99
            # Trail Gap: 0.5% (If price moves up 0.5%, move SL up)
            trail_gap = entry_price * 0.005

            order_id = self.trade_manager.place_order(
                symbol=self.symbol,
                exchange="NSE",
                transaction_type="BUY",
                quantity=self.quantity,
                order_type="LIMIT",
                price=entry_price,
                product="MIS",
                tag="SimpleStrategy",
            )
            self.has_traded = True
