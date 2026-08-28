"""Donchian channel breakout trend-following strategy (Turtle-style).

Implements the core mechanic of the Turtle Traders' system (Richard
Dennis, 1980s) -- still the conceptual basis of most CTA/managed-futures
trend-following funds today:

1. **Entry**: go long when price breaks above the highest high of the
   last `entry_lookback` bars, short when it breaks below the lowest low
   -- a pure momentum/continuation signal, the opposite mechanism from
   the ICT strategies' reversal-off-a-sweep logic in this package.
2. **Initial stop**: `atr_stop_multiple * ATR` away from the entry price
   (the Turtles' "2N stop"), sized via ATR rather than a fixed pip
   distance so it scales with how much the instrument is actually moving.
   This becomes `stop_loss_pips` on the emitted signal, so it plugs into
   `ForexPositionSizer` exactly like the ICT strategies do.
3. **Exit**: whichever comes first -- the initial stop being hit, or price
   closing back through the (shorter, `exit_lookback`) exit channel. There
   is deliberately no profit target: trend-following's edge depends on
   letting winners run and cutting losers at a fixed, known risk.

Unlike the ICT strategies, there is no killzone gating and no session
concept at all -- trend-following has no reason to be time-of-day limited,
and the entry/exit rules are the same at every hour.

This is a simplified, single-pair implementation of a well-documented,
decades-old, widely used systematic approach (see README.md for the
academic and industry evidence) -- not a guarantee that it is profitable
on this data at these parameters.
"""
from __future__ import annotations

import queue
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from .event import MarketEvent, SignalDirection, SignalEvent
from .indicators import ATRIndicator
from .strategy import Strategy


@dataclass
class _OpenPosition:
    direction: SignalDirection
    initial_stop: float


class DonchianTrendStrategy(Strategy):
    """Donchian breakout entry, ATR-sized stop, exit-channel or stop exit."""

    def __init__(
        self,
        symbol_list: List[str],
        event_queue: "queue.Queue",
        entry_lookback: int = 20,
        exit_lookback: int = 10,
        atr_period: int = 20,
        atr_stop_multiple: float = 2.0,
        pip_value: float = 0.0001,
    ) -> None:
        if entry_lookback < 2:
            raise ValueError("entry_lookback must be at least 2")
        if exit_lookback < 2:
            raise ValueError("exit_lookback must be at least 2")
        if exit_lookback >= entry_lookback:
            raise ValueError("exit_lookback must be shorter than entry_lookback (a tighter exit channel)")
        if atr_stop_multiple <= 0:
            raise ValueError("atr_stop_multiple must be positive")
        if pip_value <= 0:
            raise ValueError("pip_value must be positive")

        self.symbol_list = symbol_list
        self.event_queue = event_queue
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback
        self.atr_stop_multiple = atr_stop_multiple
        self.pip_value = pip_value

        self._history: Dict[str, Deque[dict]] = {
            symbol: deque(maxlen=entry_lookback + 1) for symbol in symbol_list
        }
        self._atr: Dict[str, ATRIndicator] = {symbol: ATRIndicator(period=atr_period) for symbol in symbol_list}
        self._current_position: Dict[str, SignalDirection] = {
            symbol: SignalDirection.EXIT for symbol in symbol_list
        }
        self._open_position: Dict[str, Optional[_OpenPosition]] = {symbol: None for symbol in symbol_list}

    def _channel(self, symbol: str, lookback: int) -> Optional[Tuple[float, float]]:
        """(highest high, lowest low) over the last `lookback` *completed*
        bars, excluding the current, still-forming one -- no lookahead."""
        history = list(self._history[symbol])[:-1]
        if len(history) < lookback:
            return None
        window = history[-lookback:]
        return max(bar["high"] for bar in window), min(bar["low"] for bar in window)

    def _emit(self, symbol: str, direction: SignalDirection, stop_loss_pips: Optional[float] = None) -> bool:
        if self._current_position[symbol] == direction:
            return False
        self._current_position[symbol] = direction
        self.event_queue.put(
            SignalEvent(
                symbol=symbol,
                direction=direction,
                strength=1.0,
                strategy_id="donchian_trend",
                stop_loss_pips=stop_loss_pips,
            )
        )
        return True

    def calculate_signals(self, event: MarketEvent) -> None:
        symbol = event.symbol
        if symbol not in self._history:
            return

        bar = event.bar
        self._history[symbol].append(bar)
        self._atr[symbol].update(bar)

        open_position = self._open_position[symbol]
        if open_position is not None:
            stop_hit = (
                open_position.direction == SignalDirection.LONG and bar["low"] <= open_position.initial_stop
            ) or (open_position.direction == SignalDirection.SHORT and bar["high"] >= open_position.initial_stop)

            exit_breakout = False
            exit_channel = self._channel(symbol, self.exit_lookback)
            if exit_channel is not None:
                exit_high, exit_low = exit_channel
                if open_position.direction == SignalDirection.LONG and bar["close"] < exit_low:
                    exit_breakout = True
                elif open_position.direction == SignalDirection.SHORT and bar["close"] > exit_high:
                    exit_breakout = True

            if stop_hit or exit_breakout:
                self._open_position[symbol] = None
                self._emit(symbol, SignalDirection.EXIT)
                return  # flat now; look for a fresh entry starting next bar

        entry_channel = self._channel(symbol, self.entry_lookback)
        atr_value = self._atr[symbol].value
        if entry_channel is None or atr_value is None:
            return  # not enough history / ATR not warmed up yet

        entry_high, entry_low = entry_channel

        if self._current_position[symbol] != SignalDirection.LONG and bar["high"] > entry_high:
            entry_price = bar["close"]
            initial_stop = entry_price - self.atr_stop_multiple * atr_value
            stop_loss_pips = abs(entry_price - initial_stop) / self.pip_value
            if self._emit(symbol, SignalDirection.LONG, stop_loss_pips=stop_loss_pips):
                self._open_position[symbol] = _OpenPosition(direction=SignalDirection.LONG, initial_stop=initial_stop)
        elif self._current_position[symbol] != SignalDirection.SHORT and bar["low"] < entry_low:
            entry_price = bar["close"]
            initial_stop = entry_price + self.atr_stop_multiple * atr_value
            stop_loss_pips = abs(initial_stop - entry_price) / self.pip_value
            if self._emit(symbol, SignalDirection.SHORT, stop_loss_pips=stop_loss_pips):
                self._open_position[symbol] = _OpenPosition(direction=SignalDirection.SHORT, initial_stop=initial_stop)
