"""Option contracts, expiry helpers and pricers."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .config import Config

MINUTES_PER_YEAR = 365 * 24 * 60
EXPIRY_TIME = time(15, 30)


@dataclass(frozen=True)
class Option:
    underlying: str
    expiry: date
    strike: float
    kind: str  # "CE" or "PE"

    def __str__(self) -> str:
        return f"{self.underlying} {self.expiry:%d-%b} {int(self.strike)} {self.kind}"


def next_expiry(d: date, weekday: int) -> date:
    """Nearest weekly expiry on or after `d` (exchange holidays are not handled)."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def atm_strike(spot: float, step: int) -> float:
    return round(spot / step) * step


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(spot: float, strike: float, t_years: float, r: float, iv: float, kind: str):
    """Return (price, delta) for a European option."""
    t = max(t_years, 1e-6)
    sq = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / sq
    d2 = d1 - sq
    if kind == "CE":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
    return max(price, 0.05), delta  # 0.05 = NSE tick size floor


def years_to_expiry(opt: Option, now: datetime) -> float:
    expiry_dt = datetime.combine(opt.expiry, EXPIRY_TIME)
    minutes = max((expiry_dt - now).total_seconds() / 60.0, 15.0)
    return minutes / MINUTES_PER_YEAR


class BlackScholesPricer:
    """Prices options from the index level. Used for backtests and as a fallback.

    This is an approximation: real premiums include IV changes (spikes on big
    moves, crush after events) and skew, which a flat IV ignores.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def price(self, opt: Option, spot: float, now: datetime) -> float:
        return black_scholes(spot, opt.strike, years_to_expiry(opt, now),
                             self.cfg.risk_free, self.cfg.iv, opt.kind)[0]

    def delta(self, opt: Option, spot: float, now: datetime) -> float:
        return black_scholes(spot, opt.strike, years_to_expiry(opt, now),
                             self.cfg.risk_free, self.cfg.iv, opt.kind)[1]
