"""Market data loaders. All return a DataFrame indexed by IST bar-start time
(tz-naive) with columns open, high, low, close.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close"]


def load_csv(path: str) -> pd.DataFrame:
    """CSV with a datetime column (first column or named date/datetime/timestamp) + OHLC."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in ("datetime", "date", "timestamp", "time") if c in df.columns), df.columns[0])
    idx = pd.to_datetime(df[tcol])
    if idx.dt.tz is not None:
        idx = idx.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df.index = idx
    return df[COLS].astype(float).sort_index()


def fetch_yfinance(symbol: str = "^NSEI", period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    """Free data from Yahoo. 5-min bars only go back ~60 days — fine for a smoke
    test, too short to judge a strategy. Use Kite historical data for that."""
    import yfinance as yf

    df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"no data returned for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
    return df[COLS].astype(float)


def fetch_kite(kite, instrument_token: int, start: date, end: date, interval: str = "5minute") -> pd.DataFrame:
    """Kite historical candles (needs the Kite Connect data subscription).
    Kite caps 5-minute requests at 100 days, so this fetches in chunks."""
    frames, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=99), end)
        rows = kite.historical_data(instrument_token, cur, stop, interval)
        if rows:
            frames.append(pd.DataFrame(rows))
        cur = stop + timedelta(days=1)
    if not frames:
        raise RuntimeError("Kite returned no candles")
    df = pd.concat(frames)
    idx = pd.to_datetime(df["date"])
    if idx.dt.tz is not None:
        idx = idx.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df.index = idx
    return df[COLS].astype(float).sort_index()


def synthetic(days: int = 120, start_price: float = 25_000, seed: int = 7) -> pd.DataFrame:
    """Random-walk 5-min Nifty-like bars. ONLY for testing that the plumbing
    works — results on this data say nothing about real-market performance."""
    rng = np.random.default_rng(seed)
    rows, price = [], start_price
    for d in pd.bdate_range("2025-01-01", periods=days):
        steps = 75 * 5                                   # one step per minute
        drift = rng.normal(0, 0.004) / steps             # daily trend ~N(0, 0.4%)
        vol = abs(rng.normal(0.008, 0.002)) / np.sqrt(steps)  # ~0.8% daily vol
        t = datetime.combine(d.date(), datetime.min.time()).replace(hour=9, minute=15)
        price *= 1 + rng.normal(0, 0.003)     # overnight gap
        for _ in range(75):                    # 09:15 → 15:25 bar starts
            o = price
            path = o * np.cumprod(1 + rng.normal(drift, vol, 5))
            c = path[-1]
            rows.append((t, o, max(o, path.max()), min(o, path.min()), c))
            price, t = c, t + timedelta(minutes=5)
    df = pd.DataFrame(rows, columns=["ts", *COLS]).set_index("ts")
    return df


def market_hours(df: pd.DataFrame) -> pd.DataFrame:
    t = df.index.time
    from datetime import time as _t
    return df[(t >= _t(9, 15)) & (t < _t(15, 30))]
