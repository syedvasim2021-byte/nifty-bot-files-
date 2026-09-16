"""
SENSEX equivalent of ic_executor.py -- identical logic, but orders go to the
BFO (BSE F&O) exchange segment instead of NFO. Kept as a separate file so it
can never accidentally affect the NIFTY executor.

Uses product=NRML (not MIS): this position is deliberately held overnight
(Wednesday->Thursday). MIS positions get force-squared-off by the broker's
RMS before market close the same day, which would silently break the whole
overnight-hold design. NRML requires more margin than MIS, so confirm
sufficient margin is available before going live.
"""
from kiteconnect import KiteConnect

import config
from logger_setup import get_logger, log_trade

log = get_logger()

MARKET_PROTECTION = -1


def _place_leg(kite: KiteConnect, tradingsymbol: str, lots: int, lot_size: int, transaction_type: str, reason: str):
    qty = lots * lot_size
    mode = "DRY_RUN" if config.DRY_RUN else "LIVE"
    log.info(f"[{mode}] {transaction_type} {tradingsymbol} qty={qty} reason={reason} (BFO)")
    log_trade(transaction_type, tradingsymbol, qty, lots, None, "MARKET", reason, mode)

    if config.DRY_RUN:
        return {"order_id": "DRY_RUN", "status": "simulated"}

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange="BFO",
        tradingsymbol=tradingsymbol,
        transaction_type=transaction_type,
        quantity=qty,
        product=kite.PRODUCT_NRML,
        order_type=kite.ORDER_TYPE_MARKET,
        market_protection=MARKET_PROTECTION,
    )
    return {"order_id": order_id, "status": "sent"}


def enter_iron_condor(kite: KiteConnect, legs: dict, lots: int):
    _place_leg(kite, legs["long_ce"]["tradingsymbol"], lots, legs["long_ce"]["lot_size"], "BUY", "IC_ENTRY_HEDGE")
    _place_leg(kite, legs["short_ce"]["tradingsymbol"], lots, legs["short_ce"]["lot_size"], "SELL", "IC_ENTRY_SHORT")
    _place_leg(kite, legs["long_pe"]["tradingsymbol"], lots, legs["long_pe"]["lot_size"], "BUY", "IC_ENTRY_HEDGE")
    _place_leg(kite, legs["short_pe"]["tradingsymbol"], lots, legs["short_pe"]["lot_size"], "SELL", "IC_ENTRY_SHORT")


def exit_call_side(kite: KiteConnect, legs: dict, lots: int, reason: str):
    _place_leg(kite, legs["short_ce"]["tradingsymbol"], lots, legs["short_ce"]["lot_size"], "BUY", reason)
    _place_leg(kite, legs["long_ce"]["tradingsymbol"], lots, legs["long_ce"]["lot_size"], "SELL", reason)


def exit_put_side(kite: KiteConnect, legs: dict, lots: int, reason: str):
    _place_leg(kite, legs["short_pe"]["tradingsymbol"], lots, legs["short_pe"]["lot_size"], "BUY", reason)
    _place_leg(kite, legs["long_pe"]["tradingsymbol"], lots, legs["long_pe"]["lot_size"], "SELL", reason)
