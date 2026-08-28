"""ICT "Killzone" liquidity-sweep strategy.

Implements a simplified version of the Inner Circle Trader (ICT) killzone
methodology, as a drop-in `Strategy` for the event-driven engine
(Open/Closed: nothing else in the engine needs to change to use it):

1. Trading is only considered during configured killzone time windows
   (Asian, London, New York AM, London Close by default) -- outside those
   windows the strategy stays flat and ignores new setups.
2. Within a killzone, the strategy watches for a *liquidity sweep*: price
   wicks beyond a recent swing high/low (where resting stop orders are
   assumed to cluster) and then closes back inside the prior range -- the
   classic ICT "stop hunt" / turtle-soup pattern.
3. A sweep only becomes a trade once a *market structure shift* (MSS)
   confirms it: price must close back beyond the opposing swing extreme
   within `mss_confirmation_bars` bars, or the setup is invalidated.
4. An open position is flattened if price re-takes the sweep extreme (the
   setup's invalidation level) or once the killzone window ends -- ICT
   practice favors managing trades within the session that produced them
   rather than holding through dead liquidity hours.

This is a simplified, illustrative implementation of a well-known
discretionary concept, not a validated trading strategy. Swing detection
uses a fixed lookback window rather than true fractal/pivot confirmation,
and "smart money" intent behind a wick is inherently an interpretation.
Treat this as a solid, testable starting point to refine, not a proven edge.
"""
from __future__ import annotations

