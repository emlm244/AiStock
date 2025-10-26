import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.agent import AdaptiveAgent, AssetClassPolicy, ObjectiveThresholds
from aistock.config import (
    BacktestConfig,
    BrokerConfig,
    DataSource,
    EngineConfig,
    RiskLimits,
    StrategyConfig,
    ContractSpec,
)
from aistock.session import LiveTradingSession


def _write_trending_series(path: str, bars: int = 200) -> None:
    start_time = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    price = 100.0
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for idx in range(bars):
            ts = start_time + timedelta(minutes=idx)
            open_price = price
            close_price = price + 0.5
            row = [
                ts.isoformat(),
                f"{open_price:.2f}",
                f"{close_price + 0.1:.2f}",
                f"{open_price - 0.1:.2f}",
                f"{close_price:.2f}",
                "10000",
            ]
            writer.writerow(row)
            price = close_price


class AdaptiveAgentTests(unittest.TestCase):
    def test_agent_adjusts_strategy_after_poor_performance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = f"{tmpdir}/AAPL.csv"
            _write_trending_series(data_path)

            training_config = BacktestConfig(
                data=DataSource(
                    path=tmpdir,
                    symbols=["AAPL"],
                    warmup_bars=20,
                    enforce_trading_hours=False,
                ),
                engine=EngineConfig(
                    strategy=StrategyConfig(short_window=3, long_window=6, ml_enabled=False),
                    risk=RiskLimits(
                        max_position_fraction=0.25,
                        per_symbol_notional_cap=100_000,
                        max_single_position_units=1_000_000,
                    ),
                ),
            )

            live_config = BacktestConfig(
                data=DataSource(
                    path=tmpdir,
                    symbols=["AAPL"],
                    warmup_bars=20,
                    enforce_trading_hours=False,
                ),
                engine=EngineConfig(
                    strategy=StrategyConfig(short_window=3, long_window=6, ml_enabled=False),
                    risk=RiskLimits(
                        max_position_fraction=0.25,
                        per_symbol_notional_cap=100_000,
                        max_single_position_units=1_000_000,
                    ),
                ),
                broker=BrokerConfig(backend="paper"),
            )

            session = LiveTradingSession(live_config, enable_checkpointing=False)

            with session._lock:  # simulate a losing streak
                session.trade_log.clear()
                timestamp = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
                for idx in range(30):
                    pnl = -5.0 if idx % 3 else 1.0
                    session.trade_log.append(
                        {
                            "timestamp": timestamp + timedelta(minutes=idx),
                            "symbol": "AAPL",
                            "quantity": 1.0,
                            "price": 100.0 + idx,
                            "realised_pnl": pnl,
                        }
                    )
                session.equity_curve = [
                    (timestamp + timedelta(minutes=idx), Decimal(str(100_000 - idx * 50)))
                    for idx in range(30)
                ]
                session._last_equity = Decimal("98500")
                session.risk.state.daily_pnl = Decimal("-1500")
                session.risk.state.start_of_day_equity = Decimal("100000")
                session.risk.state.peak_equity = Decimal("102000")

            agent = AdaptiveAgent(
                training_config=training_config,
                objectives=ObjectiveThresholds(
                    min_sharpe=0.6,
                    max_drawdown=0.25,
                    min_win_rate=0.4,
                    min_trades=10,
                    max_equity_pullback_pct=0.02,
                    max_position_fraction_cap=0.2,
                    max_daily_loss_pct=0.02,
                    max_weekly_loss_pct=0.03,
                ),
            )

            decision = agent.evaluate_and_adapt(session)

            self.assertIsNotNone(decision)
            self.assertGreaterEqual(decision.simulation.win_rate, 0.4)
            self.assertNotEqual(
                decision.applied_config.engine.strategy.long_window,
                live_config.engine.strategy.long_window,
            )
        self.assertLessEqual(
            decision.applied_config.engine.risk.max_position_fraction,
            live_config.engine.risk.max_position_fraction,
        )
        self.assertTrue(session.config.engine.strategy.ml_enabled)

    def test_asset_policy_tightens_crypto_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = f"{tmpdir}/BTC.csv"
            _write_trending_series(data_path)

            training_config = BacktestConfig(
                data=DataSource(
                    path=tmpdir,
                    symbols=["BTC"],
                    warmup_bars=20,
                    enforce_trading_hours=False,
                ),
                engine=EngineConfig(
                    strategy=StrategyConfig(short_window=3, long_window=6, ml_enabled=False),
                    risk=RiskLimits(
                        max_position_fraction=0.25,
                        per_symbol_notional_cap=100_000,
                        max_single_position_units=1_000_000,
                    ),
                ),
            )

            live_config = BacktestConfig(
                data=DataSource(
                    path=tmpdir,
                    symbols=["BTC"],
                    warmup_bars=20,
                    enforce_trading_hours=False,
                ),
                engine=EngineConfig(
                    strategy=StrategyConfig(short_window=3, long_window=6, ml_enabled=False),
                    risk=RiskLimits(
                        max_position_fraction=0.25,
                        per_symbol_notional_cap=100_000,
                        max_single_position_units=1_000_000,
                    ),
                ),
                broker=BrokerConfig(
                    backend="paper",
                    contracts={
                        "BTC": ContractSpec(
                            symbol="BTC",
                            sec_type="CRYPTO",
                            exchange="COINBASE",
                            currency="USD",
                        )
                    },
                ),
            )

            session = LiveTradingSession(live_config, enable_checkpointing=False)

            with session._lock:
                session.trade_log.clear()
                timestamp = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
                for idx in range(20):
                    pnl = -3.0 if idx % 2 == 0 else 1.0
                    session.trade_log.append(
                        {
                            "timestamp": timestamp + timedelta(minutes=idx),
                            "symbol": "BTC",
                            "quantity": 0.5,
                            "price": 100.0 + idx,
                            "realised_pnl": pnl,
                        }
                    )
                session.equity_curve = [
                    (timestamp + timedelta(minutes=idx), Decimal(str(100_000 - idx * 30)))
                    for idx in range(20)
                ]
                session._last_equity = Decimal("99400")
                session.risk.state.daily_pnl = Decimal("-800")
                session.risk.state.start_of_day_equity = Decimal("100000")
                session.risk.state.peak_equity = Decimal("101500")

            policies = {
                "CRYPTO": AssetClassPolicy(
                    sec_type="CRYPTO",
                    exchange="PAXOS",
                    currency="USD",
                    max_position_fraction=0.1,
                    per_symbol_cap=50_000,
                )
            }

            agent = AdaptiveAgent(
                training_config=training_config,
                objectives=ObjectiveThresholds(
                    min_sharpe=0.5,
                    max_drawdown=0.3,
                    min_win_rate=0.35,
                    min_trades=10,
                    max_equity_pullback_pct=0.03,
                    max_position_fraction_cap=0.2,
                ),
                asset_policies=policies,
            )

            decision = agent.evaluate_and_adapt(session)
            self.assertIsNotNone(decision)
            contract = session.config.broker.contracts["BTC"]
            self.assertEqual(contract.exchange, "PAXOS")
            self.assertLessEqual(
                session.config.engine.risk.max_position_fraction,
                0.1,
            )
            self.assertLessEqual(
                session.config.engine.risk.per_symbol_notional_cap,
                50_000,
            )


if __name__ == "__main__":
    unittest.main()
