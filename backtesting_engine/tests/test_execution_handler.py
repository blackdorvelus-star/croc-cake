"""Unit tests for the SlippageModel / CommissionModel cost models."""
from __future__ import annotations

import queue
import unittest

from backtesting_engine.event import OrderDirection, OrderEvent, OrderType
from backtesting_engine.execution_handler import CommissionModel, SimulatedExecutionHandler, SlippageModel


class SlippageModelTests(unittest.TestCase):
    def test_larger_orders_incur_more_slippage_than_smaller_ones(self) -> None:
        model = SlippageModel(base_spread_bps=1.0, impact_coefficient=15.0, fallback_avg_volume=100_000)
        reference_price = 100.0

        small_fill = model.slipped_price(OrderDirection.BUY, quantity=100, reference_price=reference_price, bar_volume=None)
        large_fill = model.slipped_price(OrderDirection.BUY, quantity=50_000, reference_price=reference_price, bar_volume=None)

        small_impact = small_fill - reference_price
        large_impact = large_fill - reference_price
        self.assertGreater(large_impact, small_impact)

    def test_buy_orders_slip_up_and_sell_orders_slip_down(self) -> None:
        model = SlippageModel(base_spread_bps=1.0, impact_coefficient=15.0, fallback_avg_volume=100_000)
        reference_price = 100.0

        buy_price = model.slipped_price(OrderDirection.BUY, quantity=1_000, reference_price=reference_price, bar_volume=None)
        sell_price = model.slipped_price(OrderDirection.SELL, quantity=1_000, reference_price=reference_price, bar_volume=None)

        self.assertGreater(buy_price, reference_price)
        self.assertLess(sell_price, reference_price)

    def test_low_bar_volume_increases_participation_rate_and_slippage(self) -> None:
        model = SlippageModel(base_spread_bps=1.0, impact_coefficient=15.0, fallback_avg_volume=1_000_000)
        reference_price = 100.0

        thin_market_price = model.slipped_price(OrderDirection.BUY, quantity=1_000, reference_price=reference_price, bar_volume=2_000)
        deep_market_price = model.slipped_price(OrderDirection.BUY, quantity=1_000, reference_price=reference_price, bar_volume=1_000_000)

        self.assertGreater(thin_market_price, deep_market_price)


class CommissionModelTests(unittest.TestCase):
    def test_minimum_commission_applies_to_small_orders(self) -> None:
        model = CommissionModel(commission_rate=0.0005, minimum_commission=1.0)
        commission = model.calculate(quantity=1, fill_price=10.0)
        self.assertEqual(commission, 1.0)

    def test_percentage_commission_applies_to_large_orders(self) -> None:
        model = CommissionModel(commission_rate=0.001, minimum_commission=1.0)
        commission = model.calculate(quantity=1_000, fill_price=100.0)
        self.assertAlmostEqual(commission, 100.0)


class SimulatedExecutionHandlerTests(unittest.TestCase):
    def test_execute_order_pushes_a_fill_event_with_costs_applied(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        handler = SimulatedExecutionHandler(event_queue)
        order = OrderEvent("AAPL", OrderType.MARKET, 100, OrderDirection.BUY)
        market_bar = {"close": 150.0, "volume": 500_000}

        fill = handler.execute_order(order, market_bar)

        self.assertIsNotNone(fill)
        self.assertEqual(fill.symbol, "AAPL")
        self.assertGreater(fill.fill_price, market_bar["close"])
        self.assertGreater(fill.commission, 0.0)
        self.assertFalse(event_queue.empty())


if __name__ == "__main__":
    unittest.main()
