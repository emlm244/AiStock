# ai_controller/mode_manager.py

"""
Mode Manager - Controls Parameter Modification Permissions

Enforces the two-mode system:
- Autonomous Mode: AI can modify most parameters (except safety limits)
- Expert Mode: User controls everything, AI cannot modify anything
"""

import logging
from typing import Tuple, Any, List
from datetime import datetime
from enum import Enum


class TradingMode(Enum):
    """Trading mode types"""
    AUTONOMOUS = "autonomous"
    EXPERT = "expert"


class ModeManager:
    """
    Manages trading mode and parameter modification permissions

    In Autonomous mode: AI can optimize parameters within safe bounds
    In Expert mode: All parameters are locked, no AI modifications allowed
    """

    # Parameters that can NEVER be modified by AI (safety-critical)
    PROTECTED_PARAMETERS = {
        'MAX_DAILY_LOSS',
        'MAX_DRAWDOWN_LIMIT',
        'TOTAL_CAPITAL',
        'TRADING_MODE_TYPE',  # Can't change mode programmatically
    }

    # Parameters that can be modified in Autonomous mode
    MODIFIABLE_IN_AUTONOMOUS = {
        'RISK_PER_TRADE',
        'STOP_LOSS_ATR_MULTIPLIER',
        'TAKE_PROFIT_RR_RATIO',
        'TAKE_PROFIT_ATR_MULTIPLIER',
        'RSI_PERIOD',
        'RSI_OVERBOUGHT',
        'RSI_OVERSOLD',
        'ATR_PERIOD',
        'MOVING_AVERAGE_PERIODS',
        'MACD_SETTINGS',
        'MOMENTUM_PRICE_CHANGE_THRESHOLD',
        'MOMENTUM_VOLUME_MULTIPLIER',
        'ADX_PERIOD',
        'BBANDS_PERIOD',
        'ENABLED_STRATEGIES',
        'ML_CONFIDENCE_THRESHOLD',
    }

    def __init__(self, settings, logger=None):
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

        # Determine current mode
        self.current_mode = self._determine_mode()

        # Track parameter changes
        self.parameter_change_history = []

        self.logger.info(f"Mode Manager initialized in {self.current_mode.value} mode")

    def _determine_mode(self) -> TradingMode:
        """Determine current trading mode from settings"""
        mode_str = getattr(self.settings, 'TRADING_MODE_TYPE', 'autonomous').lower()

        if mode_str == 'expert':
            return TradingMode.EXPERT
        else:
            return TradingMode.AUTONOMOUS

    def get_current_mode(self) -> TradingMode:
        """Get the current trading mode"""
        return self.current_mode

    def can_modify_parameter(self, param_name: str) -> bool:
        """
        Check if a parameter can be modified by AI in current mode

        Args:
            param_name: Name of the parameter to check

        Returns:
            True if parameter can be modified, False otherwise
        """
        # Protected parameters can NEVER be modified
        if param_name in self.PROTECTED_PARAMETERS:
            return False

        # In Expert mode, NOTHING can be modified by AI
        if self.current_mode == TradingMode.EXPERT:
            return False

        # In Autonomous mode, check if parameter is in modifiable list
        if self.current_mode == TradingMode.AUTONOMOUS:
            return param_name in self.MODIFIABLE_IN_AUTONOMOUS

        return False

    def validate_parameter_change(
        self,
        param_name: str,
        new_value: Any,
        reason: str = ""
    ) -> Tuple[bool, str]:
        """
        Validate if a parameter change is allowed and safe

        Args:
            param_name: Name of the parameter
            new_value: Proposed new value
            reason: Reason for the change (for logging)

        Returns:
            Tuple of (is_valid, message)
        """
        # Check if modification is allowed in current mode
        if not self.can_modify_parameter(param_name):
            msg = f"Parameter '{param_name}' cannot be modified in {self.current_mode.value} mode"
            return False, msg

        # Validate the value is within safe bounds
        is_valid, validation_msg = self._validate_value_bounds(param_name, new_value)
        if not is_valid:
            return False, validation_msg

        # All checks passed
        return True, "Parameter change validated"

    def _validate_value_bounds(self, param_name: str, value: Any) -> Tuple[bool, str]:
        """Validate that a parameter value is within acceptable bounds"""

        # Define bounds for key parameters
        bounds = {
            'RISK_PER_TRADE': (0.001, 0.05),  # 0.1% to 5%
            'STOP_LOSS_ATR_MULTIPLIER': (0.5, 10.0),
            'TAKE_PROFIT_RR_RATIO': (1.0, 10.0),
            'TAKE_PROFIT_ATR_MULTIPLIER': (1.0, 20.0),
            'RSI_PERIOD': (5, 50),
            'RSI_OVERBOUGHT': (60, 90),
            'RSI_OVERSOLD': (10, 40),
            'ATR_PERIOD': (5, 50),
            'ML_CONFIDENCE_THRESHOLD': (0.5, 0.95),
        }

        # Check if parameter has defined bounds
        if param_name in bounds:
            min_val, max_val = bounds[param_name]

            try:
                numeric_value = float(value)
                if numeric_value < min_val or numeric_value > max_val:
                    return False, f"Value {value} outside acceptable range [{min_val}, {max_val}]"
            except (ValueError, TypeError):
                return False, f"Invalid numeric value: {value}"

        # Special validation for dict parameters
        if param_name == 'MOVING_AVERAGE_PERIODS':
            if not isinstance(value, dict):
                return False, "MOVING_AVERAGE_PERIODS must be a dictionary"
            if 'short_term' not in value or 'long_term' not in value:
                return False, "MOVING_AVERAGE_PERIODS must have 'short_term' and 'long_term' keys"
            if value['short_term'] >= value['long_term']:
                return False, "Short-term MA period must be less than long-term"

        if param_name == 'ENABLED_STRATEGIES':
            if not isinstance(value, dict):
                return False, "ENABLED_STRATEGIES must be a dictionary"
            # Ensure at least one strategy is enabled
            if not any(value.values()):
                return False, "At least one strategy must be enabled"

        return True, "Value is within acceptable bounds"

    def apply_parameter_change(
        self,
        param_name: str,
        new_value: Any,
        changed_by: str = "AI",
        reason: str = ""
    ) -> bool:
        """
        Apply a parameter change if validation passes

        Args:
            param_name: Name of the parameter
            new_value: New value to set
            changed_by: Who/what is making the change
            reason: Reason for the change

        Returns:
            True if change was applied, False otherwise
        """
        # Validate the change
        is_valid, msg = self.validate_parameter_change(param_name, new_value, reason)

        if not is_valid:
            self.logger.warning(f"Parameter change rejected: {msg}")
            return False

        # Get old value for logging
        old_value = getattr(self.settings, param_name, None)

        # Apply the change
        try:
            setattr(self.settings, param_name, new_value)

            # Log the change
            change_record = {
                'timestamp': datetime.now(),
                'parameter': param_name,
                'old_value': old_value,
                'new_value': new_value,
                'changed_by': changed_by,
                'reason': reason,
                'mode': self.current_mode.value
            }
            self.parameter_change_history.append(change_record)

            self.logger.info(
                f"Parameter changed: {param_name} = {new_value} "
                f"(was {old_value}) by {changed_by}. Reason: {reason}"
            )

            return True

        except Exception as e:
            self.logger.error(f"Failed to apply parameter change: {e}")
            return False

    def apply_parameter_batch(
        self,
        param_updates: dict,
        changed_by: str = "AI",
        reason: str = ""
    ) -> Tuple[int, int, List[str]]:
        """
        Apply a batch of parameter changes

        Args:
            param_updates: Dictionary of {param_name: new_value}
            changed_by: Who/what is making the changes
            reason: Reason for the changes

        Returns:
            Tuple of (success_count, failed_count, failed_params)
        """
        success_count = 0
        failed_count = 0
        failed_params = []

        for param_name, new_value in param_updates.items():
            if self.apply_parameter_change(param_name, new_value, changed_by, reason):
                success_count += 1
            else:
                failed_count += 1
                failed_params.append(param_name)

        self.logger.info(
            f"Batch parameter update: {success_count} succeeded, "
            f"{failed_count} failed. Failed params: {failed_params}"
        )

        return success_count, failed_count, failed_params

    def get_modifiable_parameters(self) -> List[str]:
        """Get list of parameters that can be modified in current mode"""
        if self.current_mode == TradingMode.EXPERT:
            return []
        elif self.current_mode == TradingMode.AUTONOMOUS:
            return list(self.MODIFIABLE_IN_AUTONOMOUS)
        return []

    def get_parameter_change_history(self, limit: int = 100) -> List[dict]:
        """Get recent parameter change history"""
        return self.parameter_change_history[-limit:]

    def set_mode(self, new_mode: TradingMode, reason: str = "") -> bool:
        """
        Change the trading mode (use with caution)

        Args:
            new_mode: New trading mode to set
            reason: Reason for mode change

        Returns:
            True if mode was changed successfully
        """
        old_mode = self.current_mode

        if old_mode == new_mode:
            self.logger.info(f"Already in {new_mode.value} mode")
            return True

        self.current_mode = new_mode

        self.logger.warning(
            f"Trading mode changed from {old_mode.value} to {new_mode.value}. "
            f"Reason: {reason}"
        )

        # Update settings
        self.settings.TRADING_MODE_TYPE = new_mode.value

        return True
