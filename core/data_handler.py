"""
Market data access. Live data comes from yfinance (no API key needed).
generate_synthetic() produces a realistic random-walk OHLCV series for
offline testing when no network / API access is available.
"""
import numpy as np
import pandas as pd

from core.logger import get_logger

log = get_logger("data_handler")

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def fetch_ohlcv(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Fetch historical OHLCV data for `symbol` via yfinance."""
    import yfinance as yf

    log.info(f"Fetching {symbol} | period={period} interval={interval}")
    raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)

    if raw is None or raw.empty:
        raise RuntimeError(f"No data returned for {symbol}. Check symbol/interval/network.")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(columns=str.lower)
    raw = raw[REQUIRED_COLS].dropna()
    raw.index.name = "date"
    return raw


def fetch_latest_bar(symbol: str, interval: str = "1d") -> pd.Series:
    """Fetch the most recent completed bar — used by the live/paper loop."""
    df = fetch_ohlcv(symbol, period="5d", interval=interval)
    return df.iloc[-1]


def generate_synthetic(n: int = 500, start_price: float = 150.0, seed: int = 42) -> pd.DataFrame:
    """Random-walk OHLCV generator for backtesting the engine without network access."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")

    returns = rng.normal(loc=0.0004, scale=0.014, size=n)
    close = start_price * np.exp(np.cumsum(returns))

    daily_range = np.abs(rng.normal(loc=0.01, scale=0.006, size=n)) * close
    open_ = close * (1 + rng.normal(0, 0.003, size=n))
    high = np.maximum(open_, close) + daily_range * rng.uniform(0.2, 0.6, size=n)
    low = np.minimum(open_, close) - daily_range * rng.uniform(0.2, 0.6, size=n)
    volume = rng.integers(1_000_000, 8_000_000, size=n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.index.name = "date"
    return df
