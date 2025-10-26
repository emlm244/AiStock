import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.brokers.base import BaseBroker
from aistock.config import (
    BacktestConfig,
    BrokerConfig,
    DataSource,
    EngineConfig,
    RiskLimits,
    StrategyConfig,
)
from aistock.data import Bar
from aistock.idempotency import OrderIdempotencyTracker
from aistock.session import LiveTradingSession


class _StaticBroker(BaseBroker):
    def __init__(self):
        super().__init__()
        self.submitted_orders = []
        self.position_requests = 0

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def submit(self, order):
        self.submitted_orders.append(order)
        return len(self.submitted_orders)

    def cancel(self, order_id: int) -> bool:
        return True

    def get_positions(self) -> dict[str, tuple[float, float]]:
        self.position_requests += 1
        return {}


class _RecordingTracker(OrderIdempotencyTracker):
    def __init__(self, storage_path: str):
        super().__init__(storage_path)
        self.clear_invocations = 0

    def clear_old_ids(self, retention_count: int = 10000) -> None:
        self.clear_invocations += 1
        super().clear_old_ids(retention_count)


class SessionTests(unittest.TestCase):
    def _make_config(self, tmpdir: str) -> BacktestConfig:
        return BacktestConfig(
            data=DataSource(
                path=tmpdir,
                symbols=["AAPL"],
                warmup_bars=5,
                enforce_trading_hours=False,
            ),
            engine=EngineConfig(
                initial_equity=100_000,
                strategy=StrategyConfig(short_window=3, long_window=5),
                risk=RiskLimits(
                    max_position_fraction=1.0,
                    per_symbol_notional_cap=1_000_000,
                    max_single_position_units=1_000_000,
                ),
            ),
            broker=BrokerConfig(backend="paper"),
        )

    def test_reconciliation_uses_bar_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._make_config(tmpdir)
            session = LiveTradingSession(config, checkpoint_dir=tmpdir, enable_checkpointing=False)

            broker = _StaticBroker()
            broker.set_fill_handler(session._handle_fill)
            session.broker = broker
            session._reconciliation_interval = timedelta(minutes=30)

            t0 = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)

            self.assertTrue(session._should_reconcile(t0))
            session._reconcile_positions(t0)
            self.assertEqual(session._last_reconciliation_time, t0)
            self.assertEqual(broker.position_requests, 1)

            t1 = t0 + timedelta(minutes=10)
            self.assertFalse(session._should_reconcile(t1))

            t2 = t0 + timedelta(minutes=35)
            self.assertTrue(session._should_reconcile(t2))
            session._reconcile_positions(t2)
            self.assertEqual(session._last_reconciliation_time, t2)
            self.assertEqual(broker.position_requests, 2)

    def test_clear_old_ids_runs_on_new_session_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._make_config(tmpdir)
            session = LiveTradingSession(config, checkpoint_dir=tmpdir, enable_checkpointing=False)

            tracker_path = os.path.join(tmpdir, "ids.json")
            tracker = _RecordingTracker(tracker_path)
            session.idempotency_tracker = tracker

            broker = _StaticBroker()
            broker.set_fill_handler(session._handle_fill)
            session.broker = broker

            base_ts = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
            bars: list[Bar] = []
            price = Decimal("100")
            for idx in range(30):
                price += Decimal("0.5")
                ts = base_ts + timedelta(minutes=idx)
                bars.append(
                    Bar(
                        symbol="AAPL",
                        timestamp=ts,
                        open=price,
                        high=price + Decimal("0.1"),
                        low=price - Decimal("0.1"),
                        close=price,
                        volume=1000,
                    )
                )

            session.history["AAPL"] = bars
            session.last_prices["AAPL"] = bars[-1].close
            session.risk.state.last_reset_date = (bars[-1].timestamp - timedelta(days=1)).date()

            session._evaluate_signal(bars[-1].timestamp, "AAPL")

            self.assertGreaterEqual(tracker.clear_invocations, 1)
            self.assertEqual(len(broker.submitted_orders), 1)
            order = broker.submitted_orders[0]
            self.assertIsNotNone(order.client_order_id)


if __name__ == "__main__":
    unittest.main()
