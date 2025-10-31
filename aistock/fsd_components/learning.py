"""Learning coordination for FSD."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..fsd import FSDConfig, RLAgent, SymbolStats


class LearningCoordinator:
    """Coordinates Q-learning updates and statistics.

    Responsibilities:
    - Update Q-values after fills
    - Calculate rewards
    - Track per-symbol performance
    - Update statistics
    """

    def __init__(
        self,
        rl_agent: RLAgent,
        config: FSDConfig,
        symbol_performance: dict[str, SymbolStats],
        trade_history: list[dict[str, Any]],
    ):
        self.rl_agent = rl_agent
        self.config = config
        self.symbol_performance = symbol_performance
        self.trade_history = trade_history

        self.logger = logging.getLogger(__name__)

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
        last_state: dict[str, Any],
        last_action: str,
    ) -> None:
        """Update learning after fill."""
        # Calculate reward
        reward = self._calculate_reward(realised_pnl, fill_price, abs(signed_quantity))

        # Create next state
        next_state = last_state.copy()
        next_state['position_pct'] = new_position / 1000.0

        # Update Q-values
        done = abs(new_position) < 0.01
        try:
            self.rl_agent.update_q_value(
                state=last_state,
                action=last_action,
                reward=reward,
                next_state=next_state,
                done=done,
            )
        except Exception as exc:
            self.logger.error(f'Q-value update failed: {exc}', exc_info=True)

        # Update statistics
        self.rl_agent.total_trades += 1
        self.rl_agent.total_pnl += realised_pnl

        if realised_pnl > 0:
            self.rl_agent.winning_trades += 1

        # Per-symbol performance
        if symbol not in self.symbol_performance:
            from ..fsd import SymbolStats
            self.symbol_performance[symbol] = SymbolStats(
                trades=0,
                wins=0,
                total_pnl=0.0,
                confidence_adj=0.0,
            )

        perf = self.symbol_performance[symbol]
        perf['trades'] += 1
        perf['total_pnl'] += realised_pnl
        if realised_pnl > 0:
            perf['wins'] += 1

        # Trade history
        self.trade_history.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'quantity': signed_quantity,
            'price': fill_price,
            'pnl': realised_pnl,
            'position_before': previous_position,
            'position_after': new_position,
        })

        self.logger.info(f'Learning update: {symbol} pnl={realised_pnl:.2f}')

    def _calculate_reward(self, pnl: float, price: float, quantity: float) -> float:
        """Calculate reward for RL agent."""
        reward = pnl

        # Risk penalty
        position_value = price * quantity
        risk_penalty = self.config.risk_penalty_factor * position_value
        reward -= risk_penalty

        # Transaction cost
        transaction_cost = self.config.transaction_cost_factor * position_value
        reward -= transaction_cost

        return reward
