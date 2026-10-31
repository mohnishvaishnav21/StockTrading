"""All tunable settings in one place.

Every rupee limit here is a HARD limit enforced in code, not a suggestion.
Defaults are sized for ₹2,00,000 capital trading Nifty options (buying only).
"""
from dataclasses import dataclass
from datetime import time


@dataclass
class Config:
    # --- Account ---------------------------------------------------------
    capital: float = 200_000

    # --- Instrument --------------------------------------------------------
    underlying: str = "NIFTY"          # name as it appears in Kite's NFO instrument dump
    spot_symbol: str = "NSE:NIFTY 50"  # Kite LTP key for the index
    spot_token: int = 256265           # Kite instrument token for NIFTY 50 (historical data)
    # NSE revises lot sizes periodically. Verify the current Nifty lot size before
    # trusting any rupee numbers; in live paper mode the bot reads it from Kite and warns.
    lot_size: int = 65
    strike_step: int = 50
    expiry_weekday: int = 1            # 0=Mon … 1=Tue (Nifty weekly expiry). Holidays not handled.

    # --- Strategy: Opening Range Breakout on 5-min Nifty bars ----------------
    bar_minutes: int = 5
    market_open: time = time(9, 15)
    or_end: time = time(9, 30)         # opening range = 09:15–09:30
    entry_cutoff: time = time(13, 30)  # no new trades after this
    square_off: time = time(15, 15)    # everything closed by this time
    min_or_pct: float = 0.15           # skip days whose opening range is too tight (chop) …
    max_or_pct: float = 0.90           # … or too wide (risk too big for the account)
    reward_risk: float = 2.0           # target = 2 × stop distance on the index
    max_trades_per_day: int = 2
    skip_expiry_day: bool = True       # avoid 0-DTE gamma/theta lottery

    # --- Risk (hard limits) ---------------------------------------------------
    risk_per_trade: float = 2_000      # 1% of capital at the planned stop
    max_daily_loss: float = 4_000      # 2% — stop trading for the day
    max_monthly_loss: float = 20_000   # 10% — stop trading for the rest of the month
    max_lots: int = 2
    max_premium_pct: float = 0.30      # never put more than 30% of capital into premium

    # --- Simulation assumptions (backtest / paper without live option prices) --
    iv: float = 0.13                   # annualised implied vol used for Black-Scholes pricing
    risk_free: float = 0.065
    slippage_pct: float = 0.5          # % of premium lost per side (bid-ask + impact)
