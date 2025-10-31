"""Warmup simulator for FSD pre-training."""

from __future__ import annotations

import logging
from collections import deque
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..data import Bar
    from ..fsd import FSDConfig, RLAgent
    from ..portfolio import Portfolio
    from .state_extractor import MarketStateExtractor


class WarmupSimulator:
    """Simulates trading on historical data for pre-training.

    Responsibilities:
    - Process historical bars
    - Simulate trades
    - Update Q-values
    - Track warmup statistics
    """

    def __init__(
        self,
        rl_agent: RLAgent,
        config: FSDConfig,
        state_extractor: MarketStateExtractor,
        portfolio: Portfolio,
    ):
        self.rl_agent = rl_agent
        self.config = config
        self.state_extractor = state_extractor
        self.portfolio = portfolio

        self.logger = logging.getLogger(__name__)

    def warmup_from_historical(
        self,
        historical_bars: dict[str, list[Bar]],
        observation_fraction: float = 0.5,
    ) -> dict[str, Any]:
        """Warm up with historical simulation."""
        if not historical_bars:
            return {
                'status': 'no_data',
                'total_bars_processed': 0,
                'q_values_learned': len(self.rl_agent.q_values),
                'simulated_trades': 0,
                'simulated_win_rate': 0.0,
                'simulated_pnl': 0.0,
            }

        total_bars = 0
        simulated_trades = 0
        simulated_pnl = 0.0
        simulated_wins = 0
        sim_positions: dict[str, float] = {}
        sim_cash = float(self.portfolio.initial_cash)

        observation_fraction = max(0.0, min(1.0, observation_fraction))
        warmup_threshold = 0.40
        original_exploration = self.rl_agent.exploration_rate
        self.rl_agent.exploration_rate = max(original_exploration, 0.20)

        for symbol, bars in historical_bars.items():
            if not bars or len(bars) < 20:
                continue

            n = len(bars)
            total_bars += n
            observe_upto = max(20, int(n * observation_fraction))

            # Observation phase
            for i in range(20, observe_upto, 5):
                window = bars[i - 20 : i + 1]
                state = self.state_extractor.extract_state(
                    symbol, window, {symbol: window[-1].close}, sim_cash
                )
                if state:
                    state_hash = self.rl_agent.hash_state(state)
                    if state_hash not in self.rl_agent.q_values:
                        self.rl_agent.q_values[state_hash] = dict.fromkeys(
                            self.rl_agent.get_actions(), 0.0
                        )

            # Simulation phase
            for i in range(max(20, observe_upto), n - 1, 2):
                window = bars[i - 20 : i + 1]
                current_price = float(window[-1].close)
                next_price = float(bars[i + 1].close)

                state = self.state_extractor.extract_state(
                    symbol, window, {symbol: Decimal(str(current_price))}, sim_cash
                )
                if not state:
                    continue

                action_type = self.rl_agent.select_action(state, training=True)
                confidence = self.rl_agent.get_confidence(state, action_type)

                if action_type not in ['BUY', 'SELL', 'INCREASE_SIZE', 'DECREASE_SIZE']:
                    continue
                if confidence < warmup_threshold:
                    continue

                current_position = sim_positions.get(symbol, 0.0)

                # Execute simulated trade
                if action_type in ['BUY', 'INCREASE_SIZE']:
                    max_spend = sim_cash * 0.05
                    quantity = max_spend / current_price if current_price > 0 else 0
                    if quantity > 0:
                        sim_positions[symbol] = current_position + quantity
                        sim_cash -= quantity * current_price
                        simulated_trades += 1

                elif action_type in ['SELL', 'DECREASE_SIZE'] and abs(current_position) > 0.001:
                    quantity = abs(current_position) * 0.5
                    realized = (next_price - current_price) * quantity
                    sim_positions[symbol] = current_position - quantity
                    sim_cash += quantity * next_price
                    simulated_pnl += realized
                    simulated_trades += 1

                    if realized > 0:
                        simulated_wins += 1

                    # Learn from trade
                    reward = self._calculate_reward(realized, current_price, quantity)
                    next_state = self.state_extractor.extract_state(
                        symbol,
                        bars[i - 19 : i + 2],
                        {symbol: Decimal(str(next_price))},
                        sim_cash,
                    )
                    if next_state:
                        self.rl_agent.update_q_value(
                            state=state,
                            action=action_type,
                            reward=reward,
                            next_state=next_state,
                            done=(abs(sim_positions.get(symbol, 0.0)) < 0.001),
                        )

        # Restore exploration
        self.rl_agent.exploration_rate = original_exploration

        win_rate = (simulated_wins / simulated_trades) if simulated_trades > 0 else 0.0

        return {
            'status': 'complete',
            'total_bars_processed': total_bars,
            'q_values_learned': len(self.rl_agent.q_values),
            'simulated_trades': simulated_trades,
            'simulated_win_rate': win_rate,
            'simulated_pnl': simulated_pnl,
        }

    def _calculate_reward(self, pnl: float, price: float, quantity: float) -> float:
        """Calculate reward."""
        reward = pnl
        position_value = price * quantity
        risk_penalty = self.config.risk_penalty_factor * position_value
        transaction_cost = self.config.transaction_cost_factor * position_value
        return reward - risk_penalty - transaction_cost
