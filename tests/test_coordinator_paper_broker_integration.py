from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aistock.brokers.paper import PaperBroker
from aistock.capital_management import CompoundingStrategy
from aistock.config import BacktestConfig, BrokerConfig, DataSource, EngineConfig, ExecutionConfig, StrategyConfig
from aistock.data import Bar
from aistock.portfolio import Portfolio
from aistock.risk import RiskEngine
from aistock.session.analytics_reporter import AnalyticsReporter
from aistock.session.bar_processor import BarProcessor
from aistock.session.coordinator import TradingCoordinator
from aistock.session.reconciliation import PositionReconciler
from aistock.stop_control import StopConfig, StopController


class _DecisionEngineStub:
    def evaluate_opportunity(self, symbol: str, bars: list[Bar], last_prices: dict[str, Decimal]) -> dict[str, Any]:
        return {'should_trade': True, 'action': {'size_fraction': 0.1, 'signal': 1}}

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        return

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        return

    def start_session(self) -> dict[str, Any]:
        return {}

    def end_session(self) -> dict[str, Any]:
        return {}

    def save_state(self, filepath: str) -> None:
        return

    def load_state(self, filepath: str) -> bool:
        return False


class _DecisionEngineMaxCapitalStub:
    max_capital = 1000.0

    def evaluate_opportunity(self, symbol: str, bars: list[Bar], last_prices: dict[str, Decimal]) -> dict[str, Any]:
        return {'should_trade': True, 'action': {'size_fraction': 1.0, 'signal': 1}}

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        return

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        return

    def start_session(self) -> dict[str, Any]:
        return {}

    def end_session(self) -> dict[str, Any]:
        return {}

    def save_state(self, filepath: str) -> None:
        return

    def load_state(self, filepath: str) -> bool:
        return False


class _DecisionEngineNoTrade:
    def evaluate_opportunity(self, symbol: str, bars: list[Bar], last_prices: dict[str, Decimal]) -> dict[str, Any]:
        return {'should_trade': False, 'action': {}}

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        return

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        return

    def start_session(self) -> dict[str, Any]:
        return {}

    def end_session(self) -> dict[str, Any]:
        return {}

    def save_state(self, filepath: str) -> None:
        return

    def load_state(self, filepath: str) -> bool:
        return False


class _NoopCheckpointer:
    enabled = False

    def save_async(self) -> None:
        return

    def shutdown(self) -> None:
        return


def test_paper_broker_fills_triggered_by_coordinator_bar(tmp_path) -> None:
    """
    Regression: coordinator.process_bar() must drive PaperBroker.process_bar() so submitted orders can fill.

    Without this hookup, paper backtests place orders but never receive fills.
    """
    checkpoint_dir = tmp_path / 'state'

    data = DataSource(path=str(tmp_path), timezone=timezone.utc, symbols=('AAPL',), enforce_trading_hours=False)
    engine = EngineConfig(strategy=StrategyConfig(), initial_equity=10000.0)
    engine.risk.max_position_fraction = 1.0
    engine.risk.per_trade_risk_pct = 1.0
    execution = ExecutionConfig(slip_bps_limit=0.0, partial_fill_probability=0.0)
    config = BacktestConfig(data=data, engine=engine, execution=execution, broker=BrokerConfig(backend='paper'))

    portfolio = Portfolio(cash=Decimal('10000'))
    risk_engine = RiskEngine(engine.risk, portfolio, bar_interval=timedelta(minutes=1), minimum_balance_enabled=False)
    broker = PaperBroker(execution)

    bar_processor = BarProcessor(timeframe_manager=None, warmup_bars=50)
    reconciler = PositionReconciler(portfolio, broker, risk_engine, interval_minutes=999999)
    analytics = AnalyticsReporter(portfolio, str(checkpoint_dir))

    coordinator = TradingCoordinator(
        config=config,
        portfolio=portfolio,
        risk_engine=risk_engine,
        decision_engine=_DecisionEngineStub(),
        broker=broker,
        bar_processor=bar_processor,
        reconciler=reconciler,
        checkpointer=_NoopCheckpointer(),
        analytics=analytics,
        capital_manager=CompoundingStrategy(),
        stop_controller=StopController(StopConfig(enable_eod_flatten=False)),
        symbols=['AAPL'],
        checkpoint_dir=str(checkpoint_dir),
    )

    coordinator.start()

    ts = datetime(2025, 1, 1, 14, 30, tzinfo=timezone.utc)
    bar = Bar(
        symbol='AAPL',
        timestamp=ts,
        open=Decimal('100'),
        high=Decimal('100'),
        low=Decimal('100'),
        close=Decimal('100'),
        volume=1_000,
    )
    coordinator.process_bar(bar)

    assert portfolio.get_position('AAPL') != Decimal('0')
    snap = coordinator.snapshot()
    assert len(snap['trades']) == 1


