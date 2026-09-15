"""
Backtests the breakout+retest strategy (see strategy.py) against historical
NIFTY 50 index 15-min candles, fetched via your existing Kite Connect access.

IMPORTANT CAVEAT: this measures the UNDERLYING INDEX's point movement from
entry to exit, not actual option premium P&L. A real ATM option does not
move point-for-point with the index -- it loses value to time decay (theta)
every day it's held, has a bid-ask spread, and its price reacts to implied
volatility changes as well as the index. So:
  - A "win" here (positive index points captured) is a NECESSARY condition
    for the option trade to have been profitable, not a sufficient one.
  - Trades that take many candles to resolve are hurt worse by theta in
    reality than this backtest reflects.
  - Treat this as a check on SIGNAL QUALITY (how often does the pattern
    trigger, and does price move favorably afterward), not a profit
    estimate. A real backtest would need historical option premiums too.

Run with:
    python backtest.py
"""
from datetime import datetime, timedelta
import pandas as pd

import config
from auth import get_kite_session

BACKTEST_DAYS = 180  # change this to backtest a longer/shorter period


def fetch_all_candles(kite, days):
    token = None
    for inst in kite.instruments("NSE"):
        if inst["tradingsymbol"] == "NIFTY 50":
            token = inst["instrument_token"]
            break
    if token is None:
        raise RuntimeError("Could not resolve NIFTY 50 instrument token.")

    all_rows = []
    to_dt = datetime.now()
    remaining = days
    while remaining > 0:
        chunk = min(remaining, 60)  # fetch in 60-day windows regardless of API limits
        from_dt = to_dt - timedelta(days=chunk)
        print(f"  fetching {from_dt.date()} to {to_dt.date()}...")
        data = kite.historical_data(token, from_dt, to_dt, "15minute")
        all_rows = data + all_rows
        to_dt = from_dt
        remaining -= chunk

    df = pd.DataFrame(all_rows).drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    return df


def run_backtest(df):
    """Mirrors strategy.py's rules exactly, walking candle-by-candle."""
    trades = []
    pending = None    # dict: direction, ref_high, ref_low
    position = None   # dict: direction, entry_time, entry_price, sl

    for i in range(1, len(df)):
        prev, curr = df.iloc[i - 1], df.iloc[i]
        t = curr["date"]

        if position is not None:
            # 1. Check breach against the CURRENT sl (set at entry or by the
            #    previous candle) -- this candle has not yet contributed to
            #    trailing.
            breached = False
            exit_price = None
            if position["direction"] == "CE" and curr["low"] <= position["sl"]:
                breached, exit_price = True, position["sl"]
            elif position["direction"] == "PE" and curr["high"] >= position["sl"]:
                breached, exit_price = True, position["sl"]

            forced = t.strftime("%H:%M") >= config.SQUARE_OFF_TIME

            if breached or forced:
                if not breached:
                    exit_price = curr["close"]
                pts = (
                    (exit_price - position["entry_price"])
                    if position["direction"] == "CE"
                    else (position["entry_price"] - exit_price)
                )
                trades.append({
                    "direction": position["direction"],
                    "entry_time": position["entry_time"],
                    "entry_price": position["entry_price"],
                    "exit_time": t,
                    "exit_price": exit_price,
                    "reason": "SL" if breached else "SQUARE_OFF",
                    "points": pts,
                })
                position = None
            else:
                # 2. NOW trail SL to this candle's own extreme, for the next check.
                position["sl"] = curr["low"] if position["direction"] == "CE" else curr["high"]
            continue

        # Flat: scan for breakout / retest exactly like strategy.py
        if curr["close"] > prev["high"]:
            pending = {"direction": "CE", "ref_high": prev["high"], "ref_low": prev["low"]}
            continue
        if curr["close"] < prev["low"]:
            pending = {"direction": "PE", "ref_high": prev["high"], "ref_low": prev["low"]}
            continue

        if pending is None:
            continue

        if pending["direction"] == "CE":
            if curr["low"] <= pending["ref_high"] and curr["close"] >= pending["ref_high"]:
                position = {"direction": "CE", "entry_time": t, "entry_price": curr["close"], "sl": pending["ref_low"]}
                pending = None
        else:
            if curr["high"] >= pending["ref_low"] and curr["close"] <= pending["ref_low"]:
                position = {"direction": "PE", "entry_time": t, "entry_price": curr["close"], "sl": pending["ref_high"]}
                pending = None

    return pd.DataFrame(trades)


def main():
    kite = get_kite_session()
    print(f"Fetching {BACKTEST_DAYS} days of NIFTY 50 15-min candles...")
    df = fetch_all_candles(kite, BACKTEST_DAYS)
    print(f"Got {len(df)} candles, {df['date'].min()} to {df['date'].max()}\n")

    trades = run_backtest(df)
    if trades.empty:
        print("No signals triggered in this period.")
        return

    wins = trades[trades["points"] > 0]
    losses = trades[trades["points"] <= 0]

    print(f"Total signals: {len(trades)}")
    print(f"  CE: {len(trades[trades['direction']=='CE'])}    PE: {len(trades[trades['direction']=='PE'])}")
    print(f"Favorable moves (proxy 'wins'): {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
    print(f"Unfavorable moves (proxy 'losses'): {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
    print(f"Average points per trade: {trades['points'].mean():.2f}")
    print(f"Total points captured: {trades['points'].sum():.2f}")
    print(f"Best trade: {trades['points'].max():.2f} pts   Worst trade: {trades['points'].min():.2f} pts")
    print(f"Avg holding time: {(trades['exit_time'] - trades['entry_time']).mean()}")

    trades.to_csv("backtest_results.csv", index=False)
    print("\nFull trade log saved to backtest_results.csv")
    print("Remember: these are INDEX points, not option P&L -- see the caveat at the top of this file.")


if __name__ == "__main__":
    main()
