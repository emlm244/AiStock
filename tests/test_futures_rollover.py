"""
Tests for futures contract rollover system.

Coverage for:
- FuturesContractSpec dataclass
- ContractValidationResult
- RolloverConfig and validation
- RolloverManager lifecycle
- FuturesPreflightChecker
- Symbol mapping persistence
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aistock.config import ContractSpec
from aistock.futures.contracts import FuturesContractSpec, SymbolMapping
from aistock.futures.preflight import FuturesPreflightChecker, PreflightResult
from aistock.futures.rollover import (
    RolloverConfig,
    RolloverEvent,
    RolloverManager,
    RolloverStatus,
)

# ==================== FuturesContractSpec Tests ====================


class TestFuturesContractSpec:
    """Tests for FuturesContractSpec dataclass."""

    def test_creation_with_defaults(self) -> None:
        """Test creating spec with minimal fields."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )
        assert spec.symbol == 'ESH26'
        assert spec.sec_type == 'FUT'
        assert spec.exchange == 'CME'
        assert spec.multiplier == 50
        assert spec.expiration_date is None
        assert spec.con_id is None

    def test_creation_with_expiration(self) -> None:
        """Test creating spec with expiration date."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
            con_id=123456,
            underlying='ES',
        )
        assert spec.expiration_date == '20260320'
        assert spec.con_id == 123456
        assert spec.underlying == 'ES'

    def test_days_to_expiry_future_date(self) -> None:
        """Test days_to_expiry with future expiration."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
        )
        # Test with fixed reference date
        days = spec.days_to_expiry(reference_date=date(2026, 3, 10))
        assert days == 10

    def test_days_to_expiry_past_date(self) -> None:
        """Test days_to_expiry with expired contract."""
        spec = FuturesContractSpec(
            symbol='ESZ25',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20251219',
        )
        days = spec.days_to_expiry(reference_date=date(2025, 12, 25))
        assert days == -6

    def test_days_to_expiry_no_expiration(self) -> None:
        """Test days_to_expiry when expiration not set."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )
        assert spec.days_to_expiry() is None

    def test_is_expired(self) -> None:
        """Test is_expired check."""
        spec = FuturesContractSpec(
            symbol='ESZ25',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20251219',
        )
        assert spec.is_expired(reference_date=date(2025, 12, 25))
        assert not spec.is_expired(reference_date=date(2025, 12, 15))

    def test_is_near_expiry(self) -> None:
        """Test is_near_expiry within rollover window."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
        )
        # 5 days before expiry - should be near
        assert spec.is_near_expiry(threshold_days=7, reference_date=date(2026, 3, 15))
        # 20 days before expiry - should not be near
        assert not spec.is_near_expiry(threshold_days=7, reference_date=date(2026, 3, 1))

    def test_missing_multiplier_raises(self) -> None:
        """Test that FUT without multiplier raises error."""
        with pytest.raises(ValueError, match='requires multiplier'):
            FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
            )

    def test_stock_without_multiplier_ok(self) -> None:
        """Test that STK without multiplier is allowed."""
        spec = FuturesContractSpec(
            symbol='AAPL',
            sec_type='STK',
            exchange='SMART',
        )
        assert spec.multiplier is None


# ==================== RolloverConfig Tests ====================


class TestRolloverConfig:
    """Tests for RolloverConfig validation."""

    def test_default_values(self) -> None:
        """Test default config values."""
        config = RolloverConfig()
        assert config.warn_days_before_expiry == 7
        assert config.auto_detect_front_month is True
        assert config.persist_mappings is True

    def test_validate_valid_config(self) -> None:
        """Test validation passes with valid config."""
        config = RolloverConfig(warn_days_before_expiry=5)
        config.validate()  # Should not raise

    def test_validate_invalid_warn_days(self) -> None:
        """Test validation fails with invalid warn_days."""
        config = RolloverConfig(warn_days_before_expiry=0)
        with pytest.raises(ValueError, match='warn_days_before_expiry must be >= 1'):
            config.validate()


# ==================== RolloverManager Tests ====================


