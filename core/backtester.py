"""
Event-driven backtester: walks bar-by-bar so stop-loss / take-profit and
position sizing behave exactly as they would in live trading (no lookahead).
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.risk_manager import RiskManager
from config import BotConfig


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp | None
    entry_price: float
    exit_price: float | None
    shares: int
    stop_price: float
    target_price: float
    exit_reason: str = ""
    pnl: float = 0.0


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def run_backtest(ind_df: pd.DataFrame, cfg: BotConfig) -> BacktestResult:
    risk = RiskManager(cfg.risk)
    cash = cfg.risk.initial_capital
    equity_curve = []
    trades: list[Trade] = []
    open_trade: Trade | None = None

    dates = ind_df.index

    for i in range(len(ind_df)):
        row = ind_df.iloc[i]
        date = dates[i]
        price = row["close"]

        # mark-to-market equity
        equity = cash + (open_trade.shares * price if open_trade else 0)
        equity_curve.append(equity)

        if open_trade is not None:
            hit_stop = row["low"] <= open_trade.stop_price
            hit_target = row["high"] >= open_trade.target_price
            signal_exit = row["signal"] == -1

            exit_price = None
            reason = ""
            if hit_stop:
                exit_price, reason = open_trade.stop_price, "stop_loss"
            elif hit_target:
                exit_price, reason = open_trade.target_price, "take_profit"
            elif signal_exit:
                exit_price, reason = price, "signal_exit"

            if exit_price is not None:
                cash += open_trade.shares * exit_price
                open_trade.exit_date = date
                open_trade.exit_price = exit_price
                open_trade.exit_reason = reason
                open_trade.pnl = (exit_price - open_trade.entry_price) * open_trade.shares
                trades.append(open_trade)
                open_trade = None

        elif row["signal"] == 1 and not np.isnan(row.get("atr", np.nan)):
            plan = risk.size_position(equity=cash, entry_price=price, atr_value=row["atr"])
            if plan and plan.shares > 0 and plan.shares * price <= cash:
                cash -= plan.shares * price
                open_trade = Trade(
                    entry_date=date,
                    exit_date=None,
                    entry_price=price,
                    exit_price=None,
                    shares=plan.shares,
                    stop_price=plan.stop_price,
                    target_price=plan.target_price,
                )

    # liquidate any open position at the final close for reporting purposes
    if open_trade is not None:
        last_price = ind_df.iloc[-1]["close"]
        cash += open_trade.shares * last_price
        open_trade.exit_date = dates[-1]
        open_trade.exit_price = last_price
        open_trade.exit_reason = "end_of_data"
        open_trade.pnl = (last_price - open_trade.entry_price) * open_trade.shares
        trades.append(open_trade)
        equity_curve[-1] = cash

    equity_series = pd.Series(equity_curve, index=dates, name="equity")
    metrics = compute_metrics(equity_series, trades, cfg.risk.initial_capital)
    return BacktestResult(equity_curve=equity_series, trades=trades, metrics=metrics)


def compute_metrics(equity: pd.Series, trades: list, initial_capital: float) -> dict:
    total_return_pct = (equity.iloc[-1] / initial_capital - 1) * 100

    daily_returns = equity.pct_change().dropna()
    sharpe = 0.0
    if daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    n_days = max((equity.index[-1] - equity.index[0]).days, 1)
    cagr = ((equity.iloc[-1] / initial_capital) ** (365 / n_days) - 1) * 100 if equity.iloc[-1] > 0 else -100

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    return {
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "num_trades": len(trades),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "final_equity": round(equity.iloc[-1], 2),
    }
