"""Unit tests for the random-entry baseline strategy."""
from __future__ import annotations

import queue
import unittest
from datetime import datetime

from backtesting_engine.event import MarketEvent, SignalDirection
from backtesting_engine.random_baseline_strategy import RandomKillzoneEntryStrategy

IN_KILLZONE = datetime(2024, 1, 1, 8, 0)
OUTSIDE_KILLZONE = datetime(2024, 1, 1, 14, 0)


def _bar(ts: datetime) -> dict:
    return {"open": 1.10, "high": 1.101, "low": 1.099, "close": 1.10, "volume": 1000.0, "timestamp": ts}


class RandomKillzoneEntryStrategyTests(unittest.TestCase):
    def test_never_enters_outside_a_killzone(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = RandomKillzoneEntryStrategy(
            symbol_list=["EURUSD"], event_queue=event_queue, entry_probability_per_bar=1.0, random_seed=1
        )
        for _ in range(20):
            strategy.calculate_signals(MarketEvent("EURUSD", _bar(OUTSIDE_KILLZONE)))
        self.assertTrue(event_queue.empty())

    def test_probability_one_enters_on_first_killzone_bar_with_stop(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = RandomKillzoneEntryStrategy(
            symbol_list=["EURUSD"],
            event_queue=event_queue,
            entry_probability_per_bar=1.0,
            stop_loss_pips=15.0,
            random_seed=1,
        )
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(IN_KILLZONE)))

        self.assertFalse(event_queue.empty())
        signal = event_queue.get_nowait()
        self.assertIn(signal.direction, (SignalDirection.LONG, SignalDirection.SHORT))
        self.assertEqual(signal.stop_loss_pips, 15.0)

    def test_stays_flat_and_never_pyramids_while_already_in_a_position(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = RandomKillzoneEntryStrategy(
            symbol_list=["EURUSD"], event_queue=event_queue, entry_probability_per_bar=1.0, random_seed=1
        )
        for _ in range(10):
            strategy.calculate_signals(MarketEvent("EURUSD", _bar(IN_KILLZONE)))
        # Only the very first bar should have produced an entry signal.
        self.assertEqual(event_queue.qsize(), 1)

    def test_flattens_on_killzone_end(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = RandomKillzoneEntryStrategy(
            symbol_list=["EURUSD"], event_queue=event_queue, entry_probability_per_bar=1.0, random_seed=1
        )
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(IN_KILLZONE)))
        event_queue.get_nowait()  # the entry signal

        strategy.calculate_signals(MarketEvent("EURUSD", _bar(OUTSIDE_KILLZONE)))
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)

    def test_same_seed_is_deterministic(self) -> None:
        results = []
        for _ in range(2):
            event_queue: "queue.Queue" = queue.Queue()
            strategy = RandomKillzoneEntryStrategy(
                symbol_list=["EURUSD"], event_queue=event_queue, entry_probability_per_bar=0.5, random_seed=42
            )
            for _ in range(30):
                strategy.calculate_signals(MarketEvent("EURUSD", _bar(IN_KILLZONE)))
            directions = []
            while not event_queue.empty():
                directions.append(event_queue.get_nowait().direction)
            results.append(directions)
        self.assertEqual(results[0], results[1])

    def test_rejects_invalid_parameters(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        with self.assertRaises(ValueError):
            RandomKillzoneEntryStrategy(symbol_list=["EURUSD"], event_queue=event_queue, entry_probability_per_bar=0.0)
        with self.assertRaises(ValueError):
            RandomKillzoneEntryStrategy(symbol_list=["EURUSD"], event_queue=event_queue, stop_loss_pips=0.0)


if __name__ == "__main__":
    unittest.main()
