"""ICT "2022 Model" strategy: sweep -> MSS -> FVG -> time-boxed entry.

A stricter, four-stage refinement of `ict_strategy.ICTKillzoneStrategy`,
built from the same event-driven `Strategy` interface (Open/Closed: no
other engine component changes to use it). Per symbol, a setup advances
through a small state machine, reset to idle the moment the killzone ends
or any stage invalidates:

1. **Liquidity sweep** -- price wicks beyond a *fractal-confirmed* swing
   high/low and closes back inside (see `FractalSwingDetector`: a strict
   5-candle fractal, 2 bars lower/higher on each side -- not a rolling
   min/max window).
2. **Market structure shift (MSS)** -- a later candle's *close* (never a
   wick) breaks back beyond the opposing fractal swing point.
3. **Fair Value Gap (FVG)** -- once MSS is confirmed, each new 3-candle
   window is scanned for a qualifying imbalance in the setup's direction
   (`candle[0].high < candle[2].low` for a bullish FVG, mirrored for
   bearish).
4. **Time-boxed entry** -- once an FVG forms, the strategy waits for price
   to trade back into that zone before emitting a signal. If the killzone
   ends first, the setup is discarded outright: there is never an entry
   outside the session that produced it.

Note on the entry rule: a naive reading of a "2022 model" sketch might
fire the entry the instant the FVG forms. That is not what's implemented
here -- the whole point of the time-boxed cancellation rule above is that
the entry is a *resting* order at the FVG zone, filled only if price
returns to it before the killzone closes. Firing immediately on FVG
formation would make that cancellation rule meaningless.

Like `ICTKillzoneStrategy`, this remains a simplified, illustrative
implementation of a discretionary concept, not a validated edge.
"""
from __future__ import annotations

import logging
import queue
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Sequence

from .entry_filters import passes_entry_filters
from .event import MarketEvent, SignalDirection, SignalEvent
from .htf_bias import DailyBiasFilter
from .ict_strategy import DEFAULT_KILLZONES, Killzone, KillzoneFilter
from .indicators import ADXIndicator
from .strategy import Strategy
from .trade_management import TakeProfitManager

logger = logging.getLogger(__name__)


class FractalSwingDetector:
    """Strict 5-candle fractal swing detection.

    A bar is a confirmed swing high only once its high is strictly greater
    than the highs of the 2 bars immediately before *and* the 2 bars
    immediately after it (symmetric for a swing low). Confirmation
    therefore always lags the live bar by 2 bars -- there is no way to
    know a fractal is one any earlier than that.
    """

    def __init__(self) -> None:
        self._window: Deque[dict] = deque(maxlen=5)
        self.last_confirmed_swing_high: Optional[float] = None
        self.last_confirmed_swing_low: Optional[float] = None

    def update(self, bar: dict) -> None:
        self._window.append(bar)
        if len(self._window) < 5:
            return
        bars = list(self._window)
        center = bars[2]
        neighbors = bars[0:2] + bars[3:5]

        if all(center["high"] > neighbor["high"] for neighbor in neighbors):
            self.last_confirmed_swing_high = center["high"]
        if all(center["low"] < neighbor["low"] for neighbor in neighbors):
            self.last_confirmed_swing_low = center["low"]


class _SweepDirection(Enum):
    BULLISH = "BULLISH"  # sell-side liquidity swept -> bias up
    BEARISH = "BEARISH"  # buy-side liquidity swept -> bias down


class _SetupPhase(Enum):
    IDLE = "IDLE"
    SWEPT = "SWEPT"
    MSS_CONFIRMED = "MSS_CONFIRMED"
    FVG_PENDING = "FVG_PENDING"


@dataclass
class _FVGZone:
    direction: SignalDirection  # LONG (bullish FVG) or SHORT (bearish FVG)
    zone_low: float
    zone_high: float


@dataclass
class _SymbolState:
    phase: _SetupPhase = _SetupPhase.IDLE
    sweep_direction: Optional[_SweepDirection] = None
    invalidation_level: Optional[float] = None
    fvg_zone: Optional[_FVGZone] = None
    bars_in_phase: int = 0


