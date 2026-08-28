"""Risk management middleware for the event-driven backtesting engine.

The RiskManager sits between OrderEvent creation (Portfolio) and execution
(ExecutionHandler). Every OrderEvent must pass through
`RiskManager.process_order` before it may reach the ExecutionHandler, and
every mark-to-market update must pass through
`RiskManager.evaluate_portfolio_risk` so hard limits are caught immediately
rather than only when the next order happens to be placed.

Two independent kill switches are enforced:

1. **Rate limiter** -- rejects new orders once more than
   `max_orders_per_minute` have been submitted within any rolling
   60-second window (protects against a runaway strategy/feedback loop).
2. **Hard drawdown limit** -- once Total Equity has fallen by more than
   `max_drawdown_pct` relative to the equity at session open, all trading
   is halted and a LiquidateEvent is emitted to flatten every open
   position.

Design notes (SOLID):
- Single Responsibility: this module only vets orders/portfolio state; it
  never computes P&L or executes trades itself.
- Open/Closed: new kill switches can be added as additional private check
  methods without modifying existing ones.
- Dependency Inversion: RiskManager depends only on a minimal structural
  `PortfolioLike` protocol, not a concrete Portfolio implementation.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Optional, Protocol, runtime_checkable

from .event import LiquidateEvent, OrderEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class PortfolioLike(Protocol):
    """Minimal structural interface the RiskManager depends on."""

    initial_capital: float

    @property
    def current_equity(self) -> float: ...


class RiskManager:
    """Middleware enforcing hard risk kill-switches on the order flow."""

    def __init__(
        self,
        portfolio: PortfolioLike,
        max_orders_per_minute: int = 10,
        max_drawdown_pct: float = 0.02,
    ) -> None:
        if max_orders_per_minute <= 0:
            raise ValueError("max_orders_per_minute must be positive")
        if not (0.0 < max_drawdown_pct < 1.0):
            raise ValueError("max_drawdown_pct must be within (0, 1)")

        self.portfolio = portfolio
        self.max_orders_per_minute = max_orders_per_minute
        self.max_drawdown_pct = max_drawdown_pct

        self._order_timestamps: Deque[float] = deque()
        self.trading_halted: bool = False
        self._halt_reason: Optional[str] = None

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    def _prune_old_orders(self, now: float) -> None:
        window_start = now - 60.0
        while self._order_timestamps and self._order_timestamps[0] < window_start:
            self._order_timestamps.popleft()

    def _rate_limit_breached(self, now: float) -> bool:
        self._prune_old_orders(now)
        return len(self._order_timestamps) >= self.max_orders_per_minute

    def _drawdown_breached(self) -> bool:
        opening_equity = self.portfolio.initial_capital
        if opening_equity <= 0:
            return False
        current_equity = self.portfolio.current_equity
        drawdown = (opening_equity - current_equity) / opening_equity
        return drawdown >= self.max_drawdown_pct

    def evaluate_portfolio_risk(self, now: Optional[float] = None) -> Optional[LiquidateEvent]:
        """Proactively evaluate hard risk limits against the current portfolio
        state. Must be called after every mark-to-market update (i.e. on
        every MarketEvent) so a drawdown breach triggers an *immediate*
        liquidation instead of waiting for the next signal/order.
        """
        if self.trading_halted:
            return None

        if self._drawdown_breached():
            now = now if now is not None else time.time()
            self._halt_reason = (
                f"Hard drawdown limit breached: equity down "
                f">= {self.max_drawdown_pct:.2%} since session open"
            )
            self.trading_halted = True
            logger.critical(self._halt_reason)
            return LiquidateEvent(reason=self._halt_reason, timestamp=now)

        return None

    def process_order(self, order_event: OrderEvent) -> Optional[OrderEvent]:
        """Vet a single OrderEvent. Returns it unchanged if approved, or None
        if it is rejected (trading halted, or rate limit exceeded)."""
        if self.trading_halted:
            logger.warning(
                "Order rejected for %s: trading halted (%s)",
                order_event.symbol,
                self._halt_reason,
            )
            return None

        now = order_event.timestamp
        if self._rate_limit_breached(now):
            logger.warning(
                "Order rejected for %s: rate limit exceeded (%d orders/min)",
                order_event.symbol,
                self.max_orders_per_minute,
            )
            return None

        self._order_timestamps.append(now)
        return order_event

    def reset_halt(self) -> None:
        """Re-arm the RiskManager after a halt (e.g. at the start of a new session).

        Not called automatically: resuming trading after a hard drawdown
        breach must always be a deliberate, explicit decision.
        """
        self.trading_halted = False
        self._halt_reason = None
        self._order_timestamps.clear()
