import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from core.backtester import BacktestResult

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def print_metrics(result: BacktestResult):
    print("\n===== BACKTEST RESULTS =====")
    for k, v in result.metrics.items():
        print(f"{k:>18}: {v}")
    print("=============================\n")


def save_chart(ind_df, result: BacktestResult, symbol: str, filename: str = "backtest_report.png"):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(ind_df.index, ind_df["close"], label="Close", color="#1f77b4", linewidth=1)
    ax1.plot(ind_df.index, ind_df["sma_fast"], label=f"SMA fast", color="orange", linewidth=1)
    ax1.plot(ind_df.index, ind_df["sma_slow"], label=f"SMA slow", color="green", linewidth=1)

    for t in result.trades:
        ax1.scatter(t.entry_date, t.entry_price, marker="^", color="green", s=70, zorder=5)
        if t.exit_date is not None:
            color = "red" if t.pnl < 0 else "blue"
            ax1.scatter(t.exit_date, t.exit_price, marker="v", color=color, s=70, zorder=5)

    ax1.set_title(f"{symbol} — Price & Trades")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    ax2.plot(result.equity_curve.index, result.equity_curve.values, color="#333", linewidth=1.2)
    ax2.set_title("Equity Curve")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"Chart saved -> {path}")
    return path
