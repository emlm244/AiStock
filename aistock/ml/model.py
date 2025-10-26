from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class LogisticRegressionModel:
    feature_names: list[str]
    weights: list[float]
    bias: float
    means: list[float]
    stds: list[float]

    def _vectorise(self, features: dict[str, float]) -> list[float]:
        return [features.get(name, 0.0) for name in self.feature_names]

    def _standardise(self, vector: Sequence[float]) -> list[float]:
        return [
            (value - mean) / std if std != 0 else 0.0
            for value, mean, std in zip(vector, self.means, self.stds)
        ]

    def predict_proba(self, features: dict[str, float]) -> float:
        vector = self._vectorise(features)
        standardised = self._standardise(vector)
        z = self.bias
        for value, weight in zip(standardised, self.weights):
            z += weight * value
        return 1 / (1 + math.exp(-z))

    def predict(self, features: dict[str, float]) -> int:
        return 1 if self.predict_proba(features) >= 0.5 else 0


def train_logistic_regression(
    samples: Sequence[tuple[dict[str, float], int]],
    learning_rate: float = 0.01,
    epochs: int = 200,
    l2_penalty: float = 0.0,
) -> LogisticRegressionModel:
    if not samples:
        raise ValueError("No samples provided for training.")
    feature_names = sorted({name for feats, _ in samples for name in feats})
    vectors = [[feats.get(name, 0.0) for name in feature_names] for feats, _ in samples]
    labels = [label for _, label in samples]

    columns = list(zip(*vectors)) if vectors else [[] for _ in feature_names]
    means = [_mean(column) for column in columns]
    stds = [_std(column, mean) for column, mean in zip(columns, means)]

    standardised_vectors = [
        [(value - mean) / std if std != 0 else 0.0 for value, mean, std in zip(vector, means, stds)]
        for vector in vectors
    ]

    weights = [0.0 for _ in feature_names]
    bias = 0.0

    for _ in range(epochs):
        grad_w = [0.0 for _ in feature_names]
        grad_b = 0.0
        for vector, label in zip(standardised_vectors, labels):
            z = bias + sum(weight * value for weight, value in zip(weights, vector))
            prediction = 1 / (1 + math.exp(-z))
            error = prediction - label
            for idx, value in enumerate(vector):
                grad_w[idx] += error * value
            grad_b += error
        m = len(samples)
        for idx in range(len(weights)):
            weights[idx] -= learning_rate * ((grad_w[idx] / m) + l2_penalty * weights[idx])
        bias -= learning_rate * grad_b / m

    return LogisticRegressionModel(feature_names=feature_names, weights=weights, bias=bias, means=means, stds=stds)


def save_model(model: LogisticRegressionModel, path: str) -> None:
    payload = {
        "feature_names": model.feature_names,
        "weights": model.weights,
        "bias": model.bias,
        "means": model.means,
        "stds": model.stds,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_model(path: str) -> LogisticRegressionModel:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return LogisticRegressionModel(
        feature_names=list(payload["feature_names"]),
        weights=list(payload["weights"]),
        bias=float(payload["bias"]),
        means=list(payload.get("means", [0.0] * len(payload["feature_names"]))),
        stds=list(payload.get("stds", [1.0] * len(payload["feature_names"]))),
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], mean: float) -> float:
    if not values:
        return 1.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) if variance > 0 else 1.0
