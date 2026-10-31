"""Live PAPER trading on Zerodha Kite Connect.

Reads real Nifty and real option prices from Kite, runs the strategy, and
records simulated fills to journal/paper_trades.csv. It never places orders.
"""
from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

from .broker import PaperBroker
from .config import Config
from .options import BlackScholesPricer, Option
from .session import TradingSession
from .strategy import Bar

log = logging.getLogger(__name__)
TOKEN_FILE = Path(".kite_token")


# ------------------------------------------------------------------ auth
def kite_client():
    from kiteconnect import KiteConnect

    api_key = os.environ["KITE_API_KEY"]
    kite = KiteConnect(api_key=api_key)
    if TOKEN_FILE.exists():
        kite.set_access_token(TOKEN_FILE.read_text().strip())
    return kite


def login() -> None:
    """Kite access tokens expire daily (~6 AM). Run this once each morning."""
    kite = kite_client()
    print("1. Open this URL and log in:\n  ", kite.login_url())
    print("2. After login you are redirected to your app's redirect URL; copy the request_token from it.")
    request_token = input("request_token: ").strip()
    data = kite.generate_session(request_token, api_secret=os.environ["KITE_API_SECRET"])
    TOKEN_FILE.write_text(data["access_token"])
    print("Saved access token to", TOKEN_FILE)


# --------------------------------------------------------------- pricing
class KitePricer:
    """Real option LTPs from Kite; Black-Scholes only for delta (sizing)."""

    def __init__(self, kite, cfg: Config):
        self.kite, self.cfg = kite, cfg
        self.bs = BlackScholesPricer(cfg)
        self._symbols: dict[tuple, str] = {}
        for ins in kite.instruments("NFO"):
            if ins["name"] == cfg.underlying and ins["instrument_type"] in ("CE", "PE"):
                self._symbols[(ins["expiry"], float(ins["strike"]), ins["instrument_type"])] = ins["tradingsymbol"]
                if ins["lot_size"] != cfg.lot_size:
                    log.warning("Kite lot size %s != config lot_size %s — updating config",
                                ins["lot_size"], cfg.lot_size)
                    cfg.lot_size = ins["lot_size"]
        self.expiries = sorted({k[0] for k in self._symbols})

    def symbol(self, opt: Option) -> str:
        key = (opt.expiry, float(opt.strike), opt.kind)
        if key not in self._symbols:
            raise KeyError(f"{opt} not in Kite instrument list (holiday-shifted expiry?)")
        return "NFO:" + self._symbols[key]

    def price(self, opt: Option, spot: float, now: datetime) -> float:
        sym = self.symbol(opt)
        return float(self.kite.ltp([sym])[sym]["last_price"])

    def delta(self, opt: Option, spot: float, now: datetime) -> float:
        return self.bs.delta(opt, spot, now)


