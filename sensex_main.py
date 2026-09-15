"""
Iron Condor strategy for SENSEX -- mirrors iron_condor_main.py (NIFTY) but:
  - Entry: Wednesday 09:30 (config.IC_ENTRY_DAY_SENSEX / IC_ENTRY_TIME_SENSEX)
  - Square-off: Thursday 15:15 (SENSEX's weekly expiry day, BSE)
  - Short strikes = spot +/- IC_SHORT_DISTANCE_SENSEX (default 700)
  - Hedge strikes = short strikes +/- IC_WING_WIDTH_SENSEX further out (default 700)
  - Uses sensex_instruments.py / sensex_executor.py (BFO exchange), not the
    NIFTY ic_instruments.py / ic_executor.py (NFO exchange)
  - Separate state file (config.IC_STATE_FILE_SENSEX) so this cannot collide
    with the NIFTY Iron Condor's state

Run this in its OWN screen session, separate from iron_condor_main.py --
they are independent strategies with independent state.

Run with:
    python sensex_main.py
Start with DRY_RUN=true (the default) and watch it through at least one full
Wednesday->Thursday cycle before ever going live.
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


def _try_entry(kite, state: dict, now: datetime) -> dict:
    weekday = now.strftime("%A")
    today_str = now.date().isoformat()
    hhmm = now.strftime("%H:%M")

    if weekday != config.IC_ENTRY_DAY_SENSEX:
        return state
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


def _manage_open_position(kite, state: dict, now: datetime) -> dict:
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

    weekday = now.strftime("%A")
    hhmm = now.strftime("%H:%M")
    if weekday == config.IC_SQUAREOFF_DAY_SENSEX and hhmm >= config.IC_SQUAREOFF_TIME_SENSEX:
        if state["call_side_open"]:
            log.info("SENSEX forced square-off (call side)")
            sensex_executor.exit_call_side(kite, legs, config.IC_LOTS_SENSEX, "SQUARE_OFF")
            state["call_side_open"] = False
            changed = True
        if state["put_side_open"]:
            log.info("SENSEX forced square-off (put side)")
            sensex_executor.exit_put_side(kite, legs, config.IC_LOTS_SENSEX, "SQUARE_OFF")
            state["put_side_open"] = False
            changed = True

    if not state["call_side_open"] and not state["put_side_open"]:
        log.info("SENSEX: both sides closed. Cycle complete, back to FLAT.")
        state = {"status": "FLAT"}
        changed = True

    if changed:
        _save_state(state)
    return state


def run():
    log.info(f"Starting SENSEX Iron Condor bot. Mode: {'DRY_RUN (simulation)' if config.DRY_RUN else 'LIVE'}")
    if not config.DRY_RUN:
        log.warning(
            "LIVE mode: real orders will be sent with real money, across a "
            "Wednesday->Thursday overnight position on BFO. Confirm static IP / "
            "Algo-ID registration and margin availability before proceeding."
        )

    state = _load_state()
    log.info(f"Loaded state: {state}")

    kite = None
    last_session_date = None

    while True:
        try:
            now = datetime.now()
            today = now.date()

            if kite is None or today != last_session_date:
                kite = get_kite_session()
                last_session_date = today

            if _in_market_hours(now):
                state = _try_entry(kite, state, now)
                state = _manage_open_position(kite, state, now)
                time.sleep(config.IC_POLL_INTERVAL_SECONDS_SENSEX)
            else:
                log.info(f"Outside market hours (state={state.get('status')}). Sleeping...")
                time.sleep(300)

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
            if state.get("status") == "OPEN":
                log.warning(
                    "A SENSEX Iron Condor position is still open in state file "
                    f"({config.IC_STATE_FILE_SENSEX}). Restarting the bot will "
                    "resume monitoring it -- it is NOT auto-closed by stopping the script."
                )
            sys.exit(0)
        except Exception as e:
            log.exception(f"Unhandled error in SENSEX Iron Condor loop: {e}")
            time.sleep(config.IC_POLL_INTERVAL_SECONDS_SENSEX)


if __name__ == "__main__":
    run()
