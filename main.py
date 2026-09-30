"""
CLI entry point.

  python main.py backtest --symbol AAPL --period 2y --interval 1d
  python main.py backtest --synthetic          (no network needed, for a quick demo)
  python main.py paper --symbol AAPL           (runs the local paper-trading loop)

Paper/live mode polls the latest completed bar every `poll_seconds` and
applies the same signal + risk logic used in the backtest, so behaviour is
consistent between research and execution.
"""
import argparse
import time

from config import BotConfig
from core.logger import get_logger
from core.data_handler import fetch_ohlcv, fetch_latest_bar, generate_synthetic
from core.strategy import generate_signals
from core.backtester import run_backtest
from core.report import print_metrics, save_chart
from core.risk_manager import RiskManager
from execution.broker import get_broker

log = get_logger("main")


def cmd_backtest(args):
    cfg = BotConfig(symbol=args.symbol, interval=args.interval, history_period=args.period)
    cfg.risk.initial_capital = args.capital

    if args.synthetic:
        df = generate_synthetic(n=args.synthetic_bars)
        label = "SYNTHETIC"
    else:
        df = fetch_ohlcv(cfg.symbol, period=cfg.history_period, interval=cfg.interval)
        label = cfg.symbol

    ind_df = generate_signals(df, cfg.strategy).dropna(subset=["sma_slow", "atr"])
    result = run_backtest(ind_df, cfg)

    print_metrics(result)
    save_chart(ind_df, result, label)


def cmd_paper(args):
    cfg = BotConfig(symbol=args.symbol, interval=args.interval, broker=args.broker)
    cfg.risk.initial_capital = args.capital

    broker = get_broker(cfg)
    risk = RiskManager(cfg.risk)

    log.info(f"Starting paper trading loop | symbol={cfg.symbol} broker={cfg.broker} "
             f"poll={cfg.poll_seconds}s")

    while True:
        try:
            df = fetch_ohlcv(cfg.symbol, period=cfg.history_period, interval=cfg.interval)
            ind_df = generate_signals(df, cfg.strategy).dropna(subset=["sma_slow", "atr"])
            last = ind_df.iloc[-1]
            price = last["close"]

            equity = broker.get_equity(price)
            if risk.check_daily_loss_limit(equity):
                log.warning("Daily loss limit hit — trading halted until reset.")
                time.sleep(cfg.poll_seconds)
                continue

            shares_held = broker.get_position_shares()

            if last["signal"] == 1 and shares_held == 0:
                plan = risk.size_position(equity, price, last["atr"])
                if plan:
                    broker.buy(plan.shares, price)
                    log.info(f"Entry plan: stop={plan.stop_price} target={plan.target_price}")

            elif last["signal"] == -1 and shares_held > 0:
                broker.sell(shares_held, price)

            log.info(f"Bar close={price:.2f} signal={last['signal']} equity={equity:.2f}")

        except Exception as e:
            log.error(f"Loop error: {e}")

        time.sleep(cfg.poll_seconds)


def build_parser():
    p = argparse.ArgumentParser(description="Rule-based algorithmic trading bot")
    sub = p.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run a historical backtest")
    bt.add_argument("--symbol", default="AAPL")
    bt.add_argument("--period", default="2y")
    bt.add_argument("--interval", default="1d")
    bt.add_argument("--capital", type=float, default=100_000.0)
    bt.add_argument("--synthetic", action="store_true", help="Use generated data, no network call")
    bt.add_argument("--synthetic-bars", type=int, default=500)
    bt.set_defaults(func=cmd_backtest)

    pt = sub.add_parser("paper", help="Run the live paper/real trading loop")
    pt.add_argument("--symbol", default="AAPL")
    pt.add_argument("--interval", default="1d")
    pt.add_argument("--capital", type=float, default=100_000.0)
    pt.add_argument("--broker", choices=["paper", "alpaca"], default="paper")
    pt.set_defaults(func=cmd_paper)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
