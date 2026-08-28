"""Main event loop wiring DataHandler, Strategy, Portfolio, RiskManager and
ExecutionHandler together, plus a heartbeat/watchdog safety mechanism.

Event flow per iteration:

    DataHandler.update_bars()
        -> MarketEvent
    Portfolio.update_timeindex() + RiskManager.evaluate_portfolio_risk()
        -> [optional] LiquidateEvent
    Strategy.calculate_signals()
        -> [optional] SignalEvent
    Portfolio.update_signal()
        -> [optional] OrderEvent
    RiskManager.process_order()          <-- middleware, can reject
        -> [approved] OrderEvent
    ExecutionHandler.execute_order()
        -> FillEvent
    Portfolio.update_fill()
"""
from __future__ import annotations

import logging
import queue
import time
from typing import Dict, Optional

from .data_handler import DataHandler
from .event import Event, EventType, FillEvent, LiquidateEvent, MarketEvent, OrderEvent, SignalEvent
from .execution_handler import ExecutionHandler
from .portfolio import Portfolio
from .risk_manager import RiskManager
from .strategy import Strategy

logger = logging.getLogger(__name__)


class MarketDataStallError(RuntimeError):
    """Raised by the watchdog when no MarketEvent has been processed within
    `heartbeat_timeout_seconds`.

    In a live/paper trading deployment this typically signals a dead
    websocket, a disconnected broker feed, or a stuck upstream process --
    situations where continuing to trade blind is far more dangerous than
    stopping and raising a critical alert.
    """


class Backtest:
    """Orchestrates the event-driven backtest main loop."""

    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        execution_handler: ExecutionHandler,
        heartbeat_timeout_seconds: float = 30.0,
    ) -> None:
        event_queue = getattr(data_handler, "event_queue", None)
        if not isinstance(event_queue, queue.Queue):
            raise TypeError("data_handler must expose a queue.Queue as `event_queue`")

        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.execution_handler = execution_handler
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds

        self.event_queue: "queue.Queue" = event_queue
        self._latest_bars: Dict[str, dict] = {}
        self._last_market_event_wall_time: Optional[float] = None

    def _check_watchdog(self) -> None:
        """Raise MarketDataStallError if too much wall-clock time has passed
        since the last MarketEvent was processed. No-op before the first bar
        arrives, since there is nothing to stall yet."""
        if self._last_market_event_wall_time is None:
            return
        elapsed = time.time() - self._last_market_event_wall_time
        if elapsed > self.heartbeat_timeout_seconds:
            raise MarketDataStallError(
                f"No MarketEvent processed for {elapsed:.1f}s "
                f"(timeout={self.heartbeat_timeout_seconds}s). The market data "
                "stream appears to have stalled -- aborting rather than trading blind."
            )

    def _handle_market_event(self, event: MarketEvent) -> None:
        self._last_market_event_wall_time = time.time()
        self._latest_bars[event.symbol] = event.bar
        self.portfolio.update_timeindex(event)

        liquidate_event = self.risk_manager.evaluate_portfolio_risk()
        if liquidate_event is not None:
            self.event_queue.put(liquidate_event)
            return  # trading halted: skip signal generation for this bar

        self.strategy.calculate_signals(event)

    def _handle_signal_event(self, event: SignalEvent) -> None:
        order_event = self.portfolio.update_signal(event)
        if order_event is not None:
            self.event_queue.put(order_event)

    def _handle_order_event(self, event: OrderEvent) -> None:
        approved_event = self.risk_manager.process_order(event)
        if approved_event is None:
            return  # rejected: rate limit exceeded or trading halted

        market_bar = self._latest_bars.get(event.symbol)
        if market_bar is None:
            logger.warning("No market data yet for %s; dropping order.", event.symbol)
            return
        self.execution_handler.execute_order(approved_event, market_bar)

    def _handle_fill_event(self, event: FillEvent) -> None:
        self.portfolio.update_fill(event)

    def _handle_liquidate_event(self, event: LiquidateEvent) -> None:
        logger.critical("LiquidateEvent received (%s). Flattening all open positions.", event.reason)
        for order_event in self.portfolio.generate_liquidation_orders():
            market_bar = self._latest_bars.get(order_event.symbol)
            if market_bar is None:
                logger.warning("Cannot liquidate %s: no market data available.", order_event.symbol)
                continue
            # Liquidation orders deliberately bypass RiskManager.process_order:
            # trading is already halted, and the sole purpose here is to
            # reduce risk, never to add to it.
            self.execution_handler.execute_order(order_event, market_bar)

    def _dispatch(self, event: Event) -> None:
        handlers = {
            EventType.MARKET: self._handle_market_event,
            EventType.SIGNAL: self._handle_signal_event,
            EventType.ORDER: self._handle_order_event,
            EventType.FILL: self._handle_fill_event,
            EventType.LIQUIDATE: self._handle_liquidate_event,
        }
        handlers[event.type](event)

    def run(self) -> None:
        logger.info("Starting event-driven backtest.")
        while self.data_handler.continue_backtest:
            self.data_handler.update_bars()
            self._check_watchdog()

            while True:
                try:
                    event = self.event_queue.get(block=False)
                except queue.Empty:
                    break
                self._dispatch(event)

        logger.info("Backtest complete. Final equity: %.2f", self.portfolio.current_equity)
