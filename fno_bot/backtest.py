"""Replay historical bars through the live engine and report honest statistics."""
from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from .broker import PaperBroker
from .config import Config
from .data import market_hours
from .options import BlackScholesPricer
from .session import TradingSession
from .strategy import Bar


def run_backtest(df: pd.DataFrame, cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    broker = PaperBroker(cfg.slippage_pct)
    session = TradingSession(cfg, BlackScholesPricer(cfg), broker)
    df = market_hours(df)
    daily = {}
    for day, bars in df.groupby(df.index.date):
        session.start_day(day)
        before = len(broker.trades)
        for ts, r in bars.iterrows():
            session.on_bar(Bar(ts.to_pydatetime(), r.open, r.high, r.low, r.close))
        if session.position:  # data ended early that day
            last_ts = bars.index[-1].to_pydatetime()
            session.force_close(last_ts, bars.close.iloc[-1], "end of data")
        daily[day] = sum(t.net_pnl for t in broker.trades[before:])
    trades = pd.DataFrame([asdict(t) for t in broker.trades])
    return {"trades": trades, "daily": pd.Series(daily, name="net_pnl"), "config": cfg}


def summarize(result: dict, daily_goal: float = 10_000) -> dict:
    cfg: Config = result["config"]
    trades, daily = result["trades"], result["daily"]
    equity = cfg.capital + daily.cumsum()
    drawdown = (equity - equity.cummax()).min() if len(equity) else 0.0
    if trades.empty:
        return {"days": len(daily), "trades": 0}
    wins = trades[trades.net_pnl > 0]
    losses = trades[trades.net_pnl <= 0]
    months = max(len(daily) / 21, 1e-9)
    return {
        "days": len(daily),
        "trades": len(trades),
        "net_pnl": round(daily.sum()),
        "return_pct": round(daily.sum() / cfg.capital * 100, 2),
        "avg_per_month": round(daily.sum() / months),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(wins.net_pnl.mean()) if len(wins) else 0,
        "avg_loss": round(losses.net_pnl.mean()) if len(losses) else 0,
        "profit_factor": round(wins.net_pnl.sum() / -losses.net_pnl.sum(), 2) if losses.net_pnl.sum() < 0 else float("inf"),
        "total_charges": round(trades.charges.sum()),
        "max_drawdown": round(drawdown),
        "best_day": round(daily.max()),
        "worst_day": round(daily.min()),
        "green_days_pct": round((daily > 0).sum() / len(daily) * 100, 1),
        f"days_hitting_{int(daily_goal)}": int((daily >= daily_goal).sum()),
        "exit_reasons": trades.exit_reason.value_counts().to_dict(),
    }


def format_summary(s: dict) -> str:
    return "\n".join(f"  {k:<22} {v}" for k, v in s.items())
