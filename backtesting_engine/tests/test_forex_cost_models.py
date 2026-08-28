"""Unit tests for the Forex-specific cost and position-sizing models."""
from __future__ import annotations

import unittest

from backtesting_engine.event import OrderDirection
from backtesting_engine.forex_cost_models import (
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
)


class ForexCommissionModelTests(unittest.TestCase):
    def test_commission_scales_with_lots_not_price(self) -> None:
        model = ForexCommissionModel(commission_per_standard_lot=3.0)
        # 1 standard lot (100,000 units), regardless of price.
        self.assertAlmostEqual(model.calculate(quantity=100_000, fill_price=1.0850), 3.0)
        self.assertAlmostEqual(model.calculate(quantity=100_000, fill_price=150.0), 3.0)

    def test_commission_scales_linearly_with_lot_count(self) -> None:
        model = ForexCommissionModel(commission_per_standard_lot=3.0)
        half_lot = model.calculate(quantity=50_000, fill_price=1.0850)
        two_lots = model.calculate(quantity=200_000, fill_price=1.0850)
        self.assertAlmostEqual(half_lot, 1.5)
        self.assertAlmostEqual(two_lots, 6.0)

    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            ForexCommissionModel(commission_per_standard_lot=-1.0)
        with self.assertRaises(ValueError):
            ForexCommissionModel(standard_lot_size=0)


class ForexSlippageModelTests(unittest.TestCase):
    def test_buy_slips_up_and_sell_slips_down_by_fixed_pips(self) -> None:
        model = ForexSlippageModel(slippage_pips=1.0, is_jpy_pair=False)
        reference_price = 1.0850

        buy_price = model.slipped_price(OrderDirection.BUY, quantity=100_000, reference_price=reference_price)
        sell_price = model.slipped_price(OrderDirection.SELL, quantity=100_000, reference_price=reference_price)

        self.assertAlmostEqual(buy_price, reference_price + 0.0001)
        self.assertAlmostEqual(sell_price, reference_price - 0.0001)

    def test_jpy_pair_uses_a_larger_pip_value(self) -> None:
        model = ForexSlippageModel(slippage_pips=1.0, is_jpy_pair=True)
        reference_price = 150.00

        buy_price = model.slipped_price(OrderDirection.BUY, quantity=100_000, reference_price=reference_price)
        self.assertAlmostEqual(buy_price, reference_price + 0.01)

    def test_slippage_does_not_scale_with_order_size(self) -> None:
        """Documents the model's known simplification: unlike the generic
        SlippageModel, pip slippage here is constant regardless of size."""
        model = ForexSlippageModel(slippage_pips=0.5)
        reference_price = 1.0850

        small = model.slipped_price(OrderDirection.BUY, quantity=1_000, reference_price=reference_price)
        large = model.slipped_price(OrderDirection.BUY, quantity=10_000_000, reference_price=reference_price)
        self.assertAlmostEqual(small, large)


class ForexPositionSizerTests(unittest.TestCase):
    def test_calculate_lot_size_matches_fixed_fractional_formula(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        # 1% of 100,000 = 1,000 capital at risk; 20 pip stop -> $50/pip risk
        # budget; at $10/pip/lot that's 5.0 standard lots.
        lots = sizer.calculate_lot_size(account_equity=100_000.0, stop_loss_pips=20.0)
        self.assertAlmostEqual(lots, 5.0)

    def test_lot_size_rounds_to_nearest_micro_lot(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        lots = sizer.calculate_lot_size(account_equity=100_000.0, stop_loss_pips=33.0)
        self.assertEqual(lots, round(1000.0 / 33.0 / 10.0, 2))

    def test_sizing_scales_with_current_equity_not_a_frozen_balance(self) -> None:
        sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
        smaller_account_lots = sizer.calculate_lot_size(account_equity=50_000.0, stop_loss_pips=20.0)
        larger_account_lots = sizer.calculate_lot_size(account_equity=100_000.0, stop_loss_pips=20.0)
        self.assertLess(smaller_account_lots, larger_account_lots)

    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            ForexPositionSizer(risk_per_trade_pct=0.0)
        with self.assertRaises(ValueError):
            ForexPositionSizer(risk_per_trade_pct=1.0)
        with self.assertRaises(ValueError):
            ForexPositionSizer(pip_value_per_standard_lot=0)

        sizer = ForexPositionSizer()
        with self.assertRaises(ValueError):
            sizer.calculate_lot_size(account_equity=0.0, stop_loss_pips=20.0)
        with self.assertRaises(ValueError):
            sizer.calculate_lot_size(account_equity=100_000.0, stop_loss_pips=0.0)


if __name__ == "__main__":
    unittest.main()
