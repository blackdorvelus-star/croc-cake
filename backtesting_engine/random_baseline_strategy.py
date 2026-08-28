"""Random-entry baseline strategy, used to test whether an ICT strategy's
entry timing is actually distinguishable from chance.

Gated by the same killzone windows and using the same fixed stop distance
(so position sizing via a shared PositionSizer produces comparable risk
per trade), this strategy replaces the sweep -> MSS -> (FVG) entry logic
with a coin flip. Running it many times with different seeds and comparing
the distribution of outcomes to a real strategy's single result is a
lightweight Monte Carlo permutation test: if the real strategy's
performance sits comfortably inside the random distribution, its "edge" is
not distinguishable from noise on the data at hand.
"""
from __future__ import annotations

import queue
import random
from typing import List, Optional, Sequence

from .event import MarketEvent, SignalDirection, SignalEvent
from .ict_strategy import DEFAULT_KILLZONES, Killzone, KillzoneFilter
from .strategy import Strategy


class RandomKillzoneEntryStrategy(Strategy):
    """Enters long or short at random (coin flip) while inside a killzone
    and flat, with a fixed stop distance; flattens once the killzone ends,
    exactly like `ICTKillzoneStrategy` -- the only difference is *when* to
    enter is decided by chance instead of a sweep/MSS/FVG signal.
    """

    def __init__(
        self,
        symbol_list: List[str],
        event_queue: "queue.Queue",
        killzones: Optional[Sequence[Killzone]] = None,
        reference_timezone: Optional[str] = None,
        entry_probability_per_bar: float = 0.01,
        stop_loss_pips: float = 20.0,
        random_seed: Optional[int] = None,
    ) -> None:
        if not (0.0 < entry_probability_per_bar <= 1.0):
            raise ValueError("entry_probability_per_bar must be within (0, 1]")
        if stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be positive")

        self.symbol_list = symbol_list
        self.event_queue = event_queue
        self._killzone_filter = KillzoneFilter(killzones or DEFAULT_KILLZONES, reference_timezone)
        self.entry_probability_per_bar = entry_probability_per_bar
        self.stop_loss_pips = stop_loss_pips
        self._rng = random.Random(random_seed)

        self._current_position = {symbol: SignalDirection.EXIT for symbol in symbol_list}

    def calculate_signals(self, event: MarketEvent) -> None:
        symbol = event.symbol
        if symbol not in self._current_position:
            return

        in_killzone = self._killzone_filter.contains(event.bar.get("timestamp"))

        if not in_killzone:
            if self._current_position[symbol] != SignalDirection.EXIT:
                self._current_position[symbol] = SignalDirection.EXIT
                self.event_queue.put(
                    SignalEvent(symbol=symbol, direction=SignalDirection.EXIT, strategy_id="random_baseline")
                )
            return

        if self._current_position[symbol] != SignalDirection.EXIT:
            return  # already in a (random) trade; wait for killzone end to close it

        if self._rng.random() < self.entry_probability_per_bar:
            direction = self._rng.choice([SignalDirection.LONG, SignalDirection.SHORT])
            self._current_position[symbol] = direction
            self.event_queue.put(
                SignalEvent(
                    symbol=symbol,
                    direction=direction,
                    strategy_id="random_baseline",
                    stop_loss_pips=self.stop_loss_pips,
                )
            )
