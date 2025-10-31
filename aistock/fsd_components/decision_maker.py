"""Decision making logic for FSD."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..fsd import FSDConfig, RLAgent, SymbolStats
    from ..professional import ProfessionalSafeguards


class DecisionMaker:
    """Makes trading decisions based on RL agent and safeguards.

    Responsibilities:
    - Get action from RL agent
    - Apply confidence adjustments
    - Check safeguards
    - Apply position sizing
    - Check parallel trading limits
    """

    def __init__(
        self,
        rl_agent: RLAgent,
        config: FSDConfig,
        current_positions: dict[str, Decimal],
        symbol_performance: dict[str, SymbolStats],
        safeguards: ProfessionalSafeguards | None = None,
    ):
        self.rl_agent = rl_agent
        self.config = config
        self.current_positions = current_positions
        self.symbol_performance = symbol_performance
        self.safeguards = safeguards

        self.logger = logging.getLogger(__name__)

    def make_decision(
        self,
        state: dict[str, Any],
        symbol: str,
        bars: list[Any],
        edge_case_result: dict[str, Any] | None = None,
        timeframe_divergence: bool = False,
    ) -> dict[str, Any]:
        """Make a trading decision."""
        # Get RL action
        action_type = self.rl_agent.select_action(state, training=True)
        base_confidence = self.rl_agent.get_confidence(state, action_type)

        # Apply adjustments
        adjusted_confidence = base_confidence
        safeguard_adjustment = 0.0
        safeguard_multiplier = 1.0
        warnings: list[str] = []

        # Edge case adjustments
        edge_case_multiplier = 1.0
        if edge_case_result and not edge_case_result.get('blocked'):
            adjusted_confidence += edge_case_result.get('confidence_adjustment', 0.0)
            edge_case_multiplier = edge_case_result.get('position_multiplier', 1.0)
            warnings.extend(edge_case_result.get('warnings', []))

        # Safeguard checks
        if self.safeguards:
            safeguard_result = self.safeguards.check_trading_allowed(
                symbol=symbol,
                bars=bars,
                current_time=datetime.now(),
                timeframe_divergence=timeframe_divergence,
            )

            if not safeguard_result.allowed:
                return {
                    'should_trade': False,
                    'action': {'trade': False},
                    'confidence': 0.0,
                    'state': state,
                    'reason': f'safeguards_blocked: {safeguard_result.reason}',
                    'warnings': safeguard_result.warnings,
                }

            safeguard_adjustment = safeguard_result.confidence_adjustment
            safeguard_multiplier = safeguard_result.position_size_multiplier
            warnings.extend(safeguard_result.warnings)

        adjusted_confidence += safeguard_adjustment

        # Per-symbol adaptive confidence
        if self.config.enable_per_symbol_params and symbol in self.symbol_performance:
            perf = self.symbol_performance[symbol]
            if perf['trades'] >= 3:
                win_rate = perf['wins'] / perf['trades']
                avg_pnl = perf['total_pnl'] / perf['trades']

                if win_rate > 0.6 and avg_pnl > 0:
                    perf['confidence_adj'] = min(0.15, perf['confidence_adj'] + 0.02)
                elif win_rate < 0.4 or avg_pnl < 0:
                    perf['confidence_adj'] = max(-0.15, perf['confidence_adj'] - 0.02)

                adjusted_confidence += perf['confidence_adj']

        # Clamp confidence
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        # Volatility bias
        volatility_bias = getattr(self.config, 'volatility_bias', 'balanced')
        bias_adjustment = 0.0
        if volatility_bias == 'high':
            if state.get('volatility') == 'high':
                adjusted_confidence = min(1.0, adjusted_confidence + 0.08)
            elif state.get('volatility') == 'low':
                adjusted_confidence *= 0.9
            bias_adjustment = adjusted_confidence - base_confidence
        elif volatility_bias == 'low':
            if state.get('volatility') == 'high':
                adjusted_confidence *= 0.75
            elif state.get('volatility') == 'low':
                adjusted_confidence = min(1.0, adjusted_confidence + 0.05)
            bias_adjustment = adjusted_confidence - base_confidence

        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        # Check threshold
        threshold = self.config.min_confidence_threshold

        # Check if should trade
        should_trade = action_type in ['BUY', 'SELL', 'INCREASE_SIZE', 'DECREASE_SIZE']

        if not should_trade or adjusted_confidence < threshold:
            reason = 'hold_action' if not should_trade else f'confidence_too_low ({adjusted_confidence:.2f} < {threshold:.2f})'
            return {
                'should_trade': False,
                'action': {'trade': False},
                'confidence': adjusted_confidence,
                'state': state,
                'reason': reason,
                'confidence_breakdown': {
                    'base': base_confidence,
                    'adjusted': adjusted_confidence,
                    'threshold': threshold,
                    'safeguard_adjustment': safeguard_adjustment,
                    'volatility_bias': volatility_bias,
                    'bias_adjustment': bias_adjustment,
                },
            }

        # Calculate size
        max_fraction = max(0.0, min(self.config.max_capital_per_position, 1.0))

        if action_type == 'BUY':
            size_fraction = adjusted_confidence * max_fraction
            trade_signal = 1
        elif action_type == 'SELL':
            size_fraction = adjusted_confidence * max_fraction
            trade_signal = -1
        elif action_type == 'INCREASE_SIZE':
            size_fraction = adjusted_confidence * max_fraction * 0.5
            trade_signal = 1
        elif action_type == 'DECREASE_SIZE':
            size_fraction = adjusted_confidence * max_fraction * 0.5
            trade_signal = -1
        else:
            size_fraction = 0.0
            trade_signal = 0

        # Apply multipliers
        size_fraction *= safeguard_multiplier
        size_fraction *= edge_case_multiplier

        return {
            'should_trade': True,
            'action': {
                'trade': True,
                'type': action_type,
                'size_fraction': size_fraction,
                'signal': trade_signal,
            },
            'confidence': adjusted_confidence,
            'state': state,
            'reason': 'trade_approved',
            'confidence_breakdown': {
                'base': base_confidence,
                'adjusted': adjusted_confidence,
                'threshold': threshold,
                'safeguard_adjustment': safeguard_adjustment,
                'volatility_bias': volatility_bias,
                'bias_adjustment': bias_adjustment,
            },
            'warnings': warnings,
        }

    def check_parallel_limits(self, symbol: str) -> dict[str, Any] | None:
        """Check if parallel trading limits allow new position."""
        num_positions = len([pos for pos in self.current_positions.values() if abs(pos) > Decimal('0.01')])

        if num_positions >= self.config.max_concurrent_positions:
            current_position = self.current_positions.get(symbol, Decimal('0'))
            if abs(current_position) < Decimal('0.01'):
                return {
                    'blocked': True,
                    'reason': f'max_positions_reached ({num_positions}/{self.config.max_concurrent_positions})',
                }

        return None
