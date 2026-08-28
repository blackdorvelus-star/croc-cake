"""Unit tests for the RiskManager kill switches (no external dependencies)."""
from __future__ import annotations

import time
import unittest

from backtesting_engine.event import LiquidateEvent, OrderDirection, OrderEvent, OrderType
from backtesting_engine.risk_manager import RiskManager


class _FakePortfolio:
    """Minimal stand-in satisfying the RiskManager's PortfolioLike protocol."""

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        self.initial_capital = initial_capital
        self._equity = initial_capital

    @property
    def current_equity(self) -> float:
        return self._equity

    def set_equity(self, value: float) -> None:
        self._equity = value


def _make_order(symbol: str = "AAPL", timestamp: float | None = None) -> OrderEvent:
    return OrderEvent(symbol, OrderType.MARKET, 10, OrderDirection.BUY, timestamp=timestamp)


class RateLimiterTests(unittest.TestCase):
    def test_orders_within_limit_are_approved(self) -> None:
        portfolio = _FakePortfolio()
        risk_manager = RiskManager(portfolio, max_orders_per_minute=5, max_drawdown_pct=0.02)
        now = time.time()

        for _ in range(5):
            order = _make_order(timestamp=now)
            self.assertIsNotNone(risk_manager.process_order(order))

    def test_orders_beyond_limit_are_rejected(self) -> None:
        portfolio = _FakePortfolio()
        risk_manager = RiskManager(portfolio, max_orders_per_minute=3, max_drawdown_pct=0.02)
        now = time.time()

        for _ in range(3):
            self.assertIsNotNone(risk_manager.process_order(_make_order(timestamp=now)))

        rejected = risk_manager.process_order(_make_order(timestamp=now))
        self.assertIsNone(rejected)

    def test_old_orders_fall_out_of_the_rolling_window(self) -> None:
        portfolio = _FakePortfolio()
        risk_manager = RiskManager(portfolio, max_orders_per_minute=2, max_drawdown_pct=0.02)
        t0 = 1_000.0

        self.assertIsNotNone(risk_manager.process_order(_make_order(timestamp=t0)))
        self.assertIsNotNone(risk_manager.process_order(_make_order(timestamp=t0 + 1)))
        # Third order in the same minute should be rejected.
        self.assertIsNone(risk_manager.process_order(_make_order(timestamp=t0 + 2)))
        # But once 60s+ have passed, the window has rolled forward.
        self.assertIsNotNone(risk_manager.process_order(_make_order(timestamp=t0 + 61)))


class DrawdownKillSwitchTests(unittest.TestCase):
    def test_no_breach_when_equity_is_healthy(self) -> None:
        portfolio = _FakePortfolio(initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio, max_drawdown_pct=0.02)
        portfolio.set_equity(99_000.0)  # -1%, within tolerance

        self.assertIsNone(risk_manager.evaluate_portfolio_risk())
        self.assertFalse(risk_manager.trading_halted)

    def test_breach_halts_trading_and_emits_liquidate_event(self) -> None:
        portfolio = _FakePortfolio(initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio, max_drawdown_pct=0.02)
        portfolio.set_equity(97_000.0)  # -3%, breaches the 2% limit

        event = risk_manager.evaluate_portfolio_risk()

        self.assertIsInstance(event, LiquidateEvent)
        self.assertTrue(risk_manager.trading_halted)

    def test_orders_rejected_after_drawdown_halt(self) -> None:
        portfolio = _FakePortfolio(initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio, max_drawdown_pct=0.02)
        portfolio.set_equity(97_000.0)
        risk_manager.evaluate_portfolio_risk()

        self.assertIsNone(risk_manager.process_order(_make_order()))

    def test_reset_halt_re_arms_the_risk_manager(self) -> None:
        portfolio = _FakePortfolio(initial_capital=100_000.0)
        risk_manager = RiskManager(portfolio, max_drawdown_pct=0.02)
        portfolio.set_equity(97_000.0)
        risk_manager.evaluate_portfolio_risk()
        self.assertTrue(risk_manager.trading_halted)

        risk_manager.reset_halt()
        self.assertFalse(risk_manager.trading_halted)
        self.assertIsNotNone(risk_manager.process_order(_make_order()))


if __name__ == "__main__":
    unittest.main()
