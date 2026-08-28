"""Unit tests for the higher-timeframe daily bias filter, with particular
attention to the no-lookahead guarantee."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backtesting_engine.htf_bias import Bias, DailyBiasFilter


def _bar(close: float, ts: datetime) -> dict:
    return {"open": close, "high": close, "low": close, "close": close, "timestamp": ts}


class DailyBiasFilterTests(unittest.TestCase):
    def test_no_bias_before_first_day_completes(self) -> None:
        bias_filter = DailyBiasFilter(ema_period=5)
        start = datetime(2024, 1, 1, 0, 0)
        for hour in range(24):
            bias_filter.update(_bar(100.0, start + timedelta(hours=hour)))
        self.assertIsNone(bias_filter.bias)  # still inside day 1, nothing "completed" yet

    def test_todays_bars_never_affect_todays_own_bias(self) -> None:
        """The defining no-lookahead property: bias during a given day must
        depend only on prior days, never on that day's own (still forming)
        price action -- however extreme."""
        bias_filter = DailyBiasFilter(ema_period=5)
        start = datetime(2024, 1, 1, 0, 0)

        # Day 1: flat at 100 all day.
        for hour in range(24):
            bias_filter.update(_bar(100.0, start + timedelta(hours=hour)))
        # Day 2 begins: bias is still None (only one completed day, EMA needs
        # at least one prior close to compare a new one against -- here the
        # very first finalized close *becomes* the EMA, so bias appears only
        # once a second day starts and finalizes day 1).
        day2_start = start + timedelta(days=1)
        bias_filter.update(_bar(100.0, day2_start))
        self.assertIsNotNone(bias_filter.bias)
        bias_after_first_bar_of_day2 = bias_filter.bias

        # The rest of day 2 makes an enormous upward move -- if this leaked
        # into "today's" bias, it would flip bullish immediately.
        for hour in range(1, 24):
            bias_filter.update(_bar(100.0 + hour * 50.0, day2_start + timedelta(hours=hour)))
        self.assertEqual(bias_filter.bias, bias_after_first_bar_of_day2)  # unchanged all through day 2

        # Only once day 3 begins does day 2's huge close get folded into the EMA.
        day3_start = start + timedelta(days=2)
        bias_filter.update(_bar(100.0, day3_start))
        self.assertEqual(bias_filter.bias, Bias.BULLISH)

    def test_rejects_invalid_period(self) -> None:
        with self.assertRaises(ValueError):
            DailyBiasFilter(ema_period=1)


if __name__ == "__main__":
    unittest.main()
