"""Command line entry point.

  python main.py backtest --synthetic            # plumbing test, fake data
  python main.py backtest --csv data/nifty5m.csv # your own 5-min data
  python main.py backtest --yfinance             # last ~60 days from Yahoo
  python main.py backtest --kite --days 365      # Kite historical (data subscription)
  python main.py login                           # daily Kite login
  python main.py paper                           # live paper trading (no real orders)
"""
import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

from fno_bot.backtest import format_summary, run_backtest, summarize
from fno_bot.config import Config


def main() -> None:
    p = argparse.ArgumentParser(description="Nifty options ORB paper-trading system")
    sub = p.add_subparsers(dest="cmd", required=True)

    bt = sub.add_parser("backtest")
    src = bt.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--yfinance", action="store_true")
    src.add_argument("--kite", action="store_true")
    src.add_argument("--synthetic", action="store_true")
    bt.add_argument("--days", type=int, default=365, help="history length for --kite / --synthetic")
    bt.add_argument("--iv", type=float, help="override implied vol (e.g. 0.12)")
    bt.add_argument("-v", "--verbose", action="store_true", help="log every trade")

    sub.add_parser("login")
    pp = sub.add_parser("paper")
    pp.add_argument("--poll", type=float, default=2.0)

    args = p.parse_args()
    verbose = getattr(args, "verbose", False) or args.cmd == "paper"
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()

    if args.cmd == "login":
        from fno_bot.live import login
        login()
    elif args.cmd == "paper":
        from fno_bot.live import run_paper
        run_paper(cfg, args.poll)
    else:
        from fno_bot import data
        if args.iv:
            cfg.iv = args.iv
        if args.csv:
            df = data.load_csv(args.csv)
        elif args.yfinance:
            df = data.fetch_yfinance()
        elif args.kite:
            from fno_bot.live import kite_client
            df = data.fetch_kite(kite_client(), cfg.spot_token, date.today() - timedelta(days=args.days), date.today())
        else:
            df = data.synthetic(days=args.days)
            print("NOTE: synthetic random-walk data — tests the plumbing only, not the strategy.\n")
        result = run_backtest(df, cfg)
        print("Backtest summary")
        print(format_summary(summarize(result)))
        out = Path("reports")
        out.mkdir(exist_ok=True)
        result["trades"].to_csv(out / "backtest_trades.csv", index=False)
        result["daily"].to_csv(out / "backtest_daily.csv")
        print(f"\nTrades and daily P&L written to {out}/")


if __name__ == "__main__":
    main()
