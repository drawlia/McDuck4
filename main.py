
from datetime import time as time_obj
import time
import logging
from src.kite_client import KiteWrapper
from src.trade_manager import TradeManager
from src.strategies.iron_fly import IronFlyStrategy
from src.strategies.momentum_buy import MomentumBuyStrategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
SYMBOL = "NIFTY"
EXPIRY_STAMP = "26FEB" # Update this to current expiry, e.g., 23N02 for weekly or 23OCT for monthly
QUANTITY = 65 # 1 Lot for Iron Fly
HEDGE_DIST = 500
SL_MTM = 2000
START_TIME = time_obj(9, 18) # 9:18 AM
END_TIME = time_obj(15, 20) # 3:20 PM

# Momentum Strategy Config
MOMENTUM_CANDLE_SIZE = 50
MOMENTUM_INTERVAL = "15minute"
MOMENTUM_QUANTITY = 65 # 1 Lot

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
        end_time=END_TIME
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
