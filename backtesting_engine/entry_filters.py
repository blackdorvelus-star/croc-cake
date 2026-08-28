"""Shared optional entry-filter logic for ICT-style strategies.

Extracted so `ICTKillzoneStrategy` and `ICT2022Strategy` apply the exact
same higher-timeframe-bias / ADX-regime gating rather than two copies that
could quietly drift apart. Both filters fail closed: an entry is blocked
if the relevant filter hasn't warmed up yet, never allowed through by
default (both filters are off unless explicitly configured).
"""
from __future__ import annotations

from typing import Optional

from .event import SignalDirection
from .htf_bias import Bias, DailyBiasFilter
from .indicators import ADXIndicator


def passes_entry_filters(
    direction: SignalDirection,
    htf_bias_filter: Optional[DailyBiasFilter],
    adx_filter: Optional[ADXIndicator],
    max_adx_for_entry: Optional[float],
) -> bool:
    if htf_bias_filter is not None:
        if htf_bias_filter.bias is None:
            return False
        required = Bias.BULLISH if direction == SignalDirection.LONG else Bias.BEARISH
        if htf_bias_filter.bias != required:
            return False
    if max_adx_for_entry is not None:
        if adx_filter.value is None or adx_filter.value > max_adx_for_entry:
            return False
    return True
