from datetime import date, datetime, timedelta

import pytest

from fno_bot.backtest import run_backtest, summarize
from fno_bot.broker import PaperBroker
from fno_bot.config import Config
from fno_bot.costs import round_trip_charges
from fno_bot.data import synthetic
from fno_bot.live import BarBuilder
from fno_bot.options import BlackScholesPricer, Option, atm_strike, black_scholes, next_expiry
from fno_bot.risk import RiskManager
from fno_bot.session import TradingSession
from fno_bot.strategy import Bar, OpeningRangeBreakout

DAY = date(2025, 3, 5)  # a Wednesday (not expiry)


def bar(h, m, o, hi, lo, c):
    return Bar(datetime.combine(DAY, datetime.min.time()).replace(hour=h, minute=m), o, hi, lo, c)


def opening_range(lo=24_980, hi=25_020):
    # three bars 09:15, 09:20, 09:25 → OR 24980–25020 (0.16%), midpoint 25,000
    return [bar(9, 15, 25_000, hi, 24_990, 25_010), bar(9, 20, 25_010, 25_015, lo, 24_995),
            bar(9, 25, 24_995, 25_010, 24_985, 25_000)]


# ---------------------------------------------------------------- pricing
def test_put_call_parity():
    t, r = 5 / 365, 0.065
    c, _ = black_scholes(25_000, 25_000, t, r, 0.13, "CE")
    p, _ = black_scholes(25_000, 25_000, t, r, 0.13, "PE")
    import math
    assert c - p == pytest.approx(25_000 - 25_000 * math.exp(-r * t), abs=0.01)


def test_expiry_and_strike_helpers():
    assert next_expiry(date(2025, 3, 5), 1) == date(2025, 3, 11)  # Wed → next Tue
    assert next_expiry(date(2025, 3, 11), 1) == date(2025, 3, 11)  # Tue → same day
    assert atm_strike(25_024, 50) == 25_000
    assert atm_strike(25_026, 50) == 25_050


def test_charges_are_reasonable():
    # 1 lot of 65 bought at 100, sold at 110: ~₹50–70 in charges
    assert 45 < round_trip_charges(100, 110, 65) < 75


# --------------------------------------------------------------- strategy
def test_orb_long_signal_and_levels():
    s = OpeningRangeBreakout(Config())
    for b in opening_range():
        assert s.on_bar(b) is None
    sig = s.on_bar(bar(9, 30, 25_010, 25_035, 25_005, 25_030))
    assert sig.kind == "CE"
    assert sig.stop == 25_000            # OR midpoint
    assert sig.target == 25_030 + 2 * 30
    # same direction again → no second signal
    assert s.on_bar(bar(9, 35, 25_060, 25_090, 25_055, 25_080)) is None


def test_orb_skips_too_wide_range():
    s = OpeningRangeBreakout(Config())
    for b in opening_range(lo=24_700, hi=25_100):  # 1.6% wide
        s.on_bar(b)
    assert s.on_bar(bar(9, 30, 25_100, 25_200, 25_090, 25_150)) is None


def test_orb_no_entry_after_cutoff():
    s = OpeningRangeBreakout(Config())
    for b in opening_range():
        s.on_bar(b)
    assert s.on_bar(bar(13, 30, 25_040, 25_070, 25_035, 25_060)) is None


# ------------------------------------------------------------------- risk
def test_sizing_respects_risk_and_capital():
    cfg = Config()
    rm = RiskManager(cfg)
    rm.start_day(DAY)
    # delta .5, 60pt stop, 65 qty → ~₹1,950+ per lot → at most 1 lot for ₹2,000 risk
    # delta .5 × 60pt stop × 65 qty ≈ ₹1,950 + costs per lot → over ₹2,000 → skip
    assert rm.size(premium=120, delta=0.5, stop_distance=60) == 0
    # 30pt stop ≈ ₹1,050 per lot → 1 lot
    assert rm.size(premium=120, delta=0.5, stop_distance=30) == 1
    # tiny stop → capped at max_lots
    assert rm.size(premium=120, delta=0.5, stop_distance=5) == cfg.max_lots
    # huge premium → capital cap kicks in
    assert rm.size(premium=10_000, delta=0.5, stop_distance=1) == 0


def test_daily_loss_limit_halts_trading():
    cfg = Config()
    rm = RiskManager(cfg)
    rm.start_day(DAY)
    rm.record_trade(-cfg.max_daily_loss)
    assert not rm.can_open()
    rm.start_day(DAY + timedelta(days=1))
    assert rm.can_open()


def test_monthly_loss_limit_persists_across_days():
    cfg = Config()
    rm = RiskManager(cfg)
    rm.start_day(DAY)
    rm.record_trade(-cfg.max_monthly_loss)
    rm.start_day(DAY + timedelta(days=1))
    assert not rm.can_open()
    rm.start_day(date(2025, 4, 1))  # new month resets
    assert rm.can_open()


