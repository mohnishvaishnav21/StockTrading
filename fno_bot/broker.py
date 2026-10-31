"""Paper broker: simulated fills with slippage and real Zerodha charges.

There is deliberately NO live order placement in this codebase yet. Going live
should only happen after weeks of paper results you are happy with.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .costs import round_trip_charges
from .options import Option


@dataclass
class Trade:
    option: str
    qty: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    gross_pnl: float
    charges: float
    net_pnl: float
    exit_reason: str
    signal: str


@dataclass
class Position:
    option: Option
    qty: int
    entry_time: datetime
    entry_price: float
    stop: float      # index level
    target: float    # index level
    signal: str


class PaperBroker:
    def __init__(self, slippage_pct: float, journal_path: str | Path | None = None):
        self.slip = slippage_pct / 100
        self.trades: list[Trade] = []
        self.journal_path = Path(journal_path) if journal_path else None

    def buy_fill(self, quoted: float) -> float:
        return round(quoted * (1 + self.slip), 2)

    def sell_fill(self, quoted: float) -> float:
        return max(round(quoted * (1 - self.slip), 2), 0.05)

    def close(self, pos: Position, quoted_exit: float, now: datetime, reason: str) -> Trade:
        exit_price = self.sell_fill(quoted_exit)
        gross = (exit_price - pos.entry_price) * pos.qty
        charges = round_trip_charges(pos.entry_price, exit_price, pos.qty)
        trade = Trade(str(pos.option), pos.qty, pos.entry_time, pos.entry_price, now,
                      exit_price, round(gross, 2), round(charges, 2), round(gross - charges, 2),
                      reason, pos.signal)
        self.trades.append(trade)
        self._journal(trade)
        return trade

    def _journal(self, trade: Trade) -> None:
        if not self.journal_path:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.journal_path.exists()
        with self.journal_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(trade)))
            if new:
                w.writeheader()
            w.writerow(asdict(trade))
