"""
Calibration utilities for setting adaptive thresholds from historical results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable, Sequence

from .agent import ObjectiveThresholds
from .engine import BacktestResult


@dataclass(frozen=True)
class CalibrationSummary:
    thresholds: ObjectiveThresholds
    baseline: dict[str, float]
    samples: int

    def to_dict(self) -> dict[str, object]:
        thresholds = {
            "min_sharpe": self.thresholds.min_sharpe,
            "max_drawdown": self.thresholds.max_drawdown,
            "min_win_rate": self.thresholds.min_win_rate,
            "min_trades": self.thresholds.min_trades,
            "max_equity_pullback_pct": self.thresholds.max_equity_pullback_pct,
            "max_position_fraction_cap": self.thresholds.max_position_fraction_cap,
            "max_daily_loss_pct": self.thresholds.max_daily_loss_pct,
            "max_weekly_loss_pct": self.thresholds.max_weekly_loss_pct,
        }
        return {
            "thresholds": thresholds,
            "baseline": self.baseline,
            "samples": self.samples,
        }


def calibrate_objectives(
    results: Sequence[BacktestResult],
    safety_margin: float = 0.15,
) -> CalibrationSummary:
    """
    Derive guardrails for the adaptive agent from historical simulations.

    Args:
        results: One or more backtest runs representative of live conditions.
        safety_margin: Fractional buffer applied when generating thresholds. Higher
            values make the agent intervene earlier.
    """

    if not results:
        raise ValueError("At least one BacktestResult is required for calibration.")
    if safety_margin < 0:
        raise ValueError("safety_margin must be non-negative")

    sharpe_values = [_finite(result.metrics.get("sharpe")) for result in results]
    drawdowns = [float(result.max_drawdown) for result in results]
    win_rates = [result.win_rate for result in results]
    trade_counts = [len(result.trades) for result in results]
    pullbacks = [_max_equity_pullback(result) for result in results]
    daily_losses = [_max_loss_pct(result.equity_curve, horizon=1) for result in results]
    weekly_losses = [_max_loss_pct(result.equity_curve, horizon=5) for result in results]

    baseline_sharpe = median(sharpe_values)
    baseline_drawdown = max(drawdowns)
    baseline_win_rate = median(win_rates)
    baseline_pullback = max(pullbacks)
    baseline_daily = max(daily_losses)
    baseline_weekly = max(weekly_losses)
    baseline_trades = median(trade_counts)

    thresholds = ObjectiveThresholds(
        min_sharpe=max(0.0, baseline_sharpe * (1 - safety_margin)),
        max_drawdown=baseline_drawdown * (1 + safety_margin),
        min_win_rate=max(0.0, baseline_win_rate * (1 - safety_margin)),
        min_trades=max(20, int(baseline_trades * 0.5)),
        max_equity_pullback_pct=baseline_pullback * (1 + safety_margin),
        max_position_fraction_cap=0.20,
        max_daily_loss_pct=baseline_daily * (1 + safety_margin),
        max_weekly_loss_pct=baseline_weekly * (1 + safety_margin),
    )

    baseline = {
        "median_sharpe": baseline_sharpe,
        "max_drawdown": baseline_drawdown,
        "median_win_rate": baseline_win_rate,
        "median_trades": baseline_trades,
        "max_equity_pullback": baseline_pullback,
        "max_daily_loss_pct": baseline_daily,
        "max_weekly_loss_pct": baseline_weekly,
    }

    return CalibrationSummary(
        thresholds=thresholds,
        baseline=baseline,
        samples=len(results),
    )


def _finite(value) -> float:
    if value is None:
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value != value or value == float("inf") or value == float("-inf"):
        return 0.0
    return value


def _max_equity_pullback(result: BacktestResult) -> float:
    curve = [float(equity) for _, equity in result.equity_curve]
    if not curve:
        return 0.0
    peak = curve[0]
    max_pullback = 0.0
    for value in curve:
        if value > peak:
            peak = value
        if peak > 0:
            pullback = (peak - value) / peak
            if pullback > max_pullback:
                max_pullback = pullback
    return max_pullback


def _max_loss_pct(equity_curve: Iterable[tuple[datetime, object]], horizon: int) -> float:
    """
    Maximum loss over a sliding window of length ``horizon`` (in bars).
    """
    equities = [float(equity) for _, equity in equity_curve]
    if len(equities) <= horizon:
        return 0.0
    max_loss = 0.0
    for idx in range(horizon, len(equities)):
        start = equities[idx - horizon]
        end = equities[idx]
        if start <= 0:
            continue
        loss = (start - end) / start
        if loss > max_loss:
            max_loss = loss
    return max_loss
