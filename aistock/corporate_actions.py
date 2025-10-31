"""
Corporate actions tracking for accurate historical backtests.

⚠️ NOTE: This module is currently NOT integrated into the FSD trading system.
It provides utilities for tracking splits/dividends but requires manual integration.
Corporate action adjustments would need to be applied during data ingestion.
Retained for future enhancement.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path


class ActionType(str, Enum):
    """Type of corporate action."""

    SPLIT = 'split'
    DIVIDEND = 'dividend'
    SPIN_OFF = 'spin_off'
    MERGER = 'merger'


@dataclass(frozen=True)
class CorporateAction:
    """
    Corporate action event.

    Attributes:
        symbol: Ticker symbol
        ex_date: Ex-dividend/ex-split date (when price adjusts)
        action_type: Type of action
        ratio: For splits (e.g., 2.0 for 2:1 split)
        amount: For dividends (per share amount)
        description: Human-readable description
    """

    symbol: str
    ex_date: date
    action_type: ActionType
    ratio: Decimal | None = None  # For splits
    amount: Decimal | None = None  # For dividends
    description: str = ''

    def __post_init__(self):
        """Validate action parameters."""
        if self.action_type == ActionType.SPLIT and self.ratio is None:
            raise ValueError(f'Split action requires ratio, got {self}')
        if self.action_type == ActionType.DIVIDEND and self.amount is None:
            raise ValueError(f'Dividend action requires amount, got {self}')


class CorporateActionTracker:
    """
    Track and apply corporate actions to historical data.

    P1 Enhancement: Ensures backtest data is properly adjusted.
    """

    def __init__(self, actions: list[CorporateAction] | None = None):
        """
        Initialize tracker with optional pre-loaded actions.

        Args:
            actions: List of corporate actions (will be sorted by ex_date)
        """
        self._actions: dict[str, list[CorporateAction]] = {}
        if actions:
            for action in actions:
                self.add_action(action)

    def add_action(self, action: CorporateAction) -> None:
        """Add a corporate action to the tracker."""
        if action.symbol not in self._actions:
            self._actions[action.symbol] = []
        self._actions[action.symbol].append(action)
        # Keep sorted by ex_date
        self._actions[action.symbol].sort(key=lambda a: a.ex_date)

    def get_actions(
        self, symbol: str, start_date: date | None = None, end_date: date | None = None
    ) -> list[CorporateAction]:
        """
        Get corporate actions for a symbol within a date range.

        Args:
            symbol: Ticker symbol
            start_date: Optional start date (inclusive)
            end_date: Optional end date (inclusive)

        Returns:
            List of actions, sorted by ex_date
        """
        actions = self._actions.get(symbol, [])
        if start_date:
            actions = [a for a in actions if a.ex_date >= start_date]
        if end_date:
            actions = [a for a in actions if a.ex_date <= end_date]
        return actions

    def adjust_price(self, symbol: str, price: Decimal, timestamp: datetime) -> Decimal:
        """
        Adjust a price for all corporate actions before the given timestamp.

        P1 Enhancement: Backward adjustment for historical consistency.

        For splits:
        - Forward (2:1 split on 2024-01-15): Pre-split price $100 -> Post-split $50
        - Backward adjustment: Post-split $50 -> Pre-split $100 (multiply by ratio)

        Args:
            symbol: Ticker symbol
            price: Unadjusted price
            timestamp: Price timestamp

        Returns:
            Adjusted price
        """
        actions = self._actions.get(symbol, [])
        adjusted = price
        price_date = timestamp.date()

        for action in actions:
            if action.ex_date > price_date:
                # Action is in the future relative to this price
                if action.action_type == ActionType.SPLIT and action.ratio:
                    # Backward adjust: multiply by split ratio
                    adjusted *= action.ratio
                elif action.action_type == ActionType.DIVIDEND and action.amount:
                    # Backward adjust for dividends (add back dividend)
                    adjusted += action.amount

        return adjusted

    def check_for_action(self, symbol: str, timestamp: datetime) -> CorporateAction | None:
        """
        Check if there's a corporate action on a specific date.

        Args:
            symbol: Ticker symbol
            timestamp: Date to check

        Returns:
            CorporateAction if found, None otherwise
        """
        check_date = timestamp.date()
        actions = self._actions.get(symbol, [])
        for action in actions:
            if action.ex_date == check_date:
                return action
        return None

    def save_to_csv(self, path: str) -> None:
        """
        Save corporate actions to CSV file.

        CSV format:
        symbol,ex_date,action_type,ratio,amount,description
        """
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['symbol', 'ex_date', 'action_type', 'ratio', 'amount', 'description'])

            for _symbol, actions in sorted(self._actions.items()):
                for action in actions:
                    writer.writerow(
                        [
                            action.symbol,
                            action.ex_date.isoformat(),
                            action.action_type.value,
                            str(action.ratio) if action.ratio else '',
                            str(action.amount) if action.amount else '',
                            action.description,
                        ]
                    )

    @staticmethod
    def load_from_csv(path: str) -> CorporateActionTracker:
        """
        Load corporate actions from CSV file.

        CSV format:
        symbol,ex_date,action_type,ratio,amount,description
        """
        tracker = CorporateActionTracker()
        csv_path = Path(path)

        if not csv_path.exists():
            return tracker  # Empty tracker

        with csv_path.open('r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                action = CorporateAction(
                    symbol=row['symbol'],
                    ex_date=date.fromisoformat(row['ex_date']),
                    action_type=ActionType(row['action_type']),
                    ratio=Decimal(row['ratio']) if row.get('ratio') else None,
                    amount=Decimal(row['amount']) if row.get('amount') else None,
                    description=row.get('description', ''),
                )
                tracker.add_action(action)

        return tracker


# Convenience functions
def create_split(symbol: str, ex_date: date, ratio: Decimal, description: str = '') -> CorporateAction:
    """
    Create a stock split action.

    Args:
        symbol: Ticker symbol
        ex_date: Ex-split date
        ratio: Split ratio (e.g., 2.0 for 2:1 split, 0.5 for 1:2 reverse split)
        description: Optional description

    Example:
        >>> split = create_split("AAPL", date(2024, 6, 10), Decimal("4.0"), "4-for-1 stock split")
    """
    if not description:
        description = f'{ratio}:1 split'
    return CorporateAction(
        symbol=symbol,
        ex_date=ex_date,
        action_type=ActionType.SPLIT,
        ratio=ratio,
        description=description,
    )


def create_dividend(symbol: str, ex_date: date, amount: Decimal, description: str = '') -> CorporateAction:
    """
    Create a dividend action.

    Args:
        symbol: Ticker symbol
        ex_date: Ex-dividend date
        amount: Dividend amount per share
        description: Optional description

    Example:
        >>> div = create_dividend("MSFT", date(2024, 2, 15), Decimal("0.75"), "Q1 2024 dividend")
    """
    if not description:
        description = f'${amount} dividend'
    return CorporateAction(
        symbol=symbol,
        ex_date=ex_date,
        action_type=ActionType.DIVIDEND,
        amount=amount,
        description=description,
    )
