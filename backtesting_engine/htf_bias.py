"""Higher-timeframe directional bias filter.

Aggregates the same H1 bar stream a strategy already sees into daily bars
internally -- no separate data feed needed. The bias used during any bar
is always derived strictly from days that have already closed, never from
the still-forming current day, so there is no lookahead: today's H1 bars
only ever see yesterday's (or earlier's) completed daily close vs. its
EMA.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Bias(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class DailyBiasFilter:
    """Bullish when the last *completed* daily close is above an EMA of
    completed daily closes, bearish when below. `bias` is None until the
    EMA has produced its first value (after the first completed day)."""

    def __init__(self, ema_period: int = 50) -> None:
        if ema_period < 2:
            raise ValueError("ema_period must be at least 2")
        self.ema_period = ema_period
        self._alpha = 2.0 / (ema_period + 1)
        self._ema: Optional[float] = None
        self._current_day = None
        self._current_day_close: Optional[float] = None
        self.bias: Optional[Bias] = None

    def update(self, bar: dict) -> None:
        timestamp = bar.get("timestamp")
        to_date = getattr(timestamp, "date", None)
        if to_date is None:
            return  # no usable date info on this bar; bias stays whatever it last was
        day = to_date()

        if self._current_day is None:
            self._current_day = day
        elif day != self._current_day:
            self._finalize_day(self._current_day_close)
            self._current_day = day

        self._current_day_close = bar["close"]

    def _finalize_day(self, close: Optional[float]) -> None:
        if close is None:
            return
        self._ema = close if self._ema is None else self._alpha * close + (1 - self._alpha) * self._ema
        self.bias = Bias.BULLISH if close > self._ema else Bias.BEARISH