# ---------------------------------------------------------------- session
def make_session():
    cfg = Config()
    s = TradingSession(cfg, BlackScholesPricer(cfg), PaperBroker(cfg.slippage_pct))
    s.start_day(DAY)
    return s


def test_session_trade_hits_target():
    s = make_session()
    for b in opening_range():
        s.on_bar(b)
    s.on_bar(bar(9, 30, 25_010, 25_035, 25_005, 25_030))
    assert s.position is not None and s.position.option.kind == "CE"
    s.on_bar(bar(9, 35, 25_030, 25_100, 25_025, 25_095))  # target 25,090
    assert s.position is None
    t = s.broker.trades[0]
    assert t.exit_reason == "target" and t.net_pnl > 0


def test_session_stop_and_square_off():
    s = make_session()
    for b in opening_range():
        s.on_bar(b)
    s.on_bar(bar(9, 30, 25_010, 25_035, 25_005, 25_030))
    s.on_bar(bar(9, 35, 25_030, 25_035, 24_990, 24_995))  # stop 25,000
    assert s.broker.trades[-1].exit_reason == "stop"
    assert s.broker.trades[-1].net_pnl < 0
    # bearish breakout later, held to square-off
    s.on_bar(bar(10, 0, 24_990, 24_995, 24_965, 24_970))
    assert s.position and s.position.option.kind == "PE"
    s.on_bar(bar(15, 10, 24_975, 24_985, 24_960, 24_975))  # bar ends 15:15
    assert s.position is None and s.broker.trades[-1].exit_reason == "square-off"


def test_no_trades_on_expiry_day():
    cfg = Config()
    s = TradingSession(cfg, BlackScholesPricer(cfg), PaperBroker(cfg.slippage_pct))
    s.start_day(date(2025, 3, 11))  # Tuesday expiry
    for b in opening_range():
        s.on_bar(Bar(b.ts.replace(day=11), b.open, b.high, b.low, b.close))
    s.on_bar(Bar(datetime(2025, 3, 11, 9, 30), 25_010, 25_035, 25_005, 25_030))
    assert s.position is None


# ------------------------------------------------------------- end to end
def test_backtest_never_breaches_daily_limit_by_much():
    cfg = Config()
    result = run_backtest(synthetic(days=120), cfg)
    summary = summarize(result)
    assert summary["trades"] > 0
    # gaps/bar granularity can overshoot slightly, never wildly
    assert result["daily"].min() > -cfg.max_daily_loss * 1.5
    assert (result["trades"].exit_time.dt.time <= cfg.square_off).all()


def test_bar_builder_buckets():
    bb = BarBuilder(5)
    t0 = datetime(2025, 3, 5, 9, 15, 1)
    assert bb.update(t0, 100) is None
    assert bb.update(t0 + timedelta(minutes=2), 105) is None
    done = bb.update(t0 + timedelta(minutes=5), 103)
    assert done.ts == datetime(2025, 3, 5, 9, 15) and done.high == 105 and done.close == 105


def test_kite_pricer_with_fake_client():
    from fno_bot.live import KitePricer

    class FakeKite:
        def instruments(self, exch):
            return [{"name": "NIFTY", "instrument_type": "CE", "expiry": date(2025, 3, 11),
                     "strike": 25000.0, "tradingsymbol": "NIFTY2531125000CE", "lot_size": 75}]

        def ltp(self, syms):
            return {s: {"last_price": 123.45} for s in syms}

    cfg = Config()
    pricer = KitePricer(FakeKite(), cfg)
    assert cfg.lot_size == 75  # corrected from the live instrument list
    opt = Option("NIFTY", date(2025, 3, 11), 25_000, "CE")
    assert pricer.price(opt, 25_000, datetime(2025, 3, 5, 10)) == 123.45
    with pytest.raises(KeyError):
        pricer.symbol(Option("NIFTY", date(2025, 3, 11), 25_050, "CE"))


def test_completed_bars_from_1min():
    import pandas as pd
    from fno_bot.live import completed_bars

    idx = pd.date_range("2025-03-05 09:15", periods=12, freq="1min")  # 09:15 … 09:26
    df = pd.DataFrame({"open": range(12), "high": [x + 1 for x in range(12)],
                       "low": range(12), "close": range(12)}, index=idx, dtype=float)
    bars = completed_bars(df, 5, datetime(2025, 3, 5, 9, 27, 10))
    assert [b.ts.minute for b in bars] == [15, 20]   # 09:25 bar still forming
    assert bars[0].open == 0 and bars[0].high == 5 and bars[0].close == 4


def test_daily_loss_cap_is_3000():
    assert Config().max_daily_loss == 3_000
