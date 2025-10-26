import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.config import StrategyConfig
from aistock.data import Bar
from aistock.ml.pipeline import train_model
from aistock.ml.strategy import MachineLearningStrategy
from aistock.strategy import StrategyContext


class MLPipelineTests(unittest.TestCase):
    def test_training_and_strategy_prediction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/TEST.csv"
            start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
            rows = []
            price = 100.0
            for i in range(200):
                trend = 0.8 if (i // 40) % 2 == 0 else -0.8
                price += trend
                rows.append(
                    {
                        "timestamp": (start + timedelta(minutes=i)).isoformat(),
                        "open": price - 0.2,
                        "high": price + 0.5,
                        "low": price - 0.5,
                        "close": price,
                        "volume": 1000 + i,
                    }
                )
            with open(path, "w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
                writer.writeheader()
                writer.writerows(rows)

            result = train_model(
                data_dir=tmpdir,
                symbols=["TEST"],
                lookback=20,
                horizon=1,
                epochs=80,
                learning_rate=0.05,
                model_path=f"{tmpdir}/model.json",
            )

            self.assertGreater(result.train_accuracy, 0.5)
            self.assertGreater(result.test_accuracy, 0.5)

            # Validate strategy integration
            bars = [
                Bar(
                    symbol="TEST",
                    timestamp=start + timedelta(minutes=i),
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=float(row["volume"]),
                )
                for i, row in enumerate(rows)
            ]
            config = StrategyConfig(ml_enabled=True, ml_model_path=result.model_path)
            strategy = MachineLearningStrategy(config)
            context = StrategyContext(symbol="TEST", history=bars[-config.ml_feature_lookback :])
            target = strategy.generate(context)
            # Strategy should produce a confidence within [0,1]
            self.assertGreaterEqual(target.confidence, 0.0)
            self.assertLessEqual(target.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
