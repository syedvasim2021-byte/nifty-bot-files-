"""
Iron Condor strategy for NIFTY -- Option 2 design (single-day monitoring):

  Monday, config.IC_ENTRY_TIME_NIFTY (default 09:30): capture spot price as
  the reference (S). Sell CE at S+IC_SHORT_DISTANCE_NIFTY and PE at
  S-IC_SHORT_DISTANCE_NIFTY. Buy CE at (S+distance+IC_WING_WIDTH_NIFTY) and
  PE at (S-distance-IC_WING_WIDTH_NIFTY) as hedges.

  For the REST OF MONDAY ONLY: if spot crosses the short CE level, close
  just the call spread (buy back short CE, sell the long CE hedge) and
  leave the put spread running. Mirror for the short PE level. Checked
  every IC_POLL_INTERVAL_SECONDS against live LTP.

  At Monday's market close, monitoring STOPS -- deliberately. There is no
  Tuesday activity at all: no login, no breach checks, no forced
  square-off. Whatever position remains open settles automatically at
  expiry (Tuesday, cash-settled index options) via the exchange. This
  trades "the bot exits early on a breach, capping realized loss below the
  theoretical max" for "only 1 day/week of login required instead of 2".
  The theoretical max loss (from the hedge) is unchanged either way; what's
  given up is the chance of a smaller, earlier realized loss if Monday's
  breach continues moving against the position on Tuesday. Decided on
  explicitly, with that trade-off understood.

  State (config.IC_STATE_FILE) persists across restarts within Monday
  (e.g. if the bot is restarted for a fresh login). It resets to FLAT the
  moment Monday's market hours end, regardless of whether both sides
  closed on their own -- the bot considers its job done for the week at
  that point.

Run with:
    python iron_condor_main.py
Start with DRY_RUN=true (the default).
"""
import json
import os
import sys
import time
from datetime import datetime

import config
import ic_instruments
import ic_executor
from auth import get_kite_session
from logger_setup import get_logger

log = get_logger()

INACTIVE_SLEEP_SECONDS = 1800  # 30 min -- nothing to do most of the week, no need to poll often


def _load_state() -> dict:
    if not os.path.exists(config.IC_STATE_FILE):
        return {"status": "FLAT"}
    with open(config.IC_STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict):
    with open(config.IC_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _in_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return config.MARKET_OPEN <= hhmm <= config.MARKET_CLOSE


def _is_active_window(now: datetime) -> bool:
    """True only on the entry day, during market hours -- the ONLY time this
    bot needs a live Kite session or does anything at all."""
    return now.strftime("%A") == config.IC_ENTRY_DAY_NIFTY and _in_market_hours(now)


def _try_entry(kite, state: dict, now: datetime) -> dict:
    today_str = now.date().isoformat()
    hhmm = now.strftime("%H:%M")

    if hhmm < config.IC_ENTRY_TIME_NIFTY:
        return state
    if state.get("entry_date") == today_str:
        return state  # already entered today

    spot = ic_instruments.get_spot_price(kite)
    legs = ic_instruments.resolve_iron_condor_legs(kite, spot)
    ic_executor.enter_iron_condor(kite, legs, config.IC_LOTS)

    log.info(f"IC ENTERED for {today_str}: reference_spot={spot:.2f}")
    new_state = {
        "status": "OPEN",
        "entry_date": today_str,
        "reference_spot": spot,
        "legs": legs,
        "call_side_open": True,
        "put_side_open": True,
    }
    _save_state(new_state)
    return new_state


def _manage_open_position(kite, state: dict) -> dict:
    """Breach checks only -- no forced square-off here anymore (see module
    docstring). Runs only while _is_active_window() is True, i.e. only on
    Monday during market hours."""
    if state.get("status") != "OPEN":
        return state

    legs = state["legs"]
    ref = state["reference_spot"]
    upper = ref + config.IC_SHORT_DISTANCE_NIFTY
    lower = ref - config.IC_SHORT_DISTANCE_NIFTY

    spot = ic_instruments.get_spot_price(kite)
    changed = False

    if state["call_side_open"] and spot >= upper:
        log.info(f"CALL side breach: spot {spot:.2f} >= {upper:.2f}")
        ic_executor.exit_call_side(kite, legs, config.IC_LOTS, "CALL_SIDE_BREACH")
        state["call_side_open"] = False
        changed = True

    if state["put_side_open"] and spot <= lower:
        log.info(f"PUT side breach: spot {spot:.2f} <= {lower:.2f}")
        ic_executor.exit_put_side(kite, legs, config.IC_LOTS, "PUT_SIDE_BREACH")
        state["put_side_open"] = False
        changed = True

    if not state["call_side_open"] and not state["put_side_open"]:
        log.info("Both sides closed (breached) before Monday's close. Back to FLAT.")
        state = {"status": "FLAT"}
        changed = True

    if changed:
        _save_state(state)
    return state


def run():
    log.info(f"Starting Iron Condor bot (single-day monitoring). Mode: {'DRY_RUN (simulation)' if config.DRY_RUN else 'LIVE'}")
    if not config.DRY_RUN:
        log.warning(
            "LIVE mode: real orders will be sent with real money. Remember: any "
            "position still open at Monday's close is UNMONITORED until expiry "
            "-- the exchange settles it automatically, but the bot will not "
            "react to further adverse moves on Tuesday. This was a deliberate choice."
        )

    state = _load_state()
    log.info(f"Loaded state: {state}")

    kite = None
    last_session_date = None
    was_active = False

    while True:
        try:
            now = datetime.now()
            active = _is_active_window(now)

            if not active:
                if state.get("status") == "OPEN":
                    log.info(
                        "Entry day's market hours have ended with no forced "
                        "square-off (by design). Resetting to FLAT for next "
                        "week -- any remaining legs settle automatically at expiry."
                    )
                    state = {"status": "FLAT"}
                    _save_state(state)
                if was_active:
                    log.info(f"Leaving active window. Next login needed: {config.IC_ENTRY_DAY_NIFTY} market hours.")
                was_active = False
                kite = None  # don't hold a session open when we don't need one
                time.sleep(INACTIVE_SLEEP_SECONDS)
                continue

            was_active = True
            today = now.date()
            if kite is None or today != last_session_date:
                kite = get_kite_session()
                last_session_date = today

            state = _try_entry(kite, state, now)
            state = _manage_open_position(kite, state)
            time.sleep(config.IC_POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
            if state.get("status") == "OPEN":
                log.warning(
                    f"An Iron Condor position is still open in state file "
                    f"({config.IC_STATE_FILE}). Restarting the bot will resume "
                    "monitoring it if still within Monday's market hours."
                )
            sys.exit(0)
        except Exception as e:
            log.exception(f"Unhandled error in Iron Condor loop: {e}")
            time.sleep(config.IC_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
