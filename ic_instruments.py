"""
Resolves the 4 legs of a NIFTY Iron Condor for a given reference spot price:
  short_ce  -- SELL, nearest strike to  spot + IC_SHORT_DISTANCE_NIFTY
  long_ce   -- BUY,  nearest strike to  spot + IC_SHORT_DISTANCE_NIFTY + IC_WING_WIDTH_NIFTY  (hedge)
  short_pe  -- SELL, nearest strike to  spot - IC_SHORT_DISTANCE_NIFTY
  long_pe   -- BUY,  nearest strike to  spot - IC_SHORT_DISTANCE_NIFTY - IC_WING_WIDTH_NIFTY  (hedge)

All 4 legs use the same expiry: the nearest upcoming weekly expiry at the time of
entry (NIFTY's weekly expiry is Tuesday as of Sep 2025 -- confirm this hasn't
changed again before relying on it).

Reuses the same instrument-dump approach as instruments.py (lot_size always read
live, never hardcoded, since NSE revises it periodically).
"""
from datetime import date
import pandas as pd

import config
from logger_setup import get_logger

log = get_logger()

_instrument_cache = {"df": None, "fetched_on": None}


def _nfo_instruments(kite):
    today = date.today()
    if _instrument_cache["df"] is not None and _instrument_cache["fetched_on"] == today:
        return _instrument_cache["df"]

    log.info("Fetching NFO instrument dump (Iron Condor)...")
    data = kite.instruments("NFO")
    df = pd.DataFrame(data)
    df = df[df["name"] == config.OPTION_SYMBOL_PREFIX]
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    _instrument_cache["df"] = df
    _instrument_cache["fetched_on"] = today
    return df


def get_spot_price(kite) -> float:
    quote = kite.ltp([f"NSE:{config.UNDERLYING_INDEX}"])
    return quote[f"NSE:{config.UNDERLYING_INDEX}"]["last_price"]


def get_nearest_expiry(kite) -> date:
    df = _nfo_instruments(kite)
    today = date.today()
    upcoming = sorted(e for e in df["expiry"].unique() if e >= today)
    if not upcoming:
        raise RuntimeError("No upcoming NIFTY option expiry found in instrument dump.")
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
    """
    Returns dict with keys: short_ce, long_ce, short_pe, long_pe (each a leg dict),
    plus expiry and reference_spot for record-keeping.
    """
    df = _nfo_instruments(kite)
    expiry = get_nearest_expiry(kite)

    ce_chain = df[(df["expiry"] == expiry) & (df["instrument_type"] == "CE")]
    pe_chain = df[(df["expiry"] == expiry) & (df["instrument_type"] == "PE")]
    if ce_chain.empty or pe_chain.empty:
        raise RuntimeError(f"No option chain found for expiry {expiry}")

    short_ce_target = reference_spot + config.IC_SHORT_DISTANCE_NIFTY
    long_ce_target = short_ce_target + config.IC_WING_WIDTH_NIFTY
    short_pe_target = reference_spot - config.IC_SHORT_DISTANCE_NIFTY
    long_pe_target = short_pe_target - config.IC_WING_WIDTH_NIFTY

    short_ce = _leg_from_row(_closest_strike_row(ce_chain, short_ce_target))
    long_ce = _leg_from_row(_closest_strike_row(ce_chain, long_ce_target))
    short_pe = _leg_from_row(_closest_strike_row(pe_chain, short_pe_target))
    long_pe = _leg_from_row(_closest_strike_row(pe_chain, long_pe_target))

    log.info(
        f"IC legs @ spot {reference_spot:.2f}: "
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
