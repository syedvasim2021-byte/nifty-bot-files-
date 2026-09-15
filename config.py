"""
Central configuration. Everything is read from environment variables
(via a local .env file) so no secrets ever live in source code.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


# ---- Kite Connect credentials ----
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")

# ---- Capital & risk ----
CAPITAL = _float("CAPITAL", 200000)
MAX_DAILY_LOSS_PCT = _float("MAX_DAILY_LOSS_PCT", 3.0)        # % of capital, hard stop for the day
MAX_TRADES_PER_DAY = _int("MAX_TRADES_PER_DAY", 4)
MAX_LOTS_PER_TRADE = _int("MAX_LOTS_PER_TRADE", 2)             # safety ceiling, independent of strategy sizing

# The breakout+retest strategy uses a FIXED lot count per trade (as specified),
# not %-risk based sizing. Still capped by MAX_LOTS_PER_TRADE above as a safety net.
STRATEGY_FIXED_LOTS = _int("STRATEGY_FIXED_LOTS", 1)

# Legacy %-based sizing/exit settings, kept only so RiskManager.position_size()/
# check_exit() (unused by main.py now) still work if you call them yourself.
# NOT used by the breakout+retest strategy, which uses fixed lots and a
# structural (candle-level) SL instead.
RISK_PER_TRADE_PCT = _float("RISK_PER_TRADE_PCT", 1.0)
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", 30)
TARGET_PCT = _float("TARGET_PCT", 50)

# ---- Strategy / instrument ----
UNDERLYING_INDEX = os.getenv("UNDERLYING_INDEX", "NIFTY 50")
OPTION_SYMBOL_PREFIX = os.getenv("OPTION_SYMBOL_PREFIX", "NIFTY")
CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "15minute")     # Kite interval string
CANDLE_INTERVAL_MINUTES = _int("CANDLE_INTERVAL_MINUTES", 15)  # same value, as an int, for time math
# Poll fairly often: the *signal* only re-evaluates once a new 15-min candle closes,
# but a short poll interval means stop-loss breaches (checked against live LTP) are
# caught quickly instead of waiting up to 15 minutes for the next candle.
POLL_INTERVAL_SECONDS = _int("POLL_INTERVAL_SECONDS", 20)
SQUARE_OFF_TIME = os.getenv("SQUARE_OFF_TIME", "15:20")       # forced intraday square-off

# ---- Safety ----
DRY_RUN = _bool("DRY_RUN", True)

# ---- Fixed market timings (IST) ----
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"

# ---- Iron Condor strategy (NIFTY) ----
# Entry: Monday at IC_ENTRY_TIME_NIFTY. Short strikes = spot +/- IC_SHORT_DISTANCE_NIFTY.
# Hedge (long) strikes = short strikes +/- IC_WING_WIDTH_NIFTY further out (caps max loss).
# Exit: a side closes the moment spot crosses its short strike; whatever remains open
# is force-closed on Tuesday at IC_SQUAREOFF_TIME_NIFTY.
IC_ENTRY_DAY_NIFTY = "Monday"
IC_ENTRY_TIME_NIFTY = "09:30"
IC_SQUAREOFF_DAY_NIFTY = "Tuesday"
IC_SQUAREOFF_TIME_NIFTY = "15:15"
IC_SHORT_DISTANCE_NIFTY = _int("IC_SHORT_DISTANCE_NIFTY", 250)
IC_WING_WIDTH_NIFTY = _int("IC_WING_WIDTH_NIFTY", 200)
IC_LOTS = _int("IC_LOTS", 1)
IC_POLL_INTERVAL_SECONDS = _int("IC_POLL_INTERVAL_SECONDS", 30)
IC_STATE_FILE = "ic_state_nifty.json"

# ---- Iron Condor strategy (SENSEX) ----
# Completely separate from the NIFTY one above -- different exchange (BSE, not
# NSE), different expiry day (Thursday), different entry day (Wednesday, i.e.
# T-1 to expiry, same as NIFTY's Monday->Tuesday pattern).
# Short strikes = spot +/- IC_SHORT_DISTANCE_SENSEX. Hedge strikes = short
# strikes +/- IC_WING_WIDTH_SENSEX further out.
IC_ENTRY_DAY_SENSEX = "Wednesday"
IC_ENTRY_TIME_SENSEX = "09:30"
IC_SQUAREOFF_DAY_SENSEX = "Thursday"
IC_SQUAREOFF_TIME_SENSEX = "15:15"
IC_SHORT_DISTANCE_SENSEX = _int("IC_SHORT_DISTANCE_SENSEX", 700)
IC_WING_WIDTH_SENSEX = _int("IC_WING_WIDTH_SENSEX", 700)
IC_LOTS_SENSEX = _int("IC_LOTS_SENSEX", 1)
IC_POLL_INTERVAL_SECONDS_SENSEX = _int("IC_POLL_INTERVAL_SECONDS_SENSEX", 30)
IC_STATE_FILE_SENSEX = "ic_state_sensex.json"
SENSEX_OPTION_PREFIX = "SENSEX"  # instrument `name` filter in the BFO dump

# NOTE on lot size: NSE revises index F&O lot sizes periodically (it changed at least
# twice across 2025-2026). This bot deliberately does NOT hardcode a lot size anywhere.
# instruments.py always reads `lot_size` fresh from the live Kite instrument dump so a
# future NSE revision can never silently produce a wrong order quantity.

if not DRY_RUN and (not KITE_API_KEY or not KITE_API_SECRET):
    raise RuntimeError(
        "DRY_RUN is false but KITE_API_KEY / KITE_API_SECRET are missing. "
        "Refusing to start in live mode without credentials."
    )
