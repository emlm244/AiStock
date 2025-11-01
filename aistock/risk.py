"""
Risk management for backtest engines.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from .config import RiskLimits
from .portfolio import Portfolio


class RiskViolation(Exception):
    """Exception raised when a risk limit is violated."""

    pass


@dataclass
class RiskState:
    """Serializable risk state for persistence."""

    daily_start_equity: Decimal = Decimal('0')
    start_of_day_equity: Decimal = Decimal('0')  # Kept for backward compatibility
    peak_equity: Decimal = Decimal('0')
    halted: bool = False
    is_halted: bool = False  # Kept for backward compatibility
    halt_reason: str = ''
    last_reset_date: str = ''
    daily_pnl: Decimal = Decimal('0')
    daily_order_count: int = 0
    order_timestamps: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Sync backward compatibility fields
        if self.start_of_day_equity and self.start_of_day_equity != Decimal('0'):
            self.daily_start_equity = self.start_of_day_equity
        elif self.daily_start_equity:
            self.start_of_day_equity = self.daily_start_equity

        if self.is_halted != self.halted:
            self.halted = self.is_halted = self.halted or self.is_halted


class RiskEngine:
    """
    Risk management engine for backtesting and live trading.

    P0 Fix (CRITICAL-2): Thread-safe to prevent race conditions in risk checks.

    Enforces:
    - Daily loss limits
    - Maximum drawdown halts
    - Position size limits
    - Pre-trade risk checks
    - Order rate limiting
    - Minimum balance protection (NEW: prevents trading below user-defined threshold)
    """

    def __init__(
        self,
        risk_config: RiskLimits,
        portfolio: Portfolio,
        bar_interval: timedelta,
        state: RiskState | None = None,
        minimum_balance: Decimal | None = None,
        minimum_balance_enabled: bool = True,
    ):
        self._lock = threading.RLock()  # P0 Fix: Thread safety (reentrant for halt calls)
        self.config: RiskLimits = risk_config
        self.portfolio: Portfolio = portfolio
        self.bar_interval = bar_interval

        # NEW: Minimum balance protection
        self.minimum_balance = minimum_balance or Decimal('0')
        self.minimum_balance_enabled = minimum_balance_enabled

        # Initialize or restore state
        if state:
            self.state = state
            self.daily_start_equity = state.daily_start_equity
            self.peak_equity = state.peak_equity
            self._is_halted = state.is_halted
            self._halt_reason = state.halt_reason
        else:
            self.state = RiskState(
                daily_start_equity=portfolio.initial_cash,
                peak_equity=portfolio.initial_cash,
            )
            self.daily_start_equity = portfolio.initial_cash
            self.peak_equity = portfolio.initial_cash
            self._is_halted = False
            self._halt_reason = ''

    def check_pre_trade(
        self,
        symbol: str,
        quantity_delta: Decimal,
        price: Decimal,
        current_equity: Decimal,
        last_prices: dict[str, Decimal],
        timestamp: datetime | None = None,
    ):
        """
        Check if a trade violates risk limits.

        P0 Fix (CRITICAL-2): Thread-safe to prevent race conditions.

        Args:
            symbol: Trading symbol
            quantity_delta: Proposed quantity change
            price: Execution price
            current_equity: Current portfolio equity
            last_prices: Dict of current prices for all symbols
            timestamp: Current timestamp (for rate limiting)

        Raises:
            RiskViolation: If trade violates risk limits
        """
        with self._lock:  # P0 Fix: Thread safety
            # Ensure reset for new day
            if timestamp:
                self._ensure_reset(timestamp, current_equity)

            # Check if trading is halted
            if self._is_halted:
                # Allow flattening trades only
                current_pos = self.portfolio.get_position(symbol)
                is_flattening = (current_pos > 0 and quantity_delta < 0 and abs(quantity_delta) <= current_pos) or (
                    current_pos < 0 and quantity_delta > 0 and abs(quantity_delta) <= abs(current_pos)
                )
                if not is_flattening:
                    raise RiskViolation(f'Trading halted: {self._halt_reason}')

            # NEW: Check minimum balance protection
            if self.minimum_balance_enabled and self.minimum_balance > Decimal('0'):
                # Calculate what the TOTAL EQUITY would be after this trade
                # We need to check equity, not just cash, because positions have value too
                trade_cost = abs(quantity_delta * price)

                # For buy orders, cash decreases; for sell orders, equity stays same (converting position to cash)
                projected_equity = current_equity - trade_cost if quantity_delta > 0 else current_equity

                # Check if projected EQUITY would fall below minimum
                if projected_equity < self.minimum_balance:
                    margin = self.minimum_balance - projected_equity
                    raise RiskViolation(
                        f'Minimum balance protection: Trade would bring equity to ${projected_equity:.2f}, '
                        f'below minimum of ${self.minimum_balance:.2f} (${margin:.2f} short). '
                        f'Trade BLOCKED for safety.'
                    )

            current_pos = self.portfolio.get_position(symbol)

            # Check per-trade notional cap if configured
            per_trade_cap_pct = getattr(self.config, 'per_trade_risk_pct', 0.0)
            if per_trade_cap_pct and per_trade_cap_pct > 0:
                per_trade_cap = current_equity * Decimal(str(per_trade_cap_pct))
                trade_notional = abs(quantity_delta * price)
                is_closing_trade = (current_pos > 0 and quantity_delta < 0) or (current_pos < 0 and quantity_delta > 0)
                if not is_closing_trade and trade_notional > per_trade_cap:
                    raise RiskViolation(
                        f'Per-trade cap exceeded: ${trade_notional:.2f} > '
                        f'${per_trade_cap:.2f} ({per_trade_cap_pct:.2%} of equity)'
                    )

            # Check order rate limits (if enabled)
            if hasattr(self.config, 'rate_limit_enabled') and self.config.rate_limit_enabled and timestamp:
                self._check_rate_limits(timestamp)

            # Check daily loss limit
            daily_loss = (self.daily_start_equity - current_equity) / self.daily_start_equity
            if daily_loss >= self.config.max_daily_loss_pct:
                self.halt('Daily loss limit exceeded')
                raise RiskViolation(f'Daily loss limit exceeded: {daily_loss:.2%}')

            # Check maximum drawdown
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity
                self.state.peak_equity = current_equity

            drawdown = (self.peak_equity - current_equity) / self.peak_equity
            if drawdown >= self.config.max_drawdown_pct:
                self.halt('Maximum drawdown exceeded')
                raise RiskViolation(f'Maximum drawdown exceeded: {drawdown:.2%}')

            # Check position size limit (use max_position_fraction if available)
            max_pos_pct = getattr(self.config, 'max_position_fraction', getattr(self.config, 'max_position_pct', 0.25))

            # Calculate projected position value
            new_pos = current_pos + quantity_delta
            position_value = abs(new_pos * price)
            position_pct = position_value / current_equity if current_equity > 0 else 0

            if position_pct > max_pos_pct:
                raise RiskViolation(f'Position size {position_pct:.2%} exceeds limit {max_pos_pct:.2%}')

    def reset_daily(self, current_equity: Decimal):
        """
        Reset daily tracking (call at start of each trading day).

        P0 Fix (CRITICAL-2): Thread-safe.
        """
        with self._lock:
            self.daily_start_equity = current_equity
            self.state.daily_start_equity = current_equity
            self.state.daily_pnl = Decimal('0')
            self.state.daily_order_count = 0
            self.state.order_timestamps = []

    def _ensure_reset(self, timestamp: datetime, current_equity: Decimal):
        """Ensure daily reset has occurred."""
        current_date = timestamp.date().isoformat()
        if not self.state.last_reset_date or self.state.last_reset_date != current_date:
            self.reset_daily(current_equity)
            self.state.last_reset_date = current_date
            self._is_halted = False
            self._halt_reason = ''
            self.state.is_halted = False
            self.state.halt_reason = ''

    def _check_rate_limits(self, timestamp: datetime):
        """Check if order rate limits would be violated."""
        # Per-minute limit
        if hasattr(self.config, 'max_orders_per_minute'):
            one_minute_ago = timestamp - timedelta(minutes=1)
            recent_orders = [ts for ts in self.state.order_timestamps if datetime.fromisoformat(ts) > one_minute_ago]
            if len(recent_orders) >= self.config.max_orders_per_minute:
                raise RiskViolation(
                    f'Order rate limit exceeded: {len(recent_orders)}/{self.config.max_orders_per_minute} per minute'
                )

        # Per-day limit
        if hasattr(self.config, 'max_orders_per_day') and (
            self.state.daily_order_count >= self.config.max_orders_per_day
        ):
            raise RiskViolation(
                f'Daily order limit exceeded: {self.state.daily_order_count}/{self.config.max_orders_per_day}'
            )

    def _record_order_submission(self, timestamp: datetime):
        """Record an order submission for rate limiting."""
        self.state.order_timestamps.append(timestamp.isoformat())
        self.state.daily_order_count += 1

    # Public wrapper for recording submissions from orchestrators
    def record_order_submission(self, timestamp: datetime) -> None:
        """
        Record an order submission (external call).

        P0 Fix (CRITICAL-2): Thread-safe.

        Use this immediately after a successful pre-trade risk check to
        advance the order-rate tracking window.
        """
        with self._lock:
            self._record_order_submission(timestamp)

    def halt(self, reason: str):
        """
        Halt trading with a reason.

        P0 Fix (CRITICAL-2): Thread-safe.
        """
        with self._lock:
            self._is_halted = True
            self._halt_reason = reason
            self.state.is_halted = True
            self.state.halt_reason = reason

    def is_halted(self) -> bool:
        """
        Check if trading is halted.

        P0 Fix (CRITICAL-2): Thread-safe.
        """
        with self._lock:
            return self._is_halted

    def halt_reason(self) -> str:
        """
        Get halt reason.

        P0 Fix (CRITICAL-2): Thread-safe.
        """
        with self._lock:
            return self._halt_reason

    def register_trade(
        self,
        realised_pnl: Decimal,
        unrealised_pnl: Decimal,
        timestamp: datetime,
        equity: Decimal,
        last_prices: dict[str, Decimal],
    ):
        """
        Register a completed trade for daily P&L tracking.

        P0 Fix (CRITICAL-2): Thread-safe.
        """
        with self._lock:
            self.state.daily_pnl += realised_pnl

            # Check if daily loss limit breached
            daily_loss_pct = abs(self.state.daily_pnl) / self.daily_start_equity if self.daily_start_equity > 0 else 0
            if daily_loss_pct >= self.config.max_daily_loss_pct:
                self.halt('Daily loss limit exceeded')
