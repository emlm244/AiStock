"""
FSD (Full Self-Driving) Reinforcement Learning Trading Agent.

This is the core AI that makes ALL trading decisions in FSD mode.
Uses Q-Learning to learn optimal trading policies from experience.

PROFESSIONAL ENHANCEMENTS:
- Multi-timeframe analysis integration
- Candlestick pattern recognition
- Professional trading safeguards
"""

import hashlib
import json
import math
import random
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict, cast

import numpy as np

from .data import Bar
from .portfolio import Portfolio

if TYPE_CHECKING:
    from .edge_cases import EdgeCaseHandler
    from .patterns import PatternDetector
    from .professional import ProfessionalSafeguards
    from .timeframes import TimeframeManager


@dataclass
class FSDConfig:
    """Configuration for FSD RL agent."""

    # Learning parameters
    learning_rate: float = 0.001
    discount_factor: float = 0.95
    exploration_rate: float = 0.1
    exploration_decay: float = 0.995
    min_exploration_rate: float = 0.05  # 5% floor (was 1%) to maintain adaptability

    # Q-value decay for regime adaptation (prevents "nostalgia" for old market patterns)
    # Q-values decay by this factor per day (0.9999 = ~3.5% decay per month)
    enable_q_value_decay: bool = True
    q_value_decay_per_day: float = 0.9999

    # Constraints
    max_capital: float = 10000.0
    max_timeframe_seconds: int = 300  # 5 minutes
    min_confidence_threshold: float = 0.6
    max_loss_per_trade_pct: float = 5.0

    # Reward shaping
    risk_penalty_factor: float = 0.1
    transaction_cost_factor: float = 0.001

    # State discretization
    price_change_bins: int = 10
    volume_bins: int = 5
    position_bins: int = 5

    # ===== ADVANCED FEATURES =====
    # Parallel trading
    max_concurrent_positions: int = 5  # Max positions held at once
    max_capital_per_position: float = 0.2  # Max 20% capital per position

    # Per-symbol adaptation
    enable_per_symbol_params: bool = True  # Learn different params per symbol
    adaptive_confidence: bool = True  # Adjust confidence based on performance

    # Dynamic confidence adaptation (REPLACES trade deadline feature)
    # Gradually lowers confidence threshold if no trades in session (max reduction)
    max_confidence_decay: float = 0.15  # Max 15% reduction over session
    # Minutes before confidence starts decaying
    confidence_decay_start_minutes: int = 30
    # Enable session-based confidence adaptation
    enable_session_adaptation: bool = True
    # Volatility targeting preference: 'balanced', 'high', or 'low'
    volatility_bias: str = 'balanced'

    def validate(self) -> None:
        """
        P2-4 Fix: Validate FSD configuration parameters on startup.

        Raises:
            ValueError: If any parameter is invalid
        """
        # Learning parameters
        if not 0.0 < self.learning_rate <= 1.0:
            raise ValueError(f'learning_rate must be in (0, 1], got {self.learning_rate}')

        if not 0.0 <= self.discount_factor <= 1.0:
            raise ValueError(f'discount_factor must be in [0, 1], got {self.discount_factor}')

        if not 0.0 <= self.exploration_rate <= 1.0:
            raise ValueError(f'exploration_rate must be in [0, 1], got {self.exploration_rate}')

        if not 0.0 < self.exploration_decay <= 1.0:
            raise ValueError(f'exploration_decay must be in (0, 1], got {self.exploration_decay}')

        if not 0.0 <= self.min_exploration_rate <= self.exploration_rate:
            raise ValueError(
                f'min_exploration_rate must be in [0, exploration_rate], '
                f'got {self.min_exploration_rate} (exploration_rate={self.exploration_rate})'
            )

        # Q-value decay
        if not 0.0 < self.q_value_decay_per_day <= 1.0:
            raise ValueError(f'q_value_decay_per_day must be in (0, 1], got {self.q_value_decay_per_day}')

        # Constraints
        if self.max_capital <= 0:
            raise ValueError(f'max_capital must be positive, got {self.max_capital}')

        if self.max_timeframe_seconds <= 0:
            raise ValueError(f'max_timeframe_seconds must be positive, got {self.max_timeframe_seconds}')

        if not 0.0 <= self.min_confidence_threshold <= 1.0:
            raise ValueError(f'min_confidence_threshold must be in [0, 1], got {self.min_confidence_threshold}')

        if not 0.0 < self.max_loss_per_trade_pct <= 100.0:
            raise ValueError(f'max_loss_per_trade_pct must be in (0, 100], got {self.max_loss_per_trade_pct}')

        # Reward shaping
        if self.risk_penalty_factor < 0:
            raise ValueError(f'risk_penalty_factor must be non-negative, got {self.risk_penalty_factor}')

        if self.transaction_cost_factor < 0:
            raise ValueError(f'transaction_cost_factor must be non-negative, got {self.transaction_cost_factor}')

        # State discretization
        if self.price_change_bins < 2:
            raise ValueError(f'price_change_bins must be >= 2, got {self.price_change_bins}')

        if self.volume_bins < 2:
            raise ValueError(f'volume_bins must be >= 2, got {self.volume_bins}')

        if self.position_bins < 2:
            raise ValueError(f'position_bins must be >= 2, got {self.position_bins}')

        # Parallel trading
        if self.max_concurrent_positions < 1:
            raise ValueError(f'max_concurrent_positions must be >= 1, got {self.max_concurrent_positions}')

        if not 0.0 < self.max_capital_per_position <= 1.0:
            raise ValueError(f'max_capital_per_position must be in (0, 1], got {self.max_capital_per_position}')

        # Confidence adaptation
        if not 0.0 <= self.max_confidence_decay <= 1.0:
            raise ValueError(f'max_confidence_decay must be in [0, 1], got {self.max_confidence_decay}')

        if self.confidence_decay_start_minutes < 0:
            raise ValueError(
                f'confidence_decay_start_minutes must be non-negative, got {self.confidence_decay_start_minutes}'
            )

        # Volatility bias
        valid_volatility_biases = {'balanced', 'high', 'low'}
        if self.volatility_bias not in valid_volatility_biases:
            raise ValueError(f'volatility_bias must be one of {valid_volatility_biases}, got {self.volatility_bias!r}')