# ----------------------------------------------------------- bar builder
class BarBuilder:
    """Turns polled LTPs into fixed-interval bars aligned to 09:15."""

    def __init__(self, minutes: int):
        self.minutes = minutes
        self.cur: Bar | None = None

    def bucket(self, now: datetime) -> datetime:
        open_ = now.replace(hour=9, minute=15, second=0, microsecond=0)
        n = int((now - open_).total_seconds() // (self.minutes * 60))
        return open_ + timedelta(minutes=n * self.minutes)

    def update(self, now: datetime, price: float) -> Bar | None:
        b = self.bucket(now)
        done = None
        if self.cur and self.cur.ts != b:
            done, self.cur = self.cur, None
        if self.cur is None:
            self.cur = Bar(b, price, price, price, price)
        else:
            self.cur.high = max(self.cur.high, price)
            self.cur.low = min(self.cur.low, price)
            self.cur.close = price
        return done


# ------------------------------------------------------------- main loop
def run_paper(cfg: Config | None = None, poll_seconds: float = 2.0) -> None:
    cfg = cfg or Config()
    kite = kite_client()
    pricer = KitePricer(kite, cfg)
    broker = PaperBroker(cfg.slippage_pct, journal_path="journal/paper_trades.csv")
    session = TradingSession(cfg, pricer, broker)
    builder = BarBuilder(cfg.bar_minutes)

    now = datetime.now()
    if now.time() > cfg.or_end:
        log.warning("Started after %s — opening range is missing, no trades today.", cfg.or_end)
    session.start_day(now.date())
    log.info("Paper trading %s, capital ₹%.0f, daily loss cap ₹%.0f",
             cfg.underlying, cfg.capital, cfg.max_daily_loss)

    close_time = (datetime.combine(now.date(), cfg.square_off) + timedelta(minutes=1)).time()
    spot = None
    while True:
        now = datetime.now()
        if now.time() >= close_time:
            break
        try:
            spot = float(kite.ltp([cfg.spot_symbol])[cfg.spot_symbol]["last_price"])
        except Exception as e:  # network blips must not kill the loop
            log.error("LTP fetch failed: %s", e)
            _time.sleep(poll_seconds)
            continue
        if now.time() >= cfg.market_open:
            session.on_tick(now, spot)
            bar = builder.update(now, spot)
            if bar:
                session.on_bar(bar)
        _time.sleep(poll_seconds)

    if session.position and spot is not None:
        session.force_close(datetime.now(), spot, "square-off")
    log.info("Day done. Trades: %d, net ₹%.0f", len(broker.trades), session.risk.day_pnl)


# ------------------------------------------------- free mode (no Kite needed)
def completed_bars(df_1m, minutes: int, now: datetime) -> list[Bar]:
    """Group 1-min candles into `minutes` bars; return only bars that have finished."""
    if df_1m.empty:
        return []
    agg = df_1m.resample(f"{minutes}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    last_data = df_1m.index[-1] + timedelta(minutes=1)
    cutoff = min(last_data, now)
    return [Bar(ts.to_pydatetime(), r.open, r.high, r.low, r.close)
            for ts, r in agg.iterrows() if ts + timedelta(minutes=minutes) <= cutoff]


def run_paper_free(cfg: Config | None = None, poll_seconds: float = 60.0) -> None:
    """Paper trade with free Yahoo Finance Nifty data and Black-Scholes option prices.

    Limitations vs the Kite mode: option prices are ESTIMATES from the index
    (real premiums move with IV and skew), Yahoo data can lag by a minute or
    more, and stops are checked once per poll.
    """
    from .data import fetch_yfinance

    cfg = cfg or Config()
    broker = PaperBroker(cfg.slippage_pct, journal_path="journal/paper_trades_free.csv")
    session = TradingSession(cfg, BlackScholesPricer(cfg), broker)
    now = datetime.now()
    if now.time() > cfg.or_end:
        log.warning("Started after %s — opening range is missing, no trades today.", cfg.or_end)
    session.start_day(now.date())
    log.info("FREE paper mode: Yahoo 1-min Nifty + estimated option prices. "
             "Daily loss cap ₹%.0f", cfg.max_daily_loss)

    close_time = (datetime.combine(now.date(), cfg.square_off) + timedelta(minutes=1)).time()
    seen: set[datetime] = set()
    spot = None
    while datetime.now().time() < close_time:
        now = datetime.now()
        try:
            df = fetch_yfinance(period="1d", interval="1m")
            df = df[df.index.date == now.date()]
        except Exception as e:
            log.error("data fetch failed: %s", e)
            _time.sleep(poll_seconds)
            continue
        if not df.empty:
            for bar in completed_bars(df, cfg.bar_minutes, now):
                if bar.ts not in seen:
                    seen.add(bar.ts)
                    session.on_bar(bar)
            spot = float(df.close.iloc[-1])
            session.on_tick(now, spot)
        _time.sleep(poll_seconds)

    if session.position and spot is not None:
        session.force_close(datetime.now(), spot, "square-off")
    log.info("Day done. Trades: %d, net ₹%.0f", len(broker.trades), session.risk.day_pnl)
