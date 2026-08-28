"""Technical indicators, computed incrementally one bar at a time.

Kept separate from the strategies that use them (Single Responsibility):
these classes know nothing about ICT concepts, killzones, sweeps, or
trading decisions -- they only turn a stream of bars into a number.
"""
from __future__ import annotations

from typing import List, Optional


class ADXIndicator:
    """Wilder's Average Directional Index (ADX), computed incrementally.

    Intended use in this codebase: gate a mean-reversion-style entry (a
    liquidity sweep expecting a reversal) to ADX below a threshold. A low
    reading indicates a ranging market, where reversals off a sweep are
    more plausible than during an already-established trend (where a
    "sweep" is more likely a continuation than a reversal).

    `value` is None until the indicator has warmed up (roughly
    2 * period bars of history).
    """

    def __init__(self, period: int = 14) -> None:
        if period < 2:
            raise ValueError("period must be at least 2")
        self.period = period

        self._prev_high: Optional[float] = None
        self._prev_low: Optional[float] = None
        self._prev_close: Optional[float] = None

        self._tr_values: List[float] = []
        self._plus_dm_values: List[float] = []
        self._minus_dm_values: List[float] = []
        self._smoothed_tr: Optional[float] = None
        self._smoothed_plus_dm: Optional[float] = None
        self._smoothed_minus_dm: Optional[float] = None

        self._dx_values: List[float] = []
        self.value: Optional[float] = None

    def update(self, bar: dict) -> None:
        high, low, close = bar["high"], bar["low"], bar["close"]

        if self._prev_high is None:
            self._prev_high, self._prev_low, self._prev_close = high, low, close
            return

        up_move = high - self._prev_high
        down_move = self._prev_low - low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        true_range = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))

        self._prev_high, self._prev_low, self._prev_close = high, low, close

        if self._smoothed_tr is None:
            self._tr_values.append(true_range)
            self._plus_dm_values.append(plus_dm)
            self._minus_dm_values.append(minus_dm)
            if len(self._tr_values) < self.period:
                return
            self._smoothed_tr = sum(self._tr_values)
            self._smoothed_plus_dm = sum(self._plus_dm_values)
            self._smoothed_minus_dm = sum(self._minus_dm_values)
        else:
            self._smoothed_tr += true_range - self._smoothed_tr / self.period
            self._smoothed_plus_dm += plus_dm - self._smoothed_plus_dm / self.period
            self._smoothed_minus_dm += minus_dm - self._smoothed_minus_dm / self.period

        if self._smoothed_tr == 0:
            return  # degenerate flat market this bar; skip its DX contribution

        plus_di = 100.0 * self._smoothed_plus_dm / self._smoothed_tr
        minus_di = 100.0 * self._smoothed_minus_dm / self._smoothed_tr
        di_sum = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0.0

        if self.value is None:
            self._dx_values.append(dx)
            if len(self._dx_values) < self.period:
                return
            self.value = sum(self._dx_values) / self.period
        else:
            self.value = (self.value * (self.period - 1) + dx) / self.period
