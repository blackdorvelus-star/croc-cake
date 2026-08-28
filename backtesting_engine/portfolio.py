"""Portfolio layer: position sizing, holdings and equity accounting.

The Portfolio is the sole owner of position and cash state. It turns
SignalEvents into OrderEvents (a position-sizing decision) and updates its
books when FillEvents come back from the ExecutionHandler. Mark-to-market
equity is refreshed on every MarketEvent so the RiskManager always has an
up-to-date view of Total Equity to check its hard drawdown limit against.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .event import (
    FillEvent,
    MarketEvent,
    OrderDirection,
    OrderEvent,
    OrderType,
    SignalDirection,
    SignalEvent,
)


@dataclass
class EquityPoint:
    timestamp: Any
    equity: float


class Portfolio:
    """Tracks cash, positions and equity; sizes orders from signals.

    Position sizing here is intentionally a simple fixed-quantity model to
    keep the skeleton readable -- swap `update_signal` for volatility
    targeting, Kelly sizing, or an ML-based position sizer without touching
    any other layer.
    """

    def __init__(
        self,
        symbol_list: List[str],
        initial_capital: float = 100_000.0,
        fixed_order_quantity: int = 100,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if fixed_order_quantity <= 0:
            raise ValueError("fixed_order_quantity must be positive")

        self.symbol_list = symbol_list
        self.initial_capital = initial_capital
        self.fixed_order_quantity = fixed_order_quantity

        self.cash: float = initial_capital
        self.positions: Dict[str, int] = {symbol: 0 for symbol in symbol_list}
        self.latest_prices: Dict[str, float] = {symbol: 0.0 for symbol in symbol_list}
        self.equity_curve: List[EquityPoint] = []

    @property
    def current_equity(self) -> float:
        holdings_value = sum(self.positions[s] * self.latest_prices[s] for s in self.symbol_list)
        return self.cash + holdings_value

    def update_timeindex(self, event: MarketEvent) -> None:
        """Mark-to-market on every new bar and record an equity curve point."""
        self.latest_prices[event.symbol] = event.bar["close"]
        self.equity_curve.append(EquityPoint(timestamp=event.bar.get("timestamp"), equity=self.current_equity))

    def update_signal(self, event: SignalEvent) -> Optional[OrderEvent]:
        """Translate a SignalEvent into a sized OrderEvent, or None if the
        signal implies no change to the current position."""
        current_position = self.positions[event.symbol]

        if event.direction == SignalDirection.LONG and current_position <= 0:
            quantity = self.fixed_order_quantity - current_position
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, OrderDirection.BUY)

        if event.direction == SignalDirection.SHORT and current_position >= 0:
            quantity = self.fixed_order_quantity + current_position
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, OrderDirection.SELL)

        if event.direction == SignalDirection.EXIT and current_position != 0:
            quantity = abs(current_position)
            direction = OrderDirection.SELL if current_position > 0 else OrderDirection.BUY
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, direction)

        return None

    def update_fill(self, event: FillEvent) -> None:
        signed_quantity = event.quantity if event.direction == OrderDirection.BUY else -event.quantity
        self.positions[event.symbol] += signed_quantity
        self.cash += -signed_quantity * event.fill_price - event.commission

    def generate_liquidation_orders(self) -> List[OrderEvent]:
        """Build MARKET orders that flatten every currently open position.

        Used exclusively by the engine when a LiquidateEvent fires; these
        orders bypass the RiskManager since trading is already halted and
        their sole purpose is to *reduce* risk.
        """
        orders: List[OrderEvent] = []
        for symbol, quantity in self.positions.items():
            if quantity == 0:
                continue
            direction = OrderDirection.SELL if quantity > 0 else OrderDirection.BUY
            orders.append(OrderEvent(symbol, OrderType.MARKET, abs(quantity), direction))
        return orders
