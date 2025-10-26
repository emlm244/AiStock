"""
Deterministic risk engine enforcing portfolio level limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from .config import RiskLimits
from .portfolio import Portfolio


@dataclass
class RiskState:
    last_reset_date: date
    daily_pnl: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    start_of_day_equity: Decimal = Decimal("0")
    halted: bool = False
    halt_reason: str | None = None


class RiskViolation(Exception):  # noqa: N818 - "Violation" is clearer than "ViolationError"
    """Raised when a pre- or post-trade risk check fails."""


@dataclass
class RiskEngine:
    limits: RiskLimits
    portfolio: Portfolio
    bar_interval: timedelta
    state: RiskState = field(default_factory=lambda: RiskState(last_reset_date=date.min))

    def _ensure_reset(self, current_time: datetime, equity: Decimal) -> None:
        today = current_time.date()
        if today != self.state.last_reset_date:
            self.state.daily_pnl = Decimal("0")
            self.state.last_reset_date = today
            self.state.start_of_day_equity = equity
            self.state.halted = False
            self.state.halt_reason = None
            if equity > self.state.peak_equity:
                self.state.peak_equity = equity
        elif self.state.start_of_day_equity == Decimal("0"):
            # Engine was instantiated mid-session; capture baseline for daily loss checks.
            self.state.start_of_day_equity = equity

    def register_trade(
        self,
        pnl: Decimal,
        commission: Decimal,
        timestamp: datetime,
        equity: Decimal,
        last_prices: dict[str, Decimal],
    ) -> None:
        self._ensure_reset(timestamp, equity)
        self.state.daily_pnl += pnl
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity
        self._check_limits(equity, last_prices, timestamp)

    def _check_limits(self, equity: Decimal, last_prices: dict[str, Decimal], timestamp: datetime) -> None:
        peak = max(self.state.peak_equity, equity)
        drawdown_pct = Decimal("0")
        if peak > 0:
            drawdown_pct = (peak - equity) / peak

        if self.limits.kill_switch_enabled and equity <= 0:
            self.halt("Equity depleted; kill switch engaged.")
            return

        if drawdown_pct > Decimal(str(self.limits.max_drawdown_pct)):
            self.halt(f"Drawdown limit breached: {drawdown_pct:.2%} > {self.limits.max_drawdown_pct:.2%}")
            return

        daily_loss_pct = Decimal("0")
        start_equity = self.state.start_of_day_equity if self.state.start_of_day_equity > 0 else equity
        if start_equity > 0:
            loss = self.state.daily_pnl if self.state.daily_pnl < 0 else Decimal("0")
            daily_loss_pct = -loss / start_equity

        if daily_loss_pct > Decimal(str(self.limits.max_daily_loss_pct)):
            self.halt(f"Daily loss limit breached: {daily_loss_pct:.2%}")

        gross = self.portfolio.gross_exposure(last_prices)
        if equity > 0 and gross / equity > Decimal(str(self.limits.max_gross_exposure)):
            self.halt(f"Gross exposure {gross} exceeds limit {self.limits.max_gross_exposure} * equity")

        leverage = Decimal("0")
        if equity > 0:
            leverage = gross / equity
        if leverage > Decimal(str(self.limits.max_leverage)):
            self.halt(f"Leverage {leverage:.2f} exceeds limit {self.limits.max_leverage}")

        for symbol in list(self.portfolio.positions.keys()):
            holding = self.portfolio.holding_period_bars(symbol, timestamp, self.bar_interval)
            if holding > self.limits.max_holding_period_bars:
                self.halt(f"Holding period for {symbol} exceeded limit ({holding} bars)")
                break

    def halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason

    def check_pre_trade(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        equity: Decimal,
        last_prices: dict[str, Decimal],
    ) -> None:
        current_position = self.portfolio.position(symbol)
        projected_qty = current_position.quantity + quantity

        if self.state.halted:
            current_qty = current_position.quantity
            if current_qty == 0:
                raise RiskViolation(f"Trading halted: {self.state.halt_reason}")
            if current_qty * projected_qty < 0:
                raise RiskViolation("Trading halted: only flattening existing positions is permitted.")
            if abs(projected_qty) > abs(current_qty):
                raise RiskViolation("Trading halted: cannot increase exposure while halted.")

        position_value = abs(quantity * price)
        max_alloc = Decimal(str(self.limits.max_position_fraction)) * equity
        if max_alloc > 0 and position_value > max_alloc:
            raise RiskViolation(
                f"Position value {position_value} exceeds limit {max_alloc} ({self.limits.max_position_fraction:.2%})"
            )

        if (
            self.limits.max_single_position_units > 0
            and abs(projected_qty) > Decimal(str(self.limits.max_single_position_units))
        ):
            raise RiskViolation(
                f"Projected position size {projected_qty} units exceeds limit {self.limits.max_single_position_units}"
            )

        projected_notional = abs(projected_qty * price)
        if (
            self.limits.per_symbol_notional_cap > 0
            and projected_notional > Decimal(str(self.limits.per_symbol_notional_cap))
        ):
            raise RiskViolation(
                f"Projected notional {projected_notional} exceeds per-symbol cap {self.limits.per_symbol_notional_cap}"
            )
        if max_alloc > 0 and projected_notional > max_alloc:
            raise RiskViolation(
                f"Projected position value {projected_notional} exceeds limit {max_alloc} "
                f"({self.limits.max_position_fraction:.2%})"
            )

        gross_current = self.portfolio.gross_exposure(last_prices)
        current_price = last_prices.get(symbol, price)
        old_notional = abs(current_position.quantity * current_price)
        projected_gross = gross_current - old_notional + projected_notional
        if equity > 0 and projected_gross / equity > Decimal(str(self.limits.max_gross_exposure)):
            raise RiskViolation(
                f"Projected gross exposure {projected_gross} breaches limit {self.limits.max_gross_exposure} * equity"
            )

        if equity > 0 and projected_gross / equity > Decimal(str(self.limits.max_leverage)):
            raise RiskViolation(
                f"Projected leverage {projected_gross / equity:.2f} exceeds limit {self.limits.max_leverage}"
            )

    def is_halted(self) -> bool:
        return self.state.halted

    def halt_reason(self) -> str | None:
        return self.state.halt_reason
