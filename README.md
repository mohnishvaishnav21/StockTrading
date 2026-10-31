# Nifty Options Paper-Trading System (Zerodha)

An automated **paper-trading** system for Nifty weekly options, built to be
honest about results before any real money is involved.

> **No strategy is foolproof, and no system can promise a fixed daily profit.**
> This one is designed to *find out* whether an edge exists — with strict loss
> limits — not to chase a number. It never places real orders.

## What it does

| Part | File | Purpose |
|---|---|---|
| Strategy | `fno_bot/strategy.py` | Opening Range Breakout on 5-min Nifty: break above 09:15–09:30 high → buy ATM Call; break below low → buy ATM Put |
| Risk manager | `fno_bot/risk.py` | Hard limits: ₹2,000 risk/trade, ₹4,000 max daily loss, ₹20,000 max monthly loss, max 2 lots, max 2 trades/day |
| Engine | `fno_bot/session.py` | One engine for backtest **and** live paper — stop/target/square-off/limit checks |
| Costs | `fno_bot/costs.py` | Zerodha options charges: brokerage, STT, exchange, SEBI, stamp, GST |
| Backtest | `fno_bot/backtest.py` | Replays history, reports win rate, drawdown, profit factor, charges |
| Live paper | `fno_bot/live.py` | Real prices from Kite Connect, simulated fills, journal in `journal/paper_trades.csv` |

All settings live in `fno_bot/config.py` (sized for ₹2,00,000 capital).

## Setup

```bash
pip install -r requirements.txt
python -m pytest              # 15 tests
python main.py backtest --synthetic   # checks everything runs (fake data!)
```

## The plan (don't skip steps)

**Phase 1 — Backtest on real data (now).**
```bash
python main.py backtest --yfinance          # free, only last ~60 days of 5-min data
python main.py backtest --csv my_nifty_5m.csv   # columns: datetime,open,high,low,close
```
60 days is not enough to judge anything. Aim for 1–2 years of 5-min data
(Kite historical data, or a CSV from any data vendor):
```bash
python main.py backtest --kite --days 730
```
Trades and daily P&L go to `reports/`. Backtests price options with
Black-Scholes at a flat IV (`--iv` to change), so treat results as approximate.

**Phase 2 — Live paper trading (4–6 weeks minimum).**
1. Create an app at the Kite Connect developer console (paid subscription for
   market data — check Zerodha's site for current pricing). Set its redirect URL.
2. Export credentials (never commit them):
   ```bash
   export KITE_API_KEY=...  KITE_API_SECRET=...
   ```
3. Every trading morning before 09:15:
   ```bash
   python main.py login     # Kite tokens expire daily
   python main.py paper     # runs until 15:16, uses REAL option prices, fake fills
   ```

**Phase 3 — Only then consider real money**, and only if paper results show:
- profit factor > 1.3 **after** charges, over 40+ trades
- max drawdown you could genuinely stomach in real money
- results roughly matching the backtest (if not, the backtest was lying)

Real order placement is intentionally not implemented. Going live also brings
SEBI's retail algo rules (static IP, broker-side registration for algos above
the order-rate threshold) — check current requirements with Zerodha first.

## Honest expectations

- ₹2L capital → a good month for a solid strategy is maybe 2–5%
  (₹4–10k **per month**), with losing months mixed in. ₹10k/day would be
  ~5% per day; strategies that "do" that blow up accounts.
- The backtest prints `days_hitting_10000` so you can see how rare that is.
- SEBI's studies found ~9 in 10 individual F&O traders lose money.

## Known limitations
- Exchange holidays aren't handled (expiry shifts; the live mode errors loudly
  if the option isn't in Kite's instrument list).
- Live bars are built from polled LTPs (every 2 s), not exchange candles.
- Verify the Nifty lot size in `config.py`; live mode auto-corrects it from Kite.
