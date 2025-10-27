"""
FSD (Full Self-Driving) Reinforcement Learning Trading Agent.

This is the core AI that makes ALL trading decisions in FSD mode.
Uses Q-Learning to learn optimal trading policies from experience.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Tuple, Any
import numpy as np
import hashlib
import json


@dataclass
class FSDConfig:
    """Configuration for FSD RL agent."""
    # Learning parameters
    learning_rate: float = 0.001
    discount_factor: float = 0.95
    exploration_rate: float = 0.1
    exploration_decay: float = 0.995
    min_exploration_rate: float = 0.01
    
    # Constraints
    max_capital: float = 10000.0
    max_timeframe_seconds: int = 300  # 5 minutes
    min_confidence_threshold: float = 0.6
    
    # Reward shaping
    risk_penalty_factor: float = 0.1
    transaction_cost_factor: float = 0.001
    
    # State discretization
    price_change_bins: int = 10
    volume_bins: int = 5
    position_bins: int = 5


class RLAgent:
    """
    Q-Learning Reinforcement Learning Agent.
    
    State: Market features + position + P&L + time remaining
    Actions: BUY, SELL, HOLD, MODIFY_SIZE
    Reward: Realized P&L - risk penalty - transaction costs
    """
    
    def __init__(self, config: FSDConfig):
        self.config = config
        
        # Q-value table: {state_hash: {action: q_value}}
        self.q_values: Dict[str, Dict[str, float]] = {}
        
        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.exploration_rate = config.exploration_rate
        
        # Episode tracking
        self.current_episode_rewards = []
    
    def _hash_state(self, state: Dict[str, Any]) -> str:
        """Create hashable state representation."""
        # Discretize continuous values
        discretized = {
            'price_change_bin': self._discretize(
                state.get('price_change_pct', 0),
                -0.05, 0.05,
                self.config.price_change_bins
            ),
            'volume_bin': self._discretize(
                state.get('volume_ratio', 1.0),
                0.5, 2.0,
                self.config.volume_bins
            ),
            'position_bin': self._discretize(
                state.get('position_pct', 0),
                -0.5, 0.5,
                self.config.position_bins
            ),
            'trend': state.get('trend', 'neutral'),  # 'up', 'down', 'neutral'
            'volatility': state.get('volatility', 'normal'),  # 'low', 'normal', 'high'
        }
        
        # Create hash
        state_str = json.dumps(discretized, sort_keys=True)
        return hashlib.md5(state_str.encode()).hexdigest()
    
    def _discretize(self, value: float, min_val: float, max_val: float, bins: int) -> int:
        """Discretize continuous value into bins."""
        if value <= min_val:
            return 0
        if value >= max_val:
            return bins - 1
        
        range_size = max_val - min_val
        bin_size = range_size / bins
        bin_idx = int((value - min_val) / bin_size)
        
        return min(bin_idx, bins - 1)
    
    def get_actions(self) -> List[str]:
        """Get list of possible actions."""
        return ['BUY', 'SELL', 'HOLD', 'INCREASE_SIZE', 'DECREASE_SIZE']
    
    def select_action(self, state: Dict[str, Any], training: bool = True) -> str:
        """
        Select action using epsilon-greedy policy.
        
        Args:
            state: Current state dictionary
            training: If True, use exploration; if False, pure exploitation
        
        Returns:
            Selected action
        """
        state_hash = self._hash_state(state)
        
        # Initialize Q-values for this state if new
        if state_hash not in self.q_values:
            self.q_values[state_hash] = {action: 0.0 for action in self.get_actions()}
        
        # Epsilon-greedy
        if training and np.random.random() < self.exploration_rate:
            # Explore: random action
            return np.random.choice(self.get_actions())
        else:
            # Exploit: best Q-value
            q_vals = self.q_values[state_hash]
            return max(q_vals, key=q_vals.get)
    
    def update_q_value(
        self,
        state: Dict[str, Any],
        action: str,
        reward: float,
        next_state: Dict[str, Any],
        done: bool
    ):
        """
        Update Q-value using Q-learning update rule.
        
        Q(s,a) ← Q(s,a) + α[r + γ·max Q(s',a') - Q(s,a)]
        """
        state_hash = self._hash_state(state)
        next_state_hash = self._hash_state(next_state)
        
        # Initialize if needed
        if state_hash not in self.q_values:
            self.q_values[state_hash] = {a: 0.0 for a in self.get_actions()}
        if next_state_hash not in self.q_values:
            self.q_values[next_state_hash] = {a: 0.0 for a in self.get_actions()}
        
        # Current Q-value
        current_q = self.q_values[state_hash][action]
        
        # Max future Q-value
        if done:
            max_future_q = 0.0
        else:
            max_future_q = max(self.q_values[next_state_hash].values())
        
        # Q-learning update
        new_q = current_q + self.config.learning_rate * (
            reward + self.config.discount_factor * max_future_q - current_q
        )
        
        self.q_values[state_hash][action] = new_q
        
        # Decay exploration
        if done:
            self.exploration_rate = max(
                self.config.min_exploration_rate,
                self.exploration_rate * self.config.exploration_decay
            )
    
    def get_confidence(self, state: Dict[str, Any], action: str) -> float:
        """
        Get confidence score for an action in a state.
        
        Returns value between 0 and 1.
        """
        state_hash = self._hash_state(state)
        
        if state_hash not in self.q_values:
            return 0.5  # Neutral confidence for unseen states
        
        q_vals = self.q_values[state_hash]
        action_q = q_vals.get(action, 0.0)
        
        # Normalize Q-values to [0, 1] using sigmoid
        confidence = 1 / (1 + np.exp(-action_q))
        
        return confidence


class FSDEngine:
    """
    Full Self-Driving Trading Engine.
    
    This is the AI brain that:
    1. Evaluates market conditions and opportunities
    2. Decides whether to trade and how much
    3. Learns from every trade outcome
    4. Adapts strategy parameters dynamically
    """
    
    def __init__(self, config: FSDConfig, portfolio):
        self.config = config
        self.portfolio = portfolio
        self.rl_agent = RLAgent(config)
        
        # Trading state
        self.current_positions: Dict[str, Decimal] = {}
        self.trade_intents: List[Dict] = []
        
        # Performance tracking
        self.episode_start_equity = float(portfolio.initial_cash)
        self.last_state: Dict[str, Any] = {}
        self.last_action: str = 'HOLD'
    
    def extract_state(
        self,
        symbol: str,
        bars: List,
        last_prices: Dict[str, Decimal]
    ) -> Dict[str, Any]:
        """
        Extract state features from market data.
        
        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices for all symbols
        
        Returns:
            State dictionary
        """
        if len(bars) < 20:
            return {}
        
        # Recent price changes
        recent_closes = [float(bar.close) for bar in bars[-20:]]
        current_price = recent_closes[-1]
        prev_price = recent_closes[-2] if len(recent_closes) > 1 else current_price
        
        price_change_pct = (current_price - prev_price) / prev_price if prev_price > 0 else 0
        
        # Volume analysis
        recent_volumes = [bar.volume for bar in bars[-20:]]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 1
        current_volume = bars[-1].volume
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Trend detection (simple moving averages)
        if len(recent_closes) >= 10:
            short_ma = np.mean(recent_closes[-5:])
            long_ma = np.mean(recent_closes[-10:])
            
            if short_ma > long_ma * 1.01:
                trend = 'up'
            elif short_ma < long_ma * 0.99:
                trend = 'down'
            else:
                trend = 'neutral'
        else:
            trend = 'neutral'
        
        # Volatility (standard deviation of returns)
        if len(recent_closes) >= 10:
            returns = np.diff(recent_closes) / recent_closes[:-1]
            volatility_val = np.std(returns)
            
            if volatility_val < 0.01:
                volatility = 'low'
            elif volatility_val > 0.03:
                volatility = 'high'
            else:
                volatility = 'normal'
        else:
            volatility = 'normal'
        
        # Position state
        current_position = self.current_positions.get(symbol, Decimal('0'))
        equity = float(self.portfolio.get_equity(last_prices))
        position_value = float(current_position) * current_price
        position_pct = position_value / equity if equity > 0 else 0
        
        return {
            'symbol': symbol,
            'price_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'trend': trend,
            'volatility': volatility,
            'position_pct': position_pct,
            'current_price': current_price,
        }
    
    def evaluate_opportunity(
        self,
        symbol: str,
        bars: List,
        last_prices: Dict[str, Decimal]
    ) -> Dict[str, Any]:
        """
        Evaluate whether to trade this symbol.
        
        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices
        
        Returns:
            Decision dictionary with:
            - should_trade: bool
            - action: dict with trade details
            - confidence: float
            - state: dict
        """
        # Extract current state
        state = self.extract_state(symbol, bars, last_prices)
        
        if not state:
            return {
                'should_trade': False,
                'action': {'trade': False},
                'confidence': 0.0,
                'state': {}
            }
        
        # Get RL agent's action
        action_type = self.rl_agent.select_action(state, training=True)
        confidence = self.rl_agent.get_confidence(state, action_type)
        
        # Store state/action for learning
        self.last_state = state
        self.last_action = action_type
        
        # Convert action to trading decision
        should_trade = action_type in ['BUY', 'SELL', 'INCREASE_SIZE', 'DECREASE_SIZE']
        
        if not should_trade or confidence < self.config.min_confidence_threshold:
            return {
                'should_trade': False,
                'action': {'trade': False},
                'confidence': confidence,
                'state': state
            }
        
        # Determine size fraction based on confidence and action
        if action_type == 'BUY':
            size_fraction = confidence * 0.1  # Max 10% of equity
            trade_signal = 1
        elif action_type == 'SELL':
            size_fraction = confidence * 0.1
            trade_signal = -1
        elif action_type == 'INCREASE_SIZE':
            size_fraction = confidence * 0.05  # Smaller adjustments
            trade_signal = 1
        elif action_type == 'DECREASE_SIZE':
            size_fraction = confidence * 0.05
            trade_signal = -1
        else:
            size_fraction = 0.0
            trade_signal = 0
        
        return {
            'should_trade': True,
            'action': {
                'trade': True,
                'type': action_type,
                'size_fraction': size_fraction,
                'signal': trade_signal,
            },
            'confidence': confidence,
            'state': state
        }
    
    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: Dict,
        target_notional: float,
        target_quantity: float
    ):
        """Log that FSD wants to make this trade."""
        self.trade_intents.append({
            'symbol': symbol,
            'timestamp': timestamp,
            'decision': decision,
            'target_notional': target_notional,
            'target_quantity': target_quantity,
        })
    
    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float
    ):
        """
        Update RL agent after trade fill (LEARNING HAPPENS HERE).
        
        Args:
            symbol: Trading symbol
            timestamp: Fill timestamp
            fill_price: Execution price
            realised_pnl: Realized P&L from this trade
            signed_quantity: Quantity traded (signed)
            previous_position: Position before trade
            new_position: Position after trade
        """
        # Update position tracking
        self.current_positions[symbol] = Decimal(str(new_position))
        
        # Calculate reward
        reward = self._calculate_reward(realised_pnl, fill_price, abs(signed_quantity))
        
        # Get next state (would need current market data)
        # For now, use last state as approximation
        next_state = self.last_state.copy()
        next_state['position_pct'] = new_position / 1000.0  # Normalized
        
        # Update Q-values (LEARNING!)
        done = abs(new_position) < 0.01  # Episode done if position closed
        self.rl_agent.update_q_value(
            state=self.last_state,
            action=self.last_action,
            reward=reward,
            next_state=next_state,
            done=done
        )
        
        # Update statistics
        self.rl_agent.total_trades += 1
        self.rl_agent.total_pnl += realised_pnl
        
        if realised_pnl > 0:
            self.rl_agent.winning_trades += 1
    
    def _calculate_reward(self, pnl: float, price: float, quantity: float) -> float:
        """
        Calculate reward for RL agent.
        
        Reward = PnL - risk_penalty - transaction_costs
        """
        # Base reward is the P&L
        reward = pnl
        
        # Penalize risk (larger positions = more risk)
        position_value = price * quantity
        risk_penalty = self.config.risk_penalty_factor * position_value
        reward -= risk_penalty
        
        # Penalize transaction costs
        transaction_cost = self.config.transaction_cost_factor * position_value
        reward -= transaction_cost
        
        return reward
    
    def save_state(self, filepath: str):
        """Save FSD Q-values and statistics."""
        state = {
            'q_values': self.rl_agent.q_values,
            'total_trades': self.rl_agent.total_trades,
            'winning_trades': self.rl_agent.winning_trades,
            'total_pnl': self.rl_agent.total_pnl,
            'exploration_rate': self.rl_agent.exploration_rate,
        }
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self, filepath: str):
        """Load FSD Q-values and statistics."""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            self.rl_agent.q_values = state.get('q_values', {})
            self.rl_agent.total_trades = state.get('total_trades', 0)
            self.rl_agent.winning_trades = state.get('winning_trades', 0)
            self.rl_agent.total_pnl = state.get('total_pnl', 0.0)
            self.rl_agent.exploration_rate = state.get('exploration_rate', self.config.exploration_rate)
            
            return True
        except (FileNotFoundError, json.JSONDecodeError):
            return False
