"""Event definitions for the event-driven backtesting engine.

Every component in the system (DataHandler, Strategy, Portfolio,
RiskManager, ExecutionHandler) communicates exclusively by placing and
consuming Event objects on a single shared FIFO queue. No component ever
calls another directly, which keeps them independently testable and
swappable (Dependency Inversion / Open-Closed principles).
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional


class EventType(Enum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    LIQUIDATE = "LIQUIDATE"


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"


class OrderDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MKT"
    LIMIT = "LMT"


class Event:
    """Base class every event derives from.

    `timestamp` defaults to wall-clock time at creation. This is
    intentional: it is what lets the RiskManager's rate limiter and the
    engine's watchdog reason about *real* elapsed time, which matters both
    in a fast historical replay (where many orders can be generated within
    the same wall-clock second) and in a live deployment.
    """

    type: EventType

    def __init__(self, timestamp: Optional[float] = None) -> None:
        self.timestamp = timestamp if timestamp is not None else time.time()


class MarketEvent(Event):
    """Signals that new market data (a bar) is available for a symbol.

    `bar` is a plain dict with at least the keys: open, high, low, close,
    volume, timestamp (the *historical* bar timestamp, distinct from
    Event.timestamp which is wall-clock creation time).
    """

    def __init__(self, symbol: str, bar: dict, timestamp: Optional[float] = None) -> None:
        super().__init__(timestamp)
        self.type = EventType.MARKET
        self.symbol = symbol
        self.bar = bar

    def __repr__(self) -> str:
        return f"MarketEvent(symbol={self.symbol}, close={self.bar.get('close')})"


class SignalEvent(Event):
    """A directional trading opinion emitted by a Strategy."""

    def __init__(
        self,
        symbol: str,
        direction: SignalDirection,
        strength: float = 1.0,
        strategy_id: str = "default",
        timestamp: Optional[float] = None,
    ) -> None:
        super().__init__(timestamp)
        self.type = EventType.SIGNAL
        self.symbol = symbol
        self.direction = direction
        self.strength = strength
        self.strategy_id = strategy_id

    def __repr__(self) -> str:
        return f"SignalEvent(symbol={self.symbol}, direction={self.direction}, strength={self.strength:.2f})"


class OrderEvent(Event):
    """An order the Portfolio wants to place. Must be vetted by the RiskManager
    before reaching the ExecutionHandler."""

    def __init__(
        self,
        symbol: str,
        order_type: OrderType,
        quantity: int,
        direction: OrderDirection,
        timestamp: Optional[float] = None,
    ) -> None:
        super().__init__(timestamp)
        self.type = EventType.ORDER
        if quantity <= 0:
            raise ValueError("OrderEvent quantity must be strictly positive")
        self.symbol = symbol
        self.order_type = order_type
        self.quantity = quantity
        self.direction = direction

    def __repr__(self) -> str:
        return (
            f"OrderEvent(symbol={self.symbol}, type={self.order_type}, "
            f"qty={self.quantity}, dir={self.direction})"
        )


class FillEvent(Event):
    """Confirmation that an order was executed, including realistic costs."""

    def __init__(
        self,
        symbol: str,
        quantity: int,
        direction: OrderDirection,
        fill_price: float,
        commission: float,
        slippage: float,
        timestamp: Optional[float] = None,
    ) -> None:
        super().__init__(timestamp)
        self.type = EventType.FILL
        self.symbol = symbol
        self.quantity = quantity
        self.direction = direction
        self.fill_price = fill_price
        self.commission = commission
        self.slippage = slippage

    def __repr__(self) -> str:
        return (
            f"FillEvent(symbol={self.symbol}, qty={self.quantity}, dir={self.direction}, "
            f"price={self.fill_price:.4f}, commission={self.commission:.4f})"
        )


class LiquidateEvent(Event):
    """Emitted by the RiskManager when a hard risk limit (e.g. drawdown) is
    breached. Instructs the engine to flatten every open position
    immediately, bypassing normal signal/order flow."""

    def __init__(self, reason: str, timestamp: Optional[float] = None) -> None:
        super().__init__(timestamp)
        self.type = EventType.LIQUIDATE
        self.reason = reason

    def __repr__(self) -> str:
        return f"LiquidateEvent(reason={self.reason!r})"
