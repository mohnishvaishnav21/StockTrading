"""Opening Range Breakout (ORB) on the Nifty index.

Rules
-----
1. Record the high/low of 09:15–09:30 (the opening range, OR).
2. Skip the day if the OR is too tight (chop) or too wide (risk too big).
3. A 5-min candle CLOSING above OR high → buy ATM Call (CE).
   A 5-min candle CLOSING below OR low  → buy ATM Put  (PE).
4. Stop on the index = OR midpoint. Target = entry ± reward_risk × stop distance.
5. At most one trade per direction per day; no entries after the cutoff.

Why this strategy: it is simple, widely studied, has few parameters to overfit,
and has a defined stop before entry so position size can be computed from risk.
It is NOT guaranteed to be profitable — run the backtest and paper trade first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Config


@dataclass
class Bar:
    ts: datetime  # bar START time
    open: float
    high: float
    low: float
    close: float


@dataclass
class Signal:
    kind: str           # "CE" (bullish) or "PE" (bearish)
    entry: float        # index level at signal
    stop: float         # index stop level
    target: float       # index target level
    reason: str


class OpeningRangeBreakout:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.valid_day: bool | None = None  # decided once OR completes
        self.taken: set[str] = set()

    def on_bar(self, bar: Bar) -> Signal | None:
        cfg = self.cfg
        t = bar.ts.time()
        if t < cfg.market_open:
            return None
        if t < cfg.or_end:
            self.or_high = bar.high if self.or_high is None else max(self.or_high, bar.high)
            self.or_low = bar.low if self.or_low is None else min(self.or_low, bar.low)
            return None
        if self.or_high is None:
            return None  # no data for the opening range (e.g. joined late)
        if self.valid_day is None:
            width_pct = (self.or_high - self.or_low) / self.or_low * 100
            self.valid_day = cfg.min_or_pct <= width_pct <= cfg.max_or_pct
        if not self.valid_day or t >= cfg.entry_cutoff:
            return None

        mid = (self.or_high + self.or_low) / 2
        if bar.close > self.or_high and "CE" not in self.taken:
            self.taken.add("CE")
            risk = bar.close - mid
            return Signal("CE", bar.close, mid, bar.close + cfg.reward_risk * risk,
                          f"close {bar.close:.1f} > OR high {self.or_high:.1f}")
        if bar.close < self.or_low and "PE" not in self.taken:
            self.taken.add("PE")
            risk = mid - bar.close
            return Signal("PE", bar.close, mid, bar.close - cfg.reward_risk * risk,
                          f"close {bar.close:.1f} < OR low {self.or_low:.1f}")
        return None