def test_max_capital_limits_position_size(tmp_path) -> None:
    checkpoint_dir = tmp_path / 'state'

    data = DataSource(path=str(tmp_path), timezone=timezone.utc, symbols=('AAPL',), enforce_trading_hours=False)
    engine = EngineConfig(strategy=StrategyConfig(), initial_equity=10000.0)
    engine.risk.max_position_fraction = 1.0
    engine.risk.per_trade_risk_pct = 1.0
    execution = ExecutionConfig(slip_bps_limit=0.0, partial_fill_probability=0.0)
    config = BacktestConfig(data=data, engine=engine, execution=execution, broker=BrokerConfig(backend='paper'))

    portfolio = Portfolio(cash=Decimal('10000'))
    risk_engine = RiskEngine(engine.risk, portfolio, bar_interval=timedelta(minutes=1), minimum_balance_enabled=False)
    broker = PaperBroker(execution)

    bar_processor = BarProcessor(timeframe_manager=None, warmup_bars=50)
    reconciler = PositionReconciler(portfolio, broker, risk_engine, interval_minutes=999999)
    analytics = AnalyticsReporter(portfolio, str(checkpoint_dir))

    coordinator = TradingCoordinator(
        config=config,
        portfolio=portfolio,
        risk_engine=risk_engine,
        decision_engine=_DecisionEngineMaxCapitalStub(),
        broker=broker,
        bar_processor=bar_processor,
        reconciler=reconciler,
        checkpointer=_NoopCheckpointer(),
        analytics=analytics,
        capital_manager=CompoundingStrategy(),
        stop_controller=StopController(StopConfig(enable_eod_flatten=False)),
        symbols=['AAPL'],
        checkpoint_dir=str(checkpoint_dir),
    )

    coordinator.start()

    ts = datetime(2025, 1, 1, 14, 30, tzinfo=timezone.utc)
    bar = Bar(
        symbol='AAPL',
        timestamp=ts,
        open=Decimal('100'),
        high=Decimal('100'),
        low=Decimal('100'),
        close=Decimal('100'),
        volume=1_000,
    )
    coordinator.process_bar(bar)

    assert portfolio.get_position('AAPL') == Decimal('10')


def test_max_holding_period_forces_exit(tmp_path) -> None:
    checkpoint_dir = tmp_path / 'state'

    data = DataSource(path=str(tmp_path), timezone=timezone.utc, symbols=('AAPL',), enforce_trading_hours=False)
    engine = EngineConfig(strategy=StrategyConfig(), initial_equity=10000.0)
    engine.risk.max_position_fraction = 1.0
    engine.risk.per_trade_risk_pct = 1.0
    engine.risk.max_holding_period_bars = 1
    execution = ExecutionConfig(slip_bps_limit=0.0, partial_fill_probability=0.0)
    config = BacktestConfig(data=data, engine=engine, execution=execution, broker=BrokerConfig(backend='paper'))

    portfolio = Portfolio(cash=Decimal('10000'))
    entry_time = datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc)
    portfolio.apply_fill('AAPL', Decimal('10'), Decimal('100'), Decimal('0'), entry_time)

    risk_engine = RiskEngine(engine.risk, portfolio, bar_interval=timedelta(minutes=1), minimum_balance_enabled=False)
    broker = PaperBroker(execution)

    bar_processor = BarProcessor(timeframe_manager=None, warmup_bars=50)
    reconciler = PositionReconciler(portfolio, broker, risk_engine, interval_minutes=999999)
    analytics = AnalyticsReporter(portfolio, str(checkpoint_dir))

    coordinator = TradingCoordinator(
        config=config,
        portfolio=portfolio,
        risk_engine=risk_engine,
        decision_engine=_DecisionEngineNoTrade(),
        broker=broker,
        bar_processor=bar_processor,
        reconciler=reconciler,
        checkpointer=_NoopCheckpointer(),
        analytics=analytics,
        capital_manager=CompoundingStrategy(),
        stop_controller=StopController(StopConfig(enable_eod_flatten=False)),
        symbols=['AAPL'],
        checkpoint_dir=str(checkpoint_dir),
    )

    coordinator.start()

    ts = datetime(2025, 1, 1, 14, 2, tzinfo=timezone.utc)
    bar = Bar(
        symbol='AAPL',
        timestamp=ts,
        open=Decimal('100'),
        high=Decimal('100'),
        low=Decimal('100'),
        close=Decimal('100'),
        volume=1_000,
    )
    coordinator.process_bar(bar)

    assert portfolio.get_position('AAPL') == Decimal('0')
