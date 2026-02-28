
import logging
from src.strategies.base import BaseStrategy

import datetime

logger = logging.getLogger(__name__)

class IronFlyStrategy(BaseStrategy):
    def __init__(self, kite_client, trade_manager, expiry_stamp, hedge_dist=200, quantity=50, sl_mtm=2000, target_mtm=None, start_time=None, end_time=None):
        """
        expiry_stamp: e.g. "23OCT" for monthly or "23N02" for weekly.
                      Format: NIFTY<expiry_stamp><strike><CE/PE>
        hedge_dist: Distance of OTM buys from ATM (default 200).
        quantity: Lot size * Lots (default 50 for 1 lot).
        sl_mtm: Combined MTM Stop Loss (absolute value).
        start_time: datetime.time object for start time (e.g., 09:18)
        end_time: datetime.time object for auto-exit time (e.g., 15:20)
        """
        super().__init__(kite_client, trade_manager)
        self.expiry_stamp = expiry_stamp
        self.hedge_dist = hedge_dist
        self.quantity = quantity
        self.sl_mtm = -abs(sl_mtm) # Negative value for loss threshold
        self.target_mtm = target_mtm
        self.start_time = start_time
        self.end_time = end_time
        
        self.state = "INIT" # INIT, OPEN, EXITED
        self.legs = [] # List of {symbol, side: BUY/SELL, entry_price, quantity}
        self.atm_strike = None
        self.max_mtm_reached = -999999
        self.trailing_sl_value = self.sl_mtm # Starts at initial SL

        # Restore positions from CSV if any
        self.restore_state()

    def restore_state(self):
        try:
            open_trades = self.trade_manager.get_open_trades_from_csv()
            if "IronFly" in open_trades:
                logger.info("Restoring IronFly positions from log...")
                self.legs = open_trades["IronFly"]
                self.state = "OPEN"
                # Approximate max_mtm from current if we were to be precise, 
                # but for now we just resume monitoring.
        except Exception as e:
            logger.error(f"Error restoring IronFly state: {e}")

    def get_strike_symbol(self, strike, option_type):
        # Example: NIFTY23OCT19500CE
        return f"NIFTY{self.expiry_stamp}{int(strike)}{option_type}"

    def on_tick(self):
        if self.state == "EXITED":
            return

        now = datetime.datetime.now().time()

        # 0. AUTO-EXIT LOGIC
        if self.end_time and now >= self.end_time:
            if self.state == "OPEN":
                logger.info(f"End time {self.end_time} reached. Exiting all positions.")
                self.exit_all_positions()
            else:
                self.state = "EXITED" # Prevent any more activity
            return

        # 1. ENTRY LOGIC
        if self.state == "INIT":
            # Check Start Time
            if self.start_time:
                if now < self.start_time:
                    logger.info(f"Waiting for start time {self.start_time}. Current: {now}")
                    return

            # Get Spot Price from NSE
            spot_symbol = "NSE:NIFTY 50"
            quote = self.kite_client.get_quote([spot_symbol])
            if not quote or spot_symbol not in quote:
                logger.error(f"Could not fetch quote for {spot_symbol}")
                return

            ltp = quote[spot_symbol]["last_price"]
            self.atm_strike = round(ltp / 50) * 50
            logger.info(f"NIFTY Spot: {ltp} -> ATM Strike: {self.atm_strike}")

            self.enter_iron_fly()
            self.state = "OPEN"
            return

        # 2. MONITORING LOGIC
        if self.state == "OPEN":
            self.monitor_positions()

    def enter_iron_fly(self):
        # 1. Define Strikes
        atm_ce = self.get_strike_symbol(self.atm_strike, "CE")
        atm_pe = self.get_strike_symbol(self.atm_strike, "PE")
        hedge_ce = self.get_strike_symbol(self.atm_strike + self.hedge_dist, "CE")
        hedge_pe = self.get_strike_symbol(self.atm_strike - self.hedge_dist, "PE")

        # 2. Prepare Order Requests
        # Standard Iron Fly: Buy OTM Wings, Sell ATM Body
        orders = [
            {"symbol": hedge_ce, "side": "BUY"},
            {"symbol": hedge_pe, "side": "BUY"},
            {"symbol": atm_ce, "side": "SELL"},
            {"symbol": atm_pe, "side": "SELL"},
        ]

        logger.info(f"Entering Iron Fly at ATM {self.atm_strike}")

        # 3. Execute Orders
        # Note: In real trading, you might want to place BUY orders first for margin benefit.
        for order in orders:
            order_id = self.trade_manager.place_order(
                symbol=order["symbol"],
                exchange="NFO",
                transaction_type=order["side"],
                quantity=self.quantity,
                order_type="MARKET",
                product="MIS", # Intraday
                tag="IronFly"
            )
            
            if order_id:
                # We record the trade. For accurate P&L, we need execution price.
                # Here we will fetch LTP immediately after to approximate entry price.
                # In production, we should wait for order update via WebSocket or Postback.
                quote = self.kite_client.get_quote([f"NFO:{order['symbol']}"])
                entry_price = 0
                if quote and f"NFO:{order['symbol']}" in quote:
                    entry_price = quote[f"NFO:{order['symbol']}"]["last_price"]
                
                self.legs.append({
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "quantity": self.quantity,
                    "entry_price": entry_price,
                    "order_id": order_id
                })
                logger.info(f"Entered {order['side']} {order['symbol']} at approx {entry_price}")

    def monitor_positions(self):
        if not self.legs:
            return

        # 1. Get Current Prices
        symbols = [f"NFO:{leg['symbol']}" for leg in self.legs]
        quotes = self.kite_client.get_quote(symbols)
        if not quotes:
            return

        total_mtm = 0
        
        # 2. Calculate Combined MTM
        for leg in self.legs:
            key = f"NFO:{leg['symbol']}"
            if key not in quotes:
                continue
            
            ltp = quotes[key]["last_price"]
            entry = leg["entry_price"]
            qty = leg["quantity"]

            if leg["side"] == "BUY":
                leg_mtm = (ltp - entry) * qty
            else: # SELL
                leg_mtm = (entry - ltp) * qty
            
            total_mtm += leg_mtm

        logger.info(f"Strategy MTM: {total_mtm:.2f} | Max MTM: {self.max_mtm_reached:.2f} | Trailing SL: {self.trailing_sl_value:.2f}")

        # 3. Update Max MTM
        if total_mtm > self.max_mtm_reached:
            self.max_mtm_reached = total_mtm
            self.update_trailing_sl(total_mtm)

        # 4. Check Exit Conditions
        if total_mtm <= self.trailing_sl_value:
            logger.info(f"Trailing SL Hit! MTM: {total_mtm} <= SL: {self.trailing_sl_value}")
            self.exit_all_positions()
        
        elif self.target_mtm and total_mtm >= self.target_mtm:
            logger.info(f"Target Hit! MTM: {total_mtm} >= Target: {self.target_mtm}")
            self.exit_all_positions()

    def update_trailing_sl(self, current_mtm):
        # Logic: 
        # If MTM > 1000, Trail SL to Cost (0)
        # If MTM > 2000, Trail SL to 1000
        # Example: For every 1000 profit, move SL up by 1000
        
        # Simple Logic: Trailing SL is continuously (Max MTM - 2000)
        # But initially, SL is -2000.
        # If Max MTM is 500, SL is -1500 (locked in some loss reduction).
        # If Max MTM is 3000, SL is 1000 (locked in profit).
        
        # However, we only move SL UP, never down.
        # Initial SL = -2000 (self.sl_mtm)
        
        # Let's say we want to trail such that we risk only X amount from peak.
        # Let's use `sl_mtm` magnitude as the "trailing buffer".
        
        buffer = abs(self.sl_mtm) 
        new_sl = self.max_mtm_reached - buffer
        
        # Ensure we don't move SL down (although max_mtm only goes up, so new_sl usually goes up)
        # But purely, new_sl should be > old_sl
        if new_sl > self.trailing_sl_value:
            self.trailing_sl_value = new_sl
            logger.info(f"Trailing SL adjusted to {self.trailing_sl_value}")

    def exit_all_positions(self):
        logger.info("Exiting all positions...")
        
        # Separate legs into Buy and Sell orders for exit
        # Buying back shorts first, then selling longs
        buy_orders = []
        sell_orders = []

        for leg in self.legs:
            exit_side = "SELL" if leg["side"] == "BUY" else "BUY"
            order_params = {
                "symbol": leg["symbol"],
                "exchange": "NFO",
                "transaction_type": exit_side,
                "quantity": leg["quantity"],
                "order_type": "MARKET",
                "product": "MIS",
                "tag": "IronFly"
            }
            if exit_side == "BUY":
                buy_orders.append(order_params)
            else:
                sell_orders.append(order_params)

        # 1. Execute BUYs first
        for order in buy_orders:
            self.trade_manager.place_order(**order)
            logger.info(f"Exit (Cover): BUY {order['symbol']}")

        # 2. Execute SELLs second
        for order in sell_orders:
            self.trade_manager.place_order(**order)
            logger.info(f"Exit (Close): SELL {order['symbol']}")
        
        self.state = "EXITED"
        logger.info(f"Iron Fly Strategy Exited. Final MTM (approx peak): {self.max_mtm_reached}")
