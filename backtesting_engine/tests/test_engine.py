"""Unit tests for the Backtest event loop, including the heartbeat/watchdog."""
from __future__ import annotations

import queue
import time
import unittest
from typing import List

from backtesting_engine.data_handler import DataHandler
from backtesting_engine.engine import Backtest, MarketDataStallError
from backtesting_engine.event import MarketEvent
from backtesting_engine.execution_handler import SimulatedExecutionHandler
from backtesting_engine.portfolio import Portfolio
from backtesting_engine.risk_manager import RiskManager
from backtesting_engine.strategy import Strategy


class _NoOpStrategy(Strategy):
    def calculate_signals(self, event: MarketEvent) -> None:
        pass


class _StallingDataHandler(DataHandler):
    """Emits a handful of bars, then keeps `continue_backtest` True forever
    without producing any further MarketEvents -- simulating a dead feed."""

    def __init__(self, event_queue: "queue.Queue", symbol: str, n_bars: int, stall_sleep: float) -> None:
        self.event_queue = event_queue
        self.symbol = symbol
        self.continue_backtest = True
        self._remaining = n_bars
        self._stall_sleep = stall_sleep

    def get_latest_bars(self, symbol: str, n: int = 1) -> List[dict]:
        return []

    def update_bars(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            self.event_queue.put(
                MarketEvent(self.symbol, {"close": 100.0, "volume": 10_000, "timestamp": time.time()})
            )
        else:
            time.sleep(self._stall_sleep)  # simulate a feed that stopped delivering data


class WatchdogTests(unittest.TestCase):
    def _build_backtest(self, n_bars: int, stall_sleep: float, heartbeat_timeout: float) -> Backtest:
        event_queue: "queue.Queue" = queue.Queue()
        symbol = "AAPL"
        data_handler = _StallingDataHandler(event_queue, symbol, n_bars=n_bars, stall_sleep=stall_sleep)
        portfolio = Portfolio(symbol_list=[symbol], initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio)
        execution_handler = SimulatedExecutionHandler(event_queue)
        strategy = _NoOpStrategy()
        return Backtest(
            data_handler=data_handler,
            strategy=strategy,
            portfolio=portfolio,
            risk_manager=risk_manager,
            execution_handler=execution_handler,
            heartbeat_timeout_seconds=heartbeat_timeout,
        )

    def test_stalled_feed_raises_market_data_stall_error(self) -> None:
        backtest = self._build_backtest(n_bars=2, stall_sleep=0.05, heartbeat_timeout=0.03)
        with self.assertRaises(MarketDataStallError):
            backtest.run()

    def test_healthy_feed_does_not_raise(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        symbol = "AAPL"

        class _FiniteDataHandler(DataHandler):
            def __init__(self) -> None:
                self.event_queue = event_queue
                self.continue_backtest = True
                self._remaining = 5

            def get_latest_bars(self, symbol: str, n: int = 1) -> List[dict]:
                return []

            def update_bars(self) -> None:
                if self._remaining > 0:
                    self._remaining -= 1
                    self.event_queue.put(MarketEvent(symbol, {"close": 100.0, "volume": 10_000}))
                else:
                    self.continue_backtest = False

        data_handler = _FiniteDataHandler()
        portfolio = Portfolio(symbol_list=[symbol], initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio)
        execution_handler = SimulatedExecutionHandler(event_queue)
        backtest = Backtest(
            data_handler=data_handler,
            strategy=_NoOpStrategy(),
            portfolio=portfolio,
            risk_manager=risk_manager,
            execution_handler=execution_handler,
            heartbeat_timeout_seconds=30.0,
        )
        backtest.run()  # should complete without raising


if __name__ == "__main__":
    unittest.main()
