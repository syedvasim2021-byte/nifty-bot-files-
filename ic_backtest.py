"""
Iron Condor "signal quality" backtest for NIFTY (Monday->Tuesday) and SENSEX
(Wednesday->Thursday), using historical INDEX candles only.

IMPORTANT CAVEAT -- read this before trusting any number below:
  This does NOT measure real option P&L. Kite Connect does not provide
  historical option premium data for expired weekly contracts, so an actual
  rupee-profit backtest of the Iron Condor isn't possible with this API.
  What this DOES measure: for each weekly cycle, using only the underlying
  index's price path, whether the CALL side's strike level was breached,
  the PUT side's was, both, or neither (= both sides would have expired
  worthless = max profit for the seller, before costs).
  This is a reasonable proxy for "how often does this structure survive",
  but says nothing about actual premium collected, IV, theta decay, or
  what a real breach would have cost you in premium terms.

Run with:
    python ic_backtest.py
"""
from datetime import datetime, timedelta
import pandas as pd

import config
from auth import get_kite_session

BACKTEST_DAYS = 730  # ~2 years; change to backtest a longer/shorter period


def fetch_index_candles(kite, exchange: str, tradingsymbol: str, days: int) -> pd.DataFrame:
    token = None
    for inst in kite.instruments(exchange):
        if inst["tradingsymbol"] == tradingsymbol:
            token = inst["instrument_token"]
            break
    if token is None:
        raise RuntimeError(f"Could not resolve instrument token for {exchange}:{tradingsymbol}")

    all_rows = []
    to_dt = datetime.now()
    remaining = days
    while remaining > 0:
        chunk = min(remaining, 60)
        from_dt = to_dt - timedelta(days=chunk)
        print(f"  [{tradingsymbol}] fetching {from_dt.date()} to {to_dt.date()}...")
        data = kite.historical_data(token, from_dt, to_dt, "15minute")
        all_rows = data + all_rows
        to_dt = from_dt
        remaining -= chunk

    df = pd.DataFrame(all_rows).drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    return df


def analyze_weekly_cycles(candles: pd.DataFrame, entry_weekday: str, entry_time: str,
                           squareoff_time: str, distance: float) -> pd.DataFrame:
    """
    For every occurrence of `entry_weekday` in the data, takes the price at
    the first candle at/after entry_time as the reference, then checks the
    underlying's path up to squareoff_time the NEXT calendar day for a
    breach of reference +/- distance.
    """
    results = []
    entry_dates = sorted(set(d.date() for d in candles["date"] if d.strftime("%A") == entry_weekday))

    for entry_date in entry_dates:
        day_candles = candles[candles["date"].dt.date == entry_date]
        entry_candles = day_candles[day_candles["date"].dt.strftime("%H:%M") >= entry_time]
        if entry_candles.empty:
            continue
        entry_row = entry_candles.iloc[0]
        ref = entry_row["open"]
        entry_dt = entry_row["date"]

        upper = ref + distance
        lower = ref - distance

        cutoff_date = entry_date + timedelta(days=1)
        cutoff_dt = datetime.combine(cutoff_date, datetime.strptime(squareoff_time, "%H:%M").time())

        window = candles[(candles["date"] > entry_dt) & (candles["date"] <= cutoff_dt)]
        if window.empty:
            continue  # likely the square-off day was a holiday -- skip, can't determine outcome

        ce_breach = (window["high"] >= upper).any()
        pe_breach = (window["low"] <= lower).any()

        if ce_breach and pe_breach:
            outcome = "BOTH_BREACHED"
        elif ce_breach:
            outcome = "CE_BREACHED"
        elif pe_breach:
            outcome = "PE_BREACHED"
        else:
            outcome = "BOTH_SURVIVED (max profit)"

        results.append({
            "entry_date": entry_date, "reference": round(ref, 2),
            "upper": round(upper, 2), "lower": round(lower, 2), "outcome": outcome,
        })

    return pd.DataFrame(results)


def print_summary(label: str, df: pd.DataFrame):
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    if df.empty:
        print("No cycles found in this data.")
        return
    total = len(df)
    print(f"Total weekly cycles analyzed: {total}\n")
    counts = df["outcome"].value_counts()
    for outcome, count in counts.items():
        print(f"  {outcome}: {count} ({count/total*100:.1f}%)")


def main():
    kite = get_kite_session()

    # ---- NIFTY ----
    print("\nFetching NIFTY 50 index candles...")
    nifty_candles = fetch_index_candles(kite, "NSE", "NIFTY 50", BACKTEST_DAYS)
    if not nifty_candles.empty:
        print(f"Got {len(nifty_candles)} candles, {nifty_candles['date'].min()} to {nifty_candles['date'].max()}")
        nifty_results = analyze_weekly_cycles(
            nifty_candles, config.IC_ENTRY_DAY_NIFTY, config.IC_ENTRY_TIME_NIFTY,
            config.IC_SQUAREOFF_TIME_NIFTY, config.IC_SHORT_DISTANCE_NIFTY,
        )
        print_summary(f"NIFTY (Mon->Tue, +/-{config.IC_SHORT_DISTANCE_NIFTY} pts)", nifty_results)
        nifty_results.to_csv("ic_backtest_nifty.csv", index=False)
    else:
        print("No NIFTY candles returned.")

    # ---- SENSEX ----
    print("\nFetching SENSEX index candles...")
    try:
        sensex_candles = fetch_index_candles(kite, "BSE", "SENSEX", BACKTEST_DAYS)
    except Exception as e:
        print(f"Could not fetch SENSEX historical data: {e}")
        sensex_candles = pd.DataFrame()

    if not sensex_candles.empty:
        print(f"Got {len(sensex_candles)} candles, {sensex_candles['date'].min()} to {sensex_candles['date'].max()}")
        sensex_results = analyze_weekly_cycles(
            sensex_candles, config.IC_ENTRY_DAY_SENSEX, config.IC_ENTRY_TIME_SENSEX,
            config.IC_SQUAREOFF_TIME_SENSEX, config.IC_SHORT_DISTANCE_SENSEX,
        )
        print_summary(f"SENSEX (Wed->Thu, +/-{config.IC_SHORT_DISTANCE_SENSEX} pts)", sensex_results)
        sensex_results.to_csv("ic_backtest_sensex.csv", index=False)
    else:
        print("No SENSEX candles available (Kite may not provide historical SENSEX index data).")

    print("\nRemember: BOTH_SURVIVED = both sides likely expired worthless = max premium kept.")
    print("A breach does NOT necessarily mean a large loss -- it depends on how far past the")
    print("strike price moved and when you exited. This backtest cannot quantify that in rupees.")


if __name__ == "__main__":
    main()
