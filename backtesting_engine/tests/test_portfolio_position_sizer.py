"""Unit tests for Portfolio's optional risk-based position sizing."""
from __future__ import annotations

import unittest

from backtesting_engine.event import OrderDirection, SignalDirection, SignalEvent
from backtesting_engine.forex_cost_models import ForexPositionSizer
from backtesting_engine.portfolio import Portfolio


class PortfolioFixedSizingRegressionTests(unittest.TestCase):
    def test_without_a_sizer_uses_fixed_order_quantity(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0, fixed_order_quantity=100)
        signal = SignalEvent("EURUSD", SignalDirection.LONG, stop_loss_pips=20.0)  # ignored: no sizer configured

        order = portfolio.update_signal(signal)

        self.assertIsNotNone(order)
        self.assertEqual(order.quantity, 100)
        self.assertEqual(order.direction, OrderDirection.BUY)


class PortfolioRiskBasedSizingTests(unittest.TestCase):
    def test_sizer_computes_quantity_from_stop_distance_and_equity(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        portfolio = Portfolio(
            symbol_list=["EURUSD"],
            initial_capital=100_000.0,
            position_sizer=sizer,
            lot_size=100_000.0,
        )
        # 1% of 100,000 / 20 pips / $10 per pip per lot = 5.0 lots = 500,000 units.
        signal = SignalEvent("EURUSD", SignalDirection.LONG, stop_loss_pips=20.0)

        order = portfolio.update_signal(signal)

        self.assertIsNotNone(order)
        self.assertEqual(order.quantity, 500_000)
        self.assertEqual(order.direction, OrderDirection.BUY)

    def test_falls_back_to_fixed_quantity_when_signal_has_no_stop(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        portfolio = Portfolio(
            symbol_list=["EURUSD"],
            initial_capital=100_000.0,
            fixed_order_quantity=1_000,
            position_sizer=sizer,
        )
        signal = SignalEvent("EURUSD", SignalDirection.LONG)  # no stop_loss_pips

        order = portfolio.update_signal(signal)

        self.assertIsNotNone(order)
        self.assertEqual(order.quantity, 1_000)

    def test_sizing_reflects_drawn_down_equity_not_opening_capital(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        portfolio = Portfolio(
            symbol_list=["EURUSD"],
            initial_capital=100_000.0,
            position_sizer=sizer,
        )
        portfolio.cash = 50_000.0  # simulate a drawdown having occurred
        signal = SignalEvent("EURUSD", SignalDirection.LONG, stop_loss_pips=20.0)

        order = portfolio.update_signal(signal)

        # Half the equity -> half the position size (2.5 lots = 250,000 units).
        self.assertEqual(order.quantity, 250_000)


if __name__ == "__main__":
    unittest.main()
