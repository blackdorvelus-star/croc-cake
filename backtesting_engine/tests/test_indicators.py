"""Unit tests for the ADX indicator."""
from __future__ import annotations

import unittest

from backtesting_engine.indicators import ADXIndicator


class ADXIndicatorTests(unittest.TestCase):
    def test_no_value_before_warmup(self) -> None:
        adx = ADXIndicator(period=14)
        for _ in range(10):
            adx.update({"high": 101, "low": 99, "close": 100})
        self.assertIsNone(adx.value)

    def test_strong_trend_produces_high_adx(self) -> None:
        adx = ADXIndicator(period=14)
        price = 100.0
        for _ in range(60):
            adx.update({"high": price + 0.5, "low": price - 0.1, "close": price + 0.3})
            price += 1.0
        self.assertIsNotNone(adx.value)
        self.assertGreater(adx.value, 70.0)

    def test_choppy_range_produces_low_adx(self) -> None:
        adx = ADXIndicator(period=14)
        price = 100.0
        for i in range(60):
            delta = 0.5 if i % 2 == 0 else -0.5
            adx.update({"high": price + abs(delta) + 0.1, "low": price - abs(delta) - 0.1, "close": price + delta})
        self.assertIsNotNone(adx.value)
        self.assertLess(adx.value, 20.0)

    def test_rejects_invalid_period(self) -> None:
        with self.assertRaises(ValueError):
            ADXIndicator(period=1)


if __name__ == "__main__":
    unittest.main()
