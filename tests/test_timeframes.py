from aistock.timeframes import TimeframeManager


def test_invalid_timeframe_defaults_to_one_minute():
    manager = TimeframeManager(symbols=['AAPL'], timeframes=['bad_tf'])
    assert manager.timeframes == ['1m']
