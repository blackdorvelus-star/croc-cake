"""Machine-Learning model wrapper used by the Strategy layer.

Wraps XGBoost behind a minimal, backtest-friendly interface
(`predict_up_probability`). If the `xgboost` package cannot be imported,
the module transparently falls back to a small deterministic mock exposing
the same `predict_proba` contract, so the rest of the codebase never needs
to know which implementation is active (Liskov Substitution).

This is intentionally a *dummy/demo* model: it is fit once, at start-up, on
synthetic bootstrap samples purely so `predict_up_probability` is callable
out of the box and the asynchronous Strategy -> ML -> SignalEvent pipeline
can be demonstrated end to end. Before using anything like this near real
capital, replace `_fit_on_synthetic_bootstrap_data` with a properly
validated, walk-forward trained model loaded from disk.
"""
from __future__ import annotations

import logging
import random
from typing import List, Sequence

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb

    _HAS_XGBOOST = True
except ImportError:  # pragma: no cover - exercised only when xgboost is absent
    _HAS_XGBOOST = False
    logger.warning("xgboost is not installed; falling back to a deterministic mock model.")


class _MockGradientBoostedModel:
    """Dependency-free stand-in used only when xgboost cannot be imported.

    Mirrors the subset of the xgboost/sklearn API this codebase relies on:
    `fit(X, y)` and `predict_proba(X) -> List[[p_down, p_up]]`.
    """

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> "_MockGradientBoostedModel":
        return self

    def predict_proba(self, X: Sequence[Sequence[float]]) -> List[List[float]]:
        probabilities = []
        for row in X:
            score = sum(row) / max(len(row), 1)
            p_up = 1.0 / (1.0 + pow(2.718281828, -score))
            probabilities.append([1.0 - p_up, p_up])
        return probabilities


class DummyXGBoostSignalModel:
    """Fake/demo ML model producing a P(price up) forecast from bar features.

    Exists to demonstrate *where* and *how* a trained ML model plugs into
    the event-driven Strategy layer, running asynchronously with respect to
    MarketEvent arrival (inference only happens once enough rolling history
    has accumulated, and only every N bars — see MLMomentumStrategy).
    """

    def __init__(self, random_state: int = 42) -> None:
        self._random_state = random_state
        self._model = self._build_model(random_state)
        self._is_fitted = False
        self._fit_on_synthetic_bootstrap_data()

    @staticmethod
    def _build_model(random_state: int):
        """Build the underlying model, falling back to the dependency-free
        mock if xgboost is missing *or* one of its own optional dependencies
        (e.g. scikit-learn, required by its sklearn-compatible wrapper) is
        not installed. This keeps the strategy usable in minimal
        environments while still using real xgboost wherever available."""
        if not _HAS_XGBOOST:
            return _MockGradientBoostedModel()
        try:
            return xgb.XGBClassifier(
                n_estimators=25,
                max_depth=3,
                learning_rate=0.1,
                random_state=random_state,
                eval_metric="logloss",
            )
        except ImportError as exc:  # pragma: no cover - depends on local env
            logger.warning("xgboost.XGBClassifier unavailable (%s); falling back to mock model.", exc)
            return _MockGradientBoostedModel()

    def _fit_on_synthetic_bootstrap_data(self) -> None:
        """Bootstraps the model on synthetic data so `predict_proba` is
        callable out of the box.

        **For demonstration only.** In production, fit this model offline
        on real, walk-forward validated, labeled features and load the
        serialized model here instead of training on synthetic data at
        every strategy start-up.
        """
        rng = random.Random(self._random_state)
        X: List[List[float]] = []
        y: List[int] = []
        for _ in range(200):
            momentum = rng.uniform(-1, 1)
            rsi = rng.uniform(0, 1)
            volatility = rng.uniform(0, 1)
            label = 1 if (momentum + (rsi - 0.5)) > 0 else 0
            X.append([momentum, rsi, volatility])
            y.append(label)

        self._model.fit(X, y)
        self._is_fitted = True

    def predict_up_probability(self, features: Sequence[float]) -> float:
        """Return P(next-period price is up) in [0, 1] given a feature vector."""
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before inference.")
        proba = self._model.predict_proba([list(features)])
        return float(proba[0][1])
