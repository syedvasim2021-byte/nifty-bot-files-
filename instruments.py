"""
Resolves the actual option contract to trade: nearest weekly expiry, ATM strike,
correct tradingsymbol and lot_size — all read live from Kite's instrument dump
rather than hardcoded, since NSE revises strikes/lot sizes/expiry days over time.
"""
from datetime import datetime, date
import pandas as pd

import config
from logger_setup import get_logger

log = get_logger()

_instrument_cache = {"df": None, "fetched_on": None}


def _nfo_instruments(kite):
    """Cached fetch of the full NFO instrument list (large payload, so fetch once/day)."""
    today = date.today()
    if _instrument_cache["df"] is not None and _instrument_cache["fetched_on"] == today:
        return _instrument_cache["df"]

    log.info("Fetching NFO instrument dump...")
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


def resolve_atm_option(kite, option_type: str):
    """
    option_type: 'CE' or 'PE'
    Returns dict: {tradingsymbol, strike, lot_size, expiry}
    """
    assert option_type in ("CE", "PE")

    df = _nfo_instruments(kite)
    expiry = get_nearest_expiry(kite)
    spot = get_spot_price(kite)

    chain = df[(df["expiry"] == expiry) & (df["instrument_type"] == option_type)]
    if chain.empty:
        raise RuntimeError(f"No {option_type} contracts found for expiry {expiry}")

    # Strike step for NIFTY is typically 50 or 100 depending on spot level; instead of
    # assuming a step, just pick the strike in the actual chain closest to spot.
    chain = chain.copy()
    chain["dist"] = (chain["strike"] - spot).abs()
    row = chain.sort_values("dist").iloc[0]

    return {
        "tradingsymbol": row["tradingsymbol"],
        "strike": float(row["strike"]),
        "lot_size": int(row["lot_size"]),
        "expiry": expiry,
        "spot_at_selection": spot,
    }
