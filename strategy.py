"""
Breakout + retest price-action strategy on the NIFTY 50 index, 15-minute candles.

Rules, as specified:

  BULLISH (CE) setup:
    1. A candle (candle 1) forms.
    2. The next candle CLOSES above candle 1's high -> "breakout candle".
       candle 1's high becomes the reference level to watch.
    3. Wait for a later candle to dip into that level and CLOSE back at/above
       it (low <= level, close >= level) -> confirmed retest.
    4. On confirmed retest: buy 1 lot ATM CE. Initial stop loss = candle 1's low.
    5. From then on, after every new 15-min candle closes, the stop loss is
       updated to literally equal that candle's low -- every time, whether
       that's tighter or looser than the previous stop.

  BEARISH (PE) setup is the exact mirror: reference = candle 1's low, retest
  is a bounce back down through it, initial SL = candle 1's high, SL trails
  to each new candle's high.

  Only the single most recent, not-yet-retested breakout is tracked at any
  time -- if a fresh breakout candle appears before the pending one is
  retested, it replaces the pending one.

ASSUMPTIONS BAKED IN HERE (tell me if any of these should change):
  - Signals are evaluated on the NIFTY 50 INDEX candles, not futures and not
    the option's own price.
  - "Crosses" / "breaks" = a candle's CLOSE beyond the reference level, not
    just a wick touching it -- matching the close-based retest confirmation.
  - The stop-loss *level* updates once per 15-min candle close (as
    described), but breaches are checked against live LTP every poll cycle
    (see main.py) rather than waiting for the next candle close, so a fast
    move against the position doesn't sit unprotected for up to 15 minutes.
  - Assumes the machine running this bot is set to IST (Asia/Kolkata) --
    the candle "is this fully closed yet" check below depends on that.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

import config
from logger_setup import get_logger

log = get_logger()

_TOKEN_CACHE = {}


def _get_underlying_token(kite):
    if "token" in _TOKEN_CACHE:
        return _TOKEN_CACHE["token"]
    for inst in kite.instruments("NSE"):
        if inst["tradingsymbol"] == "NIFTY 50":
            _TOKEN_CACHE["token"] = inst["instrument_token"]
            return inst["instrument_token"]
    raise RuntimeError("Could not resolve instrument token for NIFTY 50 index.")


def fetch_candles(kite, lookback_minutes: int = 60 * 8) -> pd.DataFrame:
    """Fetches recent 15-min candles and drops any still-forming (not yet
    closed) candle, so downstream logic only ever sees fully closed bars."""
    token = _get_underlying_token(kite)
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(minutes=lookback_minutes)
    data = kite.historical_data(token, from_dt, to_dt, config.CANDLE_INTERVAL)
    df = pd.DataFrame(data)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)

    cutoff = to_dt - timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    df = df[df["date"] <= cutoff].reset_index(drop=True)
    return df


@dataclass
class PendingSetup:
    direction: str  # "CE" or "PE"
    ref_high: float
    ref_low: float
    ref_time: object


class StrategyState:
    """Persists across poll cycles for one running session: the current
    unretested breakout (if any), and which candle was last evaluated so
    each candle is processed exactly once."""

    def __init__(self):
        self.pending: Optional[PendingSetup] = None
        self.last_evaluated_time = None


def _process_new_candle(prev_row, curr_row, state: StrategyState):
    """Runs once per newly closed candle. Returns (signal, initial_sl)."""

    # 1) Fresh breakout on this candle? Replaces any pending setup.
    if curr_row["close"] > prev_row["high"]:
        state.pending = PendingSetup(
            "CE", ref_high=prev_row["high"], ref_low=prev_row["low"], ref_time=prev_row["date"]
        )
        log.info(f"New bullish breakout at {curr_row['date']}. Watching retest of {prev_row['high']:.2f}")
        return None, None

    if curr_row["close"] < prev_row["low"]:
        state.pending = PendingSetup(
            "PE", ref_high=prev_row["high"], ref_low=prev_row["low"], ref_time=prev_row["date"]
        )
        log.info(f"New bearish breakout at {curr_row['date']}. Watching retest of {prev_row['low']:.2f}")
        return None, None

    # 2) No fresh breakout -- does this candle confirm a retest of the
    #    currently pending setup?
    if state.pending is None:
        return None, None

    if state.pending.direction == "CE":
        touched = curr_row["low"] <= state.pending.ref_high
        held = curr_row["close"] >= state.pending.ref_high
        if touched and held:
            log.info(f"CE retest confirmed at {curr_row['date']} (level {state.pending.ref_high:.2f})")
            initial_sl = state.pending.ref_low
            state.pending = None
            return "BUY_CE", initial_sl

    elif state.pending.direction == "PE":
        touched = curr_row["high"] >= state.pending.ref_low
        held = curr_row["close"] <= state.pending.ref_low
        if touched and held:
            log.info(f"PE retest confirmed at {curr_row['date']} (level {state.pending.ref_low:.2f})")
            initial_sl = state.pending.ref_high
            state.pending = None
            return "BUY_PE", initial_sl

    return None, None


def check_for_signal(kite, state: StrategyState):
    """
    Call once per poll. Only evaluates when a NEW candle has closed since the
    last call (so it's safe to call every 20 seconds). Returns
    (signal, initial_sl): signal is "BUY_CE" / "BUY_PE" / None.
    """
    df = fetch_candles(kite)
    if len(df) < 2:
        return None, None

    latest = df.iloc[-1]
    if state.last_evaluated_time is not None and latest["date"] <= state.last_evaluated_time:
        return None, None  # already processed this candle

    prev = df.iloc[-2]
    signal, initial_sl = _process_new_candle(prev, latest, state)
    state.last_evaluated_time = latest["date"]
    return signal, initial_sl


def latest_candle_extreme(kite, direction: str, after_time=None):
    """
    For trailing the stop-loss: the most recently CLOSED candle's low (CE
    position) or high (PE position) -- but ONLY if that candle closed
    strictly after `after_time`.

    Without this guard, the very first poll right after entry would see the
    retest/entry candle itself as "the latest closed candle" (the next
    15-min candle hasn't closed yet) and immediately overwrite the initial
    SL with that candle's own low/high -- collapsing the intended "initial
    SL = reference candle's low, held until the NEXT candle closes" rule.

    Returns (value, candle_time). value is None if no newer candle has
    closed yet, in which case the caller should keep the existing SL.
    """
    df = fetch_candles(kite)
    if df.empty:
        return None, after_time
    row = df.iloc[-1]
    if after_time is not None and row["date"] <= after_time:
        return None, after_time
    value = row["low"] if direction == "CE" else row["high"]
    return value, row["date"]
