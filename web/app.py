"""
Flask web dashboard for the trading bot.
Wraps the existing CLI functionality with a REST API.
"""
import sys
import os
import json
import threading
import time
from datetime import datetime

# Add parent dir to path so we can import the existing modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from config import BotConfig, StrategyConfig, RiskConfig
from core.data_handler import fetch_ohlcv, generate_synthetic
from core.strategy import generate_signals
from core.backtester import run_backtest
from core.risk_manager import RiskManager
from execution.broker import PaperBroker

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "trading-bot-dashboard-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── Global state for paper trading ───────────────────────────────────────────
paper_thread = None
paper_running = False
paper_broker = None
paper_logs = []          # recent log lines for the UI
paper_config = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """Run a backtest and return JSON results."""
    data = request.get_json(force=True)
    symbol = data.get("symbol", "AAPL")
    period = data.get("period", "2y")
    interval = data.get("interval", "1d")
    capital = float(data.get("capital", 100_000))
    use_synthetic = data.get("synthetic", False)
    synthetic_bars = int(data.get("synthetic_bars", 500))

    # Strategy params
    fast_sma = int(data.get("fast_sma", 20))
    slow_sma = int(data.get("slow_sma", 50))
    rsi_period = int(data.get("rsi_period", 14))
    rsi_overbought = float(data.get("rsi_overbought", 70))

    strat = StrategyConfig(fast_sma=fast_sma, slow_sma=slow_sma,
                           rsi_period=rsi_period, rsi_overbought=rsi_overbought)
    cfg = BotConfig(symbol=symbol, interval=interval, history_period=period, strategy=strat)
    cfg.risk.initial_capital = capital

    try:
        if use_synthetic:
            df = generate_synthetic(n=synthetic_bars)
            label = "SYNTHETIC"
        else:
            df = fetch_ohlcv(cfg.symbol, period=cfg.history_period, interval=cfg.interval)
            label = cfg.symbol

        ind_df = generate_signals(df, cfg.strategy).dropna(subset=["sma_slow", "atr"])
        result = run_backtest(ind_df, cfg)

        # Build JSON-friendly response
        # Price chart data
        dates = [d.strftime("%Y-%m-%d") for d in ind_df.index]
        chart_data = {
            "dates": dates,
            "close": ind_df["close"].round(2).tolist(),
            "sma_fast": ind_df["sma_fast"].round(2).tolist(),
            "sma_slow": ind_df["sma_slow"].round(2).tolist(),
            "rsi": ind_df["rsi"].round(2).tolist(),
            "macd": ind_df["macd"].round(4).tolist(),
            "macd_signal": ind_df["macd_signal"].round(4).tolist(),
            "macd_hist": ind_df["macd_hist"].round(4).tolist(),
            "volume": ind_df["volume"].tolist(),
        }

        # Equity curve
        eq_dates = [d.strftime("%Y-%m-%d") for d in result.equity_curve.index]
        equity_data = {
            "dates": eq_dates,
            "equity": result.equity_curve.round(2).tolist(),
        }

        # Trade list
        trades = []
        for t in result.trades:
            trades.append({
                "entry_date": t.entry_date.strftime("%Y-%m-%d"),
                "exit_date": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else None,
                "entry_price": round(t.entry_price, 2),
                "exit_price": round(t.exit_price, 2) if t.exit_price else None,
                "shares": t.shares,
                "pnl": round(t.pnl, 2),
                "exit_reason": t.exit_reason,
                "stop_price": round(t.stop_price, 2),
                "target_price": round(t.target_price, 2),
            })

        return jsonify({
            "success": True,
            "label": label,
            "metrics": result.metrics,
            "chart": chart_data,
            "equity": equity_data,
            "trades": trades,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quote", methods=["GET"])
def api_quote():
    """Fetch current price data for a symbol."""
    symbol = request.args.get("symbol", "AAPL")
    try:
        df = fetch_ohlcv(symbol, period="5d", interval="1d")
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        change = last["close"] - prev["close"]
        change_pct = (change / prev["close"]) * 100

        return jsonify({
            "success": True,
            "symbol": symbol,
            "price": round(float(last["close"]), 2),
            "change": round(float(change), 2),
            "change_pct": round(float(change_pct), 2),
            "open": round(float(last["open"]), 2),
            "high": round(float(last["high"]), 2),
            "low": round(float(last["low"]), 2),
            "volume": int(last["volume"]),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/paper/start", methods=["POST"])
def api_paper_start():
    """Start the paper trading loop in a background thread."""
    global paper_thread, paper_running, paper_broker, paper_logs, paper_config

    if paper_running:
        return jsonify({"success": False, "error": "Paper trading already running"})

    data = request.get_json(force=True)
    symbol = data.get("symbol", "AAPL")
    capital = float(data.get("capital", 100_000))
    interval = data.get("interval", "1d")

    paper_config = BotConfig(symbol=symbol, interval=interval, broker="paper")
    paper_config.risk.initial_capital = capital
    paper_broker = PaperBroker(initial_cash=capital)
    paper_logs = []
    paper_running = True

    paper_thread = threading.Thread(target=_paper_loop, daemon=True)
    paper_thread.start()

    return jsonify({"success": True, "message": f"Paper trading started for {symbol}"})


@app.route("/api/paper/stop", methods=["POST"])
def api_paper_stop():
    """Stop the paper trading loop."""
    global paper_running
    paper_running = False
    return jsonify({"success": True, "message": "Paper trading stopped"})


@app.route("/api/paper/status", methods=["GET"])
def api_paper_status():
    """Get current paper trading status."""
    global paper_running, paper_broker, paper_logs, paper_config

    if not paper_running or not paper_broker:
        return jsonify({
            "running": False,
            "logs": paper_logs[-50:],
        })

    return jsonify({
        "running": True,
        "symbol": paper_config.symbol if paper_config else "",
        "shares": paper_broker.get_position_shares(),
        "cash": round(paper_broker.state["cash"], 2),
        "history": paper_broker.state.get("history", [])[-20:],
        "logs": paper_logs[-50:],
    })


def _paper_loop():
    """Background paper trading loop."""
    global paper_running, paper_broker, paper_logs, paper_config
    risk = RiskManager(paper_config.risk)

    while paper_running:
        try:
            df = fetch_ohlcv(paper_config.symbol, period=paper_config.history_period,
                             interval=paper_config.interval)
            ind_df = generate_signals(df, paper_config.strategy).dropna(subset=["sma_slow", "atr"])
            last = ind_df.iloc[-1]
            price = float(last["close"])

            equity = paper_broker.get_equity(price)
            shares_held = paper_broker.get_position_shares()

            msg = f"[{datetime.now().strftime('%H:%M:%S')}] {paper_config.symbol} close={price:.2f} signal={int(last['signal'])} equity={equity:.2f} shares={shares_held}"

            if risk.check_daily_loss_limit(equity):
                msg += " ⚠ DAILY LOSS LIMIT"
            elif last["signal"] == 1 and shares_held == 0:
                plan = risk.size_position(equity, price, float(last["atr"]))
                if plan:
                    paper_broker.buy(plan.shares, price)
                    msg += f" → BUY {plan.shares} shares"
            elif last["signal"] == -1 and shares_held > 0:
                paper_broker.sell(shares_held, price)
                msg += f" → SELL {shares_held} shares"

            paper_logs.append(msg)
            # Keep log buffer manageable
            if len(paper_logs) > 200:
                paper_logs = paper_logs[-100:]

            socketio.emit("paper_update", {
                "log": msg,
                "equity": equity,
                "shares": shares_held,
                "price": price,
            })

        except Exception as e:
            err = f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {e}"
            paper_logs.append(err)

        time.sleep(max(paper_config.poll_seconds, 30))


if __name__ == "__main__":
    print("\n  🚀  Trading Bot Dashboard → http://localhost:5050\n")
    socketio.run(app, host="0.0.0.0", port=5050, debug=True, allow_unsafe_werkzeug=True)
