"""
Portfolio bookkeeping primitives.

Design goals:
    * Deterministic, side-effect free computations.
    * Explicit handling of cash, equity, and realised/unrealised P&L.
    * No threading or reliance on broker state; reconciliation is done via
      serialised snapshots (:meth:`Portfolio.snapshot`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    entry_time_utc: datetime | None = None
    last_update_utc: datetime | None = None
    total_volume: Decimal = Decimal("0")

    def market_value(self, price: Decimal) -> Decimal:
        return self.quantity * price

    def realise(self, fill_qty: Decimal, fill_price: Decimal, fill_time: datetime | None = None) -> Decimal:
        """
        Apply a fill and return realised P&L.

        Positive ``fill_qty`` represents a buy; negative a sell.
        """
        if fill_qty == 0:
            return Decimal("0")
        prev_qty = self.quantity
        new_qty = prev_qty + fill_qty

        realised = Decimal("0")
        same_direction = prev_qty == 0 or (prev_qty > 0 and fill_qty > 0) or (prev_qty < 0 and fill_qty < 0)

        if same_direction:
            # Increasing or opening a position in the same direction -> adjust average price.
            total_cost = (self.average_price * prev_qty) + (fill_price * fill_qty)
            self.quantity = new_qty
            if self.quantity != 0:
                self.average_price = total_cost / self.quantity
                if self.entry_time_utc is None:
                    self.entry_time_utc = fill_time
            else:
                self.average_price = Decimal("0")
                self.entry_time_utc = None
        else:
            # Reducing or reversing the position -> realise PnL on the closed portion.
            closed_qty = min(abs(fill_qty), abs(prev_qty))
            direction = Decimal("1") if prev_qty > 0 else Decimal("-1")
            realised = (fill_price - self.average_price) * (closed_qty * direction)
            self.quantity = new_qty
            if self.quantity == 0:
                self.average_price = Decimal("0")
                self.entry_time_utc = None
            elif prev_qty == 0 or (prev_qty > 0 and self.quantity > 0) or (prev_qty < 0 and self.quantity < 0):
                # Remaining position keeps existing basis.
                pass
            else:
                # Reversal -> leftover quantity inherits the fill price.
                self.average_price = fill_price
                self.entry_time_utc = fill_time
        self.last_update_utc = fill_time
        self.total_volume += abs(fill_qty)
        return realised


@dataclass
class PortfolioSnapshot:
    timestamp: datetime
    cash: Decimal
    equity: Decimal
    realised_pnl: Decimal
    unrealised_pnl: Decimal


@dataclass
class Portfolio:
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    realised_pnl: Decimal = Decimal("0")
    commissions_paid: Decimal = Decimal("0")
    trade_log: list[dict[str, object]] = field(default_factory=list)

    def position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def available_cash(self) -> Decimal:
        return self.cash

    def total_equity(self, last_prices: dict[str, Decimal]) -> Decimal:
        equity = self.cash
        for pos in self.positions.values():
            price = last_prices.get(pos.symbol)
            if price is not None:
                equity += pos.market_value(price)
        return equity

    def unrealised_pnl(self, last_prices: dict[str, Decimal]) -> Decimal:
        pnl = Decimal("0")
        for pos in self.positions.values():
            price = last_prices.get(pos.symbol)
            if price is not None:
                pnl += (price - pos.average_price) * pos.quantity
        return pnl

    def apply_fill(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        commission: Decimal = Decimal("0"),
        timestamp: datetime | None = None,
    ) -> Decimal:
        """
        Apply a fill to the portfolio.

        Returns the realised P&L from the trade (net of commission).
        """
        pos = self.position(symbol)
        realised = pos.realise(quantity, price, timestamp)
        cash_flow = quantity * price + commission
        self.cash -= cash_flow
        self.realised_pnl += realised - commission
        self.commissions_paid += commission
        self.trade_log.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "timestamp": timestamp,
                "realised_pnl": realised - commission,
                "commission": commission,
            }
        )
        return realised - commission

    def flatten(self, symbol: str, price: Decimal, commission: Decimal = Decimal("0")) -> Decimal:
        pos = self.position(symbol)
        qty = pos.quantity
        if qty == 0:
            return Decimal("0")
        return self.apply_fill(symbol, -qty, price, commission)

    def snapshot(self, timestamp: datetime, last_prices: dict[str, Decimal]) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=self.cash,
            equity=self.total_equity(last_prices),
            realised_pnl=self.realised_pnl,
            unrealised_pnl=self.unrealised_pnl(last_prices),
        )

    def gross_exposure(self, last_prices: dict[str, Decimal]) -> Decimal:
        exposure = Decimal("0")
        for pos in self.positions.values():
            price = last_prices.get(pos.symbol)
            if price is not None:
                exposure += abs(pos.quantity * price)
        return exposure

    def net_exposure(self, last_prices: dict[str, Decimal]) -> Decimal:
        exposure = Decimal("0")
        for pos in self.positions.values():
            price = last_prices.get(pos.symbol)
            if price is not None:
                exposure += pos.quantity * price
        return exposure

    def holding_period_bars(self, symbol: str, current_time: datetime, bar_interval: timedelta) -> int:
        pos = self.positions.get(symbol)
        if not pos or pos.entry_time_utc is None:
            return 0
        elapsed = current_time - pos.entry_time_utc
        if bar_interval.total_seconds() == 0:
            return 0
        return max(0, int(elapsed.total_seconds() // bar_interval.total_seconds()))
