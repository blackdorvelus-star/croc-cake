"""Take-profit management at a fixed reward:risk (R) multiple.

Every ICT strategy in this package already knows a trade's invalidation
level (the sweep extreme) the moment it enters -- that distance is already
used as the stop for position sizing (`stop_loss_pips`). This module adds
the other half: an explicit profit target at `reward_risk_ratio` times
that same distance, so a trade can win on a target hit instead of only
ever exiting via invalidation or killzone end.

Deliberately a plain add-on, not a strategy itself: it tracks one pending
target per symbol and reports whether a bar has reached it. The owning
strategy decides what to do with that (typically: emit an EXIT signal and
clear the target).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .event import SignalDirection


@dataclass
class _OpenTarget:
    direction: SignalDirection
    target_price: float


class TakeProfitManager:
    """Tracks a take-profit target per symbol at a fixed R multiple."""

    def __init__(self, reward_risk_ratio: float = 2.0) -> None:
        if reward_risk_ratio <= 0:
            raise ValueError("reward_risk_ratio must be positive")
        self.reward_risk_ratio = reward_risk_ratio
        self._targets: Dict[str, _OpenTarget] = {}

    def register_entry(
        self, symbol: str, direction: SignalDirection, entry_price: float, invalidation_level: float
    ) -> None:
        stop_distance = abs(entry_price - invalidation_level)
        sign = 1 if direction == SignalDirection.LONG else -1
        target_price = entry_price + sign * self.reward_risk_ratio * stop_distance
        self._targets[symbol] = _OpenTarget(direction=direction, target_price=target_price)

    def clear(self, symbol: str) -> None:
        self._targets.pop(symbol, None)

    def target_price(self, symbol: str) -> Optional[float]:
        target = self._targets.get(symbol)
        return target.target_price if target is not None else None

    def check_target_hit(self, symbol: str, bar: dict) -> bool:
        target = self._targets.get(symbol)
        if target is None:
            return False
        if target.direction == SignalDirection.LONG:
            return bar["high"] >= target.target_price
        return bar["low"] <= target.target_price
