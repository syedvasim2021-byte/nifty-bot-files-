# Nifty 50 Options Auto-Trade Bot (Zerodha Kite Connect)

A modular framework for automating Nifty 50 index option buying through
Zerodha's Kite Connect API. It is a **skeleton with a sensible risk-management
layer**, not a profitable strategy — you must supply and validate your own
signal logic (`strategy.py`) before risking real capital.

## ⚠️ Read this first

- **Not financial advice.** No strategy included here has been backtested or
  is guaranteed to be profitable. Nifty options bought outright lose value to
  time decay (theta) every single day they're held, even if the index doesn't
  move against you.
- **This is not a toy risk.** SEBI's own data shows the large majority of
  retail F&O traders lose money overall. Start with capital you can afford
  to lose entirely, and size positions accordingly.
- Always run with `DRY_RUN=true` first (the default) and watch it through
  multiple full sessions before ever flipping it to live.

## Regulatory compliance — SEBI's retail algo framework (current as of Sep 2026)

SEBI's retail algorithmic trading framework (circular from Feb 2025) is now
**fully in force** — the last phase became mandatory for all brokers on
April 1, 2026. Before running this bot with real orders, you need:

1. **A registered static IP.** Brokers now require API order traffic to come
   from a static IP address that's whitelisted against your API key. If
   you're running this from a laptop/home connection or a cloud box with a
   dynamic IP, you'll need a static-IP solution (a VPS with a fixed IP, or a
   static-IP proxy service) and to register that IP in your Kite Connect
   developer console.
2. **An exchange-issued Algo-ID for your strategy.** Every order placed by an
   algorithm must carry a unique ID issued by the exchange, and brokers are
   legally responsible for every algorithm running on their platform. For a
   self-built bot, this means registering your strategy with Zerodha through
   whatever self-built-algo process they have in place — check Zerodha's
   current support docs / Kite Connect developer forum for the exact steps,
   since the process is still evolving.
3. **No official sandbox.** Zerodha does not provide a Kite Connect sandbox
   environment, so `DRY_RUN` mode in this project (which simulates order
   placement and logs everything to `logs/trades.csv` without calling the
   order API) is your main way to validate behavior before going live.

None of this is legal advice — confirm current requirements directly with
your broker and, if in doubt, a professional familiar with SEBI's rules,
since requirements have been changing on a rolling basis.

## Project layout

```
config.py          Loads all settings from .env — nothing is hardcoded
auth.py             Daily Kite Connect login (official manual flow, no stored password)
instruments.py      Finds nearest-expiry ATM CE/PE, reads lot size live (never hardcoded)
strategy.py          <-- REPLACE THIS with your own signal logic
risk_manager.py     Position sizing, daily loss cutoff, max trades/day, SL/target checks
executor.py          Order placement, DRY_RUN simulation, required market_protection param
main.py              Orchestration loop
logs/                bot.log (all activity) and trades.csv (trade journal)
```

## Setup

