"""The trading engine. The SAME code runs backtests and live paper trading:
the only difference is where bars/ticks and option prices come from.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from .broker import PaperBroker, Position, Trade
from .config import Config
from .options import Option, atm_strike, next_expiry
from .risk import RiskManager
from .strategy import Bar, OpeningRangeBreakout

log = logging.getLogger(__name__)


class TradingSession:
    def __init__(self, cfg: Config, pricer, broker: PaperBroker, risk: RiskManager | None = None):
        self.cfg = cfg
        self.pricer = pricer
        self.broker = broker
        self.risk = risk or RiskManager(cfg)
        self.strategy = OpeningRangeBreakout(cfg)
        self.position: Position | None = None
        self.day: date | None = None
        self.is_expiry_day = False

    # ------------------------------------------------------------------ day
    def start_day(self, d: date) -> None:
        if self.position is not None:
            raise RuntimeError("position carried overnight — this must never happen")
        self.day = d
        self.strategy.reset()
        self.risk.start_day(d)
        self.is_expiry_day = next_expiry(d, self.cfg.expiry_weekday) == d
        if self.risk.halted_reason:
            log.warning("%s: trading halted (%s)", d, self.risk.halted_reason)

    # --------------------------------------------------------------- events
    def on_bar(self, bar: Bar) -> Trade | None:
        """Called once per completed bar."""
        bar_end = bar.ts + timedelta(minutes=self.cfg.bar_minutes)
        signal = self.strategy.on_bar(bar)  # always feed so the opening range builds

        if self.position:
            return self._check_exit(bar_end, bar.open, bar.high, bar.low, bar.close)

        if signal is None or not self.risk.can_open():
            return None
        if self.cfg.skip_expiry_day and self.is_expiry_day:
            return None
        self._open(signal, bar_end)
        return None

    def on_tick(self, now: datetime, spot: float) -> Trade | None:
        """Live mode: check stop/target/limits on every price update."""
        if self.position:
            return self._check_exit(now, spot, spot, spot, spot)
        return None

    def force_close(self, now: datetime, spot: float, reason: str) -> Trade | None:
        if self.position:
            return self._close(now, spot, reason)
        return None

    # ------------------------------------------------------------ internals
    def _open(self, signal, now: datetime) -> None:
        cfg = self.cfg
        expiry = next_expiry(now.date(), cfg.expiry_weekday)
        opt = Option(cfg.underlying, expiry, atm_strike(signal.entry, cfg.strike_step), signal.kind)
        premium = self.pricer.price(opt, signal.entry, now)
        delta = self.pricer.delta(opt, signal.entry, now)
        lots = self.risk.size(premium, delta, abs(signal.entry - signal.stop))
        if lots == 0:
            log.info("%s skip %s: 1 lot would risk more than allowed", now, signal.kind)
            return
        qty = lots * cfg.lot_size
        fill = self.broker.buy_fill(premium)
        self.position = Position(opt, qty, now, fill, signal.stop, signal.target, signal.reason)
        self.risk.trades_today += 1
        log.info("%s BUY %s x%d @ %.2f | stop %.1f target %.1f | %s",
                 now, opt, qty, fill, signal.stop, signal.target, signal.reason)

    def _check_exit(self, now, o, h, l, c) -> Trade | None:
        p = self.position
        if p.option.kind == "CE":
            if l <= p.stop:
                return self._close(now, min(o, p.stop), "stop")      # gap-through fills at open
            if h >= p.target:
                return self._close(now, max(o, p.target), "target")
        else:
            if h >= p.stop:
                return self._close(now, max(o, p.stop), "stop")
            if l <= p.target:
                return self._close(now, min(o, p.target), "target")
        if now.time() >= self.cfg.square_off:
            return self._close(now, c, "square-off")
        unrealized = (self.pricer.price(p.option, c, now) - p.entry_price) * p.qty
        if self.risk.breaches_daily_limit(unrealized):
            return self._close(now, c, "daily loss limit")
        return None

    def _close(self, now: datetime, spot: float, reason: str) -> Trade:
        p = self.position
        quoted = self.pricer.price(p.option, spot, now)
        trade = self.broker.close(p, quoted, now, reason)
        self.position = None
        self.risk.record_trade(trade.net_pnl)
        log.info("%s SELL %s @ %.2f (%s) net ₹%.0f | day ₹%.0f",
                 now, p.option, trade.exit_price, reason, trade.net_pnl, self.risk.day_pnl)
        return trade
