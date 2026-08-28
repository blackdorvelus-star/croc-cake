"""Portfolio layer: position sizing, holdings and equity accounting.

The Portfolio is the sole owner of position and cash state. It turns
SignalEvents into OrderEvents (a position-sizing decision) and updates its
books when FillEvents come back from the ExecutionHandler. Mark-to-market
equity is refreshed on every MarketEvent so the RiskManager always has an
up-to-date view of Total Equity to check its hard drawdown limit against.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

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


@dataclass
class _OpenTrade:
    direction: OrderDirection  # BUY = long trade, SELL = short trade
    quantity: int
    entry_price: float
    commission: float


@dataclass
class TradeRecord:
    """A fully closed round-trip trade, for post-hoc performance analysis
    (see `analytics.py`). Not used by any live decision in the engine."""

    symbol: str
    direction: OrderDirection
    quantity: int
    entry_price: float
    exit_price: float
    commission: float
    pnl: float


@runtime_checkable
class PositionSizer(Protocol):
    """Minimal structural interface for a risk-based position sizer
    (Dependency Inversion: Portfolio depends on this, not on any concrete
    sizer such as `forex_cost_models.ForexPositionSizer`)."""

    def calculate_lot_size(self, account_equity: float, stop_loss_pips: float) -> float: ...


class Portfolio:
    """Tracks cash, positions and equity; sizes orders from signals.

    Position sizing defaults to a simple fixed-quantity model to keep the
    skeleton readable. Pass a `position_sizer` (e.g.
    `forex_cost_models.ForexPositionSizer`) to size orders as a percentage
    of current equity risked against each signal's `stop_loss_pips`
    instead -- falls back to `fixed_order_quantity` for any signal that
    doesn't carry a stop distance.
    """

    def __init__(
        self,
        symbol_list: List[str],
        initial_capital: float = 100_000.0,
        fixed_order_quantity: int = 100,
        position_sizer: Optional[PositionSizer] = None,
        lot_size: float = 100_000.0,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if fixed_order_quantity <= 0:
            raise ValueError("fixed_order_quantity must be positive")
        if lot_size <= 0:
            raise ValueError("lot_size must be positive")

        self.symbol_list = symbol_list
        self.initial_capital = initial_capital
        self.fixed_order_quantity = fixed_order_quantity
        self.position_sizer = position_sizer
        self.lot_size = lot_size

        self.cash: float = initial_capital
        self.positions: Dict[str, int] = {symbol: 0 for symbol in symbol_list}
        self.latest_prices: Dict[str, float] = {symbol: 0.0 for symbol in symbol_list}
        self.equity_curve: List[EquityPoint] = []

        self._open_trades: Dict[str, _OpenTrade] = {}
        self.closed_trades: List[TradeRecord] = []

    @property
    def current_equity(self) -> float:
        holdings_value = sum(self.positions[s] * self.latest_prices[s] for s in self.symbol_list)
        return self.cash + holdings_value

    def update_timeindex(self, event: MarketEvent) -> None:
        """Mark-to-market on every new bar and record an equity curve point."""
        self.latest_prices[event.symbol] = event.bar["close"]
        self.equity_curve.append(EquityPoint(timestamp=event.bar.get("timestamp"), equity=self.current_equity))

    def _target_quantity(self, event: SignalEvent) -> int:
        """The desired absolute position size for an entry signal: either
        risk-based (if a `position_sizer` is configured and the signal
        carries a stop distance) or the fixed fallback quantity."""
        if self.position_sizer is not None and event.stop_loss_pips:
            lots = self.position_sizer.calculate_lot_size(
                account_equity=self.current_equity,
                stop_loss_pips=event.stop_loss_pips,
            )
            return int(round(lots * self.lot_size))
        return self.fixed_order_quantity

    def update_signal(self, event: SignalEvent) -> Optional[OrderEvent]:
        """Translate a SignalEvent into a sized OrderEvent, or None if the
        signal implies no change to the current position (or sizes to zero)."""
        current_position = self.positions[event.symbol]

        if event.direction == SignalDirection.LONG and current_position <= 0:
            quantity = self._target_quantity(event) - current_position
            if quantity <= 0:
                return None
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, OrderDirection.BUY)

        if event.direction == SignalDirection.SHORT and current_position >= 0:
            quantity = self._target_quantity(event) + current_position
            if quantity <= 0:
                return None
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, OrderDirection.SELL)

        if event.direction == SignalDirection.EXIT and current_position != 0:
            quantity = abs(current_position)
            direction = OrderDirection.SELL if current_position > 0 else OrderDirection.BUY
            return OrderEvent(event.symbol, OrderType.MARKET, quantity, direction)

        return None

    def update_fill(self, event: FillEvent) -> None:
        symbol = event.symbol
        previous_position = self.positions[symbol]
        signed_quantity = event.quantity if event.direction == OrderDirection.BUY else -event.quantity
        self.positions[symbol] = previous_position + signed_quantity
        self.cash += -signed_quantity * event.fill_price - event.commission

        self._record_trade_activity(symbol, event, previous_position, signed_quantity)

    def _record_trade_activity(
        self, symbol: str, event: FillEvent, previous_position: int, signed_quantity: int
    ) -> None:
        """Reconstructs round-trip trades from the fill stream, for
        analytics only -- this never influences sizing or risk decisions.
        A single fill can both close an existing position and open a new
        one in the opposite direction (a "flip"), so its commission is
        prorated between the closing and opening portions by quantity.
        """
        is_reducing = previous_position != 0 and (previous_position > 0) != (signed_quantity > 0)
        closing_quantity = min(abs(previous_position), abs(signed_quantity)) if is_reducing else 0

        if closing_quantity > 0:
            open_trade = self._open_trades.get(symbol)
            if open_trade is not None:
                closing_commission = event.commission * (closing_quantity / event.quantity)
                entry_commission = open_trade.commission * (closing_quantity / open_trade.quantity)
                direction_sign = 1 if open_trade.direction == OrderDirection.BUY else -1
                pnl = (
                    direction_sign * (event.fill_price - open_trade.entry_price) * closing_quantity
                    - entry_commission
                    - closing_commission
                )
                self.closed_trades.append(
                    TradeRecord(
                        symbol=symbol,
                        direction=open_trade.direction,
                        quantity=closing_quantity,
                        entry_price=open_trade.entry_price,
                        exit_price=event.fill_price,
                        commission=entry_commission + closing_commission,
                        pnl=pnl,
                    )
                )
                remaining = open_trade.quantity - closing_quantity
                if remaining <= 0:
                    del self._open_trades[symbol]
                else:
                    open_trade.quantity = remaining
                    open_trade.commission -= entry_commission

        opening_quantity = event.quantity - closing_quantity
        if opening_quantity > 0:
            opening_commission = event.commission * (opening_quantity / event.quantity)
            self._open_trades[symbol] = _OpenTrade(
                direction=event.direction,
                quantity=opening_quantity,
                entry_price=event.fill_price,
                commission=opening_commission,
            )

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