class TestRolloverManager:
    """Tests for RolloverManager."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> RolloverManager:
        """Create RolloverManager with temp directory."""
        config = RolloverConfig(
            warn_days_before_expiry=7,
            persist_mappings=True,
            mappings_path=str(tmp_path / 'mappings.json'),
        )
        return RolloverManager(config, state_dir=str(tmp_path))

    def test_register_mapping(self, manager: RolloverManager) -> None:
        """Test registering a symbol mapping."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
        )

        manager.register_mapping('ES', spec, is_front_month=True)

        retrieved = manager.get_contract('ES')
        assert retrieved is not None
        assert retrieved.symbol == 'ESH26'

    def test_get_contract_case_insensitive(self, manager: RolloverManager) -> None:
        """Test get_contract is case insensitive."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )
        manager.register_mapping('es', spec)

        assert manager.get_contract('ES') is not None
        assert manager.get_contract('es') is not None
        assert manager.get_contract('Es') is not None

    def test_check_rollover_needed_no_alerts(self, manager: RolloverManager) -> None:
        """Test no alerts when contracts far from expiry."""
        contracts = {
            'ESH26': FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20260320',
            ),
        }

        # Use patch on the spec method to return days far from expiry
        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=50):
            alerts = manager.check_rollover_needed(contracts)

        # 50 days > 7 day threshold, so no alerts
        assert len(alerts) == 0

    def test_check_rollover_needed_with_alert(self, manager: RolloverManager) -> None:
        """Test alert when contract near expiry."""
        # Create contract that expires in 5 days from a fixed reference date
        contracts = {
            'ESH26': FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20260320',
            ),
        }

        # Patch datetime to simulate being 5 days before expiry
        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=5):
            alerts = manager.check_rollover_needed(contracts)

        assert len(alerts) == 1
        assert alerts[0]['symbol'] == 'ESH26'
        assert alerts[0]['days_to_expiry'] == 5
        assert alerts[0]['urgency'] == 'warning'

    def test_check_rollover_critical_urgency(self, manager: RolloverManager) -> None:
        """Test critical urgency when contract expires in <= 2 days."""
        contracts = {
            'ESH26': FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20260320',
            ),
        }

        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=2):
            alerts = manager.check_rollover_needed(contracts)

        assert len(alerts) == 1
        assert alerts[0]['urgency'] == 'critical'

    def test_generate_rollover_orders_long_position(self, manager: RolloverManager) -> None:
        """Test generating rollover orders for long position."""
        # Register current contract
        current_spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )
        manager.register_mapping('ESH26', current_spec)

        # Next contract
        next_spec = FuturesContractSpec(
            symbol='ESM26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260619',
        )

        # Mock portfolio with long position
        portfolio = MagicMock()
        position = MagicMock()
        position.quantity = Decimal('10')
        portfolio.position.return_value = position

        close_order, open_order = manager.generate_rollover_orders('ESH26', next_spec, portfolio)

        assert close_order is not None
        assert close_order['side'] == 'SELL'
        assert close_order['quantity'] == '10'

        assert open_order is not None
        assert open_order['side'] == 'BUY'
        assert open_order['symbol'] == 'ESM26'

    def test_generate_rollover_orders_short_position(self, manager: RolloverManager) -> None:
        """Test generating rollover orders for short position."""
        current_spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )
        manager.register_mapping('ESH26', current_spec)

        next_spec = FuturesContractSpec(
            symbol='ESM26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )

        # Mock portfolio with short position
        portfolio = MagicMock()
        position = MagicMock()
        position.quantity = Decimal('-5')
        portfolio.position.return_value = position

        close_order, open_order = manager.generate_rollover_orders('ESH26', next_spec, portfolio)

        assert close_order is not None
        assert close_order['side'] == 'BUY'  # Buy to cover short
        assert close_order['quantity'] == '5'

        assert open_order is not None
        assert open_order['side'] == 'SELL'  # Re-establish short

    def test_generate_rollover_orders_no_position(self, manager: RolloverManager) -> None:
        """Test no orders when no position."""
        next_spec = FuturesContractSpec(
            symbol='ESM26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )

        portfolio = MagicMock()
        position = MagicMock()
        position.quantity = Decimal('0')
        portfolio.position.return_value = position

        close_order, open_order = manager.generate_rollover_orders('ESH26', next_spec, portfolio)

        assert close_order is None
        assert open_order is None

    def test_mappings_persistence(self, tmp_path: Path) -> None:
        """Test that mappings are persisted and loaded."""
        mappings_path = str(tmp_path / 'mappings.json')

        # Create first manager and register mapping
        config1 = RolloverConfig(mappings_path=mappings_path)
        manager1 = RolloverManager(config1, state_dir=str(tmp_path))

        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
        )
        manager1.register_mapping('ES', spec)

        # Create new manager with same path - should load mapping
        config2 = RolloverConfig(mappings_path=mappings_path)
        manager2 = RolloverManager(config2, state_dir=str(tmp_path))

        retrieved = manager2.get_contract('ES')
        assert retrieved is not None
        assert retrieved.symbol == 'ESH26'

    def test_create_rollover_event(self, manager: RolloverManager) -> None:
        """Test creating rollover event for audit."""
        event = manager.create_rollover_event(
            logical_symbol='ES',
            from_contract='ESH26',
            to_contract='ESM26',
            position_quantity=Decimal('10'),
        )

        assert event.event_id is not None
        assert event.logical_symbol == 'ES'
        assert event.from_contract == 'ESH26'
        assert event.to_contract == 'ESM26'
        assert event.position_quantity == Decimal('10')
        assert event.status == RolloverStatus.PENDING


# ==================== FuturesPreflightChecker Tests ====================


class TestFuturesPreflightChecker:
    """Tests for FuturesPreflightChecker."""

    def test_preflight_passes_no_futures(self) -> None:
        """Test preflight passes when no futures contracts."""
        checker = FuturesPreflightChecker()
        # Using FuturesContractSpec with STK to filter out as non-futures
        contracts: dict[str, FuturesContractSpec | ContractSpec] = {}
        result = checker.run_preflight(None, contracts)
        assert result.passed
        assert len(result.errors) == 0

    def test_preflight_passes_stocks_only(self) -> None:
        """Test preflight passes with only stock contracts."""
        checker = FuturesPreflightChecker()
        # Create as FuturesContractSpec but with STK type
        contracts: dict[str, FuturesContractSpec | ContractSpec] = {
            'AAPL': FuturesContractSpec(symbol='AAPL', sec_type='STK', exchange='SMART'),
            'MSFT': FuturesContractSpec(symbol='MSFT', sec_type='STK', exchange='SMART'),
        }
        result = checker.run_preflight(None, contracts)
        assert result.passed
        assert len(result.errors) == 0

    def test_preflight_passes_valid_contract(self) -> None:
        """Test preflight passes with valid futures contract."""
        checker = FuturesPreflightChecker(warn_threshold_days=7)

        contracts = {
            'ESH26': FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20260320',
            ),
        }

        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=30):
            result = checker.run_preflight(None, contracts)

        assert result.passed
        assert len(result.errors) == 0

    def test_preflight_fails_expired_contract(self) -> None:
        """Test preflight fails with expired contract."""
        checker = FuturesPreflightChecker(block_on_expired=True)

        contracts = {
            'ESZ25': FuturesContractSpec(
                symbol='ESZ25',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20251219',
            ),
        }

        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=-5):
            result = checker.run_preflight(None, contracts)

        assert not result.passed
        assert len(result.errors) == 1
        assert 'expired' in result.errors[0].lower()

    def test_preflight_warns_near_expiry(self) -> None:
        """Test preflight warns when contract near expiry."""
        checker = FuturesPreflightChecker(warn_threshold_days=7)

        contracts = {
            'ESH26': FuturesContractSpec(
                symbol='ESH26',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20260320',
            ),
        }

        from unittest.mock import patch

        # Patch the validator's _calculate_days_to_expiry to return 5 days
        with patch.object(checker._validator, '_calculate_days_to_expiry', return_value=5):
            result = checker.run_preflight(None, contracts)

        assert result.passed  # Still passes, just warnings
        assert len(result.warnings) == 1
        assert 'rollover' in result.warnings[0].lower()

    def test_preflight_does_not_block_when_disabled(self) -> None:
        """Test preflight does not block when block_on_expired=False."""
        checker = FuturesPreflightChecker(block_on_expired=False)

        contracts = {
            'ESZ25': FuturesContractSpec(
                symbol='ESZ25',
                sec_type='FUT',
                exchange='CME',
                multiplier=50,
                expiration_date='20251219',
            ),
        }

        from unittest.mock import patch

        with patch.object(FuturesContractSpec, 'days_to_expiry', return_value=-5):
            result = checker.run_preflight(None, contracts)

        # Should pass because blocking is disabled
        assert result.passed
        # But error should be in warnings
        assert len(result.warnings) >= 1


# ==================== SymbolMapping Tests ====================


class TestSymbolMapping:
    """Tests for SymbolMapping dataclass."""

    def test_creation(self) -> None:
        """Test creating a symbol mapping."""
        spec = FuturesContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
        )

        mapping = SymbolMapping(
            logical_symbol='ES',
            actual_contract='ESH26',
            contract_spec=spec,
            is_front_month=True,
        )

        assert mapping.logical_symbol == 'ES'
        assert mapping.actual_contract == 'ESH26'
        assert mapping.is_front_month is True
        assert mapping.updated_at is not None


# ==================== ContractSpec Extension Tests ====================


class TestContractSpecExtension:
    """Tests for ContractSpec with new fields."""

    def test_contract_spec_with_expiration(self) -> None:
        """Test ContractSpec can hold expiration fields."""
        spec = ContractSpec(
            symbol='ESH26',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',
            con_id=123456,
            underlying='ES',
        )

        assert spec.expiration_date == '20260320'
        assert spec.con_id == 123456
        assert spec.underlying == 'ES'

    def test_contract_spec_defaults(self) -> None:
        """Test ContractSpec defaults for new fields."""
        spec = ContractSpec(
            symbol='AAPL',
            sec_type='STK',
            exchange='SMART',
        )

        assert spec.expiration_date is None
        assert spec.con_id is None
        assert spec.underlying is None