class ICT2022Strategy(Strategy):
    """Sweep -> MSS -> FVG -> time-boxed entry, gated by killzones."""

    def __init__(
        self,
        symbol_list: List[str],
        event_queue: "queue.Queue",
        killzones: Optional[Sequence[Killzone]] = None,
        reference_timezone: Optional[str] = None,
        max_bars_awaiting_mss: int = 10,
        max_bars_awaiting_fvg: int = 5,
        pip_value: float = 0.0001,
        htf_bias_filter: Optional[DailyBiasFilter] = None,
        adx_filter: Optional[ADXIndicator] = None,
        max_adx_for_entry: Optional[float] = None,
        reward_risk_ratio: Optional[float] = None,
    ) -> None:
        if max_bars_awaiting_mss < 1:
            raise ValueError("max_bars_awaiting_mss must be at least 1")
        if max_bars_awaiting_fvg < 1:
            raise ValueError("max_bars_awaiting_fvg must be at least 1")
        if pip_value <= 0:
            raise ValueError("pip_value must be positive")
        if max_adx_for_entry is not None and adx_filter is None:
            raise ValueError("max_adx_for_entry requires an adx_filter")

        self.symbol_list = symbol_list
        self.event_queue = event_queue
        self._killzone_filter = KillzoneFilter(killzones, reference_timezone)
        # Extra defensive timeouts, on top of the mandatory killzone-end
        # cancellation: a stale sweep/MSS from early in a long killzone
        # shouldn't still be "live" hours later within the same window.
        self.max_bars_awaiting_mss = max_bars_awaiting_mss
        self.max_bars_awaiting_fvg = max_bars_awaiting_fvg
        self.pip_value = pip_value
        # Optional entry filters -- see entry_filters.passes_entry_filters
        # and trade_management.TakeProfitManager. All off by default.
        self.htf_bias_filter = htf_bias_filter
        self.adx_filter = adx_filter
        self.max_adx_for_entry = max_adx_for_entry
        self._take_profit_manager = TakeProfitManager(reward_risk_ratio) if reward_risk_ratio else None

        self._detectors: Dict[str, FractalSwingDetector] = {
            symbol: FractalSwingDetector() for symbol in symbol_list
        }
        self._recent_bars: Dict[str, Deque[dict]] = {symbol: deque(maxlen=3) for symbol in symbol_list}
        self._state: Dict[str, _SymbolState] = {symbol: _SymbolState() for symbol in symbol_list}
        self._current_position: Dict[str, SignalDirection] = {
            symbol: SignalDirection.EXIT for symbol in symbol_list
        }

    @property
    def killzones(self) -> List[Killzone]:
        return self._killzone_filter.killzones

    def _detect_sweep(self, detector: FractalSwingDetector, bar: dict) -> Optional[tuple]:
        if (
            detector.last_confirmed_swing_low is not None
            and bar["low"] < detector.last_confirmed_swing_low
            and bar["close"] > detector.last_confirmed_swing_low
        ):
            return _SweepDirection.BULLISH, bar["low"]
        if (
            detector.last_confirmed_swing_high is not None
            and bar["high"] > detector.last_confirmed_swing_high
            and bar["close"] < detector.last_confirmed_swing_high
        ):
            return _SweepDirection.BEARISH, bar["high"]
        return None

    def _detect_mss(
        self, detector: FractalSwingDetector, sweep_direction: _SweepDirection, bar: dict
    ) -> bool:
        """MSS confirmation requires the candle *body* (close) to break the
        opposing fractal level -- a wick alone is manipulation, not a
        structural shift."""
        if sweep_direction == _SweepDirection.BULLISH:
            return detector.last_confirmed_swing_high is not None and bar["close"] > detector.last_confirmed_swing_high
        return detector.last_confirmed_swing_low is not None and bar["close"] < detector.last_confirmed_swing_low

    @staticmethod
    def _detect_fvg(recent_bars: Deque[dict], sweep_direction: _SweepDirection) -> Optional[_FVGZone]:
        if len(recent_bars) < 3:
            return None
        first, _middle, third = recent_bars

        if sweep_direction == _SweepDirection.BULLISH and first["high"] < third["low"]:
            return _FVGZone(SignalDirection.LONG, zone_low=first["high"], zone_high=third["low"])
        if sweep_direction == _SweepDirection.BEARISH and first["low"] > third["high"]:
            return _FVGZone(SignalDirection.SHORT, zone_low=third["high"], zone_high=first["low"])
        return None

    @staticmethod
    def _entry_triggered(zone: _FVGZone, bar: dict) -> bool:
        if zone.direction == SignalDirection.LONG:
            return bar["low"] <= zone.zone_high
        return bar["high"] >= zone.zone_low

    def _emit_entry(self, symbol: str, zone: _FVGZone, invalidation_level: float, entry_price: float) -> None:
        if self._current_position[symbol] == zone.direction:
            return
        if not passes_entry_filters(zone.direction, self.htf_bias_filter, self.adx_filter, self.max_adx_for_entry):
            return
        if self._take_profit_manager is not None:
            self._take_profit_manager.clear(symbol)
        stop_loss_pips = abs(entry_price - invalidation_level) / self.pip_value
        self._current_position[symbol] = zone.direction
        self.event_queue.put(
            SignalEvent(
                symbol=symbol,
                direction=zone.direction,
                strength=1.0,
                strategy_id="ict_2022",
                stop_loss_pips=stop_loss_pips,
            )
        )
        if self._take_profit_manager is not None:
            self._take_profit_manager.register_entry(symbol, zone.direction, entry_price, invalidation_level)

    def _flatten_if_needed(self, symbol: str) -> None:
        if self._take_profit_manager is not None:
            self._take_profit_manager.clear(symbol)
        if self._current_position[symbol] != SignalDirection.EXIT:
            self._current_position[symbol] = SignalDirection.EXIT
            self.event_queue.put(SignalEvent(symbol=symbol, direction=SignalDirection.EXIT, strategy_id="ict_2022"))

    def calculate_signals(self, event: MarketEvent) -> None:
        symbol = event.symbol
        if symbol not in self._state:
            return

        bar = event.bar
        detector = self._detectors[symbol]
        # Swing tracking runs on every bar, in or out of a killzone: the
        # liquidity a killzone sweeps was often built up during a prior,
        # inactive session (e.g. the Asian range swept by London).
        detector.update(bar)
        self._recent_bars[symbol].append(bar)
        if self.htf_bias_filter is not None:
            self.htf_bias_filter.update(bar)
        if self.adx_filter is not None:
            self.adx_filter.update(bar)

        if self._take_profit_manager is not None and self._take_profit_manager.check_target_hit(symbol, bar):
            self._flatten_if_needed(symbol)
            return

        in_killzone = self._killzone_filter.contains(bar.get("timestamp"))
        if not in_killzone:
            if self._state[symbol].phase != _SetupPhase.IDLE:
                logger.debug("Killzone ended for %s with an unresolved setup; cancelling it.", symbol)
            self._state[symbol] = _SymbolState()  # no trade -- and no pending setup -- outside a killzone
            self._flatten_if_needed(symbol)
            return

        state = self._state[symbol]

        if state.phase == _SetupPhase.IDLE:
            sweep = self._detect_sweep(detector, bar)
            if sweep is not None:
                direction, invalidation_level = sweep
                self._state[symbol] = _SymbolState(
                    phase=_SetupPhase.SWEPT,
                    sweep_direction=direction,
                    invalidation_level=invalidation_level,
                )
                logger.debug("ICT 2022 sweep detected symbol=%s direction=%s", symbol, direction)
            return

        if state.phase == _SetupPhase.SWEPT:
            state.bars_in_phase += 1
            if self._detect_mss(detector, state.sweep_direction, bar):
                state.phase = _SetupPhase.MSS_CONFIRMED
                state.bars_in_phase = 0
                # Fall through: the impulsive candle that confirms MSS is
                # often the same candle that creates the FVG, so scan for
                # one immediately rather than waiting a full bar.
            elif state.bars_in_phase >= self.max_bars_awaiting_mss:
                self._state[symbol] = _SymbolState()
                return
            else:
                return

        if state.phase == _SetupPhase.MSS_CONFIRMED:
            state.bars_in_phase += 1
            fvg = self._detect_fvg(self._recent_bars[symbol], state.sweep_direction)
            if fvg is not None:
                state.fvg_zone = fvg
                state.phase = _SetupPhase.FVG_PENDING
                state.bars_in_phase = 0
            elif state.bars_in_phase >= self.max_bars_awaiting_fvg:
                self._state[symbol] = _SymbolState()
            return

        if state.phase == _SetupPhase.FVG_PENDING:
            if self._entry_triggered(state.fvg_zone, bar):
                self._emit_entry(symbol, state.fvg_zone, state.invalidation_level, entry_price=bar["close"])
                self._state[symbol] = _SymbolState()
            # else: keep waiting -- the killzone-end check above is what
            # eventually cancels this if price never returns to the zone.
            return
