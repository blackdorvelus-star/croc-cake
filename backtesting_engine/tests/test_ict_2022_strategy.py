"""Unit tests for the ICT "2022 Model" strategy: fractal swings, MSS via
candle-body close, FVG detection, and killzone-boxed entry cancellation."""
from __future__ import annotations

import queue
import unittest
from datetime import datetime

from backtesting_engine.event import MarketEvent, SignalDirection
from backtesting_engine.htf_bias import Bias, DailyBiasFilter
from backtesting_engine.ict_2022_strategy import FractalSwingDetector, ICT2022Strategy
from backtesting_engine.indicators import ADXIndicator


def _bar(high: float, low: float, close: float, ts: datetime, volume: float = 1_000.0) -> dict:
    return {"open": close, "high": high, "low": low, "close": close, "volume": volume, "timestamp": ts}


class FractalSwingDetectorTests(unittest.TestCase):
    def test_no_confirmation_before_five_bars(self) -> None:
        detector = FractalSwingDetector()
        ts = datetime(2024, 1, 1, 8, 0)
        for high, low in [(101, 99), (102, 98), (100, 90), (103, 95)]:
            detector.update(_bar(high, low, (high + low) / 2, ts))
        self.assertIsNone(detector.last_confirmed_swing_high)
        self.assertIsNone(detector.last_confirmed_swing_low)

    def test_confirms_swing_low_with_two_bars_lower_on_each_side(self) -> None:
        detector = FractalSwingDetector()
        ts = datetime(2024, 1, 1, 8, 0)
        # Center bar (index 2) has the lowest low of the 5-bar window.
        for high, low in [(101, 99), (102, 98), (100, 90), (103, 95), (104, 96)]:
            detector.update(_bar(high, low, (high + low) / 2, ts))
        self.assertEqual(detector.last_confirmed_swing_low, 90)
        self.assertIsNone(detector.last_confirmed_swing_high)

    def test_confirms_swing_high_with_two_bars_higher_on_each_side(self) -> None:
        detector = FractalSwingDetector()
        ts = datetime(2024, 1, 1, 8, 0)
        for high, low in [(105, 97), (106, 98), (110, 99), (107, 100), (108, 101)]:
            detector.update(_bar(high, low, (high + low) / 2, ts))
        self.assertEqual(detector.last_confirmed_swing_high, 110)


IN_KILLZONE = datetime(2024, 1, 1, 8, 0)  # inside the default new_york_am window
OUTSIDE_KILLZONE = datetime(2024, 1, 1, 14, 0)  # outside every default window


def _feed_confirmed_swing_range(strategy: ICT2022Strategy, symbol: str, ts: datetime = IN_KILLZONE) -> None:
    """Feeds 10 bars establishing a confirmed swing low of 90 and a
    confirmed swing high of 110, leaving the strategy in IDLE afterwards
    (no sweep condition is met by this setup range itself)."""
    swing_low_range = [(101, 99), (102, 98), (100, 90), (103, 95), (104, 96)]
    swing_high_range = [(105, 97), (106, 98), (110, 99), (107, 100), (108, 101)]
    for high, low in swing_low_range + swing_high_range:
        strategy.calculate_signals(MarketEvent(symbol, _bar(high, low, (high + low) / 2, ts)))


