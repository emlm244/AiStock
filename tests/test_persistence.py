import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

if 'aistock' not in sys.modules:
    pkg = types.ModuleType('aistock')
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / 'aistock')]
    sys.modules['aistock'] = pkg

portfolio_module = import_module('aistock.portfolio')
persistence_module = import_module('aistock.persistence')
risk_module = import_module('aistock.risk')

Portfolio = portfolio_module.Portfolio
Position = portfolio_module.Position

save_portfolio_snapshot = persistence_module.save_portfolio_snapshot
load_portfolio_snapshot = persistence_module.load_portfolio_snapshot
save_risk_state = persistence_module.save_risk_state
load_risk_state = persistence_module.load_risk_state
save_checkpoint = persistence_module.save_checkpoint
load_checkpoint = persistence_module.load_checkpoint

RiskState = risk_module.RiskState


class PersistenceTests(unittest.TestCase):
    def test_portfolio_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            portfolio = Portfolio(cash=Decimal('50000'))
            portfolio.positions['AAPL'] = Position(
                symbol='AAPL',
                quantity=Decimal('100'),
                average_price=Decimal('150.50'),
                entry_time_utc=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            )
            portfolio.realised_pnl = Decimal('1500')
            portfolio.commissions_paid = Decimal('10')

            path = f'{tmpdir}/portfolio.json'
            save_portfolio_snapshot(portfolio, path)

            restored = load_portfolio_snapshot(path)
            self.assertEqual(restored.cash, Decimal('50000'))
            self.assertIn('AAPL', restored.positions)
            self.assertEqual(restored.positions['AAPL'].quantity, Decimal('100'))
            self.assertEqual(restored.realised_pnl, Decimal('1500'))

    def test_risk_state_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            risk_state = RiskState(
                last_reset_date='2024-07-09',  # String ISO format
                daily_pnl=Decimal('-500'),
                peak_equity=Decimal('102000'),
                start_of_day_equity=Decimal('100000'),
                halted=True,
                halt_reason='Daily loss limit breached',
            )

            path = f'{tmpdir}/risk_state.json'
            save_risk_state(risk_state, path)

            restored = load_risk_state(path)
            self.assertEqual(restored.last_reset_date, '2024-07-09')
            self.assertEqual(restored.daily_pnl, Decimal('-500'))
            self.assertTrue(restored.halted)
            self.assertEqual(restored.halt_reason, 'Daily loss limit breached')

    def test_full_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            portfolio = Portfolio(cash=Decimal('75000'))
            risk_state = RiskState(
                last_reset_date='2024-07-09',  # String ISO format
                daily_pnl=Decimal('1000'),
                peak_equity=Decimal('76000'),
                start_of_day_equity=Decimal('75000'),
            )

            save_checkpoint(portfolio, risk_state, tmpdir)

            restored_portfolio, restored_risk = load_checkpoint(tmpdir)
            self.assertEqual(restored_portfolio.cash, Decimal('75000'))
            self.assertEqual(restored_risk.daily_pnl, Decimal('1000'))


if __name__ == '__main__':
    unittest.main()
