import csv
import tempfile
from datetime import datetime, timedelta, timezone

from aistock.calibration import calibrate_objectives
from aistock.config import BacktestConfig, DataSource, EngineConfig, StrategyConfig
from aistock.engine import BacktestRunner


def _write_series(path: str, start_price: float = 100.0) -> None:
    start_time = datetime(2020, 1, 2, 14, 30, tzinfo=timezone.utc)
    price = start_price
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for idx in range(120):
            ts = start_time + timedelta(days=idx)
            open_price = price
            price = price * 1.001
            writer.writerow(
                [
                    ts.isoformat(),
                    f"{open_price:.2f}",
                    f"{price * 1.01:.2f}",
                    f"{price * 0.99:.2f}",
                    f"{price:.2f}",
                    "100000",
                ]
            )


def test_calibrate_objectives_returns_thresholds():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_series(f"{tmpdir}/AAA.csv", 50.0)
        _write_series(f"{tmpdir}/BBB.csv", 150.0)

        config = BacktestConfig(
            data=DataSource(
                path=tmpdir,
                symbols=["AAA", "BBB"],
                enforce_trading_hours=False,
                bar_interval=timedelta(days=1),
                warmup_bars=30,
            ),
            engine=EngineConfig(
                strategy=StrategyConfig(short_window=5, long_window=15),
            ),
        )

        result = BacktestRunner(config).run()
        summary = calibrate_objectives([result])
        thresholds = summary.thresholds

        assert thresholds.min_sharpe >= 0.0
        assert thresholds.max_drawdown > 0
        assert thresholds.min_trades >= 20
        assert summary.samples == 1
