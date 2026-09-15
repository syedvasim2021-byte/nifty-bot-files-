"""
Order placement. Every order goes through place_order()/exit_position() so
DRY_RUN is enforced in exactly one place, and SEBI's mandatory
market_protection parameter on MARKET orders is never accidentally omitted.

Live compliance reminder (see README): as of the current SEBI/NSE retail
algo framework, orders placed via API must originate from a static IP
registered with your broker, and your strategy needs to be tagged/registered
through your broker to receive an exchange Algo-ID before it can legally
place live orders. This code does not (and cannot) handle that registration
for you — it happens once, on your broker's developer/algo dashboard.
"""
from kiteconnect import KiteConnect

import config
from logger_setup import get_logger, log_trade

log = get_logger()

# Zerodha requires a non-zero market_protection value on MARKET orders.
# -1 tells Kite to apply the exchange's default protection band.
MARKET_PROTECTION = -1


def place_order(kite: KiteConnect, tradingsymbol: str, lots: int, lot_size: int, ltp: float, reason: str):
    qty = lots * lot_size
    mode = "DRY_RUN" if config.DRY_RUN else "LIVE"

    log.info(f"[{mode}] BUY {tradingsymbol} qty={qty} ({lots} lot(s)) reason={reason} ~ltp={ltp}")
    log_trade("BUY", tradingsymbol, qty, lots, ltp, "MARKET", reason, mode)

    if config.DRY_RUN:
        return {"order_id": "DRY_RUN", "status": "simulated", "avg_price": ltp}

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=kite.TRANSACTION_TYPE_BUY,
        quantity=qty,
        product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_MARKET,
        market_protection=MARKET_PROTECTION,
    )
    return {"order_id": order_id, "status": "sent", "avg_price": None}


def exit_position(kite: KiteConnect, tradingsymbol: str, qty: int, ltp: float, reason: str):
    mode = "DRY_RUN" if config.DRY_RUN else "LIVE"

    log.info(f"[{mode}] SELL/EXIT {tradingsymbol} qty={qty} reason={reason} ~ltp={ltp}")
    log_trade("SELL", tradingsymbol, qty, qty, ltp, "MARKET", reason, mode)

    if config.DRY_RUN:
        return {"order_id": "DRY_RUN", "status": "simulated", "avg_price": ltp}

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_MARKET,
        market_protection=MARKET_PROTECTION,
    )
    return {"order_id": order_id, "status": "sent", "avg_price": None}
