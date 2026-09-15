"""
SENSEX equivalent of ic_instruments.py. Kept as a fully separate file (rather
than parameterizing the NIFTY one) so nothing here can ever accidentally
affect the already-working NIFTY Iron Condor.

Key differences from NIFTY:
  - SENSEX spot price and options trade on BSE, not NSE. Kite Connect uses
    the exchange code "BFO" for BSE F&O (confirmed via Kite's own forum/docs),
    vs "NFO" for NSE F&O.
  - Spot LTP is looked up as "BSE:SENSEX" (not "NSE:SENSEX", and not the
    "NIFTY 50" style name with a space).
"""
from datetime import date
import pandas as pd

import config
from logger_setup import get_logger

log = get_logger()

_instrument_cache = {"df": None, "fetched_on": None}


def _bfo_instruments(kite):
    today = date.today()
    if _instrument_cache["df"] is not None and _instrument_cache["fetched_on"] == today:
        return _instrument_cache["df"]

    log.info("Fetching BFO instrument dump (SENSEX Iron Condor)...")
    data = kite.instruments("BFO")
    df = pd.DataFrame(data)
    df = df[df["name"] == config.SENSEX_OPTION_PREFIX]
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    _instrument_cache["df"] = df
    _instrument_cache["fetched_on"] = today
    return df


def get_spot_price(kite) -> float:
    quote = kite.ltp(["BSE:SENSEX"])
    return quote["BSE:SENSEX"]["last_price"]


def get_nearest_expiry(kite) -> date:
    df = _bfo_instruments(kite)
    today = date.today()
    upcoming = sorted(e for e in df["expiry"].unique() if e >= today)
    if not upcoming:
        raise RuntimeError("No upcoming SENSEX option expiry found in instrument dump.")
    return upcoming[0]


def _closest_strike_row(chain: pd.DataFrame, target_strike: float) -> pd.Series:
    chain = chain.copy()
    chain["dist"] = (chain["strike"] - target_strike).abs()
    return chain.sort_values("dist").iloc[0]


def _leg_from_row(row) -> dict:
    return {
        "tradingsymbol": row["tradingsymbol"],
        "strike": float(row["strike"]),
        "lot_size": int(row["lot_size"]),
    }


def resolve_iron_condor_legs(kite, reference_spot: float) -> dict:
    df = _bfo_instruments(kite)
    expiry = get_nearest_expiry(kite)

    ce_chain = df[(df["expiry"] == expiry) & (df["instrument_type"] == "CE")]
    pe_chain = df[(df["expiry"] == expiry) & (df["instrument_type"] == "PE")]
    if ce_chain.empty or pe_chain.empty:
        raise RuntimeError(f"No SENSEX option chain found for expiry {expiry}")

    short_ce_target = reference_spot + config.IC_SHORT_DISTANCE_SENSEX
    long_ce_target = short_ce_target + config.IC_WING_WIDTH_SENSEX
    short_pe_target = reference_spot - config.IC_SHORT_DISTANCE_SENSEX
    long_pe_target = short_pe_target - config.IC_WING_WIDTH_SENSEX

    short_ce = _leg_from_row(_closest_strike_row(ce_chain, short_ce_target))
    long_ce = _leg_from_row(_closest_strike_row(ce_chain, long_ce_target))
    short_pe = _leg_from_row(_closest_strike_row(pe_chain, short_pe_target))
    long_pe = _leg_from_row(_closest_strike_row(pe_chain, long_pe_target))

    log.info(
        f"SENSEX IC legs @ spot {reference_spot:.2f}: "
        f"short_ce={short_ce['strike']} long_ce={long_ce['strike']} "
        f"short_pe={short_pe['strike']} long_pe={long_pe['strike']} expiry={expiry}"
    )

    return {
        "expiry": str(expiry),
        "reference_spot": reference_spot,
        "short_ce": short_ce,
        "long_ce": long_ce,
        "short_pe": short_pe,
        "long_pe": long_pe,
    }