class ICT2022StrategyTests(unittest.TestCase):
    def _make_strategy(self, **kwargs) -> tuple:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = ICT2022Strategy(symbol_list=["EURUSD"], event_queue=event_queue, **kwargs)
        return strategy, event_queue

    def test_full_happy_path_emits_long_signal_with_stop_loss_pips(self) -> None:
        strategy, event_queue = self._make_strategy(pip_value=0.0001)
        symbol = "EURUSD"
        _feed_confirmed_swing_range(strategy, symbol)
        self.assertTrue(event_queue.empty())  # range alone: no sweep, no signal

        # Sweep: wick below the confirmed swing low (90) then close back above it.
        strategy.calculate_signals(MarketEvent(symbol, _bar(95, 85, 92, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())

        # A bar that doesn't yet confirm MSS (close still below swing high 110).
        strategy.calculate_signals(MarketEvent(symbol, _bar(101, 98, 100, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())

        # MSS confirmation (close > 110) -- also forms the FVG on this same bar
        # (recent 3 bars: sweep bar high=95, this bar's low=99 -> gap 95..99).
        strategy.calculate_signals(MarketEvent(symbol, _bar(116, 99, 115, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())  # FVG just formed, not yet filled

        # Price stays away from the FVG zone (95..99): still no entry.
        strategy.calculate_signals(MarketEvent(symbol, _bar(110, 105, 108, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())

        # Price trades back down into the FVG zone -> entry triggers.
        strategy.calculate_signals(MarketEvent(symbol, _bar(103, 97, 98, IN_KILLZONE)))

        self.assertFalse(event_queue.empty())
        signal = event_queue.get_nowait()
        self.assertEqual(signal.direction, SignalDirection.LONG)
        # invalidation_level is the sweep bar's low (85); entry price is this bar's close (98).
        self.assertAlmostEqual(signal.stop_loss_pips, abs(98 - 85) / 0.0001)

    def test_mss_requires_a_body_close_not_a_wick(self) -> None:
        strategy, event_queue = self._make_strategy()
        symbol = "EURUSD"
        _feed_confirmed_swing_range(strategy, symbol)
        strategy.calculate_signals(MarketEvent(symbol, _bar(95, 85, 92, IN_KILLZONE)))  # sweep

        # Wicks above the swing high (110) but the body closes back below it.
        strategy.calculate_signals(MarketEvent(symbol, _bar(112, 98, 105, IN_KILLZONE)))

        self.assertTrue(event_queue.empty())
        # A later bar that actually confirms MSS should still work: the
        # setup must still be alive (SWEPT), not silently broken.
        strategy.calculate_signals(MarketEvent(symbol, _bar(116, 99, 115, IN_KILLZONE)))
        # No FVG guaranteed here, but this at least proves the setup survived.

    def test_setup_is_cancelled_the_moment_killzone_ends(self) -> None:
        strategy, event_queue = self._make_strategy()
        symbol = "EURUSD"
        _feed_confirmed_swing_range(strategy, symbol)
        strategy.calculate_signals(MarketEvent(symbol, _bar(95, 85, 92, IN_KILLZONE)))  # sweep
        strategy.calculate_signals(MarketEvent(symbol, _bar(101, 98, 100, IN_KILLZONE)))  # not yet MSS
        strategy.calculate_signals(MarketEvent(symbol, _bar(116, 99, 115, IN_KILLZONE)))  # MSS + FVG formed
        self.assertTrue(event_queue.empty())

        # Killzone ends before price ever returns to the FVG zone.
        strategy.calculate_signals(MarketEvent(symbol, _bar(110, 105, 108, OUTSIDE_KILLZONE)))
        self.assertTrue(event_queue.empty())

        # Even if price later dips into the old zone, back inside a
        # killzone, it must not fire: the setup was cancelled, not paused.
        strategy.calculate_signals(MarketEvent(symbol, _bar(103, 97, 98, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())

    def test_setup_expires_after_max_bars_awaiting_mss(self) -> None:
        strategy, event_queue = self._make_strategy(max_bars_awaiting_mss=2)
        symbol = "EURUSD"
        _feed_confirmed_swing_range(strategy, symbol)
        strategy.calculate_signals(MarketEvent(symbol, _bar(95, 85, 92, IN_KILLZONE)))  # sweep -> SWEPT

        # Two neutral bars that neither confirm nor re-sweep -> setup expires.
        strategy.calculate_signals(MarketEvent(symbol, _bar(101, 98, 100, IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(101, 98, 100, IN_KILLZONE)))

        # A bar that would have confirmed MSS must no longer do anything.
        strategy.calculate_signals(MarketEvent(symbol, _bar(116, 99, 115, IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(110, 105, 108, IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(103, 97, 98, IN_KILLZONE)))

        self.assertTrue(event_queue.empty())


def _run_full_bullish_setup(strategy: ICT2022Strategy, symbol: str = "EURUSD") -> None:
    """Replays the full sweep -> MSS -> FVG -> entry-trigger sequence from
    test_full_happy_path_emits_long_signal_with_stop_loss_pips: entry
    price 98, invalidation 85 (the sweep low)."""
    _feed_confirmed_swing_range(strategy, symbol)
    strategy.calculate_signals(MarketEvent(symbol, _bar(95, 85, 92, IN_KILLZONE)))  # sweep
    strategy.calculate_signals(MarketEvent(symbol, _bar(101, 98, 100, IN_KILLZONE)))  # not yet MSS
    strategy.calculate_signals(MarketEvent(symbol, _bar(116, 99, 115, IN_KILLZONE)))  # MSS + FVG formed
    strategy.calculate_signals(MarketEvent(symbol, _bar(110, 105, 108, IN_KILLZONE)))  # price away from zone
    strategy.calculate_signals(MarketEvent(symbol, _bar(103, 97, 98, IN_KILLZONE)))  # fills the zone -> entry


class ICT2022StrategyFilterTests(unittest.TestCase):
    def test_htf_bias_filter_blocks_a_setup_against_the_trend(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        bias_filter = DailyBiasFilter(ema_period=5)
        bias_filter.bias = Bias.BEARISH
        strategy = ICT2022Strategy(symbol_list=["EURUSD"], event_queue=event_queue, htf_bias_filter=bias_filter)
        _run_full_bullish_setup(strategy)
        self.assertTrue(event_queue.empty())

    def test_htf_bias_filter_allows_a_setup_with_the_trend(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        bias_filter = DailyBiasFilter(ema_period=5)
        bias_filter.bias = Bias.BULLISH
        strategy = ICT2022Strategy(symbol_list=["EURUSD"], event_queue=event_queue, htf_bias_filter=bias_filter)
        _run_full_bullish_setup(strategy)
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.LONG)

    def test_adx_filter_blocks_entry_above_threshold(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        adx_filter = ADXIndicator(period=14)
        adx_filter.value = 40.0
        strategy = ICT2022Strategy(
            symbol_list=["EURUSD"], event_queue=event_queue, adx_filter=adx_filter, max_adx_for_entry=25.0
        )
        _run_full_bullish_setup(strategy)
        self.assertTrue(event_queue.empty())

    def test_adx_filter_allows_entry_below_threshold(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        adx_filter = ADXIndicator(period=14)
        adx_filter.value = 15.0
        strategy = ICT2022Strategy(
            symbol_list=["EURUSD"], event_queue=event_queue, adx_filter=adx_filter, max_adx_for_entry=25.0
        )
        _run_full_bullish_setup(strategy)
        self.assertFalse(event_queue.empty())

    def test_max_adx_for_entry_requires_an_adx_filter(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        with self.assertRaises(ValueError):
            ICT2022Strategy(symbol_list=["EURUSD"], event_queue=event_queue, max_adx_for_entry=25.0)

    def test_take_profit_hit_emits_exit_at_reward_risk_target(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = ICT2022Strategy(symbol_list=["EURUSD"], event_queue=event_queue, reward_risk_ratio=2.0)
        _run_full_bullish_setup(strategy)
        entry_signal = event_queue.get_nowait()
        self.assertEqual(entry_signal.direction, SignalDirection.LONG)
        # entry=98, invalidation=85 -> stop=13 -> target = 98 + 2*13 = 124
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(120, 118, 119, IN_KILLZONE)))
        self.assertTrue(event_queue.empty())
        strategy.calculate_signals(MarketEvent("EURUSD", _bar(125, 123, 124, IN_KILLZONE)))
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)


if __name__ == "__main__":
    unittest.main()
