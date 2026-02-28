
from datetime import time as time_obj
import time
import logging
from src.kite_client import KiteWrapper
from src.trade_manager import TradeManager
from src.strategies.iron_fly import IronFlyStrategy
from src.strategies.momentum_buy import MomentumBuyStrategy

import os
from datetime import datetime

class NoMTMFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Strategy MTM:" in msg:
            return False
        if "Trailing SL adjusted" in msg:
            return False
        if "Trailing SL Updated" in msg:
            return False
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
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
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
EXPIRY_STAMP = "26310" # Update this to current expiry, e.g., 23N02 for weekly or 23OCT for monthly
QUANTITY = 65 # 1 Lot for Iron Fly
HEDGE_DIST = 500
SL_MTM = 2000
START_TIME = time_obj(9, 18) # 9:18 AM
END_TIME = time_obj(15, 20) # 3:20 PM
IRONFLY_PROFIT_TARGET = 1600

# Momentum Strategy Config
MOMENTUM_CANDLE_SIZE = 30 # Default, now dynamic max(40, ATR14)
MOMENTUM_INTERVAL = "5minute"
MOMENTUM_QUANTITY = 130 # 2 Lot
MOMENTUM_PROFIT_TARGET = 650

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
        end_time=END_TIME
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
        profit_target=MOMENTUM_PROFIT_TARGET
    )

    logger.info(f"Strategies Initialized: Iron Fly & Momentum Buy on {SYMBOL}")
    logger.info("Application Initialized. Starting Main Loop...")
    
    try:
        while True:
            # Run Strategy Logic
            iron_fly.on_tick()
            momentum_buy.on_tick()
            
            # Sleep to simulate tick interval (e.g., 1 second)
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping Application...")

if __name__ == "__main__":
    main()
