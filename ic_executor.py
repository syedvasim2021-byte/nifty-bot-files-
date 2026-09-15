"""
Order placement for the Iron Condor: entering all 4 legs, and closing one
side (2 legs) or both sides. Goes through the same DRY_RUN-aware pattern as
executor.py -- every order is logged and journaled, and nothing real is sent
to the exchange unless DRY_RUN=false.

Leg order on entry: the HEDGE (long) leg of each side is placed before the
SHORT leg, so the position is never briefly naked from a margin/risk
standpoint, even for the few seconds between the two calls.
"""
from kiteconnect import KiteConnect

import config
from logger_setup import get_logger, log_trade

log = get_logger()

MARKET_PROTECTION = -1


def _place_leg(kite: KiteConnect, tradingsymbol: str, lots: int, lot_size: int, transaction_type: str, reason: str):
    qty = lots * lot_size
    mode = "DRY_RUN" if config.DRY_RUN else "LIVE"
    log.info(f"[{mode}] {transaction_type} {tradingsymbol} qty={qty} reason={reason}")
    log_trade(transaction_type, tradingsymbol, qty, lots, None, "MARKET", reason, mode)

    if config.DRY_RUN:
        return {"order_id": "DRY_RUN", "status": "simulated"}

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction_type,
        quantity=qty,
        product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_MARKET,
        market_protection=MARKET_PROTECTION,
    )
    return {"order_id": order_id, "status": "sent"}


def enter_iron_condor(kite: KiteConnect, legs: dict, lots: int):
    """legs: dict from ic_instruments.resolve_iron_condor_legs()."""
    _place_leg(kite, legs["long_ce"]["tradingsymbol"], lots, legs["long_ce"]["lot_size"], "BUY", "IC_ENTRY_HEDGE")
    _place_leg(kite, legs["short_ce"]["tradingsymbol"], lots, legs["short_ce"]["lot_size"], "SELL", "IC_ENTRY_SHORT")
    _place_leg(kite, legs["long_pe"]["tradingsymbol"], lots, legs["long_pe"]["lot_size"], "BUY", "IC_ENTRY_HEDGE")
    _place_leg(kite, legs["short_pe"]["tradingsymbol"], lots, legs["short_pe"]["lot_size"], "SELL", "IC_ENTRY_SHORT")


def exit_call_side(kite: KiteConnect, legs: dict, lots: int, reason: str):
    """Buys back the short CE and sells the long CE hedge -- closes just the call spread."""
    _place_leg(kite, legs["short_ce"]["tradingsymbol"], lots, legs["short_ce"]["lot_size"], "BUY", reason)
    _place_leg(kite, legs["long_ce"]["tradingsymbol"], lots, legs["long_ce"]["lot_size"], "SELL", reason)


def exit_put_side(kite: KiteConnect, legs: dict, lots: int, reason: str):
    """Buys back the short PE and sells the long PE hedge -- closes just the put spread."""
    _place_leg(kite, legs["short_pe"]["tradingsymbol"], lots, legs["short_pe"]["lot_size"], "BUY", reason)
    _place_leg(kite, legs["long_pe"]["tradingsymbol"], lots, legs["long_pe"]["lot_size"], "SELL", reason)
