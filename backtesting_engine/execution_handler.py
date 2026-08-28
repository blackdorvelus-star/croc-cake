"""Execution layer: turns approved OrderEvents into FillEvents.

The ExecutionHandler is the last component before the (simulated) exchange.
It owns realistic transaction-cost modeling -- slippage and commission --
so the Strategy/Portfolio/RiskManager layers never need to reason about
market microstructure. Swap `SimulatedExecutionHandler` for a
`BrokerExecutionHandler` talking to a real/paper broker API to go live
without changing any other layer.
"""
from __future__ import annotations

import abc
import logging
import queue
from typing import Optional

from .event import FillEvent, OrderDirection, OrderEvent

logger = logging.getLogger(__name__)


class CommissionModel:
    """Percentage-of-notional commission with a minimum flat fee per trade,
    mirroring how most retail/institutional brokers actually charge."""

    def __init__(self, commission_rate: float = 0.0005, minimum_commission: float = 1.0) -> None:
        if commission_rate < 0 or minimum_commission < 0:
            raise ValueError("commission parameters must be non-negative")
        self.commission_rate = commission_rate
        self.minimum_commission = minimum_commission

    def calculate(self, quantity: int, fill_price: float) -> float:
        notional = abs(quantity) * fill_price
        return max(notional * self.commission_rate, self.minimum_commission)


class SlippageModel:
    """Square-root market-impact slippage model.

    Slippage is *not* a fixed number: it scales with the order's
    participation rate (order size relative to available volume for the
    bar, falling back to a fictitious average volume when the bar carries
    none). Larger orders relative to liquidity move the fill price further
    against the trader, following the square-root market-impact
    relationship widely used in execution research (impact grows with the
    square root of participation rate, not linearly).
    """

    def __init__(
        self,
        base_spread_bps: float = 1.0,
        impact_coefficient: float = 15.0,
        fallback_avg_volume: float = 1_000_000.0,
    ) -> None:
        if base_spread_bps < 0 or impact_coefficient < 0 or fallback_avg_volume <= 0:
            raise ValueError("invalid slippage model parameters")
        self.base_spread_bps = base_spread_bps
        self.impact_coefficient = impact_coefficient
        self.fallback_avg_volume = fallback_avg_volume

    def slipped_price(
        self,
        direction: OrderDirection,
        quantity: int,
        reference_price: float,
        bar_volume: Optional[float],
    ) -> float:
        volume_reference = bar_volume if bar_volume and bar_volume > 0 else self.fallback_avg_volume
        participation_rate = min(abs(quantity) / volume_reference, 1.0)

        impact_bps = self.impact_coefficient * (participation_rate ** 0.5)
        total_bps = self.base_spread_bps + impact_bps
        slippage_fraction = total_bps / 10_000.0

        sign = 1 if direction == OrderDirection.BUY else -1
        slipped_price = reference_price * (1 + sign * slippage_fraction)
        return max(slipped_price, 0.0)


class ExecutionHandler(abc.ABC):
    """Abstract execution interface (Dependency Inversion)."""

    @abc.abstractmethod
    def execute_order(self, order_event: OrderEvent, market_bar: dict) -> Optional[FillEvent]:
        """Execute an already risk-approved OrderEvent against `market_bar`."""


class SimulatedExecutionHandler(ExecutionHandler):
    """Fills orders at the current bar's close, adjusted for slippage and
    commission, then pushes a FillEvent back onto the queue."""

    def __init__(
        self,
        event_queue: "queue.Queue",
        commission_model: Optional[CommissionModel] = None,
        slippage_model: Optional[SlippageModel] = None,
    ) -> None:
        self.event_queue = event_queue
        self.commission_model = commission_model or CommissionModel()
        self.slippage_model = slippage_model or SlippageModel()

    def execute_order(self, order_event: OrderEvent, market_bar: dict) -> Optional[FillEvent]:
        reference_price = market_bar["close"]
        bar_volume = market_bar.get("volume")

        fill_price = self.slippage_model.slipped_price(
            direction=order_event.direction,
            quantity=order_event.quantity,
            reference_price=reference_price,
            bar_volume=bar_volume,
        )
        commission = self.commission_model.calculate(order_event.quantity, fill_price)
        slippage_cost = abs(fill_price - reference_price) * order_event.quantity

        fill_event = FillEvent(
            symbol=order_event.symbol,
            quantity=order_event.quantity,
            direction=order_event.direction,
            fill_price=fill_price,
            commission=commission,
            slippage=slippage_cost,
        )
        logger.info(
            "Filled %s qty=%s dir=%s ref_price=%.4f fill_price=%.4f commission=%.4f slippage=%.4f",
            order_event.symbol,
            order_event.quantity,
            order_event.direction,
            reference_price,
            fill_price,
            commission,
            slippage_cost,
        )
        self.event_queue.put(fill_event)
        return fill_event
