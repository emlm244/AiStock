"""Factory for creating trading components with DI."""

from __future__ import annotations

from decimal import Decimal

from ..brokers.base import BaseBroker
from ..brokers.ibkr import IBKRBroker
from ..brokers.paper import PaperBroker
from ..config import BacktestConfig
from ..edge_cases import EdgeCaseHandler
from ..fsd import FSDConfig, FSDEngine
from ..idempotency import OrderIdempotencyTracker
from ..patterns import PatternDetector
from ..persistence import FileStateManager
from ..portfolio import Portfolio
from ..professional import ProfessionalSafeguards
from ..risk import RiskEngine
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
        return Portfolio(cash=Decimal(str(equity)))

    def create_risk_engine(
        self,
        portfolio: Portfolio,
        minimum_balance: float = 0.0,
        minimum_balance_enabled: bool = True,
    ) -> RiskEngine:
        """Create risk engine."""
        return RiskEngine(
            self.config.engine.risk,
            portfolio,
            self.config.data.bar_interval,
            minimum_balance=Decimal(str(minimum_balance)),
            minimum_balance_enabled=minimum_balance_enabled,
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

    def create_safeguards(self, config: dict | None = None) -> ProfessionalSafeguards:
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

    def create_fsd_engine(
        self,
        portfolio: Portfolio,
        timeframe_manager: TimeframeManager | None = None,
        pattern_detector: PatternDetector | None = None,
        safeguards: ProfessionalSafeguards | None = None,
        edge_case_handler: EdgeCaseHandler | None = None,
    ) -> FSDEngine:
        """Create FSD decision engine."""
        if not self.fsd_config:
            raise ValueError('FSD config required')

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
