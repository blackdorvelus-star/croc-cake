"""Unit tests for the post-hoc performance analytics module."""
from __future__ import annotations

import unittest

from backtesting_engine.analytics import compute_performance_report
from backtesting_engine.event import FillEvent, OrderDirection
from backtesting_engine.portfolio import Portfolio


class ComputePerformanceReportTests(unittest.TestCase):
    def test_no_trades_yields_a_report_with_none_metrics(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)
        report = compute_performance_report(portfolio)
        self.assertEqual(report.num_trades, 0)
        self.assertIsNone(report.win_rate)
        self.assertIsNone(report.profit_factor)
        self.assertEqual(report.final_equity, 100_000.0)

    def test_mixed_wins_and_losses_compute_expected_metrics(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)

        # Trade 1: +100 (win)
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, 1.1000, commission=0.0, slippage=0.0))
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, 1.1010, commission=0.0, slippage=0.0))
        # Trade 2: -50 (loss)
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, 1.1010, commission=0.0, slippage=0.0))
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, 1.1005, commission=0.0, slippage=0.0))

        report = compute_performance_report(portfolio)
        self.assertEqual(report.num_trades, 2)
        self.assertEqual(report.win_rate, 0.5)
        self.assertAlmostEqual(report.total_pnl, 100 * (0.0010 - 0.0005))
        self.assertAlmostEqual(report.profit_factor, (100 * 0.0010) / (100 * 0.0005))

    def test_average_r_uses_initial_capital_and_risk_pct(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, 1.1000, commission=0.0, slippage=0.0))
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, 1.1010, commission=0.0, slippage=0.0))

        report = compute_performance_report(portfolio, risk_per_trade_pct=0.01)
        # risk_amount = 100_000 * 0.01 = 1000; pnl = (1.1010-1.1000)*100 = 0.10
        self.assertAlmostEqual(report.average_r, 0.10 / 1000.0)

    def test_all_wins_yields_infinite_profit_factor(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, 1.1000, commission=0.0, slippage=0.0))
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, 1.1010, commission=0.0, slippage=0.0))

        report = compute_performance_report(portfolio)
        self.assertEqual(report.profit_factor, float("inf"))


if __name__ == "__main__":
    unittest.main()
