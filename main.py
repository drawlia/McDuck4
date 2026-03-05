from datetime import time as time_obj
import time
import logging
from src.kite_client import KiteWrapper
from src.trade_manager import TradeManager
from src.strategies.iron_fly import IronFlyStrategy
from src.strategies.momentum_buy import MomentumBuyStrategy
from src.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy

import os
from datetime import datetime


class NoMTMFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Trailing SL adjusted" in msg:
            return False
        # Allow trailing SL updated logs
        return True


# Setup logging
log_dir = os.path.join("logs", datetime.now().strftime("%Y-%m-%d"))
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# File Handler
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
file_handler.addFilter(NoMTMFilter())
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# Configuration
SYMBOL = "NIFTY"
EXPIRY_STAMP = "26310"  # Update this to current expiry, e.g., 23N02 for weekly or 23OCT for monthly
QUANTITY = 65  # 1 Lot for Iron Fly
HEDGE_DIST = 500
SL_MTM = 2000
START_TIME = time_obj(9, 18)  # 9:18 AM
END_TIME = time_obj(15, 20)  # 3:20 PM
IRONFLY_PROFIT_TARGET = 1600

# Momentum Strategy Config
MOMENTUM_CANDLE_SIZE = 30  # Default, now dynamic max(40, ATR14)
MOMENTUM_INTERVAL = "5minute"
MOMENTUM_QUANTITY = 130  # 2 Lot
MOMENTUM_PROFIT_TARGET = 780

# ORB Strategy Config
ORB_BASE_SYMBOL = "NFO:NIFTY24MARFUT"  # Track future for ORB volume and signals
ORB_BASE_TOKEN = 13238786  # Update manually with actual Future Token
ORB_ITM_OFFSET = 100  # Distance to buy ITM Option (e.g., 100 pts ITM)
ORB_INTERVAL = "5minute"
ORB_MINUTES = 30
ORB_VOLUME_MULT = 1.5
ORB_CONFIRM_BARS = 1
ORB_ATR_STOP_MULT = 1.5
ORB_END_TIME = time_obj(15, 15)
ORB_PROFIT_TARGET = 1000


def main():
    logger.info("Starting KiteConnect Trading App...")

    # 1. Initialize Kite Client
    try:
        kite = KiteWrapper()
        # Run the manual login flow (check token or prompt user)
        # kite.login_flow() # Commented out to avoid blocking if token is valid? Keep it for safety.
        kite.login_flow()
    except Exception as e:
        logger.error(f"Failed to initialize Kite Client: {e}")
        return

    # 2. Initialize Trade Manager
    tm = TradeManager(kite)

    # 3. Initialize Strategies
    # A. ATM Iron Fly Strategy
    iron_fly = IronFlyStrategy(
        kite_client=kite,
        trade_manager=tm,
        expiry_stamp=EXPIRY_STAMP,
        hedge_dist=HEDGE_DIST,
        quantity=QUANTITY,
        sl_mtm=SL_MTM,
        target_mtm=IRONFLY_PROFIT_TARGET,
        start_time=START_TIME,
        end_time=END_TIME,
    )

    # B. Momentum Buy Strategy
    momentum_buy = MomentumBuyStrategy(
        kite_client=kite,
        trade_manager=tm,
        expiry_stamp=EXPIRY_STAMP,
        candle_size=MOMENTUM_CANDLE_SIZE,
        interval=MOMENTUM_INTERVAL,
        quantity=MOMENTUM_QUANTITY,
        end_time=END_TIME,
        profit_target=MOMENTUM_PROFIT_TARGET,
    )

    # C. Opening Range Breakout Strategy
    # ORB Quantity Config
    ORB_QUANTITY = 130  # 2 Lot for Options
    orb_strategy = OpeningRangeBreakoutStrategy(
        kite_client=kite,
        trade_manager=tm,
        base_symbol=ORB_BASE_SYMBOL,
        instrument_token=ORB_BASE_TOKEN,
        expiry_stamp=EXPIRY_STAMP,
        interval=ORB_INTERVAL,
        orb_minutes=ORB_MINUTES,
        volume_mult=ORB_VOLUME_MULT,
        confirm_bars=ORB_CONFIRM_BARS,
        atr_stop_mult=ORB_ATR_STOP_MULT,
        end_time=ORB_END_TIME,
        itm_offset=ORB_ITM_OFFSET,
        quantity=ORB_QUANTITY,
        profit_target=ORB_PROFIT_TARGET,
    )

    logger.info(f"Strategies Initialized: Iron Fly, Momentum Buy & ORB on {SYMBOL}")
    logger.info("Application Initialized. Starting Main Loop...")

    try:
        while True:
            # Run Strategy Logic
            iron_fly.on_tick()
            momentum_buy.on_tick()
            orb_strategy.on_tick()

            # Sleep to simulate tick interval (e.g., 1 second)
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping Application...")


if __name__ == "__main__":
    main()
