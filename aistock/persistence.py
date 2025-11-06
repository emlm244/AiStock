"""Helpers to persist backtest artefacts and runtime state."""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .engine import Trade
from .interfaces.portfolio import PortfolioProtocol
from .portfolio import Portfolio, Position
from .risk import RiskState

# P0-5 Fix: Global lock for atomic file writes
_PERSISTENCE_LOCK = threading.Lock()


def _atomic_write_json(data: Any, filepath: Path) -> None:
    """
    P0-5 Fix: Atomic write with locking to prevent corruption.
    P2-1 Fix: Enhanced temp file cleanup in finally block.

    Strategy:
    1. Write to temporary file
    2. Create backup of existing file (if exists)
    3. Atomically rename temp file to target
    4. Protected by global lock for thread safety
    5. Guaranteed temp file cleanup via finally block

    Args:
        data: JSON-serializable data
        filepath: Target file path
    """
    with _PERSISTENCE_LOCK:
        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first
        temp_path = filepath.with_suffix('.tmp')
        backup_path = filepath.with_suffix('.backup')

        try:
            # Step 1: Write data to temp file
            with temp_path.open('w') as handle:
                json.dump(data, handle, indent=2)

            # Step 2: Create backup of existing file (if it exists)
            if filepath.exists():
                # Use replace() for atomic operation
                filepath.replace(backup_path)

            # Step 3: Atomic rename (overwrites target atomically on both POSIX and Windows)
            temp_path.replace(filepath)

        except Exception as exc:
            raise RuntimeError(f'Atomic write failed for {filepath}: {exc}') from exc

        finally:
            # P2-1 Fix: Always cleanup temp file if it still exists
            # (shouldn't exist if rename succeeded, but handle edge cases)
            if temp_path.exists():
                import contextlib

                with contextlib.suppress(Exception):
                    temp_path.unlink()


def write_trades(trades: Iterable[Trade], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['timestamp', 'symbol', 'quantity', 'price', 'realised_pnl', 'equity', 'order_id', 'strategy'])
        for trade in trades:
            writer.writerow(
                [
                    trade.timestamp.isoformat(),
                    trade.symbol,
                    float(trade.quantity),
                    float(trade.price),
                    float(trade.realised_pnl),
                    float(trade.equity),
                    trade.order_id,
                    trade.strategy,
                ]
            )


def write_equity_curve(equity_curve: Iterable[tuple[datetime, float]], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['timestamp', 'equity'])
        for timestamp, equity in equity_curve:
            writer.writerow([timestamp.isoformat(), float(equity)])


# P0 Fix: State persistence for crash recovery


