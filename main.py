"""
Main loop for the 15-min breakout+retest strategy:

  - Watches NIFTY 50 index 15-min candles for a breakout, then a confirmed
    retest (see strategy.py for the exact rules).
  - On a confirmed retest, buys STRATEGY_FIXED_LOTS of the ATM CE/PE.
  - Stop loss is the relevant reference candle's low/high, and trails to the
    latest closed candle's low/high every 15 minutes (literally, not just
    tightening). Breaches are checked against live underlying LTP every poll
    so the exit isn't delayed until the next candle close.
  - Forces a square-off at config.SQUARE_OFF_TIME regardless of state.

Run with:
    python main.py
Start with DRY_RUN=true in .env (the default) and watch it through several
full sessions before ever going live.
"""
import sys
import time
from datetime import datetime

import config
import instruments
import strategy
from auth import get_kite_session
from executor import place_order, exit_position
from logger_setup import get_logger
from risk_manager import RiskManager

log = get_logger()


def _in_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    hhmm = now.strftime("%H:%M")
    return config.MARKET_OPEN <= hhmm <= config.MARKET_CLOSE


def _past_square_off() -> bool:
    return datetime.now().strftime("%H:%M") >= config.SQUARE_OFF_TIME


def _sl_breached(direction: str, underlying_ltp: float, sl_level: float) -> bool:
    if sl_level is None:
        return False
    if direction == "CE":
        return underlying_ltp <= sl_level
    else:  # PE
        return underlying_ltp >= sl_level


def run():
    log.info(f"Starting bot. Mode: {'DRY_RUN (simulation)' if config.DRY_RUN else 'LIVE'}")
    if not config.DRY_RUN:
        log.warning(
            "LIVE mode: real orders will be sent with real money. Confirm your "
            "strategy is registered with your broker's Algo-ID requirement and "
            "your static IP is whitelisted before proceeding."
        )

    kite = get_kite_session()
    risk = RiskManager()
    strat_state = strategy.StrategyState()

    # open_position: dict with tradingsymbol, qty, lot_size, entry_price
    # (option premium), direction ("CE"/"PE"), sl_level (underlying price)
    open_position = None

    while True:
        try:
            if not _in_market_hours():
                log.info("Outside market hours. Sleeping...")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # ---- Manage an existing open position ----
            if open_position is not None:
                underlying_ltp = instruments.get_spot_price(kite)

                # Trail the SL level to the latest closed candle's extreme,
                # but only once a candle strictly newer than the entry/retest
                # candle has closed (see strategy.latest_candle_extreme).
                new_sl, new_sl_time = strategy.latest_candle_extreme(
                    kite, open_position["direction"], after_time=open_position["sl_candle_time"]
                )
                if new_sl is not None and new_sl != open_position["sl_level"]:
                    log.info(
                        f"Trailing SL for {open_position['tradingsymbol']}: "
                        f"{open_position['sl_level']:.2f} -> {new_sl:.2f}"
                    )
                    open_position["sl_level"] = new_sl
                    open_position["sl_candle_time"] = new_sl_time

                exit_reason = None
                if _sl_breached(open_position["direction"], underlying_ltp, open_position["sl_level"]):
                    exit_reason = "STOP_LOSS"
                if _past_square_off():
                    exit_reason = "SQUARE_OFF_TIME"

                if exit_reason:
                    opt_ltp_data = kite.ltp([f"NFO:{open_position['tradingsymbol']}"])
                    opt_ltp = opt_ltp_data[f"NFO:{open_position['tradingsymbol']}"]["last_price"]

                    exit_position(kite, open_position["tradingsymbol"], open_position["qty"], opt_ltp, exit_reason)
                    pnl = (opt_ltp - open_position["entry_price"]) * open_position["qty"]
                    risk.record_trade_closed(pnl)
                    open_position = None

            # ---- Look for a new entry if flat ----
            if open_position is None and not _past_square_off():
                ok, why = risk.can_trade()
                if not ok:
                    log.info(f"Not trading: {why}")
                else:
                    signal, initial_sl = strategy.check_for_signal(kite, strat_state)
                    if signal in ("BUY_CE", "BUY_PE"):
                        option_type = "CE" if signal == "BUY_CE" else "PE"
                        contract = instruments.resolve_atm_option(kite, option_type)

                        opt_ltp_data = kite.ltp([f"NFO:{contract['tradingsymbol']}"])
                        premium = opt_ltp_data[f"NFO:{contract['tradingsymbol']}"]["last_price"]

                        lots = min(config.STRATEGY_FIXED_LOTS, config.MAX_LOTS_PER_TRADE)
                        place_order(
                            kite, contract["tradingsymbol"], lots,
                            contract["lot_size"], premium, signal,
                        )
                        risk.record_trade_opened()
                        open_position = {
                            "tradingsymbol": contract["tradingsymbol"],
                            "qty": lots * contract["lot_size"],
                            "lot_size": contract["lot_size"],
                            "entry_price": premium,
                            "direction": option_type,
                            "sl_level": initial_sl,
                            "sl_candle_time": strat_state.last_evaluated_time,
                        }
                        log.info(f"Entered {option_type} at premium {premium}, initial SL (underlying) = {initial_sl:.2f}")

            time.sleep(config.POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
            if open_position is not None:
                log.warning(
                    f"An open position remains: {open_position['tradingsymbol']} "
                    f"qty={open_position['qty']}. Square it off manually if needed."
                )
            sys.exit(0)
        except Exception as e:
            log.exception(f"Unhandled error in main loop: {e}")
            time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
