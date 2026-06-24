from datetime import time as time_obj
import time
import logging
import argparse
from getpass import getpass
from src.kite_client import KiteWrapper
from src.trade_manager import TradeManager
from src.strategies.iron_fly import IronFlyStrategy
from src.strategies.momentum_buy import MomentumBuyStrategy
from src.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.strategies.scalping_strategy import ScalpingStrategy

import os
from datetime import datetime


class NoMTMFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Trailing SL adjusted" in msg:
            return False
        if "MTM" in msg:
            return False
        # Allow trailing SL updated logs
        return True


# Setup logging
log_dir = os.path.join("logs", datetime.now().strftime("%Y-%m-%d"))
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

root_logger = logging.getLogger()
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
    handler.close()
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

EXPIRY_STAMP = "26JUN"  # Update this to current expiry, e.g., 23N02 for weekly or 23OCT for monthly
QUANTITY = 195  # 3 Lot for Iron Fly
HEDGE_DIST = 500
SL_MTM = 2000
START_TIME = time_obj(9, 18)  # 9:18 AM
END_TIME = time_obj(15, 24)  # 3:24 PM
IRONFLY_PROFIT_TARGET = 1800

# Momentum Strategy Config
MOMENTUM_CANDLE_SIZE = 20  # Default, now dynamic max(40, ATR14)
MOMENTUM_START_TIME = time_obj(9, 30)
MOMENTUM_INTERVAL = "3minute"
MOMENTUM_QUANTITY = 520  # 2 Lot



MOMENTUM_PROFIT_TARGET = 4000  # 20 points per lot target, adjust as needed


# ORB Strategy Config
ORB_BASE_SYMBOL = "NFO:NIFTY24MARFUT"  # Track future for ORB volume and signals
ORB_BASE_TOKEN = 13238786  # Update manually with actual Future Token
ORB_ITM_OFFSET = 100  # Distance to buy ITM Option (e.g., 100 pts ITM)
ORB_INTERVAL = "5minute"
ORB_MINUTES = 30
ORB_VOLUME_MULT = 1.5
ORB_CONFIRM_BARS = 2
ORB_ATR_STOP_MULT = 1.5
ORB_END_TIME = time_obj(15, 15)
ORB_PROFIT_TARGET = 1800

# Scalping Strategy Config
SCALPING_START_TIME = MOMENTUM_START_TIME
SCALPING_INTERVAL = "5minute"
SCALPING_QUANTITY = 195
SCALPING_PROFIT_TARGET = SCALPING_QUANTITY * 10
SCALPING_TRAILING_POINTS = 20
SCALPING_SMALL_CANDLE_THRESHOLD = 10  # Max body size to consider a candle "small"
SCALPING_MIN_CANDLES = 3  # Minimum consecutive small candles

# Overall Profit Threshold
OVERALL_PROFIT_THRESHOLD = 20000  # No new trades if overall profit >= 20000


def get_startup_access_token():
    parser = argparse.ArgumentParser(description="Run the KiteConnect trading app.")
    parser.add_argument(
        "--access-token",
        dest="access_token",
        help="Kite access token to use for this session.",
    )
    args = parser.parse_args()

    if args.access_token:
        return args.access_token.strip()

    token = getpass(
        "Paste Kite access token for this session "
        "(press Enter to use .env/login flow): "
    ).strip()
    return token or None


def main():
    logger.info("Starting KiteConnect Trading App...")

    # 1. Initialize Kite Client
    try:
        startup_access_token = get_startup_access_token()
        kite = KiteWrapper(access_token=startup_access_token)
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
        start_time=MOMENTUM_START_TIME,
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

    # D. Scalping Strategy
    scalping_strategy = ScalpingStrategy(
        kite_client=kite,
        trade_manager=tm,
        expiry_stamp=EXPIRY_STAMP,
        start_time=SCALPING_START_TIME,
        interval=SCALPING_INTERVAL,
        quantity=SCALPING_QUANTITY,
        end_time=END_TIME,
        profit_target=SCALPING_PROFIT_TARGET,
        trailing_points=SCALPING_TRAILING_POINTS,
        small_candle_threshold=SCALPING_SMALL_CANDLE_THRESHOLD,
        min_candles=SCALPING_MIN_CANDLES,
    )

    logger.info(
        f"Strategies Initialized: Iron Fly, Momentum Buy, ORB & Scalping on {SYMBOL}"
    )
    logger.info(f"Iron Fly entry scheduled at {START_TIME.strftime('%H:%M:%S')}")
    logger.info(f"Momentum entry starts at {MOMENTUM_START_TIME.strftime('%H:%M:%S')}")
    logger.info(f"Scalping entry starts at {SCALPING_START_TIME.strftime('%H:%M:%S')}")
    logger.info("Application Initialized. Starting Main Loop...")

    try:
        while True:
            # Check for Consecutive Losses
            consecutive_losses, trades_pnl = tm.get_consecutive_losses()

            if consecutive_losses > 2:
                if not tm.is_in_break():
                    tm.trigger_break(duration_minutes=15)
                    logger.warning(
                        f"More than 2 consecutive losses detected ({consecutive_losses} losses). Enforcing 15-minute break."
                    )

            # Check if in break period
            if tm.is_in_break():
                logger.info(
                    f"In break period due to consecutive losses. Break until: {tm.break_until_time.strftime('%H:%M:%S')}. "
                    f"Managing existing trades only."
                )
                # Still manage existing trades, but skip new entries
                if momentum_buy.state == "IN_TRADE":
                    momentum_buy.manage_trade()
                if scalping_strategy.state == "IN_TRADE":
                    scalping_strategy.manage_trade()
            else:
                # Check Overall Profit Threshold
                overall_profit = tm.calculate_overall_profit()

                if overall_profit >= OVERALL_PROFIT_THRESHOLD:
                    logger.warning(
                        f"Overall profit target reached! Profit: {overall_profit:.2f} >= Threshold: {OVERALL_PROFIT_THRESHOLD}. No new trades will be undertaken."
                    )
                    # Still manage existing trades, but skip new entries
                    if momentum_buy.state == "IN_TRADE":
                        momentum_buy.manage_trade()
                    if scalping_strategy.state == "IN_TRADE":
                        scalping_strategy.manage_trade()
                else:
                    # Run Strategy Logic

                    # iron_fly.on_tick()
                    momentum_buy.on_tick()
                    # orb_strategy.on_tick()
                    # scalping_strategy.on_tick()

            # Sleep to simulate tick interval (e.g., 1 second)
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping Application...")


if __name__ == "__main__":
    main()