def _serialize_decimal(obj: Any) -> Any:
    """Convert Decimal and datetime objects to JSON-serializable types."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def save_portfolio_snapshot(portfolio: PortfolioProtocol, path: str) -> None:
    """
    Persist portfolio state to JSON for crash recovery.

    Args:
        portfolio: Portfolio instance to serialize
        path: Target file path (will create parent directories)
    """
    positions_snapshot = portfolio.snapshot_positions()
    positions_data = []
    for _symbol, pos in positions_snapshot.items():
        positions_data.append(
            {
                'symbol': pos.symbol,
                'quantity': str(pos.quantity),
                'average_price': str(pos.average_price),
                'entry_time_utc': pos.entry_time_utc.isoformat() if pos.entry_time_utc else None,
                'last_update_utc': pos.last_update_utc.isoformat() if pos.last_update_utc else None,
                'total_volume': str(pos.total_volume),
            }
        )

    trade_log_snapshot = portfolio.get_trade_log_snapshot(limit=1000)

    snapshot = {
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'cash': str(portfolio.get_cash()),
        'positions': positions_data,
        'realised_pnl': str(portfolio.get_realised_pnl()),
        'commissions_paid': str(portfolio.get_commissions_paid()),
        'trade_log': trade_log_snapshot,
    }

    # Serialize trade log (contains Decimal objects)
    serialized_trades = []
    trade_log: list[dict[str, Any]] = snapshot.get('trade_log', [])  # type: ignore[assignment]
    for trade in trade_log:
        serialized_trade: dict[str, Any] = {}
        for key, value in trade.items():
            serialized_trade[key] = _serialize_decimal(value)
        serialized_trades.append(serialized_trade)
    snapshot['trade_log'] = serialized_trades

    # P0-5 Fix: Use atomic write to prevent corruption
    _atomic_write_json(snapshot, Path(path))


def load_portfolio_snapshot(path: str) -> Portfolio:
    """
    Restore portfolio state from JSON checkpoint.

    P0-5 Fix: Attempts backup file if primary is corrupted.

    Args:
        path: Path to checkpoint file

    Returns:
        Reconstructed Portfolio instance

    Raises:
        FileNotFoundError: If checkpoint doesn't exist
        ValueError: If checkpoint is corrupted
    """
    target = Path(path)
    backup_path = target.with_suffix('.backup')

    if not target.exists() and not backup_path.exists():
        raise FileNotFoundError(f'Portfolio checkpoint not found: {path}')

    # P0-5 Fix: Try primary file, fall back to backup if corrupted
    snapshot = None
    load_error = None

    # Try primary file first
    if target.exists():
        try:
            with target.open('r') as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError as exc:
            load_error = exc
            # Primary corrupted, will try backup

    # If primary failed or doesn't exist, try backup
    if snapshot is None and backup_path.exists():
        try:
            with backup_path.open('r') as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Both primary and backup checkpoints corrupted: {path}') from exc

    if snapshot is None:
        raise ValueError(f'Failed to load portfolio checkpoint: {path}') from load_error

    if snapshot.get('version') != '1.0':
        raise ValueError(f'Unsupported checkpoint version: {snapshot.get("version")}')

    # Reconstruct portfolio
    portfolio = Portfolio(cash=Decimal(snapshot['cash']))
    portfolio.realised_pnl = Decimal(snapshot['realised_pnl'])
    portfolio.commissions_paid = Decimal(snapshot['commissions_paid'])

    # Restore positions
    restored_positions: dict[str, Position] = {}
    for pos_data in snapshot['positions']:
        pos = Position(
            symbol=pos_data['symbol'],
            quantity=Decimal(pos_data['quantity']),
            average_price=Decimal(pos_data['average_price']),
            entry_time_utc=datetime.fromisoformat(pos_data['entry_time_utc']) if pos_data['entry_time_utc'] else None,
            last_update_utc=datetime.fromisoformat(pos_data['last_update_utc'])
            if pos_data['last_update_utc']
            else None,
            total_volume=Decimal(pos_data['total_volume']),
        )
        restored_positions[pos.symbol] = pos
    portfolio.replace_positions(restored_positions)

    # Restore trade log (deserialize Decimals)
    trade_log_data: list[dict[str, Any]] = snapshot.get('trade_log', [])  # type: ignore[assignment]
    for trade_data in trade_log_data:
        restored_trade: dict[str, Any] = {}
        for key, value in trade_data.items():
            if key in {'quantity', 'price', 'realised_pnl', 'commission'}:
                restored_trade[key] = Decimal(str(value))
            elif key == 'timestamp':
                restored_trade[key] = datetime.fromisoformat(str(value)) if value else None
            else:
                restored_trade[key] = value
        portfolio.trade_log.append(restored_trade)

    return portfolio


def save_risk_state(risk_state: RiskState, path: str) -> None:
    """
    Persist risk engine state to JSON.

    Args:
        risk_state: RiskState instance to serialize
        path: Target file path
    """
    # last_reset_date is stored as string in RiskState
    last_reset_str = str(risk_state.last_reset_date)

    snapshot = {
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'last_reset_date': last_reset_str,
        'daily_pnl': str(risk_state.daily_pnl),
        'peak_equity': str(risk_state.peak_equity),
        'start_of_day_equity': str(risk_state.start_of_day_equity),
        'halted': risk_state.halted,
        'halt_reason': risk_state.halt_reason,
    }

    # P0-5 Fix: Use atomic write to prevent corruption
    _atomic_write_json(snapshot, Path(path))


def load_risk_state(path: str) -> RiskState:
    """
    Restore risk engine state from JSON checkpoint.

    P0-5 Fix: Attempts backup file if primary is corrupted.

    Args:
        path: Path to checkpoint file

    Returns:
        Reconstructed RiskState instance
    """
    target = Path(path)
    backup_path = target.with_suffix('.backup')

    if not target.exists() and not backup_path.exists():
        raise FileNotFoundError(f'Risk state checkpoint not found: {path}')

    # P0-5 Fix: Try primary file, fall back to backup if corrupted
    snapshot = None
    load_error = None

    # Try primary file first
    if target.exists():
        try:
            with target.open('r') as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError as exc:
            load_error = exc
            # Primary corrupted, will try backup

    # If primary failed or doesn't exist, try backup
    if snapshot is None and backup_path.exists():
        try:
            with backup_path.open('r') as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Both primary and backup checkpoints corrupted: {path}') from exc

    if snapshot is None:
        raise ValueError(f'Failed to load risk state checkpoint: {path}') from load_error

    if snapshot.get('version') != '1.0':
        raise ValueError(f'Unsupported checkpoint version: {snapshot.get("version")}')

    return RiskState(
        last_reset_date=snapshot['last_reset_date'],  # Keep as string
        daily_pnl=Decimal(snapshot['daily_pnl']),
        peak_equity=Decimal(snapshot['peak_equity']),
        start_of_day_equity=Decimal(snapshot['start_of_day_equity']),
        halted=snapshot['halted'],
        halt_reason=snapshot['halt_reason'],
    )


def save_checkpoint(portfolio: PortfolioProtocol, risk_state: RiskState, checkpoint_dir: str = 'state') -> None:
    """
    Save both portfolio and risk state to a checkpoint directory.

    Creates two files:
    - {checkpoint_dir}/portfolio.json
    - {checkpoint_dir}/risk_state.json

    Args:
        portfolio: Portfolio to persist
        risk_state: RiskState to persist
        checkpoint_dir: Directory for checkpoint files (default: "state")
    """
    save_portfolio_snapshot(portfolio, f'{checkpoint_dir}/portfolio.json')
    save_risk_state(risk_state, f'{checkpoint_dir}/risk_state.json')


class FileStateManager:
    """Filesystem-backed implementation of StateManagerProtocol."""

    def save_checkpoint(self, portfolio: PortfolioProtocol, risk_state: RiskState, checkpoint_dir: str) -> None:
        save_checkpoint(portfolio, risk_state, checkpoint_dir)

    def load_checkpoint(self, checkpoint_dir: str) -> tuple[Portfolio, RiskState]:
        return load_checkpoint(checkpoint_dir)

    def save_state(self, state: dict[str, Any], filepath: str) -> None:
        _atomic_write_json(state, Path(filepath))

    def load_state(self, filepath: str) -> dict[str, Any]:
        target = Path(filepath)
        backup = target.with_suffix('.backup')

        if not target.exists() and not backup.exists():
            raise FileNotFoundError(f'State file not found: {filepath}')

        snapshot = None
        load_error = None

        # Try primary file first
        if target.exists():
            try:
                with target.open('r', encoding='utf-8') as handle:
                    snapshot = json.load(handle)
            except json.JSONDecodeError as exc:
                load_error = exc
                # Primary corrupted, will try backup

        # If primary failed or doesn't exist, try backup
        if snapshot is None and backup.exists():
            try:
                with backup.open('r', encoding='utf-8') as handle:
                    snapshot = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Both primary and backup state files corrupted: {filepath}') from exc

        if snapshot is None:
            raise ValueError(f'Failed to load state file: {filepath}') from load_error

        if not isinstance(snapshot, dict):
            raise ValueError(f'State file does not contain a JSON object: {filepath}')

        return snapshot


def load_checkpoint(checkpoint_dir: str = 'state') -> tuple[Portfolio, RiskState]:
    """
    Load both portfolio and risk state from a checkpoint directory.

    Args:
        checkpoint_dir: Directory containing checkpoint files

    Returns:
        Tuple of (Portfolio, RiskState)

    Raises:
        FileNotFoundError: If checkpoint files don't exist
    """
    portfolio = load_portfolio_snapshot(f'{checkpoint_dir}/portfolio.json')
    risk_state = load_risk_state(f'{checkpoint_dir}/risk_state.json')
    return portfolio, risk_state
