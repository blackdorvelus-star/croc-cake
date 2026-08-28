"""Unit tests for the ICT killzone liquidity-sweep strategy."""
from __future__ import annotations

import queue
import unittest
from datetime import datetime, time as dt_time

from backtesting_engine.event import MarketEvent, SignalDirection
from backtesting_engine.htf_bias import Bias, DailyBiasFilter
from backtesting_engine.ict_strategy import ICTKillzoneStrategy, Killzone
from backtesting_engine.indicators import ADXIndicator


class KillzoneTests(unittest.TestCase):
    def test_simple_window_contains_expected_times(self) -> None:
        london = Killzone("london", dt_time(2, 0), dt_time(5, 0))
        self.assertTrue(london.contains(dt_time(3, 30)))
        self.assertFalse(london.contains(dt_time(1, 59)))
        self.assertFalse(london.contains(dt_time(5, 0)))  # end is exclusive

    def test_window_wrapping_past_midnight(self) -> None:
        asian = Killzone("asian_wrap", dt_time(23, 0), dt_time(2, 0))
        self.assertTrue(asian.contains(dt_time(23, 30)))
        self.assertTrue(asian.contains(dt_time(1, 0)))
        self.assertFalse(asian.contains(dt_time(12, 0)))


def _bar(close: float, high: float, low: float, ts: datetime, volume: float = 10_000.0) -> dict:
    return {"open": close, "high": high, "low": low, "close": close, "volume": volume, "timestamp": ts}


class ICTKillzoneStrategyTests(unittest.TestCase):
    IN_KILLZONE = datetime(2024, 1, 1, 8, 0)  # inside the default new_york_am window
    OUTSIDE_KILLZONE = datetime(2024, 1, 1, 14, 0)  # outside every default window

    def _make_strategy(self, swing_lookback: int = 3, mss_confirmation_bars: int = 3) -> tuple:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"],
            event_queue=event_queue,
            swing_lookback=swing_lookback,
            mss_confirmation_bars=mss_confirmation_bars,
        )
        return strategy, event_queue

    def test_no_signal_outside_a_killzone_even_with_a_sweep(self) -> None:
        strategy, event_queue = self._make_strategy()
        symbol = "AAPL"

        # Build up a flat range, all outside any killzone.
        for price in (100.0, 100.5, 100.2):
            strategy.calculate_signals(
                MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.OUTSIDE_KILLZONE))
            )

        # Sweep the range low, then confirm structure -- still outside a killzone.
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.3, 100.4, 99.8, self.OUTSIDE_KILLZONE)))
        for _ in range(3):
            strategy.calculate_signals(MarketEvent(symbol, _bar(100.9, 101.0, 100.3, self.OUTSIDE_KILLZONE)))

        self.assertTrue(event_queue.empty())

    def test_liquidity_sweep_and_mss_confirmation_emits_long_signal(self) -> None:
        strategy, event_queue = self._make_strategy(swing_lookback=3, mss_confirmation_bars=3)
        symbol = "AAPL"

        # Establish a swing range (high=100.5, low=99.9) inside the killzone.
        for price in (100.0, 100.5, 99.9):
            strategy.calculate_signals(MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.IN_KILLZONE)))

        # Sweep below the swing low (99.9) but close back inside the range.
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.1, 99.7, self.IN_KILLZONE)))
        self.assertTrue(event_queue.empty())  # sweep alone is not enough yet

        # Confirm the market structure shift by closing back above the swing high (100.5).
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.65, 100.7, 100.4, self.IN_KILLZONE)))

        self.assertFalse(event_queue.empty())
        signal = event_queue.get_nowait()
        self.assertEqual(signal.direction, SignalDirection.LONG)
        # stop_loss_pips = |entry - invalidation_level(99.7)| / pip_value(0.0001)
        self.assertAlmostEqual(signal.stop_loss_pips, abs(100.65 - 99.7) / 0.0001)

    def test_setup_invalidated_if_sweep_extreme_is_retaken(self) -> None:
        strategy, event_queue = self._make_strategy(swing_lookback=3, mss_confirmation_bars=5)
        symbol = "AAPL"

        for price in (100.0, 100.5, 99.9):
            strategy.calculate_signals(MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.IN_KILLZONE)))

        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.1, 99.7, self.IN_KILLZONE)))  # sweep
        # Price closes back below the sweep low: setup invalidated.
        strategy.calculate_signals(MarketEvent(symbol, _bar(99.5, 99.6, 99.4, self.IN_KILLZONE)))
        # Even a later close above the old swing high must not fire a stale signal.
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.65, 100.7, 100.4, self.IN_KILLZONE)))

        self.assertTrue(event_queue.empty())

    def test_setup_expires_after_confirmation_window(self) -> None:
        strategy, event_queue = self._make_strategy(swing_lookback=3, mss_confirmation_bars=2)
        symbol = "AAPL"

        for price in (100.0, 100.5, 99.9):
            strategy.calculate_signals(MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.IN_KILLZONE)))

        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.1, 99.7, self.IN_KILLZONE)))  # sweep
        # Two bars that neither confirm nor invalidate -> setup expires.
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.05, 99.95, self.IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.05, 99.95, self.IN_KILLZONE)))
        # A later break of the old structure level must not fire (setup already expired).
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.65, 100.7, 100.4, self.IN_KILLZONE)))

        self.assertTrue(event_queue.empty())

    def test_open_position_is_flattened_once_killzone_ends(self) -> None:
        strategy, event_queue = self._make_strategy(swing_lookback=3, mss_confirmation_bars=3)
        symbol = "AAPL"

        for price in (100.0, 100.5, 99.9):
            strategy.calculate_signals(MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.1, 99.7, self.IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.65, 100.7, 100.4, self.IN_KILLZONE)))
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.LONG)

        strategy.calculate_signals(MarketEvent(symbol, _bar(100.6, 100.7, 100.5, self.OUTSIDE_KILLZONE)))
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)


