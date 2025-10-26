"""
FSD (Full Self-Driving) AI Trading Mode

Tesla-style autonomous trading with continuous reinforcement learning.
Only 2 hard constraints: max_capital, time_limit.
Everything else is self-determined by the AI.

The AI:
- Learns from every trade (good or bad)
- Chooses which stocks to trade (market scanner)
- Decides when to trade (confidence scoring)
- Can choose NOT to trade
- Saves state between sessions (persistent learning)
- Has access to ALL BOT features but makes decisions autonomously
"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .data import Bar
from .logging import configure_logger
from .ml.features import extract_features
from .ml.model import LogisticRegressionModel, load_model
from .portfolio import Portfolio


@dataclass(frozen=True)
class FSDConfig:
    """
    Configuration for FSD AI mode.

    Only 2 HARD constraints:
    - max_capital: Maximum capital AI can deploy
    - time_limit_minutes: Time window for trading (e.g., 1min, 5min, 30min bars)

    Everything else is learned/adjusted by the AI.
    """

    max_capital: float  # HARD CONSTRAINT: Cannot exceed
    time_limit_minutes: int  # HARD CONSTRAINT: Must trade within this timeframe

    # AI Learning Parameters (soft - AI can adjust these)
    learning_rate: float = 0.001
    discount_factor: float = 0.95
    exploration_rate: float = 0.20
    exploration_decay: float = 0.995
    min_exploration_rate: float = 0.01
    experience_buffer_size: int = 10000
    batch_size: int = 32

    # Market Scanner Settings
    max_stocks_to_scan: int = 500
    min_liquidity_volume: int = 100000
    min_price: float = 1.0
    max_price: float = 10000.0

    # Confidence Thresholds (AI learns optimal values)
    initial_confidence_threshold: float = 0.60

    # State Persistence
    state_save_path: str = "state/fsd/ai_state.json"
    experience_buffer_path: str = "state/fsd/experience_buffer.json"
    performance_history_path: str = "state/fsd/performance_history.json"

    # ML Model Integration
    ml_model_path: str | None = None  # Path to trained ML model (optional)

    # Trade Deadline (Urgency Mode)
    trade_deadline_minutes: int | None = None  # e.g., 60 = must trade within 1 hour (per session)
    trade_deadline_stress_enabled: bool = True  # Enable threshold lowering as deadline approaches


@dataclass
class Trade:
    """Represents a completed trade for RL learning."""

    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    quantity: float
    pnl: float
    confidence: float
    features: dict[str, float]
    size_fraction: float = 0.0
    confidence_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class Experience:
    """RL experience tuple (state, action, reward, next_state)."""
    state: dict[str, float]
    action: dict[str, Any]  # {'symbol': str, 'side': 'buy'/'sell', 'size': float}
    reward: float
    next_state: dict[str, float]
    done: bool


class ConfidenceScorer:
    """
    Multi-factor confidence scoring system.

    Analyzes:
    - Technical indicators
    - Price action (candlestick patterns)
    - Volume profile
    - Historical performance
    - ML model prediction

    Output: Confidence score 0.0 to 1.0
    """

    def __init__(self, ml_model_path: str | None = None):
        self.logger = configure_logger("ConfidenceScorer", structured=True)
        self.ml_model: LogisticRegressionModel | None = None

        # Load ML model if path provided
        if ml_model_path:
            try:
                model_path = Path(ml_model_path).expanduser()
                if model_path.exists():
                    self.ml_model = load_model(str(model_path))
                    self.logger.info(
                        "ml_model_loaded",
                        extra={"path": str(model_path), "features": len(self.ml_model.feature_names)}
                    )
                else:
                    self.logger.warning("ml_model_not_found", extra={"path": str(model_path)})
            except Exception as exc:
                self.logger.error("ml_model_load_failed", extra={"path": ml_model_path, "error": str(exc)})

    def score(self, symbol: str, bars: list[Bar], portfolio: Portfolio) -> dict[str, float]:
        """
        Calculate confidence score for trading a symbol.

        Returns:
            {
                'total_confidence': 0.0-1.0,
                'technical_score': 0.0-1.0,
                'price_action_score': 0.0-1.0,
                'volume_score': 0.0-1.0,
                'ml_score': 0.0-1.0
            }
        """
        if len(bars) < 20:
            return {'total_confidence': 0.0}

        scores = {}

        # Technical indicators
        scores['technical_score'] = self._score_technicals(bars)

        # Price action (candlestick patterns)
        scores['price_action_score'] = self._score_price_action(bars)

        # Volume profile
        scores['volume_score'] = self._score_volume(bars)

        # ML model prediction (simple momentum for now)
        scores['ml_score'] = self._score_ml_prediction(bars)

        # Weighted average (ALL algorithms used)
        # TODO: Dynamic weight adjustment based on algorithm performance
        # For now, weights are static but Q-learning implicitly learns which signals to trust
        weights = {
            'technical_score': 0.30,
            'price_action_score': 0.25,
            'volume_score': 0.20,
            'ml_score': 0.25,
        }

        total = sum(scores[k] * weights[k] for k in weights if k in scores)
        scores['total_confidence'] = max(0.0, min(1.0, total))

        return scores

    @staticmethod
    def _score_technicals(bars: list[Bar]) -> float:
        """Score based on technical indicators (SMA, RSI approximation)."""
        closes = [float(b.close) for b in bars[-20:]]

        # Simple Moving Average trend
        sma_short = sum(closes[-5:]) / 5
        sma_long = sum(closes[-20:]) / 20

        if sma_short > sma_long:
            trend_score = 0.7
        elif sma_short < sma_long * 0.98:
            trend_score = 0.3
        else:
            trend_score = 0.5

        # Price relative to SMA
        current_price = closes[-1]
        distance_from_sma = (current_price - sma_long) / sma_long

        # Prefer prices near SMA (not too extended)
        if abs(distance_from_sma) < 0.02:
            position_score = 0.8
        elif abs(distance_from_sma) < 0.05:
            position_score = 0.6
        else:
            position_score = 0.4

        return (trend_score + position_score) / 2

    @staticmethod
    def _score_price_action(bars: list[Bar]) -> float:
        """Score based on candlestick patterns."""
        if len(bars) < 3:
            return 0.5

        last_3 = bars[-3:]
        scores = []

        for bar in last_3:
            body = abs(float(bar.close) - float(bar.open))
            total_range = float(bar.high) - float(bar.low)

            if total_range == 0:
                scores.append(0.5)
                continue

            body_ratio = body / total_range

            # Strong body = conviction
            if body_ratio > 0.7:
                scores.append(0.8)
            elif body_ratio > 0.5:
                scores.append(0.6)
            else:
                scores.append(0.4)

        return sum(scores) / len(scores)

    @staticmethod
    def _score_volume(bars: list[Bar]) -> float:
        """Score based on volume profile."""
        if len(bars) < 10:
            return 0.5

        volumes = [float(b.volume) for b in bars[-10:]]
        avg_volume = sum(volumes[:-1]) / (len(volumes) - 1)

        if avg_volume == 0:
            return 0.5

        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume

        # Higher than average volume = more conviction
        if volume_ratio > 1.5:
            return 0.9
        elif volume_ratio > 1.2:
            return 0.7
        elif volume_ratio > 0.8:
            return 0.6
        else:
            return 0.4

    def _score_ml_prediction(self, bars: list[Bar], lookback: int = 30) -> float:
        """
        Score based on trained ML model prediction.

        If ML model is loaded, uses real predictions.
        Otherwise, falls back to simple momentum calculation.
        """
        # Use trained ML model if available
        if self.ml_model is not None:
            try:
                features = extract_features(bars, lookback=lookback)
                if features is None:
                    return 0.5  # Not enough data

                # Get probability of upward movement
                prob_up = self.ml_model.predict_proba(features)

                # Convert to confidence score (0.5 = neutral, 0.0/1.0 = extremes)
                # prob_up > 0.5 = bullish, prob_up < 0.5 = bearish
                return float(prob_up)

            except Exception as exc:
                self.logger.warning("ml_prediction_failed", extra={"error": str(exc)})
                # Fall through to momentum fallback

        # Fallback: Simple momentum if no ML model
        if len(bars) < 10:
            return 0.5

        closes = [float(b.close) for b in bars[-10:]]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        avg_return = sum(returns) / len(returns)

        # Positive momentum = higher score
        if avg_return > 0.01:
            return 0.8
        elif avg_return > 0:
            return 0.6
        elif avg_return > -0.01:
            return 0.4
        else:
            return 0.2


class ReinforcementLearner:
    """
    Simple Q-learning based RL agent.

    Learns optimal trading policy from experience:
    - State: market features (price, volume, indicators)
    - Action: {trade/no-trade, symbol, size}
    - Reward: PnL from trade
    """

    def __init__(self, config: FSDConfig):
        self.config = config
        self.logger = configure_logger("RLAgent", structured=True)

        # Q-table approximation (simple dict for now)
        self.q_values: dict[str, float] = {}

        # Experience replay buffer
        self.experience_buffer: deque[Experience] = deque(maxlen=config.experience_buffer_size)

        # Learning parameters
        self.learning_rate = config.learning_rate
        self.discount_factor = config.discount_factor
        self.exploration_rate = config.exploration_rate

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0

    def get_action(self, state: dict[str, float], available_symbols: list[str]) -> dict[str, Any]:
        """
        Choose action based on current state (epsilon-greedy).

        Returns:
            {'trade': bool, 'symbol': str or None, 'size_fraction': float}
        """
        # Exploration: random action
        if random.random() < self.exploration_rate:
            return self._random_action(available_symbols)

        # Exploitation: best known action
        return self._best_action(state, available_symbols)

    @staticmethod
    def _random_action(available_symbols: list[str]) -> dict[str, Any]:
        """Random exploration action."""
        # 50% chance to not trade
        if random.random() < 0.5:
            return {'trade': False, 'symbol': None, 'size_fraction': 0.0}

        # Random symbol and size
        symbol = random.choice(available_symbols) if available_symbols else None
        size_fraction = random.uniform(0.05, 0.30)

        return {'trade': True, 'symbol': symbol, 'size_fraction': size_fraction}

    def _best_action(self, state: dict[str, float], available_symbols: list[str]) -> dict[str, Any]:
        """Choose best action based on learned Q-values."""
        if not available_symbols:
            return {'trade': False, 'symbol': None, 'size_fraction': 0.0}

        best_symbol = None
        best_q = float('-inf')

        for symbol in available_symbols:
            state_key = self._state_key(state, symbol)
            q_value = self.q_values.get(state_key, 0.0)

            if q_value > best_q:
                best_q = q_value
                best_symbol = symbol

        # If best Q-value is negative, don't trade
        if best_q < 0:
            return {'trade': False, 'symbol': None, 'size_fraction': 0.0}

        # Trade with learned size (clamped to safe range)
        size_fraction = min(0.30, max(0.05, best_q / 10.0))

        return {'trade': True, 'symbol': best_symbol, 'size_fraction': size_fraction}

    def learn_from_trade(self, trade: Trade) -> None:
        """Update Q-values based on completed trade."""
        state_key = self._state_key(trade.features, trade.symbol)

        # Current Q-value
        current_q = self.q_values.get(state_key, 0.0)

        # Reward = PnL
        reward = trade.pnl

        # Update Q-value (simple Q-learning update)
        new_q = current_q + self.learning_rate * (reward - current_q)
        self.q_values[state_key] = new_q

        # Capture experience
        experience = Experience(
            state=dict(trade.features),
            action={"symbol": trade.symbol, "size_fraction": trade.size_fraction},
            reward=trade.pnl,
            next_state=dict(trade.features),
            done=True,
        )
        self.experience_buffer.append(experience)
        self._replay()

        # Update stats
        self.total_trades += 1
        if trade.pnl > 0:
            self.winning_trades += 1
        self.total_pnl += trade.pnl

        # Decay exploration rate
        self.exploration_rate = max(
            self.config.min_exploration_rate,
            self.exploration_rate * self.config.exploration_decay,
        )

        self.logger.info(
            "learned_from_trade",
            extra={
                "symbol": trade.symbol,
                "pnl": trade.pnl,
                "new_q": new_q,
                "exploration_rate": self.exploration_rate,
                "total_trades": self.total_trades,
                "win_rate": self.winning_trades / self.total_trades if self.total_trades > 0 else 0,
            },
        )

    def _replay(self) -> None:
        """Sample past experiences to reinforce learning."""
        if not self.experience_buffer:
            return

        sample_size = min(self.config.batch_size, len(self.experience_buffer))
        batch = random.sample(list(self.experience_buffer), sample_size)

        for exp in batch:
            symbol = exp.action.get("symbol")
            if not symbol:
                continue
            state_key = self._state_key(exp.state, symbol)
            current_q = self.q_values.get(state_key, 0.0)

            target = exp.reward
            if not exp.done and exp.next_state:
                future_q = self.q_values.get(self._state_key(exp.next_state, symbol), 0.0)
                target = exp.reward + self.discount_factor * future_q

            updated_q = current_q + self.learning_rate * (target - current_q)
            self.q_values[state_key] = updated_q

    @staticmethod
    def _state_key(state: dict[str, float], symbol: str) -> str:
        """Create hashable state key."""
        # Discretize continuous values
        discretized = {
            k: round(v, 2) for k, v in state.items()
        }
        return f"{symbol}_{json.dumps(discretized, sort_keys=True)}"

    def save_state(self, path: Path) -> None:
        """Save learned Q-values."""
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "q_values": self.q_values,
            "exploration_rate": self.exploration_rate,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": self.total_pnl,
        }
        with path.open("w") as f:
            json.dump(state, f, indent=2)
        self.logger.info("rl_state_saved", extra={"path": str(path), "q_values_count": len(self.q_values)})

    def load_state(self, path: Path) -> None:
        """Load learned Q-values from previous session."""
        if not path.exists():
            self.logger.info("no_previous_rl_state", extra={"path": str(path)})
            return

        with path.open("r") as f:
            state = json.load(f)

        self.q_values = state.get("q_values", {})
        self.exploration_rate = state.get("exploration_rate", self.config.exploration_rate)
        self.total_trades = state.get("total_trades", 0)
        self.winning_trades = state.get("winning_trades", 0)
        self.total_pnl = state.get("total_pnl", 0.0)

        self.logger.info(
            "rl_state_loaded",
            extra={
                "path": str(path),
                "q_values_count": len(self.q_values),
                "total_trades": self.total_trades,
                "win_rate": self.winning_trades / self.total_trades if self.total_trades > 0 else 0,
            },
        )


class FSDEngine:
    """
    Full Self-Driving AI Trading Engine.

    Only 2 HARD constraints:
    - max_capital: Cannot exceed this amount
    - time_limit_minutes: Must trade within this timeframe

    Everything else (symbol selection, position sizing, entry/exit timing)
    is autonomously determined by the AI based on continuous learning.
    """

    def __init__(self, config: FSDConfig, portfolio: Portfolio):
        self.config = config
        self.portfolio = portfolio
        self.logger = configure_logger("FSDEngine", structured=True)

        # Core AI components
        self.confidence_scorer = ConfidenceScorer(ml_model_path=config.ml_model_path)
        self.rl_agent = ReinforcementLearner(config)
        self.rl_agent.load_state(Path(config.state_save_path).expanduser())

        # Runtime state
        self._last_prices: dict[str, Decimal] = {}
        self.pending_intents: dict[str, dict[str, Any]] = {}
        self.open_positions: dict[str, dict[str, Any]] = {}
        self.trade_history: list[Trade] = []
        self.performance_history: list[dict[str, Any]] = []

        self._load_experience_buffer()
        self._load_performance_history()

        self.last_trade_timestamp: datetime | None = None

        # Session tracking
        self.session_start: datetime | None = None
        self.session_trades: list[Trade] = []

    def start_session(self) -> dict[str, Any]:
        """Start FSD trading session."""
        self.session_start = datetime.now(timezone.utc)
        self.session_trades = []
        self.pending_intents.clear()
        self.last_trade_timestamp = None

        session_state = {
            "session_start": self.session_start.isoformat(),
            "max_capital": self.config.max_capital,
            "time_limit_minutes": self.config.time_limit_minutes,
            "exploration_rate": self.rl_agent.exploration_rate,
            "q_values_learned": len(self.rl_agent.q_values),
            "experience_buffer": len(self.rl_agent.experience_buffer),
        }
        return session_state

    def can_trade(self) -> bool:
        """Check if within time limit constraint."""
        if self.session_start is None:
            return True

        elapsed = (datetime.now(timezone.utc) - self.session_start).total_seconds() / 60
        return elapsed < self.config.time_limit_minutes

    def evaluate_opportunity(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
    ) -> dict[str, Any]:
        """
        Evaluate trading opportunity for a symbol.

        Returns:
            {
                'should_trade': bool,
                'confidence': float,
                'confidence_breakdown': dict,
                'action': dict,  # From RL agent
                'reason': str,
                'state': dict,
            }
        """
        self._last_prices = last_prices

        if not bars:
            return {
                'should_trade': False,
                'confidence': 0.0,
                'confidence_breakdown': {},
                'action': {'trade': False, 'symbol': None, 'size_fraction': 0.0},
                'reason': 'insufficient_market_data',
                'state': {},
            }

        last_price = float(bars[-1].close)
        if last_price < self.config.min_price or last_price > self.config.max_price:
            return {
                'should_trade': False,
                'confidence': 0.0,
                'confidence_breakdown': {},
                'action': {'trade': False, 'symbol': None, 'size_fraction': 0.0},
                'reason': 'price_out_of_bounds',
                'state': {},
            }

        if len(bars) >= 5:
            avg_volume = sum(float(b.volume) for b in bars[-5:]) / 5
            if avg_volume < self.config.min_liquidity_volume:
                return {
                    'should_trade': False,
                    'confidence': 0.0,
                    'confidence_breakdown': {},
                    'action': {'trade': False, 'symbol': None, 'size_fraction': 0.0},
                    'reason': 'insufficient_liquidity',
                    'state': {},
                }

        # Get confidence scores
        confidence_scores = self.confidence_scorer.score(symbol, bars, self.portfolio)
        total_confidence = confidence_scores.get('total_confidence', 0.0)

        # Extract state features for RL agent
        state = self._extract_state_features(symbol, bars, confidence_scores)

        # Calculate effective threshold (with trade deadline stress if applicable)
        effective_threshold = self.config.initial_confidence_threshold
        stress_factor = 0.0
        time_remaining = None

        # Trade Deadline Stress: Lower threshold if approaching deadline with no trades
        if (
            self.config.trade_deadline_minutes is not None
            and self.config.trade_deadline_stress_enabled
            and self.session_start is not None
        ):
            elapsed_minutes = (datetime.now(timezone.utc) - self.session_start).total_seconds() / 60
            time_remaining = self.config.trade_deadline_minutes - elapsed_minutes

            # Only apply stress if:
            # 1. Still within deadline (time_remaining > 0)
            # 2. No trades made yet this session (len(self.session_trades) == 0)
            if time_remaining > 0 and len(self.session_trades) == 0:
                # Stress factor increases as deadline approaches (0.0 to 1.0)
                stress_factor = 1.0 - (time_remaining / self.config.trade_deadline_minutes)

                # Lower threshold based on stress (max 80% reduction)
                # e.g., threshold = 0.45 * (1 - 0.8 * 0.9) = 0.126 when 90% through deadline
                effective_threshold = self.config.initial_confidence_threshold * (1.0 - stress_factor * 0.8)

                self.logger.info(
                    "trade_deadline_stress_active",
                    extra={
                        "time_remaining_minutes": round(time_remaining, 2),
                        "stress_factor": round(stress_factor, 3),
                        "original_threshold": self.config.initial_confidence_threshold,
                        "effective_threshold": round(effective_threshold, 3),
                        "trades_this_session": len(self.session_trades),
                        "confidence": round(total_confidence, 3),
                    }
                )

        if total_confidence < effective_threshold:
            return {
                'should_trade': False,
                'confidence': total_confidence,
                'confidence_breakdown': confidence_scores,
                'action': {'trade': False, 'symbol': None, 'size_fraction': 0.0},
                'reason': 'confidence_below_threshold',
                'state': state,
                'trade_deadline_stress': {
                    'enabled': self.config.trade_deadline_stress_enabled,
                    'time_remaining': time_remaining,
                    'stress_factor': stress_factor,
                    'effective_threshold': effective_threshold,
                } if self.config.trade_deadline_minutes is not None else None,
            }

        # Get RL agent's action
        action = self.rl_agent.get_action(state, [symbol])

        # Check constraints
        if not self.can_trade():
            return {
                'should_trade': False,
                'confidence': total_confidence,
                'confidence_breakdown': confidence_scores,
                'action': action,
                'reason': 'time_limit_exceeded',
                'state': state,
            }

        # Check capital constraint
        available_capital = self._available_capital()
        if available_capital <= 0:
            return {
                'should_trade': False,
                'confidence': total_confidence,
                'confidence_breakdown': confidence_scores,
                'action': action,
                'reason': 'max_capital_deployed',
                'state': state,
            }

        # AI decided not to trade
        if not action['trade']:
            return {
                'should_trade': False,
                'confidence': total_confidence,
                'confidence_breakdown': confidence_scores,
                'action': action,
                'reason': 'ai_chose_no_trade',
                'state': state,
            }

        # AI wants to trade
        return {
            'should_trade': True,
            'confidence': total_confidence,
            'confidence_breakdown': confidence_scores,
            'action': action,
            'reason': 'ai_approved',
            'available_capital': available_capital,
            'state': state,
        }

    def _extract_state_features(
        self,
        symbol: str,
        bars: list[Bar],
        confidence_scores: dict[str, float],
    ) -> dict[str, float]:
        """Extract state features for RL agent."""
        if len(bars) < 10:
            return {}

        closes = [float(b.close) for b in bars[-10:]]
        volumes = [float(b.volume) for b in bars[-10:]]

        return {
            'confidence': confidence_scores.get('total_confidence', 0.0),
            'technical_score': confidence_scores.get('technical_score', 0.0),
            'price_change_pct': (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0.0,
            'volatility': (max(closes) - min(closes)) / closes[0] if closes[0] > 0 else 0.0,
            'volume_ratio': volumes[-1] / (sum(volumes[:-1]) / len(volumes[:-1])) if len(volumes) > 1 and sum(volumes[:-1]) > 0 else 1.0,
            'portfolio_utilization': self._portfolio_utilization(),
        }

    def _available_capital(self) -> float:
        """Calculate available capital (respecting max_capital constraint)."""
        if self.config.max_capital <= 0:
            return 0.0
        if not self._last_prices:
            equity = float(self.portfolio.cash)
        else:
            equity = float(self.portfolio.total_equity(self._last_prices))
        cash = float(self.portfolio.cash)
        deployed = max(0.0, equity - cash)
        available = self.config.max_capital - deployed
        return max(0.0, available)

    def _portfolio_utilization(self) -> float:
        """Calculate portfolio utilization fraction."""
        if self.config.max_capital <= 0:
            return 0.0
        if not self._last_prices:
            equity = float(self.portfolio.cash)
        else:
            equity = float(self.portfolio.total_equity(self._last_prices))
        cash = float(self.portfolio.cash)
        deployed = max(0.0, equity - cash)
        return min(1.0, deployed / self.config.max_capital)

    def register_trade_intent(
        self,
        symbol: str,
        *,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        """Persist intent metadata so fills can be tied back to the AI decision."""

        intent = {
            "timestamp": timestamp.isoformat(),
            "confidence": float(decision.get('confidence', 0.0)),
            "confidence_breakdown": decision.get('confidence_breakdown', {}),
            "state": decision.get('state', {}),
            "reason": decision.get('reason'),
            "size_fraction": float(decision.get('action', {}).get('size_fraction', 0.0)),
            "target_notional": float(target_notional),
            "target_quantity": float(target_quantity),
            "available_capital": float(decision.get('available_capital', 0.0)) if decision.get('available_capital') is not None else None,
        }
        self.pending_intents[symbol] = intent
        self.logger.debug(
            "fsd_intent_registered",
            extra={"symbol": symbol, "size_fraction": intent["size_fraction"], "confidence": intent["confidence"]},
        )

    def handle_fill(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        """Update position/trade tracking when the broker confirms a fill."""

        state = self.open_positions.setdefault(
            symbol,
            {
                "is_open": False,
                "realised_pnl": 0.0,
                "entry_quantity": 0.0,
                "peak_quantity": 0.0,
            },
        )

        state['realised_pnl'] = state.get('realised_pnl', 0.0) + realised_pnl

        intent = self.pending_intents.pop(symbol, None)

        entering_position = abs(previous_position) == 0 and abs(new_position) > 0
        closing_position = abs(new_position) == 0 and state.get('is_open')

        if entering_position:
            position = self.portfolio.position(symbol)
            state.update(
                {
                    "is_open": True,
                    "entry_time": timestamp,
                    "entry_price": float(position.average_price),
                    "entry_quantity": abs(new_position),
                    "peak_quantity": abs(new_position),
                    "confidence": float(intent.get('confidence', 0.0)) if intent else 0.0,
                    "features": intent.get('state', {}) if intent else {},
                    "confidence_breakdown": intent.get('confidence_breakdown', {}) if intent else {},
                    "size_fraction": float(intent.get('size_fraction', 0.0)) if intent else 0.0,
                    "reason": intent.get('reason') if intent else None,
                }
            )
            if intent is None:
                self.logger.warning(
                    "fsd_missing_intent_for_fill",
                    extra={"symbol": symbol, "timestamp": timestamp.isoformat(), "quantity": new_position},
                )
        else:
            if abs(new_position) > state.get('peak_quantity', 0.0):
                state['peak_quantity'] = abs(new_position)
            if abs(new_position) > 0:
                position = self.portfolio.position(symbol)
                state['entry_price'] = float(position.average_price)

        if closing_position:
            trade = Trade(
                symbol=symbol,
                entry_time=state.get('entry_time', timestamp),
                entry_price=state.get('entry_price', fill_price),
                exit_time=timestamp,
                exit_price=fill_price,
                quantity=state.get('peak_quantity', abs(signed_quantity)),
                pnl=state.get('realised_pnl', realised_pnl),
                confidence=state.get('confidence', 0.0),
                features=state.get('features', {}),
                size_fraction=state.get('size_fraction', 0.0),
                confidence_breakdown=state.get('confidence_breakdown', {}),
            )
            self.record_trade_outcome(trade)
            self.open_positions[symbol] = {
                "is_open": False,
                "realised_pnl": 0.0,
                "entry_quantity": 0.0,
                "peak_quantity": 0.0,
            }
        else:
            self.open_positions[symbol] = state

    def _load_experience_buffer(self) -> None:
        path = Path(self.config.experience_buffer_path).expanduser()
        if not path.exists():
            return
        try:
            with path.open("r") as f:
                payload = json.load(f)
        except Exception as exc:
            self.logger.error("fsd_experience_load_failed", extra={"path": str(path), "error": str(exc)})
            return

        for item in payload:
            experience = Experience(
                state=item.get("state", {}),
                action=item.get("action", {}),
                reward=float(item.get("reward", 0.0)),
                next_state=item.get("next_state", {}),
                done=bool(item.get("done", True)),
            )
            self.rl_agent.experience_buffer.append(experience)

        self.logger.info(
            "fsd_experience_loaded",
            extra={"path": str(path), "count": len(self.rl_agent.experience_buffer)},
        )

    def _save_experience_buffer(self) -> None:
        path = Path(self.config.experience_buffer_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        serialised = [
            {
                "state": exp.state,
                "action": exp.action,
                "reward": exp.reward,
                "next_state": exp.next_state,
                "done": exp.done,
            }
            for exp in list(self.rl_agent.experience_buffer)
        ]
        with path.open("w") as f:
            json.dump(serialised, f, indent=2)
        self.logger.debug(
            "fsd_experience_saved",
            extra={"path": str(path), "count": len(serialised)},
        )

    def _load_performance_history(self) -> None:
        path = Path(self.config.performance_history_path).expanduser()
        if not path.exists():
            return
        try:
            with path.open("r") as f:
                payload = json.load(f)
        except Exception as exc:
            self.logger.error("fsd_performance_load_failed", extra={"path": str(path), "error": str(exc)})
            return

        if isinstance(payload, list):
            self.performance_history.extend(payload[-1000:])
        self.logger.info(
            "fsd_performance_loaded",
            extra={"path": str(path), "count": len(self.performance_history)},
        )

    def _save_performance_history(self) -> None:
        path = Path(self.config.performance_history_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(self.performance_history[-1000:], f, indent=2)
        self.logger.debug(
            "fsd_performance_saved",
            extra={"path": str(path), "count": len(self.performance_history[-1000:])},
        )

    def record_trade_outcome(self, trade: Trade) -> None:
        """Record trade outcome and learn from it."""
        self.rl_agent.learn_from_trade(trade)
        self.session_trades.append(trade)
        self.trade_history.append(trade)
        self.performance_history.append(
            {
                "symbol": trade.symbol,
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat(),
                "pnl": trade.pnl,
                "confidence": trade.confidence,
                "size_fraction": trade.size_fraction,
            }
        )
        if len(self.performance_history) > 1000:
            self.performance_history = self.performance_history[-1000:]
        self.last_trade_timestamp = trade.exit_time
        self.logger.info(
            "fsd_trade_recorded",
            extra={
                "symbol": trade.symbol,
                "pnl": trade.pnl,
                "confidence": trade.confidence,
                "duration_minutes": (trade.exit_time - trade.entry_time).total_seconds() / 60
                if trade.exit_time and trade.entry_time
                else 0.0,
            },
        )

    def warmup_from_historical(self, historical_bars: dict[str, list[Bar]], observation_fraction: float = 0.5) -> dict[str, Any]:
        """
        Warmup FSD by processing historical data before live trading.

        This allows FSD to learn from past data without executing real trades.

        Args:
            historical_bars: Dict of symbol -> list of historical bars
            observation_fraction: Fraction of data to use for observation only (0.5 = first 50%)

        Returns:
            Warmup report with statistics
        """
        self.logger.info("fsd_warmup_starting", extra={"symbols": list(historical_bars.keys())})

        total_bars_processed = 0
        simulated_trades = 0
        total_simulated_pnl = 0.0

        for symbol, bars in historical_bars.items():
            if len(bars) < 20:
                self.logger.warning("insufficient_bars_for_warmup", extra={"symbol": symbol, "bars": len(bars)})
                continue

            # Split into observation and simulation phases
            observation_end = int(len(bars) * observation_fraction)

            # Phase 1: Observation (just build state, no decisions)
            self.logger.info(
                "warmup_observation_phase",
                extra={"symbol": symbol, "bars": observation_end}
            )

            for i in range(min(observation_end, len(bars) - 1)):
                bar = bars[i]
                # Just track prices for state building
                self._last_prices[symbol] = bar.close
                total_bars_processed += 1

            # Phase 2: Simulated Trading (make decisions, simulate outcomes, learn)
            self.logger.info(
                "warmup_simulation_phase",
                extra={"symbol": symbol, "bars": len(bars) - observation_end}
            )

            for i in range(observation_end, len(bars) - 1):
                current_bar = bars[i]
                next_bar = bars[i + 1]

                # Build history window
                history_window = bars[max(0, i - 50):i + 1]

                # Evaluate opportunity
                decision = self.evaluate_opportunity(
                    symbol=symbol,
                    bars=history_window,
                    last_prices={symbol: current_bar.close}
                )

                # If FSD decided to trade, simulate the trade
                if decision['should_trade'] and decision['action']['trade']:
                    action = decision['action']

                    # Simulate entry
                    entry_price = float(current_bar.close)
                    size_fraction = action.get('size_fraction', 0.1)

                    # Simulate exit on next bar
                    exit_price = float(next_bar.close)

                    # Calculate simulated PnL (simplified)
                    # Assume we trade $1000 worth for simulation purposes
                    notional = 1000.0 * size_fraction
                    quantity = notional / entry_price
                    pnl = (exit_price - entry_price) * quantity

                    # Create simulated trade
                    simulated_trade = Trade(
                        symbol=symbol,
                        entry_time=current_bar.timestamp,
                        entry_price=entry_price,
                        exit_time=next_bar.timestamp,
                        exit_price=exit_price,
                        quantity=quantity,
                        pnl=pnl,
                        confidence=decision['confidence'],
                        features=decision['state'],
                        size_fraction=size_fraction,
                        confidence_breakdown=decision.get('confidence_breakdown', {}),
                    )

                    # LEARN from simulated trade
                    self.rl_agent.learn_from_trade(simulated_trade)

                    simulated_trades += 1
                    total_simulated_pnl += pnl

                    self.logger.debug(
                        "warmup_simulated_trade",
                        extra={
                            "symbol": symbol,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "confidence": decision['confidence']
                        }
                    )

                total_bars_processed += 1

        warmup_report = {
            'total_bars_processed': total_bars_processed,
            'simulated_trades': simulated_trades,
            'simulated_pnl': total_simulated_pnl,
            'simulated_win_rate': self.rl_agent.winning_trades / simulated_trades if simulated_trades > 0 else 0,
            'q_values_learned': len(self.rl_agent.q_values),
            'experience_buffer_size': len(self.rl_agent.experience_buffer),
            'exploration_rate': self.rl_agent.exploration_rate,
        }

        self.logger.info("fsd_warmup_complete", extra=warmup_report)

        # Save the learned state
        state_path = Path(self.config.state_save_path).expanduser()
        self.rl_agent.save_state(state_path)

        return warmup_report

    def end_session(self) -> dict[str, Any]:
        """End FSD session and save state."""
        # Save RL agent state
        state_path = Path(self.config.state_save_path).expanduser()
        self.rl_agent.save_state(state_path)

        # Calculate session stats
        session_pnl = sum(t.pnl for t in self.session_trades)
        winning_trades = sum(1 for t in self.session_trades if t.pnl > 0)

        session_report = {
            'session_duration_minutes': (datetime.now(timezone.utc) - self.session_start).total_seconds() / 60 if self.session_start else 0,
            'total_trades': len(self.session_trades),
            'winning_trades': winning_trades,
            'win_rate': winning_trades / len(self.session_trades) if len(self.session_trades) > 0 else 0,
            'session_pnl': session_pnl,
            'cumulative_pnl': self.rl_agent.total_pnl,
            'cumulative_trades': self.rl_agent.total_trades,
            'cumulative_win_rate': self.rl_agent.winning_trades / self.rl_agent.total_trades if self.rl_agent.total_trades > 0 else 0,
            'exploration_rate': self.rl_agent.exploration_rate,
            'q_values_learned': len(self.rl_agent.q_values),
            'trade_history': len(self.trade_history),
            'experience_buffer': len(self.rl_agent.experience_buffer),
            'performance_samples': len(self.performance_history),
        }

        self._save_experience_buffer()
        self._save_performance_history()

        return session_report


__all__ = [
    "FSDConfig",
    "FSDEngine",
    "ConfidenceScorer",
    "ReinforcementLearner",
    "Trade",
]
