"""
Trend-following strategy: SMA crossover, confirmed by RSI (avoid buying
overbought / selling oversold) and MACD histogram (momentum agreement).

Signal values:  1 = long entry, -1 = exit long, 0 = hold / no action.
This is intentionally long-only (simpler risk model, suits equities in a
cash/margin-free paper account). Shorting can be added in a subclass.
"""
import pandas as pd

from core.indicators import sma, rsi, macd, atr
from config import StrategyConfig


def build_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = sma(out["close"], cfg.fast_sma)
    out["sma_slow"] = sma(out["close"], cfg.slow_sma)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    macd_line, signal_line, hist = macd(out["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["atr"] = atr(out, cfg.atr_period)
    return out


def generate_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Adds a 'signal' column to the indicator-enriched DataFrame.
    Entry: fast SMA crosses above slow SMA, RSI not overbought, MACD histogram > 0.
    Exit:  fast SMA crosses below slow SMA, OR RSI overbought (take profit into strength).
    """
    ind = build_indicators(df, cfg)

    cross_up = (ind["sma_fast"] > ind["sma_slow"]) & (ind["sma_fast"].shift(1) <= ind["sma_slow"].shift(1))
    cross_down = (ind["sma_fast"] < ind["sma_slow"]) & (ind["sma_fast"].shift(1) >= ind["sma_slow"].shift(1))

    entry = cross_up & (ind["rsi"] < cfg.rsi_overbought) & (ind["macd_hist"] > 0)
    exit_ = cross_down | (ind["rsi"] > cfg.rsi_overbought + 5)

    ind["signal"] = 0
    ind.loc[entry, "signal"] = 1
    ind.loc[exit_, "signal"] = -1

    return ind
