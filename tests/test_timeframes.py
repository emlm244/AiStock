from datetime import timezone

from aistock.config import BacktestConfig, BrokerConfig, DataSource, EngineConfig
from aistock.factories import SessionFactory
from aistock.fsd import FSDConfig
from aistock.timeframes import TimeframeManager


def test_invalid_timeframe_defaults_to_one_minute():
    manager = TimeframeManager(symbols=['AAPL'], timeframes=['bad_tf'])
    assert manager.timeframes == ['1m']


def test_session_factory_filters_timeframes_by_max_timeframe_seconds(tmp_path):
    data = DataSource(path=str(tmp_path), timezone=timezone.utc, symbols=('AAPL',), enforce_trading_hours=False)
    config = BacktestConfig(data=data, engine=EngineConfig(), broker=BrokerConfig(backend='paper'))
    fsd_config = FSDConfig(max_timeframe_seconds=300)

    factory = SessionFactory(config, fsd_config=fsd_config)
    session = factory.create_trading_session(symbols=['AAPL'], timeframes=['1m', '5m', '15m'])

    timeframe_manager = session.bar_processor.timeframe_manager
    assert timeframe_manager is not None
    assert '15m' not in timeframe_manager.timeframes
    assert '1m' in timeframe_manager.timeframes
    assert '5m' in timeframe_manager.timeframes
