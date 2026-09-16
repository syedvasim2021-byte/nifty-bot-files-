"""
Iron Condor strategy for SENSEX -- Option 2 design (single-day monitoring).
Mirrors iron_condor_main.py (NIFTY) exactly, except:
  - Entry day: Wednesday (config.IC_ENTRY_DAY_SENSEX)
  - Uses sensex_instruments.py / sensex_executor.py (BFO exchange)
  - Separate state file (config.IC_STATE_FILE_SENSEX)

For the REST OF WEDNESDAY ONLY: breach checks run against live LTP. At
Wednesday's market close, monitoring STOPS -- no Thursday login, no
Thursday breach checks, no forced square-off. Whatever remains open
settles automatically at expiry (Thursday, cash-settled) via the exchange.
Same trade-off as NIFTY: theoretical max loss (from the hedge) is
unchanged, but an early exit that might have capped a smaller realized
loss on a Monday-breach-continues-Tuesday-style move is given up, in
exchange for needing only 1 login/week instead of 2. Decided on explicitly.

Run with:
    python sensex_main.py
Start with DRY_RUN=true (the default).
"""
import json
import os
import sys
import time
from datetime import datetime

import config
import sensex_instruments
import sensex_executor
from auth import get_kite_session
from logger_setup import get_logger

log = get_logger("iron_condor_sensex")

INACTIVE_SLEEP_SECONDS = 1800  # 30 min


def _load_state() -> dict:
    if not os.path.exists(config.IC_STATE_FILE_SENSEX):
        return {"status": "FLAT"}
    with open(config.IC_STATE_FILE_SENSEX) as f:
        return json.load(f)


def _save_state(state: dict):
    with open(config.IC_STATE_FILE_SENSEX, "w") as f:
        json.dump(state, f, indent=2)


def _in_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return config.MARKET_OPEN <= hhmm <= config.MARKET_CLOSE


def _is_active_window(now: datetime) -> bool:
    return now.strftime("%A") == config.IC_ENTRY_DAY_SENSEX and _in_market_hours(now)


def _try_entry(kite, state: dict, now: datetime) -> dict:
    today_str = now.date().isoformat()
    hhmm = now.strftime("%H:%M")

    if hhmm < config.IC_ENTRY_TIME_SENSEX:
        return state
    if state.get("entry_date") == today_str:
        return state

    spot = sensex_instruments.get_spot_price(kite)
    legs = sensex_instruments.resolve_iron_condor_legs(kite, spot)
    sensex_executor.enter_iron_condor(kite, legs, config.IC_LOTS_SENSEX)

    log.info(f"SENSEX IC ENTERED for {today_str}: reference_spot={spot:.2f}")
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
    """Breach checks only. Runs only during Wednesday market hours."""
    if state.get("status") != "OPEN":
        return state

    legs = state["legs"]
    ref = state["reference_spot"]
    upper = ref + config.IC_SHORT_DISTANCE_SENSEX
    lower = ref - config.IC_SHORT_DISTANCE_SENSEX

    spot = sensex_instruments.get_spot_price(kite)
    changed = False

    if state["call_side_open"] and spot >= upper:
        log.info(f"SENSEX CALL side breach: spot {spot:.2f} >= {upper:.2f}")
        sensex_executor.exit_call_side(kite, legs, config.IC_LOTS_SENSEX, "CALL_SIDE_BREACH")
        state["call_side_open"] = False
        changed = True

    if state["put_side_open"] and spot <= lower:
        log.info(f"SENSEX PUT side breach: spot {spot:.2f} <= {lower:.2f}")
        sensex_executor.exit_put_side(kite, legs, config.IC_LOTS_SENSEX, "PUT_SIDE_BREACH")
        state["put_side_open"] = False
        changed = True

    if not state["call_side_open"] and not state["put_side_open"]:
        log.info("SENSEX: both sides closed (breached) before Wednesday's close. Back to FLAT.")
        state = {"status": "FLAT"}
        changed = True

    if changed:
        _save_state(state)
    return state


def run():
    log.info(f"Starting SENSEX Iron Condor bot (single-day monitoring). Mode: {'DRY_RUN (simulation)' if config.DRY_RUN else 'LIVE'}")
    if not config.DRY_RUN:
        log.warning(
            "LIVE mode: real orders will be sent with real money. Remember: any "
            "position still open at Wednesday's close is UNMONITORED until "
            "expiry -- the exchange settles it automatically, but the bot will "
            "not react to further adverse moves on Thursday. Deliberate choice."
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
                    log.info(f"Leaving active window. Next login needed: {config.IC_ENTRY_DAY_SENSEX} market hours.")
                was_active = False
                kite = None
                time.sleep(INACTIVE_SLEEP_SECONDS)
                continue

            was_active = True
            today = now.date()
            if kite is None or today != last_session_date:
                kite = get_kite_session()
                last_session_date = today

            state = _try_entry(kite, state, now)
            state = _manage_open_position(kite, state)
            time.sleep(config.IC_POLL_INTERVAL_SECONDS_SENSEX)

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
            if state.get("status") == "OPEN":
                log.warning(
                    f"A SENSEX Iron Condor position is still open in state file "
                    f"({config.IC_STATE_FILE_SENSEX}). Restarting the bot will "
                    "resume monitoring it if still within Wednesday's market hours."
                )
            sys.exit(0)
        except Exception as e:
            log.exception(f"Unhandled error in SENSEX Iron Condor loop: {e}")
            time.sleep(config.IC_POLL_INTERVAL_SECONDS_SENSEX)


if __name__ == "__main__":
    run()
