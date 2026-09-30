"""
Central configuration for the trading bot.
Edit values here or override via environment variables (.env).
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class StrategyConfig:
    fast_sma: int = 20
    slow_sma: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14


@dataclass
class RiskConfig:
    initial_capital: float = 100_000.0
    risk_per_trade_pct: float = 1.0        # % of equity risked per trade
    atr_stop_multiplier: float = 2.0       # stop-loss = entry -/+ ATR * multiplier
    reward_risk_ratio: float = 2.0         # take-profit distance = stop distance * ratio
    max_position_pct: float = 25.0         # max % of equity in one position
    max_daily_loss_pct: float = 3.0        # halt trading for the day if breached
    max_open_positions: int = 1


@dataclass
class BotConfig:
    symbol: str = "AAPL"
    interval: str = "1d"                   # yfinance interval: 1m,5m,15m,1h,1d...
    history_period: str = "2y"             # lookback window for backtest / warm-up
    poll_seconds: int = 60                 # loop delay in live/paper mode
    broker: str = "paper"                  # "paper" (local simulator) or "alpaca"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)


# Alpaca credentials (only needed if broker == "alpaca")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
