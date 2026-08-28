"""Unit tests for Portfolio's round-trip trade reconstruction (used only
for post-hoc analytics, never for live sizing/risk decisions)."""
from __future__ import annotations

import unittest

from backtesting_engine.event import FillEvent, OrderDirection
from backtesting_engine.portfolio import Portfolio


class SimpleRoundTripTests(unittest.TestCase):
    def test_long_trade_closed_flat_records_correct_pnl(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0, fixed_order_quantity=100)

        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, fill_price=1.1000, commission=5.0, slippage=0.0))
        self.assertEqual(portfolio.closed_trades, [])  # still open

        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, fill_price=1.1050, commission=5.0, slippage=0.0))

        self.assertEqual(len(portfolio.closed_trades), 1)
        trade = portfolio.closed_trades[0]
        self.assertEqual(trade.direction, OrderDirection.BUY)
        self.assertEqual(trade.quantity, 100)
        self.assertAlmostEqual(trade.entry_price, 1.1000)
        self.assertAlmostEqual(trade.exit_price, 1.1050)
        expected_pnl = (1.1050 - 1.1000) * 100 - 10.0  # price move minus both commissions
        self.assertAlmostEqual(trade.pnl, expected_pnl)
        self.assertEqual(portfolio.positions["EURUSD"], 0)

    def test_short_trade_pnl_sign_is_correct(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)

        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.SELL, fill_price=1.1000, commission=0.0, slippage=0.0))
        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, fill_price=1.0950, commission=0.0, slippage=0.0))

        trade = portfolio.closed_trades[0]
        self.assertEqual(trade.direction, OrderDirection.SELL)
        # Price dropped after shorting -> profit.
        self.assertAlmostEqual(trade.pnl, (1.1000 - 1.0950) * 100)


class FlipTradeTests(unittest.TestCase):
    def test_single_fill_flipping_long_to_short_closes_and_opens_in_one_shot(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)

        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, fill_price=1.1000, commission=0.0, slippage=0.0))
        # A single SELL of 150 units: closes the 100-unit long and opens a
        # fresh 50-unit short, both at the same fill price.
        portfolio.update_fill(FillEvent("EURUSD", 150, OrderDirection.SELL, fill_price=1.1020, commission=0.0, slippage=0.0))

        self.assertEqual(len(portfolio.closed_trades), 1)
        closed = portfolio.closed_trades[0]
        self.assertEqual(closed.quantity, 100)
        self.assertAlmostEqual(closed.pnl, (1.1020 - 1.1000) * 100)
        self.assertEqual(portfolio.positions["EURUSD"], -50)

        # Closing the remaining short should now produce a second trade
        # for exactly the 50 units opened by the flip.
        portfolio.update_fill(FillEvent("EURUSD", 50, OrderDirection.BUY, fill_price=1.0990, commission=0.0, slippage=0.0))
        self.assertEqual(len(portfolio.closed_trades), 2)
        second = portfolio.closed_trades[1]
        self.assertEqual(second.direction, OrderDirection.SELL)
        self.assertEqual(second.quantity, 50)
        self.assertAlmostEqual(second.entry_price, 1.1020)
        self.assertAlmostEqual(second.pnl, (1.1020 - 1.0990) * 50)

    def test_commission_is_prorated_between_closing_and_opening_portions(self) -> None:
        portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0)

        portfolio.update_fill(FillEvent("EURUSD", 100, OrderDirection.BUY, fill_price=1.1000, commission=10.0, slippage=0.0))
        # Flip fill: 100 closes the long, 50 opens a new short; commission
        # of 15 should split 100/150 to the close and 50/150 to the open.
        portfolio.update_fill(FillEvent("EURUSD", 150, OrderDirection.SELL, fill_price=1.1020, commission=15.0, slippage=0.0))

        closed = portfolio.closed_trades[0]
        expected_closing_commission = 10.0 + 15.0 * (100 / 150)
        self.assertAlmostEqual(closed.commission, expected_closing_commission)


if __name__ == "__main__":
    unittest.main()
