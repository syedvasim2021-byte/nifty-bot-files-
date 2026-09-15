"""
All position sizing and stop-the-bot safety logic lives here, separate from
signal generation and order execution, so risk rules can't be accidentally
skipped by a strategy change.

For the breakout+retest strategy (main.py), only can_trade(),
record_trade_opened(), and record_trade_closed() are actually used --
position sizing is fixed (config.STRATEGY_FIXED_LOTS) and the stop-loss is
structural (candle-level, handled in strategy.py + main.py), not %-based.
position_size() and check_exit() below are kept as legacy/reusable building
blocks in case you build a different %-risk-based strategy later.
"""
import config
from logger_setup import get_logger

log = get_logger()


class RiskManager:
    def __init__(self):
        self.trades_today = 0
        self.realized_pnl_today = 0.0
        self.max_daily_loss = config.CAPITAL * (config.MAX_DAILY_LOSS_PCT / 100)

    def can_trade(self) -> tuple[bool, str]:
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return False, f"Max trades/day reached ({config.MAX_TRADES_PER_DAY})"
        if self.realized_pnl_today <= -self.max_daily_loss:
            return False, (
                f"Daily loss limit hit: {self.realized_pnl_today:.0f} "
                f"<= -{self.max_daily_loss:.0f}"
            )
        return True, ""

    def position_size(self, premium: float, lot_size: int) -> int:
        """
        Returns number of LOTS to buy, sized so that a full stop-loss hit
        risks approximately RISK_PER_TRADE_PCT of capital, capped by
        MAX_LOTS_PER_TRADE.
        """
        if premium <= 0 or lot_size <= 0:
            return 0

        risk_amount = config.CAPITAL * (config.RISK_PER_TRADE_PCT / 100)
        risk_per_lot = premium * lot_size * (config.STOP_LOSS_PCT / 100)
        if risk_per_lot <= 0:
            return 0

        lots = int(risk_amount // risk_per_lot)
        lots = max(1, min(lots, config.MAX_LOTS_PER_TRADE))
        return lots

    def record_trade_opened(self):
        self.trades_today += 1

    def record_trade_closed(self, pnl: float):
        self.realized_pnl_today += pnl
        log.info(
            f"Trade closed. PnL: {pnl:.2f} | Day PnL: {self.realized_pnl_today:.2f} "
            f"| Trades today: {self.trades_today}/{config.MAX_TRADES_PER_DAY}"
        )

    def check_exit(self, entry_price: float, ltp: float) -> str | None:
        """Premium-based stop-loss / target check for a long option position."""
        if entry_price <= 0:
            return None
        change_pct = (ltp - entry_price) / entry_price * 100
        if change_pct <= -config.STOP_LOSS_PCT:
            return "STOP_LOSS"
        if change_pct >= config.TARGET_PCT:
            return "TARGET"
        return None
