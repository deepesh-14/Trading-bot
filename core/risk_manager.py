"""
Position sizing and stop/target calculation, decoupled from strategy signal
logic so the same risk rules apply in both backtest and live/paper trading.
"""
from dataclasses import dataclass

from config import RiskConfig


@dataclass
class TradePlan:
    shares: int
    entry_price: float
    stop_price: float
    target_price: float
    risk_amount: float


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.day_start_equity: float = cfg.initial_capital
        self.trading_halted_today: bool = False

    def size_position(self, equity: float, entry_price: float, atr_value: float) -> TradePlan | None:
        if atr_value <= 0 or entry_price <= 0:
            return None

        stop_distance = atr_value * self.cfg.atr_stop_multiplier
        stop_price = entry_price - stop_distance
        target_price = entry_price + stop_distance * self.cfg.reward_risk_ratio

        risk_amount = equity * (self.cfg.risk_per_trade_pct / 100)
        shares_by_risk = int(risk_amount / stop_distance) if stop_distance > 0 else 0

        max_notional = equity * (self.cfg.max_position_pct / 100)
        shares_by_cap = int(max_notional / entry_price)

        shares = max(0, min(shares_by_risk, shares_by_cap))
        if shares == 0:
            return None

        return TradePlan(
            shares=shares,
            entry_price=entry_price,
            stop_price=round(stop_price, 4),
            target_price=round(target_price, 4),
            risk_amount=round(shares * stop_distance, 2),
        )

    def check_daily_loss_limit(self, current_equity: float) -> bool:
        """Returns True if trading should be halted for the day."""
        loss_pct = (self.day_start_equity - current_equity) / self.day_start_equity * 100
        if loss_pct >= self.cfg.max_daily_loss_pct:
            self.trading_halted_today = True
        return self.trading_halted_today

    def reset_day(self, equity: float):
        self.day_start_equity = equity
        self.trading_halted_today = False
