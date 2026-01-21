"""Factory for creating trading components with DI."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, cast

from ..brokers.base import BaseBroker
from ..brokers.ibkr import IBKRBroker
from ..brokers.paper import PaperBroker
from ..config import BacktestConfig
from ..edge_cases import EdgeCaseHandler
from ..engines import NeuralEngine, SequentialEngine, TabularEngine
from ..fsd import FSDConfig, FSDEngine
from ..idempotency import OrderIdempotencyTracker
from ..ml.config import DoubleQLearningConfig, DuelingDQNConfig, PERConfig, SequentialConfig
from ..patterns import PatternDetector
from ..persistence import FileStateManager
from ..portfolio import Portfolio
from ..professional import ProfessionalSafeguards
from ..risk import RiskEngine, RiskState
from ..session.analytics_reporter import AnalyticsReporter
from ..session.bar_processor import BarProcessor
from ..session.checkpointer import CheckpointManager
from ..session.reconciliation import PositionReconciler
from ..timeframes import TimeframeManager


class TradingComponentsFactory:
    """Factory for creating trading components with proper DI.

    This factory encapsulates all the complex wiring between components,
    making it easy to instantiate a fully configured trading system.
    """

    def __init__(self, config: BacktestConfig, fsd_config: FSDConfig | None = None):
        self.config = config
        self.fsd_config = fsd_config

    def create_portfolio(self, initial_equity: float | None = None) -> Portfolio:
        """Create portfolio."""
        equity = initial_equity or self.config.engine.initial_equity
        settlement_tracking = bool(
            self.config.account_capabilities
            and self.config.account_capabilities.account_type == 'cash'
            and self.config.account_capabilities.enforce_settlement
        )
        return Portfolio(cash=Decimal(str(equity)), settlement_tracking=settlement_tracking)

    def create_risk_engine(
        self,
        portfolio: Portfolio,
        minimum_balance: float = 0.0,
        minimum_balance_enabled: bool = True,
        restored_state: RiskState | None = None,
    ) -> RiskEngine:
        """Create risk engine, optionally with restored state from checkpoint.

        Args:
            portfolio: Portfolio instance
            minimum_balance: Minimum balance protection threshold
            minimum_balance_enabled: Enable minimum balance check
            restored_state: Optional restored RiskState from checkpoint

        Returns:
            RiskEngine instance
        """
        return RiskEngine(
            self.config.engine.risk,
            portfolio,
            self.config.data.bar_interval,
            state=restored_state,
            minimum_balance=Decimal(str(minimum_balance)),
            minimum_balance_enabled=minimum_balance_enabled,
            account_capabilities=self.config.account_capabilities,
            contract_specs=self.config.broker.contracts if self.config.broker else None,
        )

    def create_broker(self) -> BaseBroker:
        """Create broker based on config."""
        if not self.config.broker:
            raise ValueError('Broker configuration required')

        backend = self.config.broker.backend.lower()
        if backend == 'paper':
            return PaperBroker(self.config.execution)
        elif backend == 'ibkr':
            return IBKRBroker(self.config.broker)
        else:
            raise ValueError(f'Unknown broker: {backend}')

    def create_timeframe_manager(
        self,
        symbols: list[str],
        timeframes: list[str] | None = None,
    ) -> TimeframeManager:
        """Create timeframe manager."""
        timeframes = timeframes or ['1m']
        return TimeframeManager(
            symbols=symbols,
            timeframes=timeframes,
            max_bars_per_timeframe=500,
        )

    def create_pattern_detector(self) -> PatternDetector:
        """Create pattern detector."""
        return PatternDetector(body_threshold=0.3, wick_ratio=2.0)

    def create_safeguards(self, config: dict[str, float | int] | None = None) -> ProfessionalSafeguards:
        """Create professional safeguards."""
        config = config or {}
        return ProfessionalSafeguards(
            max_trades_per_hour=int(config.get('max_trades_per_hour', 20)),
            max_trades_per_day=int(config.get('max_trades_per_day', 100)),
            chase_threshold_pct=float(config.get('chase_threshold_pct', 5.0)),
            news_volume_multiplier=float(config.get('news_volume_multiplier', 5.0)),
            end_of_day_minutes=int(config.get('end_of_day_minutes', 30)),
        )

    def create_edge_case_handler(self) -> EdgeCaseHandler:
        """Create edge case handler."""
        return EdgeCaseHandler()

    def create_advanced_risk_manager(self):
        """Create advanced risk manager if configured.

        Returns:
            AdvancedRiskManager instance or None if not configured
        """
        if not self.config.advanced_risk:
            return None

        from ..risk import AdvancedRiskManager

        return AdvancedRiskManager(self.config.advanced_risk)

    def create_fsd_engine(
        self,
        portfolio: Portfolio,
        timeframe_manager: TimeframeManager | None = None,
        pattern_detector: PatternDetector | None = None,
        safeguards: ProfessionalSafeguards | None = None,
        edge_case_handler: EdgeCaseHandler | None = None,
    ) -> FSDEngine | TabularEngine | NeuralEngine | SequentialEngine:
        """Create FSD decision engine."""
        if not self.fsd_config:
            raise ValueError('FSD config required')

        engine_type = (self.fsd_config.engine_type or 'tabular').lower().strip()
        wants_advanced_tabular = self.fsd_config.enable_double_q or self.fsd_config.enable_per
        use_advanced_engine = engine_type != 'tabular' or wants_advanced_tabular

        if not use_advanced_engine:
            return FSDEngine(
                self.fsd_config,
                portfolio,
                timeframe_manager=timeframe_manager,
                pattern_detector=pattern_detector,
                safeguards=safeguards,
                edge_case_handler=edge_case_handler,
            )

        per_config = None
        if self.fsd_config.enable_per:
            per_config = PERConfig(
                enable=True,
                buffer_size=self.fsd_config.per_buffer_size,
                alpha=self.fsd_config.per_alpha,
                beta_start=self.fsd_config.per_beta_start,
                beta_end=self.fsd_config.per_beta_end,
                beta_annealing_steps=self.fsd_config.per_annealing_steps,
                batch_size=self.fsd_config.batch_size,
                train_frequency=self.fsd_config.train_frequency,
            )

        if engine_type == 'tabular':
            double_q_config = DoubleQLearningConfig(
                enable=self.fsd_config.enable_double_q,
                target_update_freq=self.fsd_config.target_update_freq,
            )
            return TabularEngine(
                portfolio=portfolio,
                double_q_config=double_q_config,
                per_config=per_config,
                learning_rate=self.fsd_config.learning_rate,
                discount_factor=self.fsd_config.discount_factor,
                exploration_rate=self.fsd_config.exploration_rate,
                min_confidence_threshold=self.fsd_config.min_confidence_threshold,
                max_capital=self.fsd_config.max_capital,
                max_q_table_size=self.fsd_config.max_q_table_states,
            )

        if engine_type in {'dqn', 'dueling'}:
            dqn_config = DuelingDQNConfig(
                enable=engine_type == 'dueling',
                hidden_sizes=self.fsd_config.dqn_hidden_sizes,
                learning_rate=self.fsd_config.dqn_learning_rate,
                gradient_clip=self.fsd_config.dqn_gradient_clip,
                target_update_freq=self.fsd_config.target_update_freq,
            )
            return NeuralEngine(
                portfolio=portfolio,
                dqn_config=dqn_config,
                per_config=per_config,
                learning_rate=self.fsd_config.dqn_learning_rate,
                discount_factor=self.fsd_config.discount_factor,
                exploration_rate=self.fsd_config.exploration_rate,
                min_confidence_threshold=self.fsd_config.min_confidence_threshold,
                max_capital=self.fsd_config.max_capital,
                device=self.fsd_config.device,
            )

        if engine_type in {'lstm', 'transformer'}:
            seq_model = cast(Literal['lstm', 'transformer'], engine_type)
            seq_config = SequentialConfig(
                enable=True,
                model_type=seq_model,
                sequence_length=self.fsd_config.sequence_length,
                hidden_size=self.fsd_config.seq_hidden_size,
                num_layers=self.fsd_config.seq_num_layers,
                num_heads=self.fsd_config.seq_num_heads,
                dropout=self.fsd_config.seq_dropout,
                learning_rate=self.fsd_config.dqn_learning_rate,
            )
            return SequentialEngine(
                portfolio=portfolio,
                seq_config=seq_config,
                per_config=per_config,
                learning_rate=self.fsd_config.dqn_learning_rate,
                discount_factor=self.fsd_config.discount_factor,
                exploration_rate=self.fsd_config.exploration_rate,
                min_confidence_threshold=self.fsd_config.min_confidence_threshold,
                max_capital=self.fsd_config.max_capital,
                device=self.fsd_config.device,
            )

        return FSDEngine(
            self.fsd_config,
            portfolio,
            timeframe_manager=timeframe_manager,
            pattern_detector=pattern_detector,
            safeguards=safeguards,
            edge_case_handler=edge_case_handler,
        )

    def create_bar_processor(
        self,
        timeframe_manager: TimeframeManager | None = None,
    ) -> BarProcessor:
        """Create bar processor."""
        return BarProcessor(
            timeframe_manager=timeframe_manager,
            warmup_bars=self.config.data.warmup_bars,
        )

    def create_reconciler(
        self,
        portfolio: Portfolio,
        broker: BaseBroker,
        risk_engine: RiskEngine,
    ) -> PositionReconciler:
        """Create position reconciler."""
        return PositionReconciler(
            portfolio,
            broker,
            risk_engine,
            interval_minutes=60,
        )

    def create_checkpointer(
        self,
        portfolio: Portfolio,
        risk_engine: RiskEngine,
        checkpoint_dir: str = 'state',
        enabled: bool = True,
    ) -> CheckpointManager:
        """Create checkpoint manager."""

        return CheckpointManager(
            portfolio,
            risk_engine,
            FileStateManager(),
            checkpoint_dir,
            enabled,
        )

    def create_analytics_reporter(
        self,
        portfolio: Portfolio,
        checkpoint_dir: str = 'state',
    ) -> AnalyticsReporter:
        """Create analytics reporter."""
        return AnalyticsReporter(portfolio, checkpoint_dir)

    def create_idempotency_tracker(
        self,
        checkpoint_dir: str = 'state',
    ) -> OrderIdempotencyTracker:
        """Create order idempotency tracker."""
        return OrderIdempotencyTracker(storage_path=f'{checkpoint_dir}/submitted_orders.json')
