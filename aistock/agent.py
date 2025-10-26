"""
Autonomous adaptation loop for AIStock sessions.

The adaptive agent continuously monitors live trading outcomes, proposes safer
and higher-quality strategy parameters when performance drifts, validates those
proposals via backtests, and only then applies the changes to the running
session—always respecting configured risk ceilings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable

from .config import BacktestConfig, BrokerConfig, ContractSpec, EngineConfig, RiskLimits
from .engine import BacktestResult, BacktestRunner
from .logging import configure_logger
from .performance import compute_drawdown, compute_returns, sharpe_ratio


@dataclass(frozen=True)
class ObjectiveThresholds:
    """
    Guardrails for the adaptive loop.

    - ``min_sharpe``: Sharpe ratio target for both live performance and
      candidate simulations.
    - ``max_drawdown``: Maximum acceptable peak-to-trough drawdown.
    - ``min_win_rate``: Floor for signal accuracy.
    - ``min_trades``: Minimum trade count before the agent considers adapting.
    - ``max_equity_pullback_pct``: Maximum realised capital loss (as fraction of
      starting equity) tolerated before intervention.
    - ``max_position_fraction_cap``: Upper bound on position allocation when the
      agent tightens risk.
    """

    min_sharpe: float = 0.75
    max_drawdown: float = 0.20
    min_win_rate: float = 0.45
    min_trades: int = 20
    max_equity_pullback_pct: float = 0.05
    max_position_fraction_cap: float = 0.20
    max_daily_loss_pct: float | None = None
    max_weekly_loss_pct: float | None = None

    def requires_action(self, metrics: "OutcomeMetrics") -> bool:
        if metrics.trade_count < self.min_trades:
            return False
        if metrics.halted:
            return True
        if metrics.win_rate < self.min_win_rate:
            return True
        if metrics.max_drawdown > self.max_drawdown:
            return True
        if metrics.sharpe < self.min_sharpe:
            return True
        if metrics.equity_change_pct <= -self.max_equity_pullback_pct:
            return True
        if self.max_daily_loss_pct is not None and abs(metrics.notes.get("daily_loss_pct", 0.0)) > self.max_daily_loss_pct:
            return True
        if self.max_weekly_loss_pct is not None and abs(metrics.notes.get("weekly_loss_pct", 0.0)) > self.max_weekly_loss_pct:
            return True
        return False

    def accepts_simulation(self, simulated: BacktestResult) -> bool:
        sharpe = float(simulated.metrics.get("sharpe") or 0.0)
        if not math.isfinite(sharpe) or sharpe < self.min_sharpe:
            return False
        drawdown = float(simulated.max_drawdown)
        if drawdown > self.max_drawdown:
            return False
        if simulated.win_rate < self.min_win_rate:
            return False
        return True


@dataclass(frozen=True)
class OutcomeMetrics:
    win_rate: float
    trade_count: int
    realised_pnl: float
    equity_change_pct: float
    max_drawdown: float
    sharpe: float
    halted: bool
    notes: dict[str, float]


class OutcomeMonitor:
    """Summarise live trading outcomes for the adaptive agent."""

    @staticmethod
    def observe(session) -> OutcomeMetrics:
        snapshot = session.snapshot()
        trades = snapshot["trades"]
        trade_count = len(trades)
        wins = sum(1 for trade in trades if trade["realised_pnl"] > 0)
        realised_pnl = sum(trade["realised_pnl"] for trade in trades)

        win_rate = wins / trade_count if trade_count else 0.0
        equity_curve = [
            (ts, Decimal(str(equity)))
            for ts, equity in snapshot.get("equity_curve", [])
        ]

        if equity_curve:
            start_equity = equity_curve[0][1]
            final_equity = equity_curve[-1][1]
        else:
            start_equity = Decimal(str(session.config.engine.initial_equity))
            final_equity = Decimal(str(snapshot["equity"]))

        equity_change_pct = float(
            (final_equity - start_equity) / start_equity if start_equity else Decimal("0")
        )

        if equity_curve:
            drawdown = compute_drawdown(equity_curve)
            returns = compute_returns(equity_curve)
            sharpe = sharpe_ratio(returns)
        else:
            drawdown = Decimal("0")
            sharpe = 0.0

        risk_daily = Decimal(str(snapshot["risk"]["daily_pnl"]))
        daily_loss_pct = float(risk_daily / start_equity) if start_equity else 0.0

        weekly_loss_pct = float(snapshot.get("risk", {}).get("weekly_loss_pct", 0.0))

        notes = {
            "daily_loss_pct": daily_loss_pct,
            "peak_equity": snapshot["risk"]["peak_equity"],
            "weekly_loss_pct": weekly_loss_pct,
        }

        return OutcomeMetrics(
            win_rate=win_rate,
            trade_count=trade_count,
            realised_pnl=realised_pnl,
            equity_change_pct=equity_change_pct,
            max_drawdown=float(drawdown),
            sharpe=float(sharpe),
            halted=bool(snapshot["risk"]["halted"]),
            notes=notes,
        )


@dataclass(frozen=True)
class AdaptationDecision:
    reason: str
    live_metrics: OutcomeMetrics
    simulation: BacktestResult
    applied_config: BacktestConfig


@dataclass(frozen=True)
class AssetClassPolicy:
    sec_type: str
    exchange: str | None = None
    currency: str | None = None
    multiplier: float | None = None
    max_position_fraction: float | None = None
    per_symbol_cap: float | None = None


class AdaptiveAgent:
    """
    Closed-loop controller that keeps the trading session aligned with intent.

    Usage:
        agent = AdaptiveAgent(training_config)
        decision = agent.evaluate_and_adapt(session)
        if decision:
            print("Updated strategy:", decision.applied_config.engine.strategy)
    """

    def __init__(
        self,
        training_config: BacktestConfig,
        objectives: ObjectiveThresholds | None = None,
        asset_policies: dict[str, AssetClassPolicy] | None = None,
    ) -> None:
        training_config.validate()
        self.training_config = training_config
        self.objectives = objectives or ObjectiveThresholds()
        self.monitor = OutcomeMonitor()
        self.logger = configure_logger("AdaptiveAgent", structured=True)
        self.asset_policies = asset_policies or {}

    # ------------------------------------------------------------------
    def evaluate_and_adapt(self, session) -> AdaptationDecision | None:
        metrics = self.monitor.observe(session)

        if not self.objectives.requires_action(metrics):
            return None

        proposed_live_config = self._propose_live_update(session, metrics)
        if proposed_live_config is None:
            self.logger.info(
                "no_adaptation_proposed",
                extra={"reason": "unable_to_generate_candidate", "metrics": metrics.__dict__},
            )
            return None

        training_config = self._build_training_config(proposed_live_config, session.symbols)
        simulation = BacktestRunner(training_config).run()

        if not self.objectives.accepts_simulation(simulation):
            self.logger.warning(
                "adaptation_rejected_after_simulation",
                extra={
                    "live_metrics": metrics.__dict__,
                    "sim_sharpe": simulation.metrics.get("sharpe"),
                    "sim_drawdown": float(simulation.max_drawdown),
                    "sim_win_rate": simulation.win_rate,
                },
            )
            return None

        session.apply_adaptive_config(proposed_live_config)
        self.logger.info(
            "adaptation_applied",
            extra={
                "reason": "performance_deviation",
                "live_metrics": metrics.__dict__,
                "new_short_window": proposed_live_config.engine.strategy.short_window,
                "new_long_window": proposed_live_config.engine.strategy.long_window,
                "new_max_position_fraction": proposed_live_config.engine.risk.max_position_fraction,
            },
        )
        return AdaptationDecision(
            reason="performance_deviation",
            live_metrics=metrics,
            simulation=simulation,
            applied_config=proposed_live_config,
        )

    # ------------------------------------------------------------------
    def _propose_live_update(self, session, metrics: OutcomeMetrics) -> BacktestConfig | None:
        current_strategy = session.config.engine.strategy
        new_short = current_strategy.short_window
        new_long = current_strategy.long_window
        enable_ml = current_strategy.ml_enabled
        reasons: list[str] = []

        if metrics.win_rate < self.objectives.min_win_rate:
            new_short = max(3, current_strategy.short_window - 1)
            new_long = min(
                max(new_short + 2, current_strategy.long_window + 2),
                240,
            )
            reasons.append("win_rate_below_threshold")

        if metrics.max_drawdown > self.objectives.max_drawdown:
            enable_ml = True
            new_short = max(3, new_short - 1)
            new_long = max(new_long, new_short + 2)
            reasons.append("drawdown_exceeded")

        if metrics.sharpe < self.objectives.min_sharpe:
            new_short = max(3, new_short - 1)
            new_long = max(new_long + 1, new_short + 2)
            enable_ml = True
            reasons.append("sharpe_below_target")

        if not reasons:
            return None

        strategy = replace(
            current_strategy,
            short_window=new_short,
            long_window=new_long,
            ml_enabled=enable_ml,
        )

        risk_limits = self._tighten_risk_limits(session.config.engine.risk, metrics)
        broker_config, risk_limits = self._apply_asset_policies(session, risk_limits)

        engine: EngineConfig = replace(
            session.config.engine,
            strategy=strategy,
            risk=risk_limits,
        )
        data = replace(session.config.data, symbols=tuple(session.symbols))

        return replace(session.config, engine=engine, data=data, broker=broker_config)

    def _tighten_risk_limits(self, limits: RiskLimits, metrics: OutcomeMetrics) -> RiskLimits:
        new_max_fraction = limits.max_position_fraction
        new_symbol_cap = limits.per_symbol_notional_cap

        if metrics.max_drawdown > self.objectives.max_drawdown or metrics.equity_change_pct <= -self.objectives.max_equity_pullback_pct:
            new_max_fraction = max(
                0.05,
                min(
                    self.objectives.max_position_fraction_cap,
                    limits.max_position_fraction * 0.9,
                ),
            )
            new_symbol_cap = new_symbol_cap * 0.9 if new_symbol_cap > 0 else new_symbol_cap

        return replace(
            limits,
            max_position_fraction=new_max_fraction,
            per_symbol_notional_cap=new_symbol_cap,
        )

    def _apply_asset_policies(
        self,
        session,
        risk_limits: RiskLimits,
    ) -> tuple[BrokerConfig, RiskLimits]:
        if not self.asset_policies:
            return session.config.broker, risk_limits

        broker = session.config.broker
        contracts = dict(broker.contracts)
        adjusted_fraction = risk_limits.max_position_fraction
        adjusted_cap = risk_limits.per_symbol_notional_cap

        for symbol in session.symbols:
            spec = contracts.get(symbol)
            if not spec:
                spec = ContractSpec(
                    symbol=symbol,
                    sec_type=broker.ib_sec_type,
                    exchange=broker.ib_exchange,
                    currency=broker.ib_currency,
                )
            policy = self._find_policy(spec.sec_type)
            if not policy:
                contracts[symbol] = spec
                continue

            updated_spec = ContractSpec(
                symbol=symbol,
                sec_type=policy.sec_type or spec.sec_type,
                exchange=policy.exchange or spec.exchange,
                currency=policy.currency or spec.currency,
                multiplier=policy.multiplier or spec.multiplier,
                local_symbol=spec.local_symbol,
            )
            contracts[symbol] = updated_spec

            if policy.max_position_fraction is not None:
                adjusted_fraction = min(adjusted_fraction, policy.max_position_fraction)
            if policy.per_symbol_cap is not None and adjusted_cap > 0:
                adjusted_cap = min(adjusted_cap, policy.per_symbol_cap)

        updated_broker = replace(broker, contracts=contracts)
        updated_risk = replace(
            risk_limits,
            max_position_fraction=adjusted_fraction,
            per_symbol_notional_cap=adjusted_cap,
        )
        return updated_broker, updated_risk

    def _find_policy(self, sec_type: str) -> AssetClassPolicy | None:
        return self.asset_policies.get(sec_type.upper()) or self.asset_policies.get(sec_type)

    def _build_training_config(
        self,
        proposed_live_config: BacktestConfig,
        symbols: Iterable[str],
    ) -> BacktestConfig:
        data = replace(self.training_config.data, symbols=tuple(symbols))
        engine = replace(
            self.training_config.engine,
            strategy=proposed_live_config.engine.strategy,
            risk=proposed_live_config.engine.risk,
        )
        return replace(self.training_config, data=data, engine=engine)
