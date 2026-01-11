"""
Risk management for backtest engines.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..config import AccountCapabilities, ContractSpec, RiskLimits
from ..portfolio import Portfolio


class RiskViolation(Exception):  # noqa: N818
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

    Enforces (all checked in check_pre_trade):
    - Daily loss limits (max_daily_loss_pct)
    - Maximum drawdown halts (max_drawdown_pct)
    - Position size limits (max_position_fraction)
    - Gross exposure limits (max_gross_exposure)
    - Leverage limits (max_leverage)
    - Per-symbol notional caps (per_symbol_notional_cap)
    - Max position units (max_single_position_units)
    - Per-trade risk caps (per_trade_risk_pct)
    - Order rate limiting (max_orders_per_minute, max_orders_per_day)
    - Minimum balance protection
    - Account capability restrictions (futures/options/settlement)

    Note: max_holding_period_bars is validated in config but requires
    position age tracking in the coordinator/engine layer for enforcement.
    """

    def __init__(
        self,
        risk_config: RiskLimits,
        portfolio: Portfolio,
        bar_interval: timedelta,
        state: RiskState | None = None,
        minimum_balance: Decimal | None = None,
        minimum_balance_enabled: bool = True,
        account_capabilities: AccountCapabilities | None = None,
        contract_specs: dict[str, ContractSpec] | None = None,
    ):
        self._lock = threading.RLock()  # P0 Fix: Thread safety (reentrant for halt calls)
        self.config: RiskLimits = risk_config
        self.portfolio: Portfolio = portfolio
        self.bar_interval = bar_interval
        self._account_capabilities = account_capabilities
        self._contract_specs = contract_specs or {}

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
        equity: Decimal,
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
            equity: Current portfolio equity
            last_prices: Dict of current prices for all symbols
            timestamp: Current timestamp (for rate limiting)

        Raises:
            RiskViolation: If trade violates risk limits
        """
        with self._lock:  # P0 Fix: Thread safety
            # Ensure reset for new day
            if timestamp:
                self._ensure_reset(timestamp, equity)

            # Check if trading is halted
            if self._is_halted:
                # Allow flattening trades only
                current_pos = self.portfolio.get_position(symbol)
                is_flattening = (current_pos > 0 and quantity_delta < 0 and abs(quantity_delta) <= current_pos) or (
                    current_pos < 0 and quantity_delta > 0 and abs(quantity_delta) <= abs(current_pos)
                )
                if not is_flattening:
                    raise RiskViolation(f'Trading halted: {self._halt_reason}')

            # Account capability restrictions (instruments, settlement)
            if self._account_capabilities:
                self._check_account_capabilities(symbol, quantity_delta, price, timestamp)

            # NEW: Check minimum balance protection
            if self.minimum_balance_enabled and self.minimum_balance > Decimal('0'):
                # Enforce a cash floor: prevent allocating the protected balance.
                cash = self.portfolio.get_cash()
                projected_cash = cash - (quantity_delta * price)

                if projected_cash < self.minimum_balance:
                    margin = self.minimum_balance - projected_cash
                    raise RiskViolation(
                        f'Minimum balance protection: Trade would bring cash to ${projected_cash:.2f}, '
                        f'below minimum of ${self.minimum_balance:.2f} (${margin:.2f} short). '
                        f'Trade BLOCKED for safety.'
                    )

            current_pos = self.portfolio.get_position(symbol)

            # Check per-trade notional cap if configured
            per_trade_cap_pct = getattr(self.config, 'per_trade_risk_pct', 0.0)
            if per_trade_cap_pct and per_trade_cap_pct > 0:
                per_trade_cap = equity * Decimal(str(per_trade_cap_pct))
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
            if self.daily_start_equity > 0:
                daily_loss = (self.daily_start_equity - equity) / self.daily_start_equity
            else:
                daily_loss = Decimal('0')
            if daily_loss >= self.config.max_daily_loss_pct:
                self.halt('Daily loss limit exceeded')
                raise RiskViolation(f'Daily loss limit exceeded: {daily_loss:.2%}')

            # Check maximum drawdown
            if equity > self.peak_equity:
                self.peak_equity = equity
                self.state.peak_equity = equity

            drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else Decimal('0')
            if drawdown >= self.config.max_drawdown_pct:
                self.halt('Maximum drawdown exceeded')
                raise RiskViolation(f'Maximum drawdown exceeded: {drawdown:.2%}')

            # Check position size limit (use max_position_fraction if available)
            max_pos_pct = getattr(self.config, 'max_position_fraction', getattr(self.config, 'max_position_pct', 0.25))

            # Calculate projected position value
            new_pos = current_pos + quantity_delta
            position_value = abs(new_pos * price)
            position_pct = position_value / equity if equity > 0 else 0

            if position_pct > max_pos_pct:
                raise RiskViolation(f'Position size {position_pct:.2%} exceeds limit {max_pos_pct:.2%}')

            # Check gross exposure limit (sum of absolute position values / equity)
            if hasattr(self.config, 'max_gross_exposure') and self.config.max_gross_exposure > 0:
                current_gross = self.portfolio.get_gross_exposure(last_prices)
                # Calculate projected gross exposure after this trade
                trade_notional = abs(quantity_delta * price) * self._get_contract_multiplier(symbol)
                # For new/adding positions, exposure increases; for closing, it decreases
                if new_pos == 0:
                    # Flattening position - gross exposure decreases
                    projected_gross = current_gross - abs(current_pos * price) * self._get_contract_multiplier(symbol)
                elif abs(new_pos) > abs(current_pos):
                    # Adding to or opening position - gross exposure increases
                    projected_gross = current_gross + trade_notional
                else:
                    # Reducing position - gross exposure decreases
                    projected_gross = current_gross - trade_notional

                gross_exposure_ratio = projected_gross / equity if equity > 0 else Decimal('0')
                if gross_exposure_ratio > Decimal(str(self.config.max_gross_exposure)):
                    raise RiskViolation(
                        f'Gross exposure {gross_exposure_ratio:.2%} would exceed limit '
                        f'{self.config.max_gross_exposure:.2%}'
                    )

            # Check leverage limit (net exposure / equity)
            if hasattr(self.config, 'max_leverage') and self.config.max_leverage > 0:
                current_net = self.portfolio.get_net_exposure(last_prices)
                trade_signed_notional = quantity_delta * price * self._get_contract_multiplier(symbol)
                projected_net = current_net + trade_signed_notional
                leverage_ratio = abs(projected_net) / equity if equity > 0 else Decimal('0')
                if leverage_ratio > Decimal(str(self.config.max_leverage)):
                    raise RiskViolation(
                        f'Leverage {leverage_ratio:.2f}x would exceed limit '
                        f'{self.config.max_leverage:.2f}x'
                    )

            # Check per-symbol notional cap
            if hasattr(self.config, 'per_symbol_notional_cap') and self.config.per_symbol_notional_cap > 0:
                multiplier = self._get_contract_multiplier(symbol)
                projected_notional = abs(new_pos * price) * multiplier
                cap = Decimal(str(self.config.per_symbol_notional_cap))
                if projected_notional > cap:
                    raise RiskViolation(
                        f'Per-symbol notional ${projected_notional:,.2f} would exceed cap '
                        f'${cap:,.2f} for {symbol}'
                    )

            # Check max single position units
            if hasattr(self.config, 'max_single_position_units') and self.config.max_single_position_units > 0:
                max_units = Decimal(str(self.config.max_single_position_units))
                if abs(new_pos) > max_units:
                    raise RiskViolation(
                        f'Position units {abs(new_pos):,.0f} would exceed limit '
                        f'{max_units:,.0f} for {symbol}'
                    )

    def _resolve_contract_spec(self, symbol: str) -> ContractSpec | None:
        if not self._contract_specs:
            return None
        return self._contract_specs.get(symbol) or self._contract_specs.get(symbol.upper())

    def _get_contract_multiplier(self, symbol: str) -> Decimal:
        spec = self._resolve_contract_spec(symbol)
        if spec and spec.multiplier:
            return Decimal(str(spec.multiplier))
        return Decimal('1')

    def _check_account_capabilities(
        self,
        symbol: str,
        quantity_delta: Decimal,
        price: Decimal,
        timestamp: datetime | None,
    ) -> None:
        caps = self._account_capabilities
        if not caps:
            return

        spec = self._resolve_contract_spec(symbol)
        sec_type = spec.sec_type.upper() if spec and spec.sec_type else 'STK'

        if sec_type == 'FUT':
            if not caps.enable_futures:
                raise RiskViolation('Futures trading is disabled by account capabilities.')
            if caps.account_type != 'margin':
                raise RiskViolation('Futures trading requires a margin account.')
            if caps.account_balance < 2000:
                raise RiskViolation('Futures trading requires at least $2,000 total account balance.')
        elif sec_type == 'OPT':
            if not caps.enable_options:
                raise RiskViolation('Options trading is disabled by account capabilities.')
            if caps.account_type != 'margin':
                raise RiskViolation('Options trading requires a margin account.')
            if caps.account_balance < 2000:
                raise RiskViolation('Options trading requires at least $2,000 total account balance.')
        elif sec_type == 'STK':
            if not (caps.enable_stocks or caps.enable_etfs):
                raise RiskViolation('Stocks/ETFs are disabled by account capabilities.')

        if caps.account_type == 'cash' and caps.enforce_settlement and quantity_delta > 0:
            as_of = timestamp or datetime.now(timezone.utc)
            available_cash = self.portfolio.get_available_cash(as_of=as_of)
            trade_cost = quantity_delta * price * self._get_contract_multiplier(symbol)
            if trade_cost > available_cash:
                shortfall = trade_cost - available_cash
                raise RiskViolation(
                    f'Settlement restriction: available cash ${available_cash:.2f} '
                    f'cannot cover trade cost ${trade_cost:.2f} (short ${shortfall:.2f}).'
                )

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

    def adjust_for_withdrawal(self, amount: Decimal) -> None:
        """
        Adjust equity baselines after a cash withdrawal to avoid false loss halts.

        Withdrawals reduce available equity but should not count as trading losses.
        This keeps daily loss and drawdown calculations aligned with actual risk.
        """
        if amount <= 0:
            return
        with self._lock:
            updated_daily = max(Decimal('0'), self.daily_start_equity - amount)
            updated_peak = max(Decimal('0'), self.peak_equity - amount)

            self.daily_start_equity = updated_daily
            self.state.daily_start_equity = updated_daily
            self.state.start_of_day_equity = updated_daily

            self.peak_equity = updated_peak
            self.state.peak_equity = updated_peak

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

            # Check if daily loss limit breached (only for actual losses, not profits)
            if self.state.daily_pnl < 0:
                daily_loss_pct = -self.state.daily_pnl / self.daily_start_equity if self.daily_start_equity > 0 else 0
                if daily_loss_pct >= self.config.max_daily_loss_pct:
                    self.halt('Daily loss limit exceeded')
