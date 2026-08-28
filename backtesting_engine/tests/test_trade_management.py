"""Unit tests for the R-multiple take-profit manager."""
from __future__ import annotations

import unittest

from backtesting_engine.event import SignalDirection
from backtesting_engine.trade_management import TakeProfitManager


class TakeProfitManagerTests(unittest.TestCase):
    def test_long_target_computed_at_reward_risk_ratio(self) -> None:
        manager = TakeProfitManager(reward_risk_ratio=2.0)
        # entry=100, invalidation=95 -> stop distance 5 -> target 100 + 2*5 = 110
        manager.register_entry("EURUSD", SignalDirection.LONG, entry_price=100.0, invalidation_level=95.0)
        self.assertAlmostEqual(manager.target_price("EURUSD"), 110.0)

    def test_short_target_computed_at_reward_risk_ratio(self) -> None:
        manager = TakeProfitManager(reward_risk_ratio=2.0)
        # entry=100, invalidation=105 -> stop distance 5 -> target 100 - 2*5 = 90
        manager.register_entry("EURUSD", SignalDirection.SHORT, entry_price=100.0, invalidation_level=105.0)
        self.assertAlmostEqual(manager.target_price("EURUSD"), 90.0)

    def test_long_target_hit_on_high(self) -> None:
        manager = TakeProfitManager(reward_risk_ratio=2.0)
        manager.register_entry("EURUSD", SignalDirection.LONG, entry_price=100.0, invalidation_level=95.0)
        self.assertFalse(manager.check_target_hit("EURUSD", {"high": 109.0, "low": 108.0}))
        self.assertTrue(manager.check_target_hit("EURUSD", {"high": 110.5, "low": 109.0}))

    def test_short_target_hit_on_low(self) -> None:
        manager = TakeProfitManager(reward_risk_ratio=2.0)
        manager.register_entry("EURUSD", SignalDirection.SHORT, entry_price=100.0, invalidation_level=105.0)
        self.assertFalse(manager.check_target_hit("EURUSD", {"high": 92.0, "low": 91.0}))
        self.assertTrue(manager.check_target_hit("EURUSD", {"high": 91.0, "low": 89.5}))

    def test_no_target_registered_returns_false(self) -> None:
        manager = TakeProfitManager()
        self.assertFalse(manager.check_target_hit("EURUSD", {"high": 999.0, "low": 0.0}))

    def test_clear_removes_target(self) -> None:
        manager = TakeProfitManager(reward_risk_ratio=2.0)
        manager.register_entry("EURUSD", SignalDirection.LONG, entry_price=100.0, invalidation_level=95.0)
        manager.clear("EURUSD")
        self.assertIsNone(manager.target_price("EURUSD"))
        self.assertFalse(manager.check_target_hit("EURUSD", {"high": 999.0, "low": 0.0}))

    def test_rejects_invalid_ratio(self) -> None:
        with self.assertRaises(ValueError):
            TakeProfitManager(reward_risk_ratio=0.0)


if __name__ == "__main__":
    unittest.main()
