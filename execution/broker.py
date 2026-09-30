"""
Broker abstraction so the trading loop doesn't care whether orders go to a
local paper simulator or to Alpaca. Both implement: get_equity(), get_position(),
buy(qty, price), sell(qty, price).
"""
import json
import os
from abc import ABC, abstractmethod

from core.logger import get_logger

log = get_logger("broker")

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "paper_state.json")


class Broker(ABC):
    @abstractmethod
    def get_equity(self, mark_price: float) -> float: ...

    @abstractmethod
    def get_position_shares(self) -> int: ...

    @abstractmethod
    def buy(self, qty: int, price: float): ...

    @abstractmethod
    def sell(self, qty: int, price: float): ...


class PaperBroker(Broker):
    """
    Local, file-persisted paper trading simulator. No external API needed.
    Fills are assumed instant at the requested price (no slippage model —
    add one in buy()/sell() if you want to stress-test execution quality).
    """

    def __init__(self, initial_cash: float = 100_000.0):
        self.state = self._load_state(initial_cash)

    def _load_state(self, initial_cash: float) -> dict:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
        return {"cash": initial_cash, "shares": 0, "avg_entry": 0.0, "history": []}

    def _save_state(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)

    def get_equity(self, mark_price: float) -> float:
        return self.state["cash"] + self.state["shares"] * mark_price

    def get_position_shares(self) -> int:
        return self.state["shares"]

    def buy(self, qty: int, price: float):
        cost = qty * price
        if cost > self.state["cash"]:
            log.warning("Paper broker: insufficient cash for buy, skipping.")
            return
        self.state["cash"] -= cost
        self.state["shares"] += qty
        self.state["avg_entry"] = price
        self.state["history"].append({"side": "BUY", "qty": qty, "price": price})
        self._save_state()
        log.info(f"PAPER BUY {qty} @ {price:.2f}")

    def sell(self, qty: int, price: float):
        qty = min(qty, self.state["shares"])
        if qty <= 0:
            return
        self.state["cash"] += qty * price
        self.state["shares"] -= qty
        self.state["history"].append({"side": "SELL", "qty": qty, "price": price})
        self._save_state()
        log.info(f"PAPER SELL {qty} @ {price:.2f}")


class AlpacaBroker(Broker):
    """
    Thin wrapper over alpaca-py for real paper/live execution.
    Requires ALPACA_API_KEY / ALPACA_SECRET_KEY in the environment (.env).
    """

    def __init__(self, symbol: str):
        from alpaca.trading.client import TradingClient
        import config as cfg

        if not cfg.ALPACA_API_KEY or not cfg.ALPACA_SECRET_KEY:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set in environment (.env).")

        self.symbol = symbol
        self.client = TradingClient(cfg.ALPACA_API_KEY, cfg.ALPACA_SECRET_KEY, paper=cfg.ALPACA_PAPER)

    def get_equity(self, mark_price: float) -> float:
        account = self.client.get_account()
        return float(account.equity)

    def get_position_shares(self) -> int:
        from alpaca.common.exceptions import APIError
        try:
            pos = self.client.get_open_position(self.symbol)
            return int(float(pos.qty))
        except APIError:
            return 0

    def buy(self, qty: int, price: float):
        self._submit("buy", qty)

    def sell(self, qty: int, price: float):
        self._submit("sell", qty)

    def _submit(self, side: str, qty: int):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        if qty <= 0:
            return
        order = MarketOrderRequest(
            symbol=self.symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        self.client.submit_order(order)
        log.info(f"ALPACA {side.upper()} order submitted: {qty} {self.symbol}")


def get_broker(cfg) -> Broker:
    if cfg.broker == "alpaca":
        return AlpacaBroker(cfg.symbol)
    return PaperBroker(initial_cash=cfg.risk.initial_capital)
