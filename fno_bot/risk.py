"""Hard risk limits. The strategy proposes; the risk manager disposes."""
from __future__ import annotations

import math
from datetime import date

from .config import Config


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.day: date | None = None
        self.month: tuple[int, int] | None = None
        self.day_pnl = 0.0
        self.month_pnl = 0.0
        self.trades_today = 0
        self.halted_reason: str | None = None

    def start_day(self, d: date) -> None:
        self.day = d
        self.day_pnl = 0.0
        self.trades_today = 0
        if self.month != (d.year, d.month):
            self.month = (d.year, d.month)
            self.month_pnl = 0.0
        self.halted_reason = None
        if self.month_pnl <= -self.cfg.max_monthly_loss:
            self.halted_reason = "monthly loss limit"

    def record_trade(self, net_pnl: float) -> None:
        self.day_pnl += net_pnl
        self.month_pnl += net_pnl
        if self.day_pnl <= -self.cfg.max_daily_loss:
            self.halted_reason = "daily loss limit"
        if self.month_pnl <= -self.cfg.max_monthly_loss:
            self.halted_reason = "monthly loss limit"

    def can_open(self) -> bool:
        return self.halted_reason is None and self.trades_today < self.cfg.max_trades_per_day

    def breaches_daily_limit(self, unrealized: float) -> bool:
        return self.day_pnl + unrealized <= -self.cfg.max_daily_loss

    def size(self, premium: float, delta: float, stop_distance: float) -> int:
        """Lots such that hitting the stop loses ≤ risk_per_trade. 0 = skip trade."""
        cfg = self.cfg
        loss_per_lot = abs(delta) * stop_distance * cfg.lot_size + 2 * premium * cfg.lot_size * cfg.slippage_pct / 100 + 60
        remaining_today = cfg.max_daily_loss + self.day_pnl
        budget = min(cfg.risk_per_trade, remaining_today)
        lots = math.floor(budget / loss_per_lot) if loss_per_lot > 0 else 0
        max_by_capital = math.floor(cfg.capital * cfg.max_premium_pct / (premium * cfg.lot_size))
        return max(0, min(lots, cfg.max_lots, max_by_capital))
