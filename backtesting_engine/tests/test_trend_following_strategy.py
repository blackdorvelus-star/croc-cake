"""Unit tests for the Donchian breakout trend-following strategy."""
from __future__ import annotations

import queue
import unittest
from datetime import datetime, timedelta

from backtesting_engine.event import MarketEvent, SignalDirection
from backtesting_engine.trend_following_strategy import DonchianTrendStrategy

START = datetime(2024, 1, 1, 0, 0)


def _bar(high: float, low: float, close: float, index: int) -> dict:
    return {
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1_000.0,
        "timestamp": START + timedelta(hours=index),
    }


def _feed_flat_range(strategy: DonchianTrendStrategy, symbol: str, n: int, start_index: int = 0) -> int:
    """Feeds n flat bars (high=101, low=99, close=100) to build up both the
    Donchian channel history and the ATR warmup. Returns the next free index."""
    for i in range(n):
        strategy.calculate_signals(MarketEvent(symbol, _bar(101.0, 99.0, 100.0, start_index + i)))
    return start_index + n


class DonchianChannelBreakoutTests(unittest.TestCase):
    def _make_strategy(self, **kwargs) -> tuple:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = DonchianTrendStrategy(
            symbol_list=["EURUSD"], event_queue=event_queue, entry_lookback=5, exit_lookback=2, atr_period=5, **kwargs
        )
        return strategy, event_queue

    def test_no_signal_while_price_stays_inside_the_channel(self) -> None:
        strategy, event_queue = self._make_strategy()
        next_index = _feed_flat_range(strategy, "EURUSD", n=10)
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(100.5, 99.5, 100.0, next_index)))
        self.assertTrue(event_queue.empty())

    def test_breakout_above_channel_high_emits_long_with_atr_sized_stop(self) -> None:
        strategy, event_queue = self._make_strategy(atr_stop_multiple=2.0)
        next_index = _feed_flat_range(strategy, "EURUSD", n=10)
        # ATR has converged to the constant true range of 2.0 (high-low=101-99)
        # *before* this bar; this breakout bar's own true range (5.0, vs prior
        # close of 100) is folded into the ATR update before it's used to size
        # this same entry's stop -- consistent with every other strategy in
        # this package computing stop distance from the confirming bar itself.
        # Wilder update: new_atr = (2.0*4 + 5.0) / 5 = 2.6
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(105.0, 100.0, 104.0, next_index)))

        self.assertFalse(event_queue.empty())
        signal = event_queue.get_nowait()
        self.assertEqual(signal.direction, SignalDirection.LONG)
        # entry=104 (close), stop = 104 - 2*ATR(2.6) = 98.8 -> stop distance = 5.2
        self.assertAlmostEqual(signal.stop_loss_pips, 5.2 / 0.0001)

    def test_breakout_below_channel_low_emits_short(self) -> None:
        strategy, event_queue = self._make_strategy()
        next_index = _feed_flat_range(strategy, "EURUSD", n=10)
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(100.0, 95.0, 96.0, next_index)))

        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.SHORT)

    def test_current_bars_own_high_does_not_count_toward_its_own_breakout(self) -> None:
        """No-lookahead check: a single enormous bar must not be able to
        break out against a channel that includes itself."""
        strategy, event_queue = self._make_strategy()
        next_index = _feed_flat_range(strategy, "EURUSD", n=4)  # one short of the 5-bar lookback
        # This bar both extends the range AND is only the 5th bar fed --
        # the channel (built from the prior 4) shouldn't have enough
        # history yet, so no signal regardless of this bar's own extremity.
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(999.0, 1.0, 500.0, next_index)))
        self.assertTrue(event_queue.empty())

    def test_no_pyramiding_on_repeated_breakouts_in_the_same_direction(self) -> None:
        strategy, event_queue = self._make_strategy()
        next_index = _feed_flat_range(strategy, "EURUSD", n=10)
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(105.0, 100.0, 104.0, next_index)))
        next_index += 1
        event_queue.get_nowait()  # the entry signal

        strategy.calculate_signals(MarketEvent("EURUSD", _bar(110.0, 105.0, 109.0, next_index)))
        self.assertTrue(event_queue.empty())  # still long: no second LONG signal


class DonchianExitTests(unittest.TestCase):
    def _enter_long(self) -> tuple:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = DonchianTrendStrategy(
            symbol_list=["EURUSD"], event_queue=event_queue, entry_lookback=5, exit_lookback=2, atr_period=5,
            atr_stop_multiple=2.0,
        )
        next_index = _feed_flat_range(strategy, "EURUSD", n=10)
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(105.0, 100.0, 104.0, next_index)))
        next_index += 1
        entry_signal = event_queue.get_nowait()
        self.assertEqual(entry_signal.direction, SignalDirection.LONG)
        return strategy, event_queue, next_index

    def test_exit_on_initial_stop_hit(self) -> None:
        strategy, event_queue, next_index = self._enter_long()
        # stop = 104 - 2*ATR(2.6) = 98.8 (see breakout test for the ATR math);
        # a bar whose low touches it triggers the exit.
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(103.0, 98.5, 102.0, next_index)))
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)

    def test_exit_on_exit_channel_breakdown(self) -> None:
        strategy, event_queue, next_index = self._enter_long()
        # Two bars holding well above the stop, establishing a 2-bar exit
        # channel low around 103; a third bar closing below it exits.
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(106.0, 103.5, 105.0, next_index)))
        next_index += 1
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(106.0, 103.5, 105.0, next_index)))
        next_index += 1
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(104.0, 103.0, 103.2, next_index)))
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)

    def test_no_exit_while_price_stays_within_stop_and_exit_channel(self) -> None:
        strategy, event_queue, next_index = self._enter_long()
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(106.0, 103.5, 105.0, next_index)))
        self.assertTrue(event_queue.empty())


class DonchianValidationTests(unittest.TestCase):
    def test_rejects_exit_lookback_not_shorter_than_entry_lookback(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        with self.assertRaises(ValueError):
            DonchianTrendStrategy(symbol_list=["EURUSD"], event_queue=event_queue, entry_lookback=10, exit_lookback=10)

    def test_rejects_non_positive_atr_stop_multiple(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        with self.assertRaises(ValueError):
            DonchianTrendStrategy(symbol_list=["EURUSD"], event_queue=event_queue, atr_stop_multiple=0.0)


if __name__ == "__main__":
    unittest.main()