import logging
import queue
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from .event import MarketEvent, SignalDirection, SignalEvent
from .strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Killzone:
    """A named intraday time window, expressed in a reference timezone.

    `contains` handles windows that cross midnight (e.g. an Asian session
    window running from 20:00 to 02:00).
    """

    name: str
    start: dt_time
    end: dt_time

    def contains(self, moment: dt_time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


DEFAULT_KILLZONES: List[Killzone] = [
    Killzone("asian", dt_time(20, 0), dt_time(0, 0)),
    Killzone("london", dt_time(2, 0), dt_time(5, 0)),
    Killzone("new_york_am", dt_time(7, 0), dt_time(10, 0)),
    Killzone("london_close", dt_time(10, 0), dt_time(12, 0)),
]
"""Commonly cited ICT killzones, expressed in New York (ET) local time."""


class SweepDirection(Enum):
    BULLISH = "BULLISH"  # sell-side liquidity (a swing low) was swept -> bias up
    BEARISH = "BEARISH"  # buy-side liquidity (a swing high) was swept -> bias down


@dataclass
class _PendingSetup:
    direction: SweepDirection
    invalidation_level: float  # the sweep extreme itself; retaking it kills the setup
    structure_level: float  # opposing swing extreme that must break to confirm the MSS
    bars_remaining: int


class ICTKillzoneStrategy(Strategy):
    """Liquidity-sweep + market-structure-shift strategy, gated by killzones."""

    def __init__(
        self,
        symbol_list: List[str],
        event_queue: "queue.Queue",
        killzones: Optional[Sequence[Killzone]] = None,
        swing_lookback: int = 10,
        mss_confirmation_bars: int = 5,
        reference_timezone: Optional[str] = None,
    ) -> None:
        if swing_lookback < 2:
            raise ValueError("swing_lookback must be at least 2")
        if mss_confirmation_bars < 1:
            raise ValueError("mss_confirmation_bars must be at least 1")

        self.symbol_list = symbol_list
        self.event_queue = event_queue
        self.killzones = list(killzones) if killzones else list(DEFAULT_KILLZONES)
        self.swing_lookback = swing_lookback
        self.mss_confirmation_bars = mss_confirmation_bars
        self.reference_timezone = reference_timezone

        self._history: Dict[str, Deque[dict]] = {
            symbol: deque(maxlen=swing_lookback + 1) for symbol in symbol_list
        }
        self._pending_setup: Dict[str, Optional[_PendingSetup]] = {symbol: None for symbol in symbol_list}
        self._current_position: Dict[str, SignalDirection] = {
            symbol: SignalDirection.EXIT for symbol in symbol_list
        }

    def _time_of(self, bar_timestamp: object) -> Optional[dt_time]:
        """Best-effort extraction of a time-of-day from whatever the
        DataHandler put in `bar['timestamp']`. Returns None for anything
        that isn't a recognizable datetime, in which case killzone
        filtering fails open (see `_in_killzone`)."""
        if isinstance(bar_timestamp, datetime):
            moment = bar_timestamp
            if moment.tzinfo is not None and self.reference_timezone:
                from zoneinfo import ZoneInfo

                moment = moment.astimezone(ZoneInfo(self.reference_timezone))
            return moment.time()
        if hasattr(bar_timestamp, "to_pydatetime"):  # pandas.Timestamp
            return self._time_of(bar_timestamp.to_pydatetime())
        return None

    def _in_killzone(self, bar_timestamp: object) -> bool:
        moment = self._time_of(bar_timestamp)
        if moment is None:
            logger.warning("Bar has no usable timestamp; killzone filter disabled for this bar.")
            return True
        return any(killzone.contains(moment) for killzone in self.killzones)

    def _swing_extremes(self, symbol: str) -> Optional[Tuple[float, float]]:
        history = list(self._history[symbol])[:-1]  # exclude the current, still-forming bar
        if len(history) < self.swing_lookback:
            return None
        swing_high = max(bar["high"] for bar in history)
        swing_low = min(bar["low"] for bar in history)
        return swing_high, swing_low

    def _detect_sweep(self, symbol: str, bar: dict) -> Optional[_PendingSetup]:
        extremes = self._swing_extremes(symbol)
        if extremes is None:
            return None
        swing_high, swing_low = extremes

        if bar["low"] < swing_low and bar["close"] > swing_low:
            return _PendingSetup(
                direction=SweepDirection.BULLISH,
                invalidation_level=bar["low"],
                structure_level=swing_high,
                bars_remaining=self.mss_confirmation_bars,
            )
        if bar["high"] > swing_high and bar["close"] < swing_high:
            return _PendingSetup(
                direction=SweepDirection.BEARISH,
                invalidation_level=bar["high"],
                structure_level=swing_low,
                bars_remaining=self.mss_confirmation_bars,
            )
        return None

    def _emit(self, symbol: str, direction: SignalDirection) -> None:
        if self._current_position[symbol] == direction:
            return
        self._current_position[symbol] = direction
        self.event_queue.put(
            SignalEvent(symbol=symbol, direction=direction, strength=1.0, strategy_id="ict_killzone")
        )

    def calculate_signals(self, event: MarketEvent) -> None:
        symbol = event.symbol
        if symbol not in self._history:
            return

        bar = event.bar
        self._history[symbol].append(bar)
        in_killzone = self._in_killzone(bar.get("timestamp"))
        pending = self._pending_setup[symbol]

        if pending is not None:
            invalidated = (
                pending.direction == SweepDirection.BULLISH and bar["close"] < pending.invalidation_level
            ) or (pending.direction == SweepDirection.BEARISH and bar["close"] > pending.invalidation_level)

            if invalidated:
                self._pending_setup[symbol] = None
            else:
                confirmed = (
                    pending.direction == SweepDirection.BULLISH and bar["close"] > pending.structure_level
                ) or (pending.direction == SweepDirection.BEARISH and bar["close"] < pending.structure_level)

                if confirmed:
                    self._pending_setup[symbol] = None
                    if in_killzone:
                        direction = (
                            SignalDirection.LONG
                            if pending.direction == SweepDirection.BULLISH
                            else SignalDirection.SHORT
                        )
                        self._emit(symbol, direction)
                    return

                pending.bars_remaining -= 1
                if pending.bars_remaining <= 0:
                    self._pending_setup[symbol] = None  # setup expired without confirmation

        if not in_killzone:
            self._emit(symbol, SignalDirection.EXIT)
            return

        if self._pending_setup[symbol] is None:
            new_setup = self._detect_sweep(symbol, bar)
            if new_setup is not None:
                self._pending_setup[symbol] = new_setup
                logger.debug("ICT liquidity sweep detected symbol=%s direction=%s", symbol, new_setup.direction)