1. **Get API access**: sign up at developers.kite.trade, create an app, and
   subscribe to the Kite Connect plan (paid per API key — check current
   pricing on their site). You already need an active Zerodha trading
   account.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` / `KITE_API_SECRET`
   plus your risk settings. Leave `DRY_RUN=true`.
4. Run it:
   ```
   python main.py
   ```
   On first run it prints a login URL — open it, log in with your normal
   Zerodha credentials + 2FA, and paste the `request_token` from the
   redirect URL back into the terminal when prompted. This is required once
   per day (Kite access tokens expire daily by design).
5. Watch `logs/bot.log` and `logs/trades.csv` for a while in DRY_RUN before
   even considering live mode.

## The strategy (15-min breakout + retest)

Implemented in `strategy.py`, evaluated on NIFTY 50 index 15-min candles:

**CE (bullish):** a candle closes above the previous candle's high (breakout;
previous candle's high = reference level) → wait for a later candle to dip
into that level and close back above it (confirmed retest) → buy 1 lot ATM
CE → stop loss starts at the reference candle's low, and after every new
15-min candle close, the stop loss is updated to literally equal *that*
candle's low (not just tightened — it moves however the candles dictate).

**PE (bearish):** exact mirror — breakout below the previous candle's low,
retest is a bounce back down through it, stop loss trails to each new
candle's high.

A pending (not-yet-retested) breakout is replaced the moment a fresher
breakout candle appears — only the most recent one is ever tracked.

Stop-loss *levels* update once per candle close, but breaches are checked
against live underlying LTP on every poll (every `POLL_INTERVAL_SECONDS`),
so a fast move against the position doesn't sit unprotected for up to 15
minutes waiting for the next candle.

**Assumptions baked in — confirm these match your intent:**
- Breakout/retest signals run on the index (NIFTY 50 spot), not futures.
- "Crosses"/"retest" = candle *close* beyond the level, not a wick-only touch.
- Position size is a **fixed** `STRATEGY_FIXED_LOTS` (default 1), not
  %-risk-based sizing, per your spec.
- Only one position at a time; while a trade is open the bot stops scanning
  for new breakout/retest setups and resumes once flat.

To change any of this, `strategy.py` is where the pattern-matching logic
lives, and `main.py` is where SL trailing/breach checks happen.

## Key risk parameters (in `.env`)

| Setting | What it does |
|---|---|
| `STRATEGY_FIXED_LOTS` | Lots bought per trade (fixed, per your spec — default 1) |
| `MAX_DAILY_LOSS_PCT` | Bot stops opening new trades once daily realized loss hits this |
| `MAX_TRADES_PER_DAY` | Hard cap on entries per session |
| `MAX_LOTS_PER_TRADE` | Safety ceiling on `STRATEGY_FIXED_LOTS`, in case it's misconfigured |
| `SQUARE_OFF_TIME` | Forced exit time for intraday (MIS) positions |
| `POLL_INTERVAL_SECONDS` | How often live LTP is checked for a stop-loss breach |

`RISK_PER_TRADE_PCT` / `STOP_LOSS_PCT` / `TARGET_PCT` still exist in `.env`
but are legacy — unused by this strategy, kept only so the old %-based
methods in `risk_manager.py` still run if you call them yourself later.

## Known limitations to address before going live

- No retry/reconciliation logic if an order's status is ambiguous (e.g.
  network drop right after placing an order) — add order-status polling via
  `kite.order_history()` before trusting this with real money.
- No handling for partial fills.
- Single position at a time by design — extend `main.py` if you want
  multiple concurrent positions.
- Strategy runs on the underlying's price, not the option's own price
  action — for options-specific strategies (IV-based, Greeks-based) you'll
  need to fetch and analyze the option chain directly.

## Iron Condor strategy (NIFTY) — `iron_condor_main.py`

A separate, independent strategy from the breakout+retest bot above. Run it
with its own `python iron_condor_main.py` (separate `screen` session if you
want both strategies running at once — they don't share state).

**Rules:**
- Monday `IC_ENTRY_TIME_NIFTY` (default 09:30): capture NIFTY spot as the
  reference. Sell CE at ref+250, sell PE at ref-250. Buy CE at ref+450 and
  PE at ref-450 as hedges (`IC_SHORT_DISTANCE_NIFTY` / `IC_WING_WIDTH_NIFTY`
  in `.env`, both configurable). Max loss per side is capped at the wing
  width minus premium collected, thanks to the hedge legs.
- If spot crosses ref+250 at any point, the call spread (short CE + hedge
  CE) is closed immediately — the put spread keeps running independently.
  Mirror for ref-250 on the put side.
- Whatever is still open gets force-closed Tuesday at
  `IC_SQUAREOFF_TIME_NIFTY` (default 15:15).
- Position spans two calendar days, so state (reference price, which legs/
  sides are open) is persisted to `ic_state_nifty.json`. If the bot is
  restarted for the daily Kite re-login, it picks up exactly where it left
  off instead of losing track of an open position.

**Not yet implemented:** the holiday fallback (entering Friday afternoon if
Monday is a trading holiday) — deliberately deferred until the core
Monday→Tuesday flow has been watched running correctly. Right now, if
Monday is a holiday, the bot will simply not find an entry condition that
day and nothing will happen — check `logs/bot.log` if a Monday goes by with
no entry logged.

**Operational note:** because this position runs overnight, the daily Kite
login (access tokens expire ~6 AM) needs to happen on *both* Monday morning
(for entry) and Tuesday morning (to keep monitoring/square-off working) —
you need to be available to complete the manual login step on both days.

**Sensex version:** not yet built — same structure, different index/expiry
day/point distances (Wednesday entry, Thursday exit, ±700 points). Ask for
it once the NIFTY version has been validated.

## Iron Condor strategy (SENSEX) — `sensex_main.py`

Fully independent from `iron_condor_main.py` (NIFTY) — separate files
(`sensex_instruments.py`, `sensex_executor.py`), separate state file
(`ic_state_sensex.json`), separate screen session. Run with its own
`python sensex_main.py`.

**Key differences from the NIFTY version:**
- Trades on **BSE** (exchange code `BFO`), not NSE — SENSEX options don't
  exist on NFO.
- Entry: **Wednesday** 09:30 (`IC_ENTRY_TIME_SENSEX`). Square-off:
  **Thursday** 15:15 (`IC_SQUAREOFF_TIME_SENSEX`) — SENSEX's weekly expiry
  day is Thursday (vs NIFTY's Tuesday), so this follows the same T-1-to-
  expiry pattern.
- Short strikes = spot ± `IC_SHORT_DISTANCE_SENSEX` (default 700). Hedge
  strikes = short strikes ± `IC_WING_WIDTH_SENSEX` further out (default
  700, i.e. hedge sits at spot ± 1400).
- Same partial-exit rule as NIFTY: a breached side closes on its own, the
  other side keeps running until its own breach or Thursday square-off.

**Before going live**, confirm the BFO segment is activated on your Zerodha
account (Console → segment activation) — orders fail with a clear error if
it isn't, but it's worth checking ahead of time.

**Operational note**: same daily-login requirement as NIFTY, but on
Wednesday and Thursday instead of Monday and Tuesday. If you're running
both strategies, that's 4 days a week (Mon, Tue, Wed, Thu) you need to be
available for the login step — Friday through Sunday, neither bot needs
you.