class RLAgent:
    """
    Q-Learning Reinforcement Learning Agent.

    State: Market features + position + P&L + time remaining
    Actions: BUY, SELL, HOLD, MODIFY_SIZE
    Reward: Realized P&L - risk penalty - transaction costs
    """

    def __init__(self, config: FSDConfig):
        self.config = config

        # SIMPLIFIED: Unlimited Q-value table (no LRU eviction)
        # Since trades happen every 30+ seconds, memory usage is minimal
        # OrderedDict still used for deterministic iteration order
        self.q_values: OrderedDict[str, dict[str, float]] = OrderedDict()
        self._lock = threading.Lock()  # P0-3 Fix: Protect Q-value updates from concurrent access

        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.exploration_rate = config.exploration_rate

        # Q-value decay tracking (for regime adaptation)
        self.last_decay_timestamp: datetime | None = None

        # Episode tracking
        self.current_episode_rewards: list[float] = []
        # REMOVED: Zombie experience buffer (was never used for learning)

    def _ensure_q_table_capacity(self) -> None:
        """
        SIMPLIFIED: No capacity limits (trades are infrequent ~30s+).

        Memory usage is minimal for realistic trading scenarios.
        This method is now a no-op for backward compatibility.
        """
        # No-op: unlimited Q-table
        pass

    def check_q_table_size(self) -> dict[str, Any]:
        """
        Monitor Q-table size and log warnings if it grows too large.

        This method tracks the growth of the Q-value lookup table and emits
        log messages at various thresholds to warn about memory usage. It's
        automatically called during save_state() to provide visibility into
        the agent's memory footprint.

        Thresholds:
            - Normal: < 10K states (no logging)
            - Low: 10K - 50K states (DEBUG log)
            - Medium: 50K - 100K states (INFO log)
            - High: 100K - 200K states (WARNING log, monitor usage)
            - Critical: >= 200K states (WARNING log, consider pruning)

        Returns:
            dict[str, Any]: Dictionary containing:
                - num_states (int): Total number of learned states
                - estimated_memory_mb (float): Approximate memory usage in MB
                - level (str): Warning level ('normal', 'low', 'medium', 'high', 'critical')
                - thresholds (dict): Threshold values used for classification

        Thread Safety:
            Thread-safe. Uses internal lock when accessing Q-table size.
        """
        import logging

        logger = logging.getLogger(__name__)

        with self._lock:
            num_states = len(self.q_values)
            num_actions = len(self.get_actions())

        # Estimate memory usage (rough approximation)
        # Each Q-value is ~8 bytes (float), plus ~100 bytes overhead per state for dict/hash
        bytes_per_state = (num_actions * 8) + 100
        estimated_memory_mb = (num_states * bytes_per_state) / (1024 * 1024)

        # Define thresholds
        thresholds = {
            'low': 10000,  # 10K states
            'medium': 50000,  # 50K states
            'high': 100000,  # 100K states
            'critical': 200000,  # 200K states
        }

        # Determine warning level
        if num_states >= thresholds['critical']:
            level = 'critical'
            logger.warning(
                f'Q-table size CRITICAL: {num_states:,} states (~{estimated_memory_mb:.1f} MB). '
                'Consider enabling Q-value decay or implementing state pruning.'
            )
        elif num_states >= thresholds['high']:
            level = 'high'
            logger.warning(
                f'Q-table size HIGH: {num_states:,} states (~{estimated_memory_mb:.1f} MB). ' 'Monitor memory usage.'
            )
        elif num_states >= thresholds['medium']:
            level = 'medium'
            logger.info(f'Q-table size MEDIUM: {num_states:,} states (~{estimated_memory_mb:.1f} MB).')
        elif num_states >= thresholds['low']:
            level = 'low'
            logger.debug(f'Q-table size: {num_states:,} states (~{estimated_memory_mb:.1f} MB).')
        else:
            level = 'normal'

        return {
            'num_states': num_states,
            'estimated_memory_mb': estimated_memory_mb,
            'level': level,
            'thresholds': thresholds,
        }

    def apply_q_value_decay(self) -> dict[str, Any]:
        """
        Apply time-based decay to Q-values for regime adaptation.

        This prevents the agent from being "nostalgic" for old market patterns
        that may no longer be relevant. Q-values gradually fade if states aren't
        revisited, allowing the agent to adapt to new market regimes.

        The decay is exponential: Q(s,a) *= decay_factor^days_elapsed, where
        decay_factor is config.q_value_decay_per_day (default 0.9999).

        Example with default settings:
            - After 30 days: Q-values *= 0.9999^30 ≈ 0.997 (0.3% decay)
            - After 365 days: Q-values *= 0.9999^365 ≈ 0.965 (3.5% decay)

        The decay is applied to ALL states in the Q-table, regardless of
        whether they've been visited recently. This encourages the agent to
        re-evaluate old states if market conditions change.

        Args:
            None (uses config.enable_q_value_decay and config.q_value_decay_per_day)

        Returns:
            dict[str, Any]: Dictionary containing:
                - enabled (bool): Whether decay is enabled in config
                - first_run (bool): True if this is the first decay call (timestamp init)
                - skipped (bool): True if decay was skipped (too soon since last decay)
                - reason (str): Reason for skip (if skipped=True)
                - days_elapsed (float): Days since last decay (clamped if > 90 days)
                - decay_factor (float): Actual decay multiplier applied
                - states_decayed (int): Number of states processed
                - timestamp (str): ISO timestamp of decay operation
                - clamped (bool): True if days_elapsed was clamped to prevent extreme decay
                - original_days_elapsed (float): Original unclamped value (only if clamped=True)

        Thread Safety:
            Thread-safe. Uses internal lock when modifying Q-values.

        Side Effects:
            - Updates self.last_decay_timestamp to current time
            - Modifies all Q-values in self.q_values (if enabled and not skipped)
        """
        if not self.config.enable_q_value_decay:
            return {'enabled': False}

        current_time = datetime.now(timezone.utc)

        # Initialize timestamp if this is the first decay
        if self.last_decay_timestamp is None:
            self.last_decay_timestamp = current_time
            return {'enabled': True, 'first_run': True, 'states_decayed': 0}

        # Calculate time elapsed since last decay
        elapsed = current_time - self.last_decay_timestamp
        days_elapsed = elapsed.total_seconds() / 86400.0  # 86400 seconds in a day

        # Guard against negative time (clock adjustments/timezone issues)
        if days_elapsed < 0:
            # Clock went backward - reset timestamp and skip decay
            self.last_decay_timestamp = current_time
            return {'enabled': True, 'skipped': True, 'reason': 'negative_time_elapsed'}

        # Only apply decay if at least some time has passed
        if days_elapsed < 0.01:  # Less than ~15 minutes
            return {'enabled': True, 'skipped': True, 'reason': 'too_soon'}

        # Guard against extreme decay (e.g., multi-year gap after long downtime)
        # Cap at 90 days to prevent underflow and preserve some learned knowledge
        original_days = days_elapsed
        clamped = False
        if days_elapsed > 90:
            days_elapsed = 90
            clamped = True

        # Calculate decay factor based on days elapsed
        decay_factor = self.config.q_value_decay_per_day**days_elapsed

        # Floor decay factor to prevent complete zeroing of Q-values
        MIN_DECAY_FACTOR = 1e-12
        if decay_factor < MIN_DECAY_FACTOR:
            decay_factor = MIN_DECAY_FACTOR

        # Apply decay to all Q-values (thread-safe)
        with self._lock:
            states_decayed = 0
            for state_hash in self.q_values:
                for action in self.q_values[state_hash]:
                    self.q_values[state_hash][action] *= decay_factor
                states_decayed += 1

        # Update timestamp
        self.last_decay_timestamp = current_time

        result = {
            'enabled': True,
            'days_elapsed': days_elapsed,
            'decay_factor': decay_factor,
            'states_decayed': states_decayed,
            'timestamp': current_time.isoformat(),
            'clamped': clamped,
        }

        # Include original_days if clamped
        if clamped:
            result['original_days_elapsed'] = original_days

        return result

    def _hash_state(self, state: dict[str, object]) -> str:
        """Create hashable state representation."""
        # Discretize continuous values
        pc_val: object = state.get('price_change_pct', 0.0)
        price_change: float = float(pc_val) if isinstance(pc_val, (int, float)) else 0.0
        vr_val: object = state.get('volume_ratio', 1.0)
        vol_ratio: float = float(vr_val) if isinstance(vr_val, (int, float)) else 1.0
        pp_val: object = state.get('position_pct', 0.0)
        position_pct: float = float(pp_val) if isinstance(pp_val, (int, float)) else 0.0

        t_val: object = state.get('trend', 'neutral')
        trend_default: str = t_val if isinstance(t_val, str) else 'neutral'
        v_val: object = state.get('volatility', 'normal')
        vol_default: str = v_val if isinstance(v_val, str) else 'normal'
        # Normalize optional string fields first to avoid Any warnings
        tf_raw: object = state.get('trend_fast', trend_default)
        trend_fast_norm: str = tf_raw if isinstance(tf_raw, str) else trend_default
        ts_raw: object = state.get('trend_slow', trend_default)
        trend_slow_norm: str = ts_raw if isinstance(ts_raw, str) else trend_default
        vf_raw: object = state.get('volatility_fast', vol_default)
        vol_fast_norm: str = vf_raw if isinstance(vf_raw, str) else vol_default
        vs_raw: object = state.get('volatility_slow', vol_default)
        vol_slow_norm: str = vs_raw if isinstance(vs_raw, str) else vol_default

        discretized = {
            'price_change_bin': self._discretize(price_change, -0.05, 0.05, self.config.price_change_bins),
            'volume_bin': self._discretize(vol_ratio, 0.5, 2.0, self.config.volume_bins),
            'position_bin': self._discretize(position_pct, -0.5, 0.5, self.config.position_bins),
            'trend': trend_default,
            'volatility': vol_default,
            # Multi-timeframe features (fast≈1-3 bars, slow≈15-30 bars)
            'trend_fast': trend_fast_norm,
            'trend_slow': trend_slow_norm,
            'volatility_fast': vol_fast_norm,
            'volatility_slow': vol_slow_norm,
        }

        # Create hash
        state_str = json.dumps(discretized, sort_keys=True)
        return hashlib.md5(state_str.encode()).hexdigest()

    # Public wrapper to satisfy external callers in strict type mode
    def hash_state(self, state: dict[str, object]) -> str:
        return self._hash_state(state)

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

    def get_actions(self) -> list[str]:
        """Get list of possible actions."""
        return ['BUY', 'SELL', 'HOLD', 'INCREASE_SIZE', 'DECREASE_SIZE']

    def select_action(self, state: dict[str, object], training: bool = True) -> str:
        """
        Select action using epsilon-greedy policy.

        Args:
            state: Current state dictionary
            training: If True, use exploration; if False, pure exploitation

        Returns:
            Selected action
        """
        state_hash = self._hash_state(state)

        # P0-3 Fix: Thread-safe Q-value access
        with self._lock:
            # Initialize Q-values for this state if new
            if state_hash not in self.q_values:
                # P1-1 Fix: Evict old states if necessary before adding new one
                self._ensure_q_table_capacity()
                self.q_values[state_hash] = dict.fromkeys(self.get_actions(), 0.0)

            # Epsilon-greedy
            if training and np.random.random() < self.exploration_rate:
                # Explore: random action
                return random.choice(self.get_actions())
            else:
                # Exploit: best Q-value
                q_vals = self.q_values[state_hash]
                return max(q_vals.items(), key=lambda item: item[1])[0]

    def update_q_value(
        self, state: dict[str, object], action: str, reward: float, next_state: dict[str, object], done: bool
    ):
        """
        Update Q-value using Q-learning update rule.

        Q(s,a) ← Q(s,a) + α[r + γ·max Q(s',a') - Q(s,a)]
        """
        state_hash = self._hash_state(state)
        next_state_hash = self._hash_state(next_state)

        # P0-3 Fix: Thread-safe Q-value update
        with self._lock:
            # Initialize if needed
            if state_hash not in self.q_values:
                # P1-1 Fix: Evict old states if necessary before adding new one
                self._ensure_q_table_capacity()
                self.q_values[state_hash] = dict.fromkeys(self.get_actions(), 0.0)
            if next_state_hash not in self.q_values:
                # P1-1 Fix: Evict old states if necessary before adding new one
                self._ensure_q_table_capacity()
                self.q_values[next_state_hash] = dict.fromkeys(self.get_actions(), 0.0)

            # Current Q-value
            current_q = self.q_values[state_hash][action]

            # Max future Q-value
            max_future_q = 0.0 if done else max(self.q_values[next_state_hash].values())

            # Q-learning update
            new_q = current_q + self.config.learning_rate * (
                reward + self.config.discount_factor * max_future_q - current_q
            )

            self.q_values[state_hash][action] = new_q

            # Decay exploration
            if done:
                self.exploration_rate = max(
                    self.config.min_exploration_rate, self.exploration_rate * self.config.exploration_decay
                )

    def get_confidence(self, state: dict[str, object], action: str) -> float:
        """
        Get confidence score for an action in a state.

        Returns value between 0 and 1.

        CRITICAL FIX: Guards against sigmoid overflow with extreme Q-values.
        """
        state_hash = self._hash_state(state)

        # P0-3 Fix: Thread-safe Q-value read
        with self._lock:
            if state_hash not in self.q_values:
                return 0.5  # Neutral confidence for unseen states

            q_vals = self.q_values[state_hash]
            action_q = q_vals.get(action, 0.0)

        # CRITICAL FIX: Guard against sigmoid overflow
        # math.exp() overflows for values > 700, underflows for values < -700
        if action_q > 700:
            confidence = 1.0  # Extreme positive Q-value → max confidence
        elif action_q < -700:
            confidence = 0.0  # Extreme negative Q-value → min confidence
        else:
            # Normalize Q-values to [0, 1] using sigmoid (outside lock)
            confidence = 1.0 / (1.0 + math.exp(-action_q))

        return confidence


