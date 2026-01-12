"""Factory for creating trading sessions with full DI."""

from __future__ import annotations

from ..capital_management import CompoundingStrategy, ProfitWithdrawalStrategy
from ..config import BacktestConfig
from ..fsd import FSDConfig
from ..futures.preflight import FuturesPreflightChecker, PreflightResult
from ..futures.rollover import RolloverConfig, RolloverManager
from ..log_config import configure_logger
from ..portfolio import Portfolio
from ..risk import RiskEngine
from ..session.coordinator import TradingCoordinator
from ..stop_control import StopConfig, StopController
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
        rollover_config: RolloverConfig | None = None,
    ):
        self.config = config
        self.fsd_config = fsd_config
        self.enable_professional = enable_professional_features
        self.rollover_config = rollover_config

        self.config.validate()
        if self.fsd_config is not None:
            self.fsd_config.validate()

        self.components_factory = TradingComponentsFactory(config, fsd_config)
        self._logger = configure_logger('SessionFactory', structured=True)

    def _resolve_symbols(self, symbols: list[str] | None) -> list[str]:
        """Resolve symbols from config or universe selector.

        Args:
            symbols: Optional list of symbols

        Returns:
            Resolved list of symbols

        Raises:
            ValueError: If symbols cannot be resolved
        """
        if symbols is None:
            if not self.config.universe:
                raise ValueError('Must provide symbols or universe config')

            selector = UniverseSelector(self.config.data, self.config.engine.data_quality)
            selection = selector.select(self.config.universe)
            if not selection.symbols:
                raise ValueError('Universe selector returned no symbols')
            symbols = selection.symbols

        return symbols

    def _run_futures_preflight(
        self,
        broker: object,
    ) -> PreflightResult:
        """
        Run pre-flight validation for futures contracts.

        This method validates all configured futures contracts and:
        - Logs warnings for contracts approaching expiry
        - Disables futures for this session if contracts are invalid
        - Keeps stock trading active even when futures checks fail

        Args:
            broker: Broker instance (may support request_contract_details)

        Returns:
            PreflightResult

        Raises:
            RuntimeError: If preflight fails with blocking errors
        """
        if not self.config.broker or not self.config.broker.contracts:
            return PreflightResult(passed=True, errors=[], warnings=[], validated_contracts={})

        # Filter to futures contracts only
        futures_contracts = {
            symbol: spec for symbol, spec in self.config.broker.contracts.items() if spec.sec_type == 'FUT'
        }

        if not futures_contracts:
            caps = self.config.account_capabilities
            if caps and caps.enable_futures:
                self._logger.warning(
                    'futures_enabled_without_contracts',
                    extra={'detail': 'Futures enabled but no FUT contracts configured; disabling futures.'},
                )
                caps.enable_futures = False
            return PreflightResult(passed=True, errors=[], warnings=[], validated_contracts={})

        self._logger.info(
            'running_futures_preflight',
            extra={'contract_count': len(futures_contracts)},
        )

        warn_days = self.rollover_config.warn_days_before_expiry if self.rollover_config else 7

        checker = FuturesPreflightChecker(
            warn_threshold_days=warn_days,
            block_on_expired=False,
        )

        # Check if broker supports contract details (cast to protocol if supported)
        from ..futures.validator import IBKRBrokerProtocol

        ibkr_broker: IBKRBrokerProtocol | None = None
        if hasattr(broker, 'request_contract_details') and hasattr(broker, 'isConnected'):
            # Type-ignore because we've manually verified the required methods exist
            ibkr_broker = broker  # type: ignore[assignment]

        result = checker.run_preflight(ibkr_broker, futures_contracts)
        caps = self.config.account_capabilities
        futures_enabled = bool(caps and caps.enable_futures)

        if result.errors:
            error_msg = '; '.join(result.errors)
            self._logger.warning(
                'futures_preflight_errors',
                extra={'errors': result.errors},
            )
            if futures_enabled and caps:
                caps.enable_futures = False
                self._logger.warning(
                    'futures_disabled_due_to_preflight',
                    extra={'detail': error_msg},
                )

        # Log warnings
        for warning in result.warnings:
            self._logger.warning(f'Futures preflight warning: {warning}')

        return result

    def _wire_components(
        self,
        portfolio: Portfolio,
        risk_engine: RiskEngine,
        symbols: list[str],
        timeframes: list[str],
        safeguard_config: dict[str, float | int] | None,
        checkpoint_dir: str,
    ) -> TradingCoordinator:
        """Wire components into a trading coordinator.

        Args:
            portfolio: Portfolio instance
            risk_engine: Risk engine instance
            symbols: Trading symbols
            timeframes: Trading timeframes
            safeguard_config: Professional safeguards configuration
            checkpoint_dir: Directory for state persistence

        Returns:
            Fully wired TradingCoordinator

        Raises:
            RuntimeError: If futures preflight fails (expired contracts)
        """
        broker = self.components_factory.create_broker()

        # Run futures preflight BEFORE starting (blocks if expired contracts)
        self._run_futures_preflight(broker)

        # Create rollover manager if configured
        rollover_manager: RolloverManager | None = None
        if self.rollover_config:
            rollover_manager = RolloverManager(
                config=self.rollover_config,
                state_dir=checkpoint_dir,
            )
            self._logger.info(
                'rollover_manager_created',
                extra={'warn_days': self.rollover_config.warn_days_before_expiry},
            )

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

        # Wire advanced risk manager (if configured)
        advanced_risk_manager = self.components_factory.create_advanced_risk_manager()
        if advanced_risk_manager is not None:
            set_advanced_risk = getattr(decision_engine, 'set_advanced_risk_manager', None)
            if callable(set_advanced_risk):
                set_advanced_risk(advanced_risk_manager)

        # Create session components
        bar_processor = self.components_factory.create_bar_processor(timeframe_manager)
        reconciler = self.components_factory.create_reconciler(portfolio, broker, risk_engine)
        checkpointer = self.components_factory.create_checkpointer(portfolio, risk_engine, checkpoint_dir, enabled=True)
        analytics = self.components_factory.create_analytics_reporter(portfolio, checkpoint_dir)

        # Create capital management strategy
        if self.config.capital_management and self.config.capital_management.enabled:
            capital_manager = ProfitWithdrawalStrategy(self.config.capital_management)
        else:
            capital_manager = CompoundingStrategy()

        # Create stop controller
        stop_controller = StopController(self.config.stop_control or StopConfig())

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
            capital_manager=capital_manager,
            stop_controller=stop_controller,
            symbols=symbols,
            checkpoint_dir=checkpoint_dir,
            rollover_manager=rollover_manager,
            safeguards=safeguards,
            edge_case_handler=edge_case_handler,
        )

        return coordinator

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
        symbols = self._resolve_symbols(symbols)
        timeframes = self._filter_timeframes(timeframes or ['1m'])

        # Create core components
        portfolio = self.components_factory.create_portfolio()
        risk_engine = self.components_factory.create_risk_engine(portfolio, minimum_balance, minimum_balance_enabled)

        # Wire all components together
        return self._wire_components(portfolio, risk_engine, symbols, timeframes, safeguard_config, checkpoint_dir)

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
        symbols = self._resolve_symbols(symbols)
        timeframes = self._filter_timeframes(timeframes or ['1m'])

        # Create risk engine with restored state
        risk_engine = self.components_factory.create_risk_engine(
            restored_portfolio, minimum_balance, minimum_balance_enabled, restored_state=restored_risk_state
        )

        # Wire all components together
        return self._wire_components(
            restored_portfolio, risk_engine, symbols, timeframes, safeguard_config, checkpoint_dir
        )

    def _filter_timeframes(self, timeframes: list[str]) -> list[str]:
        """Apply max_timeframe_seconds (if configured) to the requested timeframes."""
        if not self.fsd_config:
            return timeframes
        max_seconds = int(self.fsd_config.max_timeframe_seconds)
        if max_seconds <= 0:
            return timeframes
        try:
            from ..timeframes import SECONDS_TO_TIMEFRAME, TIMEFRAME_TO_SECONDS
        except Exception:
            return timeframes

        normalized = [tf.lower().strip() for tf in timeframes if tf]
        filtered = [
            tf
            for tf in normalized
            if (TIMEFRAME_TO_SECONDS.get(tf) or 0) <= max_seconds
        ]

        decision_seconds = int(getattr(self.config.data.bar_interval, 'total_seconds', lambda: 60)())
        decision_tf = SECONDS_TO_TIMEFRAME.get(decision_seconds, '1m')
        if decision_tf not in filtered:
            filtered.insert(0, decision_tf)
        return filtered or [decision_tf]
