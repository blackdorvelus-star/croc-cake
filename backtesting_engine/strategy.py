"""Strategy layer: turns MarketEvents into SignalEvents.

Strategy is the only component allowed to look at price history and decide
directional bias. It must never touch position sizing (Portfolio's job),
risk limits (RiskManager's job) or execution mechanics (ExecutionHandler's
job) -- Single Responsibility Principle.
"""
from __future__ import annotations

import logging
import queue
from collections import deque
from typing import Deque, Dict, List, Optional

from .event import MarketEvent, SignalDirection, SignalEvent
from .ml_model import DummyXGBoostSignalModel

logger = logging.getLogger(__name__)


class Strategy:
    """Abstract strategy interface (Dependency Inversion / Open-Closed).

    Not declared with `abc.ABC` on purpose: strategies are meant to be
    lightweight, composable objects and subclasses only need to implement
    `calculate_signals`.
    """

    def calculate_signals(self, event: MarketEvent) -> None:
        raise NotImplementedError


class MLMomentumStrategy(Strategy):
    """Example ML-driven strategy backed by a (dummy) XGBoost classifier.

    For every incoming MarketEvent, rolling OHLCV history is updated. Once a
    symbol has accumulated enough history, engineered features are built and
    passed to the ML model. Inference runs *asynchronously* relative to bar
    arrival: it is only invoked every `inference_every_n_bars` bars per
    symbol, mirroring a common production pattern where inference is
    comparatively expensive and does not need to run on every tick/bar.
    """

    def __init__(
        self,
        symbol_list: List[str],
        event_queue: "queue.Queue",
        lookback: int = 20,
        inference_every_n_bars: int = 5,
        long_threshold: float = 0.60,
        short_threshold: float = 0.40,
        model: Optional[DummyXGBoostSignalModel] = None,
    ) -> None:
        if lookback < 2:
            raise ValueError("lookback must be at least 2 to compute returns")
        if not (0.0 <= short_threshold < long_threshold <= 1.0):
            raise ValueError("expected 0 <= short_threshold < long_threshold <= 1")

        self.symbol_list = symbol_list
        self.event_queue = event_queue
        self.lookback = lookback
        self.inference_every_n_bars = inference_every_n_bars
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.model = model or DummyXGBoostSignalModel()

        self._history: Dict[str, Deque[dict]] = {symbol: deque(maxlen=lookback) for symbol in symbol_list}
        self._bars_seen: Dict[str, int] = {symbol: 0 for symbol in symbol_list}
        self._current_position: Dict[str, SignalDirection] = {
            symbol: SignalDirection.EXIT for symbol in symbol_list
        }

    def _build_features(self, symbol: str) -> List[float]:
        closes = [bar["close"] for bar in self._history[symbol]]
        momentum = (closes[-1] / closes[0]) - 1.0

        gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        rsi = avg_gain / (avg_gain + avg_loss) if (avg_gain + avg_loss) > 0 else 0.5

        returns = [(closes[i] / closes[i - 1]) - 1.0 for i in range(1, len(closes))]
        mean_return = sum(returns) / len(returns) if returns else 0.0
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns) if returns else 0.0
        volatility = variance ** 0.5

        return [momentum, rsi, volatility]

    def calculate_signals(self, event: MarketEvent) -> None:
        symbol = event.symbol
        if symbol not in self._history:
            return

        self._history[symbol].append(event.bar)
        self._bars_seen[symbol] += 1

        if len(self._history[symbol]) < self.lookback:
            return  # not enough history yet to build reliable features

        if self._bars_seen[symbol] % self.inference_every_n_bars != 0:
            return  # asynchronous inference cadence: skip most bars

        features = self._build_features(symbol)
        p_up = self.model.predict_up_probability(features)
        logger.debug("ML inference symbol=%s p_up=%.4f features=%s", symbol, p_up, features)

        current_position = self._current_position[symbol]
        new_direction: Optional[SignalDirection] = None

        if p_up >= self.long_threshold and current_position != SignalDirection.LONG:
            new_direction = SignalDirection.LONG
        elif p_up <= self.short_threshold and current_position != SignalDirection.SHORT:
            new_direction = SignalDirection.SHORT
        elif self.short_threshold < p_up < self.long_threshold and current_position != SignalDirection.EXIT:
            new_direction = SignalDirection.EXIT

        if new_direction is None:
            return

        self._current_position[symbol] = new_direction
        strength = abs(p_up - 0.5) * 2.0  # confidence normalized to [0, 1]
        self.event_queue.put(
            SignalEvent(symbol=symbol, direction=new_direction, strength=strength, strategy_id="ml_momentum_xgb")
        )