class SymbolStats(TypedDict):
    trades: int
    wins: int
    total_pnl: float
    confidence_adj: float


class FSDEngine:
    """
    Full Self-Driving Trading Engine.

    This is the AI brain that:
    1. Evaluates market conditions and opportunities
    2. Decides whether to trade and how much
    3. Learns from every trade outcome
    4. Adapts strategy parameters dynamically

    PROFESSIONAL ENHANCEMENTS:
    5. Multi-timeframe correlation analysis
    6. Candlestick pattern recognition
    7. Professional trading safeguards
    """

    def __init__(
        self,
        config: FSDConfig,
        portfolio: Portfolio,
        timeframe_manager: 'TimeframeManager | None' = None,
        pattern_detector: 'PatternDetector | None' = None,
        safeguards: 'ProfessionalSafeguards | None' = None,
        edge_case_handler: 'EdgeCaseHandler | None' = None,
    ):
        self.config = config
        self.portfolio = portfolio
        self.rl_agent = RLAgent(config)

        # Professional modules (optional but recommended)
        self.timeframe_manager = timeframe_manager
        self.pattern_detector = pattern_detector
        self.safeguards = safeguards
        self.edge_case_handler = edge_case_handler

        # Trading state
        self.current_positions: dict[str, Decimal] = {}
        self.trade_intents: list[dict[str, Any]] = []
        # Trade history (capped at 10k to prevent unbounded memory growth)
        self.trade_history: deque[dict[str, Any]] = deque(maxlen=10000)

        # Performance tracking
        self.episode_start_equity = float(portfolio.initial_cash)
        self.last_state: dict[str, Any] = {}
        self.last_action: str = 'HOLD'
        self.last_trade_timestamp: datetime | None = None

        # Session tracking
        self.session_start_time: datetime | None = None
        self.session_trades: int = 0

        # GUI callback (optional) - public interface for GUI integration
        self.gui_log_callback: Any | None = None

        # ===== ADVANCED FEATURES =====
        # Per-symbol performance tracking for adaptive confidence
        self.symbol_performance: dict[str, SymbolStats] = {}
        # Format: {symbol: {'trades': int, 'wins': int, 'total_pnl': float, 'confidence_adj': float}}
        self._last_prices: dict[str, Decimal] = {}

    def extract_state(self, symbol: str, bars: list[Bar], last_prices: dict[str, Decimal]) -> dict[str, Any]:
        """
        ENHANCED: Extract state features from market data with professional analysis.

        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices for all symbols

        Returns:
            State dictionary with multi-timeframe and pattern features
        """
        if len(bars) < 20:
            return {}

        # Recent price changes
        recent_closes: list[float] = [float(bar.close) for bar in bars[-20:]]
        current_price = recent_closes[-1]
        prev_price = recent_closes[-2] if len(recent_closes) > 1 else current_price

        price_change_pct = (current_price - prev_price) / prev_price if prev_price > 0 else 0

        # Volume analysis
        recent_volumes: list[int] = [bar.volume for bar in bars[-20:]]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 1
        current_volume = bars[-1].volume
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Trend detection (multi-timeframe using different windows from same bars)
        # Fast trend ~ 1-3 minute view; Slow trend ~ 15-30 minute view
        trend = 'neutral'
        trend_fast = 'neutral'
        trend_slow = 'neutral'
        if len(recent_closes) >= 10:
            short_ma = np.mean(recent_closes[-5:])
            long_ma = np.mean(recent_closes[-10:])
            trend = 'up' if short_ma > long_ma * 1.01 else 'down' if short_ma < long_ma * 0.99 else 'neutral'
        if len(recent_closes) >= 6:
            fast_short = np.mean(recent_closes[-3:])
            fast_long = np.mean(recent_closes[-6:])
            trend_fast = (
                'up' if fast_short > fast_long * 1.01 else 'down' if fast_short < fast_long * 0.99 else 'neutral'
            )
        if len(recent_closes) >= 30:
            slow_short = np.mean(recent_closes[-15:])
            slow_long = np.mean(recent_closes[-30:])
            trend_slow = (
                'up' if slow_short > slow_long * 1.005 else 'down' if slow_short < slow_long * 0.995 else 'neutral'
            )

        # Volatility (standard deviation of returns) at multiple horizons
        volatility = 'normal'
        volatility_fast = 'normal'
        volatility_slow = 'normal'
        if len(recent_closes) >= 10:
            returns = np.diff(recent_closes) / recent_closes[:-1]
            volatility_val = np.std(returns)
            volatility = 'low' if volatility_val < 0.01 else 'high' if volatility_val > 0.03 else 'normal'
        if len(recent_closes) >= 6:
            returns_fast = np.diff(recent_closes[-6:]) / np.array(recent_closes[-6:-1])
            vol_fast_val = np.std(returns_fast)
            volatility_fast = 'low' if vol_fast_val < 0.012 else 'high' if vol_fast_val > 0.04 else 'normal'
        if len(recent_closes) >= 30:
            returns_slow = np.diff(recent_closes[-30:]) / np.array(recent_closes[-30:-1])
            vol_slow_val = np.std(returns_slow)
            volatility_slow = 'low' if vol_slow_val < 0.008 else 'high' if vol_slow_val > 0.025 else 'normal'

        # Position state
        current_position = self.current_positions.get(symbol, Decimal('0'))
        equity = float(self.portfolio.get_equity(last_prices))
        position_value = float(current_position) * current_price
        position_pct = position_value / equity if equity > 0 else 0

        state: dict[str, Any] = {
            'symbol': symbol,
            'price_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'trend': trend,
            'volatility': volatility,
            'trend_fast': trend_fast,
            'trend_slow': trend_slow,
            'volatility_fast': volatility_fast,
            'volatility_slow': volatility_slow,
            'position_pct': position_pct,
            'current_price': current_price,
        }

        # PROFESSIONAL ENHANCEMENT 1: Multi-timeframe features
        if self.timeframe_manager and self.timeframe_manager.has_sufficient_data(symbol):
            timeframe_features = self.timeframe_manager.get_timeframe_features(symbol)
            state.update(timeframe_features)

        # PROFESSIONAL ENHANCEMENT 2: Candlestick patterns
        if self.pattern_detector and len(bars) >= 3:
            patterns = self.pattern_detector.detect_patterns(bars)
            if patterns:
                # Add strongest pattern signal
                strongest = self.pattern_detector.get_strongest_signal(patterns)
                state['pattern_signal'] = strongest.value
                state['pattern_count'] = len(patterns)
                # Add individual pattern flags
                state['has_bullish_pattern'] = any(p.signal.value == 'bullish' for p in patterns)
                state['has_bearish_pattern'] = any(p.signal.value == 'bearish' for p in patterns)
            else:
                state['pattern_signal'] = 'neutral'
                state['pattern_count'] = 0
                state['has_bullish_pattern'] = False
                state['has_bearish_pattern'] = False

        return state

    def evaluate_opportunity(self, symbol: str, bars: list[Bar], last_prices: dict[str, Decimal]) -> dict[str, Any]:
        """
        ENHANCED: Evaluate whether to trade this symbol with advanced features:
        - Deadline urgency (lowers threshold as deadline approaches)
        - Adaptive confidence per symbol (learns which symbols are profitable)
        - Parallel trading limits (respects max concurrent positions)

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
            - reason: str (explanation)
        """
        # Keep a snapshot of the latest prices so fill handlers can align position normalisation with equity.
        self._last_prices = dict(last_prices)

        # ===== EDGE CASE PROTECTION (First Line of Defense) =====
        if self.edge_case_handler:
            # Get timeframe data if available
            timeframe_data = None
            if self.timeframe_manager:
                timeframe_data = {}
                for tf in self.timeframe_manager.timeframes:
                    tf_bars = self.timeframe_manager.get_bars(symbol, tf, lookback=50)
                    if tf_bars:
                        timeframe_data[tf] = tf_bars

            edge_result = self.edge_case_handler.check_edge_cases(
                symbol=symbol,
                bars=bars,
                timeframe_data=timeframe_data,
                current_time=datetime.now(timezone.utc),
            )

            if edge_result.action == 'block':
                # Critical edge case - block trading
                return {
                    'should_trade': False,
                    'action': {'trade': False},
                    'confidence': 0.0,
                    'state': {},
                    'reason': f'edge_case_blocked: {edge_result.reason}',
                    'edge_case': {
                        'severity': edge_result.severity,
                        'reason': edge_result.reason,
                    },
                }

        # Extract current state
        state = self.extract_state(symbol, bars, last_prices)

        if not state:
            return {
                'should_trade': False,
                'action': {'trade': False},
                'confidence': 0.0,
                'state': {},
                'reason': 'insufficient_data',
            }

        # ===== PROFESSIONAL SAFEGUARDS CHECK =====
        safeguard_confidence_adjustment = 0.0
        safeguard_position_multiplier = 1.0
        safeguard_warnings: list[str] = []

        if self.safeguards:
            # Check for timeframe divergence if multi-timeframe enabled
            timeframe_divergence = False
            if self.timeframe_manager and self.timeframe_manager.has_sufficient_data(symbol):
                analysis = self.timeframe_manager.analyze_cross_timeframe(symbol)
                timeframe_divergence = analysis.divergence_detected
                safeguard_confidence_adjustment += analysis.confidence_adjustment

            # Run professional safeguard checks
            safeguard_result = self.safeguards.check_trading_allowed(
                symbol=symbol,
                bars=bars,
                current_time=datetime.now(timezone.utc),
                timeframe_divergence=timeframe_divergence,
            )

            if not safeguard_result.allowed:
                # Trade blocked by safeguards
                return {
                    'should_trade': False,
                    'action': {'trade': False},
                    'confidence': 0.0,
                    'state': state,
                    'reason': f'safeguards_blocked: {safeguard_result.reason}',
                    'warnings': safeguard_result.warnings,
                }

            # Apply safeguard adjustments
            safeguard_confidence_adjustment += safeguard_result.confidence_adjustment
            safeguard_position_multiplier = safeguard_result.position_size_multiplier
            safeguard_warnings = safeguard_result.warnings

        # ===== PARALLEL TRADING LIMIT CHECK =====
        num_positions = len([pos for pos in self.current_positions.values() if abs(pos) > Decimal('0.01')])
        if num_positions >= self.config.max_concurrent_positions:
            # Already at max positions - only allow closing trades
            current_position = self.current_positions.get(symbol, Decimal('0'))
            if abs(current_position) < Decimal('0.01'):
                return {
                    'should_trade': False,
                    'action': {'trade': False},
                    'confidence': 0.0,
                    'state': state,
                    'reason': f'max_positions_reached ({num_positions}/{self.config.max_concurrent_positions})',
                }

        # Get RL agent's action
        action_type = self.rl_agent.select_action(state, training=True)
        base_confidence = self.rl_agent.get_confidence(state, action_type)

        # Store state/action for learning
        self.last_state = state
        self.last_action = action_type

        # ===== ADAPTIVE CONFIDENCE (per-symbol learning) =====
        adjusted_confidence = base_confidence

        # Apply edge case adjustments (if edge case handler detected non-blocking issues)
        edge_case_position_multiplier = 1.0
        if self.edge_case_handler:
            # Get timeframe data if available (reuse from earlier check)
            timeframe_data = None
            if self.timeframe_manager:
                timeframe_data = {}
                for tf in self.timeframe_manager.timeframes:
                    tf_bars = self.timeframe_manager.get_bars(symbol, tf, lookback=50)
                    if tf_bars:
                        timeframe_data[tf] = tf_bars

            # Re-run edge case check to get adjustments
            edge_result = self.edge_case_handler.check_edge_cases(
                symbol=symbol,
                bars=bars,
                timeframe_data=timeframe_data,
                current_time=datetime.now(timezone.utc),
            )
            if edge_result.is_edge_case and edge_result.action != 'block':
                adjusted_confidence += edge_result.confidence_adjustment
                edge_case_position_multiplier = edge_result.position_size_multiplier
                # Log edge case warning
                if edge_result.action == 'warn' or edge_result.action == 'reduce_size':
                    safeguard_warnings.append(f'Edge case: {edge_result.reason}')

        # Apply professional safeguard adjustments
        adjusted_confidence += safeguard_confidence_adjustment

        if self.config.enable_per_symbol_params and symbol in self.symbol_performance:
            perf = self.symbol_performance[symbol]
            if perf['trades'] >= 3:  # Need at least 3 trades to adapt
                win_rate = perf['wins'] / perf['trades']
                avg_pnl = perf['total_pnl'] / perf['trades']

                # Boost confidence for profitable symbols, reduce for unprofitable
                if win_rate > 0.6 and avg_pnl > 0:
                    perf['confidence_adj'] = min(0.15, perf['confidence_adj'] + 0.02)
                elif win_rate < 0.4 or avg_pnl < 0:
                    perf['confidence_adj'] = max(-0.15, perf['confidence_adj'] - 0.02)

                adjusted_confidence += perf['confidence_adj']

        # Clamp confidence to valid range
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        # ===== VOLATILITY BIAS ADJUSTMENT =====
        volatility_bias = getattr(self.config, 'volatility_bias', 'balanced')
        bias_adjustment = 0.0
        if volatility_bias == 'high':
            before_bias = adjusted_confidence
            if state.get('volatility') == 'high' or state.get('volatility_fast') == 'high':
                adjusted_confidence = min(1.0, adjusted_confidence + 0.08)
            elif state.get('volatility') == 'low':
                adjusted_confidence *= 0.9
            bias_adjustment = adjusted_confidence - before_bias
        elif volatility_bias == 'low':
            before_bias = adjusted_confidence
            if state.get('volatility') == 'high' or state.get('volatility_fast') == 'high':
                adjusted_confidence *= 0.75
            elif state.get('volatility') == 'low':
                adjusted_confidence = min(1.0, adjusted_confidence + 0.05)
            bias_adjustment = adjusted_confidence - before_bias

        # Clamp confidence again after bias adjustment
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        # ===== DYNAMIC CONFIDENCE THRESHOLD (Session-Based Adaptation) =====
        # Smarter alternative to hard deadlines - gradually lowers threshold if bot is being too conservative
        effective_threshold = self.config.min_confidence_threshold
        confidence_decay = 0.0

        if self.config.enable_session_adaptation and self.session_start_time and self.session_trades == 0:
            # No trades yet - check if we should adapt
            elapsed_minutes = (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 60

            # Only start adapting after confidence_decay_start_minutes
            if elapsed_minutes > self.config.confidence_decay_start_minutes:
                # Gradual decay over time (but never forced trading)
                decay_minutes = elapsed_minutes - self.config.confidence_decay_start_minutes
                # Decay factor: 0.0 at start, approaching 1.0 over next 60 minutes
                decay_factor = min(1.0, decay_minutes / 60.0)
                confidence_decay = decay_factor * self.config.max_confidence_decay
                effective_threshold = max(0.35, self.config.min_confidence_threshold - confidence_decay)

        # Convert action to trading decision
        should_trade = action_type in ['BUY', 'SELL', 'INCREASE_SIZE', 'DECREASE_SIZE']

        if not should_trade or adjusted_confidence < effective_threshold:
            reason = (
                'hold_action'
                if not should_trade
                else f'confidence_too_low ({adjusted_confidence:.2f} < {effective_threshold:.2f})'
            )
            return {
                'should_trade': False,
                'action': {'trade': False},
                'confidence': adjusted_confidence,
                'state': state,
                'reason': reason,
                'confidence_breakdown': {
                    'base': base_confidence,
                    'adjusted': adjusted_confidence,
                    'threshold': effective_threshold,
                    'confidence_decay': confidence_decay,
                    'safeguard_adjustment': safeguard_confidence_adjustment,
                    'volatility_bias': volatility_bias,
                    'bias_adjustment': bias_adjustment,
                },
            }

        # Determine size fraction based on confidence and action
        # Cap per-position capital
        max_fraction = max(0.0, min(self.config.max_capital_per_position, 1.0))

        if action_type == 'BUY':
            size_fraction = adjusted_confidence * max_fraction
            trade_signal = 1
        elif action_type == 'SELL':
            size_fraction = adjusted_confidence * max_fraction
            trade_signal = -1
        elif action_type == 'INCREASE_SIZE':
            size_fraction = adjusted_confidence * max_fraction * 0.5  # Smaller adjustments
            trade_signal = 1
        elif action_type == 'DECREASE_SIZE':
            size_fraction = adjusted_confidence * max_fraction * 0.5
            trade_signal = -1
        else:
            size_fraction = 0.0
            trade_signal = 0

        # Apply all position size multipliers (safeguards AND edge cases)
        size_fraction *= safeguard_position_multiplier
        size_fraction *= edge_case_position_multiplier

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
                'threshold': effective_threshold,
                'confidence_decay': confidence_decay,
                'safeguard_adjustment': safeguard_confidence_adjustment,
                'volatility_bias': volatility_bias,
                'bias_adjustment': bias_adjustment,
            },
            'warnings': safeguard_warnings,
        }

    def register_trade_intent(
        self, symbol: str, timestamp: datetime, decision: dict[str, Any], target_notional: float, target_quantity: float
    ) -> None:
        """Log that FSD wants to make this trade."""
        self.trade_intents.append(
            {
                'symbol': symbol,
                'timestamp': timestamp,
                'decision': decision,
                'target_notional': target_notional,
                'target_quantity': target_quantity,
            }
        )

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ):
        """
        ENHANCED: Update RL agent after trade fill with per-symbol learning.

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
        # For now, use last state as approximation and re-normalise by equity.
        next_state = self.last_state.copy()
        price_snapshot = dict(getattr(self, '_last_prices', {}))
        price_snapshot[symbol] = Decimal(str(fill_price))
        equity_value = float(self.portfolio.get_equity(price_snapshot))
        if equity_value > 0:
            position_notional = new_position * fill_price
            next_state['position_pct'] = position_notional / equity_value
        else:
            next_state['position_pct'] = 0.0

        # CRITICAL-2 Fix: Update Q-values (LEARNING!) with error recovery
        done = abs(new_position) < 0.01  # Episode done if position closed
        try:
            self.rl_agent.update_q_value(
                state=self.last_state, action=self.last_action, reward=reward, next_state=next_state, done=done
            )
        except Exception as q_update_error:
            # CRITICAL-2: Never let Q-value update errors break the learning pipeline
            # Log the error but continue with statistics tracking
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f'Q-value update failed for {symbol}: {q_update_error}',
                exc_info=True,
                extra={
                    'symbol': symbol,
                    'reward': reward,
                    'error_type': type(q_update_error).__name__,
                },
            )

        # Update statistics
        self.rl_agent.total_trades += 1
        self.rl_agent.total_pnl += realised_pnl

        if realised_pnl > 0:
            self.rl_agent.winning_trades += 1

        # ===== PER-SYMBOL PERFORMANCE TRACKING =====
        if symbol not in self.symbol_performance:
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

        # Track trade history
        self.trade_history.append(
            {
                'timestamp': timestamp,
                'symbol': symbol,
                'quantity': signed_quantity,
                'price': fill_price,
                'pnl': realised_pnl,
                'position_before': previous_position,
                'position_after': new_position,
            }
        )

        # Update session tracking
        self.last_trade_timestamp = timestamp
        self.session_trades += 1

        # Record trade in professional safeguards
        if self.safeguards:
            self.safeguards.record_trade(timestamp, symbol)

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
        """
        ENHANCED: Save FSD Q-values, statistics, and per-symbol performance.

        P0-NEW-2 Fix: Uses atomic writes to prevent Q-value corruption on crash.
        """
        import logging
        from pathlib import Path

        from .persistence import _atomic_write_json

        logger = logging.getLogger(__name__)

        # Check Q-table size and log warnings if needed
        q_table_info = self.rl_agent.check_q_table_size()
        if q_table_info['level'] != 'normal':
            level = q_table_info['level']
            message = (
                f"Q-table diagnostics: states={q_table_info['num_states']:,}, "
                f"estimated_mem={q_table_info['estimated_memory_mb']:.1f} MB, level={level}"
            )
            if level == 'low':
                logger.debug(message)
            elif level == 'medium':
                logger.info(message)
            else:  # high or critical
                logger.warning(message)

        # Apply Q-value decay before saving (regime adaptation)
        decay_info = self.rl_agent.apply_q_value_decay()

        # Log decay operation if it occurred
        if decay_info.get('enabled') and not decay_info.get('first_run') and not decay_info.get('skipped'):
            if decay_info.get('clamped'):
                logger.warning(
                    f"Q-value decay applied (CLAMPED): {decay_info['states_decayed']} states, "
                    f"factor={decay_info['decay_factor']:.6f}, "
                    f"days={decay_info['days_elapsed']:.2f} (original: {decay_info['original_days_elapsed']:.2f})"
                )
            else:
                logger.info(
                    f"Q-value decay applied: {decay_info['states_decayed']} states, "
                    f"factor={decay_info['decay_factor']:.6f}, days={decay_info['days_elapsed']:.2f}"
                )
        elif decay_info.get('skipped'):
            logger.debug(f"Q-value decay skipped: {decay_info.get('reason', 'unknown')}")

        state = {
            'q_values': self.rl_agent.q_values,
            'total_trades': self.rl_agent.total_trades,
            'winning_trades': self.rl_agent.winning_trades,
            'total_pnl': self.rl_agent.total_pnl,
            'exploration_rate': self.rl_agent.exploration_rate,
            # NEW: Per-symbol performance for adaptive trading
            'symbol_performance': self.symbol_performance,
            # Q-value decay timestamp for regime adaptation
            'last_decay_timestamp': self.rl_agent.last_decay_timestamp.isoformat()
            if self.rl_agent.last_decay_timestamp
            else None,
        }

        # P0-NEW-2 Fix: Use atomic write instead of direct json.dump()
        _atomic_write_json(state, Path(filepath))

    def load_state(self, filepath: str):
        """
        ENHANCED: Load FSD Q-values, statistics, and per-symbol performance.

        P0-NEW-2 Fix: Attempts backup file if primary is corrupted.
        """
        from pathlib import Path

        try:
            path = Path(filepath)
            backup_path = path.with_suffix('.backup')

            # P0-NEW-2 Fix: Try primary file first, fall back to backup if corrupted
            payload_obj: object = None

            # Try primary file
            if path.exists():
                try:
                    with open(path) as f:
                        payload_obj = json.load(f)
                except json.JSONDecodeError:
                    # Primary corrupted, will try backup
                    pass

            # If primary failed or doesn't exist, try backup
            if payload_obj is None and backup_path.exists():
                try:
                    with open(backup_path) as f:
                        payload_obj = json.load(f)
                except json.JSONDecodeError:
                    # Both corrupted - start fresh
                    return False

            if payload_obj is None:
                return False  # No files found or all corrupted

            payload: dict[str, object] = cast(dict[str, object], payload_obj) if isinstance(payload_obj, dict) else {}
            q_values_obj: object = payload.get('q_values', {})
            if isinstance(q_values_obj, dict):
                # P1-1 Fix: Convert loaded dict to OrderedDict for LRU eviction
                self.rl_agent.q_values = OrderedDict(q_values_obj)  # type: ignore[arg-type]
            else:
                self.rl_agent.q_values = OrderedDict()

            tt_obj: object = payload.get('total_trades', 0)
            self.rl_agent.total_trades = int(tt_obj) if isinstance(tt_obj, (int, float)) else 0

            tw_obj: object = payload.get('winning_trades', 0)
            self.rl_agent.winning_trades = int(tw_obj) if isinstance(tw_obj, (int, float)) else 0

            pnl_obj: object = payload.get('total_pnl', 0.0)
            self.rl_agent.total_pnl = float(pnl_obj) if isinstance(pnl_obj, (int, float)) else 0.0

            er_obj: object = payload.get('exploration_rate', self.config.exploration_rate)
            self.rl_agent.exploration_rate = (
                float(er_obj) if isinstance(er_obj, (int, float)) else self.config.exploration_rate
            )

            # NEW: Restore per-symbol performance
            sp_obj: object = payload.get('symbol_performance', {})
            self.symbol_performance = sp_obj if isinstance(sp_obj, dict) else {}

            # Restore Q-value decay timestamp (regime adaptation)
            ldt_obj: object = payload.get('last_decay_timestamp')
            if ldt_obj and isinstance(ldt_obj, str):
                try:
                    self.rl_agent.last_decay_timestamp = datetime.fromisoformat(ldt_obj)
                except (ValueError, TypeError):
                    self.rl_agent.last_decay_timestamp = None
            else:
                self.rl_agent.last_decay_timestamp = None

            return True
        except (FileNotFoundError, json.JSONDecodeError):
            return False

    def start_session(self) -> dict[str, Any]:
        """
        Start a new trading session.

        Returns:
            Session initialization stats
        """
        self.session_start_time = datetime.now(timezone.utc)
        self.session_trades = 0

        return {
            'session_start': self.session_start_time.isoformat(),
            'q_values_count': len(self.rl_agent.q_values),
            'exploration_rate': self.rl_agent.exploration_rate,
            'total_trades_all_time': self.rl_agent.total_trades,
        }

    def end_session(self) -> dict[str, Any]:
        """
        End trading session and return stats.

        Returns:
            Session summary statistics
        """
        if not self.session_start_time:
            return {}

        session_duration = datetime.now(timezone.utc) - self.session_start_time

        return {
            'session_duration_seconds': session_duration.total_seconds(),
            'session_trades': self.session_trades,
            'q_values_learned': len(self.rl_agent.q_values),
            'exploration_rate': self.rl_agent.exploration_rate,
            'total_pnl': self.rl_agent.total_pnl,
        }

    def warmup_from_historical(
        self, historical_bars: dict[str, list[Bar]], observation_fraction: float = 0.5
    ) -> dict[str, Any]:
        """
        Warm up the RL agent with realistic simulation and learning.

        Processes historical data to pre-train Q-values before live trading.
        Uses lower confidence threshold (40%) and higher exploration (20%) during warmup.

        Args:
            historical_bars: Mapping of symbol -> list[Bar]
            observation_fraction: Fraction used for observation-only (0.5 = 50% observe, 50% trade)

        Returns:
            Dict with keys: total_bars_processed, q_values_learned, simulated_trades,
            simulated_win_rate, simulated_pnl
        """
        if not historical_bars:
            return {
                'status': 'no_data',
                'total_bars_processed': 0,
                'q_values_learned': len(self.rl_agent.q_values),
                'simulated_trades': 0,
                'simulated_win_rate': 0.0,
                'simulated_pnl': 0.0,
            }

        total_bars_processed = 0
        states_discovered = 0
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
            total_bars_processed += n
            observe_upto = max(20, int(n * observation_fraction))

            # Observation phase: discover states
            for i in range(20, observe_upto, 5):  # Step by 5 for efficiency
                window = bars[i - 20 : i + 1]
                state_dict: dict[str, Any] = self.extract_state(symbol, window, {symbol: window[-1].close})
                if state_dict:
                    state_hash = self.rl_agent.hash_state(state_dict)
                    if state_hash not in self.rl_agent.q_values:
                        self.rl_agent.q_values[state_hash] = dict.fromkeys(self.rl_agent.get_actions(), 0.0)
                        states_discovered += 1

            # Simulation phase: trade and learn
            for i in range(max(20, observe_upto), n - 1, 2):  # Step by 2 for efficiency
                window = bars[i - 20 : i + 1]
                current_price_decimal = window[-1].close
                next_price_decimal = bars[i + 1].close
                current_price = float(current_price_decimal)
                next_bar_price = float(next_price_decimal)

                state2: dict[str, Any] = self.extract_state(symbol, window, {symbol: current_price_decimal})
                if not state2:
                    continue

                action_type = self.rl_agent.select_action(state2, training=True)
                confidence = self.rl_agent.get_confidence(state2, action_type)
                self.last_state = state2
                self.last_action = action_type

                if (
                    action_type not in ['BUY', 'SELL', 'INCREASE_SIZE', 'DECREASE_SIZE']
                    or confidence < warmup_threshold
                ):
                    continue

                current_position = sim_positions.get(symbol, 0.0)

                if action_type in ['BUY', 'INCREASE_SIZE']:
                    max_spend = sim_cash * 0.05
                    quantity = max_spend / current_price if current_price > 0 else 0
                    if quantity > 0:
                        sim_positions[symbol] = current_position + quantity
                        sim_cash -= quantity * current_price
                        simulated_trades += 1

                elif action_type in ['SELL', 'DECREASE_SIZE'] and abs(current_position) > 0.001:
                    quantity_to_sell = abs(current_position) * 0.5
                    realised_pnl = (next_bar_price - current_price) * quantity_to_sell
                    sim_positions[symbol] = current_position - quantity_to_sell
                    sim_cash += quantity_to_sell * next_bar_price
                    simulated_pnl += realised_pnl
                    simulated_trades += 1

                    if realised_pnl > 0:
                        simulated_wins += 1

                    # Learn from trade
                    reward = self._calculate_reward(realised_pnl, current_price, quantity_to_sell)
                    next_state2: dict[str, Any] = self.extract_state(
                        symbol, bars[i - 19 : i + 2], {symbol: next_price_decimal}
                    )
                    if next_state2:
                        self.rl_agent.update_q_value(
                            state=state2,
                            action=action_type,
                            reward=reward,
                            next_state=next_state2,
                            done=(abs(sim_positions.get(symbol, 0.0)) < 0.001),
                        )
        # Restore exploration rate to its original value
        self.rl_agent.exploration_rate = original_exploration

        simulated_win_rate = (simulated_wins / simulated_trades) if simulated_trades > 0 else 0.0

        return {
            'status': 'complete',
            'total_bars_processed': total_bars_processed,
            'q_values_learned': len(self.rl_agent.q_values),
            'simulated_trades': simulated_trades,
            'simulated_win_rate': simulated_win_rate,
            'simulated_pnl': simulated_pnl,
            # Keep legacy fields for backward compatibility
            'states_discovered': states_discovered,
        }
