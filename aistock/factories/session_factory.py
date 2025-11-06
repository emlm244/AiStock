"""Factory for creating trading sessions with full DI."""

from __future__ import annotations

from ..config import BacktestConfig
from ..fsd import FSDConfig
from ..session.coordinator import TradingCoordinator
from ..universe import UniverseSelector
from .trading_components_factory import TradingComponentsFactory


class SessionFactory:
    """Factory for creating fully configured trading sessions.

    This is the top-level factory that creates a complete trading system
    with all components properly wired together via dependency injection.

    Example:
        factory = SessionFactory(config, fsd_config)
        coordinator = factory.create_trading_session(
            symbols=['AAPL', 'MSFT'],
            checkpoint_dir='state'
        )
        coordinator.start()
    """

    def __init__(
        self,
        config: BacktestConfig,
        fsd_config: FSDConfig | None = None,
        enable_professional_features: bool = True,
    ):
        self.config = config
        self.fsd_config = fsd_config
        self.enable_professional = enable_professional_features

        self.components_factory = TradingComponentsFactory(config, fsd_config)

    def create_trading_session(
        self,
        symbols: list[str] | None = None,
        checkpoint_dir: str = 'state',
        minimum_balance: float = 0.0,
        minimum_balance_enabled: bool = True,
        timeframes: list[str] | None = None,
        safeguard_config: dict[str, float | int] | None = None,
    ) -> TradingCoordinator:
        """Create a fully configured trading session.

        Args:
            symbols: Trading symbols (or None to use universe selector)
            checkpoint_dir: Directory for state persistence
            minimum_balance: Minimum balance protection
            minimum_balance_enabled: Enable minimum balance check
            timeframes: Trading timeframes
            safeguard_config: Professional safeguards configuration

        Returns:
            TradingCoordinator ready to start trading
        """
        # Resolve symbols
        if symbols is None:
            if not self.config.universe:
                raise ValueError('Must provide symbols or universe config')

            selector = UniverseSelector(self.config.data, self.config.engine.data_quality)
            selection = selector.select(self.config.universe)
            if not selection.symbols:
                raise ValueError('Universe selector returned no symbols')
            symbols = selection.symbols

        timeframes = timeframes or ['1m']

        # Create core components (order matters for dependencies)
        portfolio = self.components_factory.create_portfolio()
        risk_engine = self.components_factory.create_risk_engine(portfolio, minimum_balance, minimum_balance_enabled)
        broker = self.components_factory.create_broker()

        # Create professional features
        timeframe_manager = None
        pattern_detector = None
        safeguards = None

        if self.enable_professional:
            timeframe_manager = self.components_factory.create_timeframe_manager(symbols, timeframes)
            pattern_detector = self.components_factory.create_pattern_detector()
            safeguards = self.components_factory.create_safeguards(safeguard_config)

        # Create edge case handler (mandatory)
        edge_case_handler = self.components_factory.create_edge_case_handler()

        # Create decision engine
        decision_engine = self.components_factory.create_fsd_engine(
            portfolio,
            timeframe_manager,
            pattern_detector,
            safeguards,
            edge_case_handler,
        )

        # Create session components
        bar_processor = self.components_factory.create_bar_processor(timeframe_manager)
        reconciler = self.components_factory.create_reconciler(portfolio, broker, risk_engine)
        checkpointer = self.components_factory.create_checkpointer(portfolio, risk_engine, checkpoint_dir, enabled=True)
        analytics = self.components_factory.create_analytics_reporter(portfolio, checkpoint_dir)

        # Create coordinator
        coordinator = TradingCoordinator(
            config=self.config,
            portfolio=portfolio,
            risk_engine=risk_engine,
            decision_engine=decision_engine,
            broker=broker,
            bar_processor=bar_processor,
            reconciler=reconciler,
            checkpointer=checkpointer,
            analytics=analytics,
            symbols=symbols,
            checkpoint_dir=checkpoint_dir,
        )

        return coordinator

    def create_with_checkpoint_restore(
        self,
        checkpoint_dir: str = 'state',
        symbols: list[str] | None = None,
        minimum_balance: float = 0.0,
        minimum_balance_enabled: bool = True,
        timeframes: list[str] | None = None,
        safeguard_config: dict[str, float | int] | None = None,
    ) -> TradingCoordinator:
        """Create session and restore from checkpoint.

        This method loads portfolio and risk state from a checkpoint directory
        and creates a trading session with the restored state, enabling crash recovery.

        Args:
            checkpoint_dir: Directory containing checkpoint files
            symbols: Trading symbols (or None to use universe selector)
            minimum_balance: Minimum balance protection
            minimum_balance_enabled: Enable minimum balance check
            timeframes: Trading timeframes
            safeguard_config: Professional safeguards configuration

        Returns:
            TradingCoordinator with restored state

        Raises:
            FileNotFoundError: If checkpoint files don't exist
            ValueError: If checkpoint is corrupted
        """
        from ..persistence import load_checkpoint

        # Load checkpoint
        restored_portfolio, restored_risk_state = load_checkpoint(checkpoint_dir)

        # Resolve symbols
        if symbols is None:
            if not self.config.universe:
                raise ValueError('Must provide symbols or universe config')

            from ..universe import UniverseSelector

            selector = UniverseSelector(self.config.data, self.config.engine.data_quality)
            selection = selector.select(self.config.universe)
            if not selection.symbols:
                raise ValueError('Universe selector returned no symbols')
            symbols = selection.symbols

        timeframes = timeframes or ['1m']

        # Create components using restored state
        portfolio = restored_portfolio
        risk_engine = self.components_factory.create_risk_engine(
            portfolio, minimum_balance, minimum_balance_enabled, restored_state=restored_risk_state
        )
        broker = self.components_factory.create_broker()

        # Create professional features
        timeframe_manager = None
        pattern_detector = None
        safeguards = None

        if self.enable_professional:
            timeframe_manager = self.components_factory.create_timeframe_manager(symbols, timeframes)
            pattern_detector = self.components_factory.create_pattern_detector()
            safeguards = self.components_factory.create_safeguards(safeguard_config)

        # Create edge case handler (mandatory)
        edge_case_handler = self.components_factory.create_edge_case_handler()

        # Create decision engine
        decision_engine = self.components_factory.create_fsd_engine(
            portfolio,
            timeframe_manager,
            pattern_detector,
            safeguards,
            edge_case_handler,
        )

        # Create session components
        bar_processor = self.components_factory.create_bar_processor(timeframe_manager)
        reconciler = self.components_factory.create_reconciler(portfolio, broker, risk_engine)
        checkpointer = self.components_factory.create_checkpointer(portfolio, risk_engine, checkpoint_dir, enabled=True)
        analytics = self.components_factory.create_analytics_reporter(portfolio, checkpoint_dir)

        # Create coordinator
        coordinator = TradingCoordinator(
            config=self.config,
            portfolio=portfolio,
            risk_engine=risk_engine,
            decision_engine=decision_engine,
            broker=broker,
            bar_processor=bar_processor,
            reconciler=reconciler,
            checkpointer=checkpointer,
            analytics=analytics,
            symbols=symbols,
            checkpoint_dir=checkpoint_dir,
        )

        return coordinator
