from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..config import StrategyConfig
from ..strategy import BaseStrategy, StrategyContext, TargetPosition
from .features import extract_features
from .model import LogisticRegressionModel, load_model


class MachineLearningStrategy(BaseStrategy):
    name = "MachineLearning"

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.min_history_bars = max(config.ml_feature_lookback, 30)
        self._model: LogisticRegressionModel | None = None
        self._model_mtime: float | None = None
        self._load_model()

    def min_history(self) -> int:
        return self.min_history_bars

    def generate(self, context: StrategyContext) -> TargetPosition:
        if not self._model:
            self._load_model()
            if not self._model:
                return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)

        features = extract_features(context.history, lookback=self.config.ml_feature_lookback)
        if not features:
            return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)

        proba = self._model.predict_proba(features)
        threshold = self.config.ml_confidence_threshold
        if proba > threshold:
            confidence = min(1.0, (proba - threshold) / (1 - threshold))
            return TargetPosition(context.symbol, Decimal("1"), confidence=confidence)
        if proba < 1 - threshold:
            confidence = min(1.0, (threshold - proba) / threshold)
            return TargetPosition(context.symbol, Decimal("-1"), confidence=confidence)
        return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        model_path = Path(self.config.ml_model_path)
        if not model_path.exists():
            return
        mtime = model_path.stat().st_mtime
        if self._model and self._model_mtime == mtime:
            return
        try:
            self._model = load_model(str(model_path))
            self._model_mtime = mtime
        except Exception:
            self._model = None
            self._model_mtime = None