class ICTKillzoneStrategyFilterTests(unittest.TestCase):
    """Tests for the optional htf_bias_filter / adx_filter / reward_risk_ratio
    entry filters -- all off by default, so these construct strategies with
    them explicitly configured."""

    IN_KILLZONE = ICTKillzoneStrategyTests.IN_KILLZONE

    def _run_bullish_sweep_and_mss(self, strategy, symbol: str = "AAPL") -> "queue.Queue":
        for price in (100.0, 100.5, 99.9):
            strategy.calculate_signals(MarketEvent(symbol, _bar(price, price + 0.1, price - 0.1, self.IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.0, 100.1, 99.7, self.IN_KILLZONE)))
        strategy.calculate_signals(MarketEvent(symbol, _bar(100.65, 100.7, 100.4, self.IN_KILLZONE)))

    def test_htf_bias_filter_blocks_a_setup_against_the_trend(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        bias_filter = DailyBiasFilter(ema_period=5)
        bias_filter.bias = Bias.BEARISH  # opposes the bullish sweep below
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            htf_bias_filter=bias_filter,
        )
        self._run_bullish_sweep_and_mss(strategy)
        self.assertTrue(event_queue.empty())

    def test_htf_bias_filter_allows_a_setup_with_the_trend(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        bias_filter = DailyBiasFilter(ema_period=5)
        bias_filter.bias = Bias.BULLISH  # agrees with the bullish sweep below
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            htf_bias_filter=bias_filter,
        )
        self._run_bullish_sweep_and_mss(strategy)
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.LONG)

    def test_no_bias_yet_blocks_entry_fail_closed(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        bias_filter = DailyBiasFilter(ema_period=5)  # .bias stays None: never warmed up
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            htf_bias_filter=bias_filter,
        )
        self._run_bullish_sweep_and_mss(strategy)
        self.assertTrue(event_queue.empty())

    def test_adx_filter_blocks_entry_above_threshold(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        adx_filter = ADXIndicator(period=14)
        adx_filter.value = 40.0  # strongly trending; above the threshold below
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            adx_filter=adx_filter, max_adx_for_entry=25.0,
        )
        self._run_bullish_sweep_and_mss(strategy)
        self.assertTrue(event_queue.empty())

    def test_adx_filter_allows_entry_below_threshold(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        adx_filter = ADXIndicator(period=14)
        adx_filter.value = 15.0  # ranging; below the threshold below
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            adx_filter=adx_filter, max_adx_for_entry=25.0,
        )
        self._run_bullish_sweep_and_mss(strategy)
        self.assertFalse(event_queue.empty())

    def test_max_adx_for_entry_requires_an_adx_filter(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        with self.assertRaises(ValueError):
            ICTKillzoneStrategy(symbol_list=["AAPL"], event_queue=event_queue, max_adx_for_entry=25.0)

    def test_take_profit_hit_emits_exit_at_reward_risk_target(self) -> None:
        event_queue: "queue.Queue" = queue.Queue()
        strategy = ICTKillzoneStrategy(
            symbol_list=["AAPL"], event_queue=event_queue, swing_lookback=3, mss_confirmation_bars=3,
            reward_risk_ratio=2.0,
        )
        self._run_bullish_sweep_and_mss(strategy)
        entry_signal = event_queue.get_nowait()
        self.assertEqual(entry_signal.direction, SignalDirection.LONG)
        # entry=100.65, invalidation=99.7 -> stop=0.95 -> target = 100.65 + 2*0.95 = 102.55
        strategy.calculate_signals(MarketEvent("AAPL", _bar(101.0, 102.0, 100.9, self.IN_KILLZONE)))
        self.assertTrue(event_queue.empty())  # short of target
        strategy.calculate_signals(MarketEvent("AAPL", _bar(102.6, 102.7, 102.0, self.IN_KILLZONE)))
        self.assertFalse(event_queue.empty())
        self.assertEqual(event_queue.get_nowait().direction, SignalDirection.EXIT)


if __name__ == "__main__":
    unittest.main()
