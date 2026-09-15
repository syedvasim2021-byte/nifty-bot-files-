"""
Iron Condor strategy for NIFTY:

  Monday, config.IC_ENTRY_TIME_NIFTY (default 09:30): capture spot price as
  the reference. Sell CE at ref+250 and PE at ref-250. Buy CE at ref+450 and
  PE at ref-450 as hedges (250/450 = IC_SHORT_DISTANCE_NIFTY / +IC_WING_WIDTH_NIFTY,
  both configurable).

  From then on: if spot crosses ref+250, close the call spread (buy back the
  short CE, sell the long CE) and leave the put spread running. Mirror for
  ref-250 on the put side. Whatever is still open gets force-closed Tuesday
  at config.IC_SQUAREOFF_TIME_NIFTY.

  This runs across TWO calendar days (Monday->Tuesday), so state (the
  reference price and which legs/sides are open) is persisted to
  config.IC_STATE_FILE on every change. If the bot is restarted (e.g. for
  the unavoidable daily Kite re-login -- access tokens expire ~6 AM), it
  picks up exactly where it left off instead of losing track of an open
  position.

  Holiday handling (e.g. Monday being a trading holiday) is NOT implemented
  yet -- this covers the core Monday->Tuesday flow only, by design, to get
  that working and tested first.

Run with:
    python iron_condor_main.py
Start with DRY_RUN=true (the default) and watch it through at least one full
Monday->Tuesday cycle before ever going live.
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

log = get_logger("iron_condor")


def _load_state() -> dict:
    if not os.path.exists(config.IC_STATE_FILE):
        return {"status": "FLAT"}
    with open(config.IC_STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict):
    with open(config.IC_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _in_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    hhmm = now.strftime("%H:%M")
    return config.MARKET_OPEN <= hhmm <= config.MARKET_CLOSE


def _try_entry(kite, state: dict, now: datetime) -> dict:
    weekday = now.strftime("%A")
    today_str = now.date().isoformat()
    hhmm = now.strftime("%H:%M")

    if weekday != config.IC_ENTRY_DAY_NIFTY:
        return state
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


def _manage_open_position(kite, state: dict, now: datetime) -> dict:
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

    weekday = now.strftime("%A")
    hhmm = now.strftime("%H:%M")
    if weekday == config.IC_SQUAREOFF_DAY_NIFTY and hhmm >= config.IC_SQUAREOFF_TIME_NIFTY:
        if state["call_side_open"]:
            log.info("Forced square-off (call side)")
            ic_executor.exit_call_side(kite, legs, config.IC_LOTS, "SQUARE_OFF")
            state["call_side_open"] = False
            changed = True
        if state["put_side_open"]:
            log.info("Forced square-off (put side)")
            ic_executor.exit_put_side(kite, legs, config.IC_LOTS, "SQUARE_OFF")
            state["put_side_open"] = False
            changed = True

    if not state["call_side_open"] and not state["put_side_open"]:
        log.info("Both sides closed. Cycle complete, back to FLAT.")
        state = {"status": "FLAT"}
        changed = True

    if changed:
        _save_state(state)
    return state


def run():
    log.info(f"Starting Iron Condor bot. Mode: {'DRY_RUN (simulation)' if config.DRY_RUN else 'LIVE'}")
    if not config.DRY_RUN:
        log.warning(
            "LIVE mode: real orders will be sent with real money, across a "
            "Monday->Tuesday overnight position. Confirm static IP / Algo-ID "
            "registration and margin availability before proceeding."
        )

    state = _load_state()
    log.info(f"Loaded state: {state}")

    kite = None
    last_session_date = None

    while True:
        try:
            now = datetime.now()
            today = now.date()

            # Refresh the Kite session once per calendar day (access tokens
            # expire daily; this strategy spans two days so we can't just
            # log in once at startup the way a single-day bot would).
            if kite is None or today != last_session_date:
                kite = get_kite_session()
                last_session_date = today

            if _in_market_hours(now):
                state = _try_entry(kite, state, now)
                state = _manage_open_position(kite, state, now)
                time.sleep(config.IC_POLL_INTERVAL_SECONDS)
            else:
                log.info(f"Outside market hours (state={state.get('status')}). Sleeping...")
                time.sleep(300)  # check every 5 min outside market hours

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
            if state.get("status") == "OPEN":
                log.warning(
                    "An Iron Condor position is still open in state file "
                    f"({config.IC_STATE_FILE}). Restarting the bot will resume "
                    "monitoring it -- it is NOT auto-closed by stopping the script."
                )
            sys.exit(0)
        except Exception as e:
            log.exception(f"Unhandled error in Iron Condor loop: {e}")
            time.sleep(config.IC_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
