"""Helpers to persist backtest artefacts and runtime state."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .engine import Trade
from .portfolio import Portfolio, Position
from .risk import RiskState


def write_trades(trades: Iterable[Trade], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "symbol", "quantity", "price", "realised_pnl", "equity", "order_id", "strategy"])
        for trade in trades:
            writer.writerow([
                trade.timestamp.isoformat(),
                trade.symbol,
                float(trade.quantity),
                float(trade.price),
                float(trade.realised_pnl),
                float(trade.equity),
                trade.order_id,
                trade.strategy,
            ])


def write_equity_curve(equity_curve: Iterable[tuple[datetime, float]], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "equity"])
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


def save_portfolio_snapshot(portfolio: Portfolio, path: str) -> None:
    """
    Persist portfolio state to JSON for crash recovery.

    Args:
        portfolio: Portfolio instance to serialize
        path: Target file path (will create parent directories)
    """
    positions_data = []
    for _symbol, pos in portfolio.positions.items():
        positions_data.append({
            "symbol": pos.symbol,
            "quantity": str(pos.quantity),
            "average_price": str(pos.average_price),
            "entry_time_utc": pos.entry_time_utc.isoformat() if pos.entry_time_utc else None,
            "last_update_utc": pos.last_update_utc.isoformat() if pos.last_update_utc else None,
            "total_volume": str(pos.total_volume),
        })

    snapshot = {
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cash": str(portfolio.cash),
        "positions": positions_data,
        "realised_pnl": str(portfolio.realised_pnl),
        "commissions_paid": str(portfolio.commissions_paid),
        "trade_log": portfolio.trade_log[-1000:],  # Keep last 1000 trades
    }

    # Serialize trade log (contains Decimal objects)
    serialized_trades = []
    for trade in snapshot["trade_log"]:
        serialized_trade = {}
        for key, value in trade.items():
            serialized_trade[key] = _serialize_decimal(value)
        serialized_trades.append(serialized_trade)
    snapshot["trade_log"] = serialized_trades

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as handle:
        json.dump(snapshot, handle, indent=2)


def load_portfolio_snapshot(path: str) -> Portfolio:
    """
    Restore portfolio state from JSON checkpoint.

    Args:
        path: Path to checkpoint file

    Returns:
        Reconstructed Portfolio instance

    Raises:
        FileNotFoundError: If checkpoint doesn't exist
        ValueError: If checkpoint is corrupted
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Portfolio checkpoint not found: {path}")

    with target.open("r") as handle:
        snapshot = json.load(handle)

    if snapshot.get("version") != "1.0":
        raise ValueError(f"Unsupported checkpoint version: {snapshot.get('version')}")

    # Reconstruct portfolio
    portfolio = Portfolio(cash=Decimal(snapshot["cash"]))
    portfolio.realised_pnl = Decimal(snapshot["realised_pnl"])
    portfolio.commissions_paid = Decimal(snapshot["commissions_paid"])

    # Restore positions
    for pos_data in snapshot["positions"]:
        pos = Position(
            symbol=pos_data["symbol"],
            quantity=Decimal(pos_data["quantity"]),
            average_price=Decimal(pos_data["average_price"]),
            entry_time_utc=datetime.fromisoformat(pos_data["entry_time_utc"]) if pos_data["entry_time_utc"] else None,
            last_update_utc=datetime.fromisoformat(pos_data["last_update_utc"]) if pos_data["last_update_utc"] else None,
            total_volume=Decimal(pos_data["total_volume"]),
        )
        portfolio.positions[pos.symbol] = pos

    # Restore trade log (deserialize Decimals)
    for trade_data in snapshot["trade_log"]:
        restored_trade = {}
        for key, value in trade_data.items():
            if key in {"quantity", "price", "realised_pnl", "commission"}:
                restored_trade[key] = Decimal(str(value))
            elif key == "timestamp":
                restored_trade[key] = datetime.fromisoformat(value) if value else None
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
    snapshot = {
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_reset_date": risk_state.last_reset_date.isoformat(),
        "daily_pnl": str(risk_state.daily_pnl),
        "peak_equity": str(risk_state.peak_equity),
        "start_of_day_equity": str(risk_state.start_of_day_equity),
        "halted": risk_state.halted,
        "halt_reason": risk_state.halt_reason,
    }

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as handle:
        json.dump(snapshot, handle, indent=2)


def load_risk_state(path: str) -> RiskState:
    """
    Restore risk engine state from JSON checkpoint.

    Args:
        path: Path to checkpoint file

    Returns:
        Reconstructed RiskState instance
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Risk state checkpoint not found: {path}")

    with target.open("r") as handle:
        snapshot = json.load(handle)

    if snapshot.get("version") != "1.0":
        raise ValueError(f"Unsupported checkpoint version: {snapshot.get('version')}")

    return RiskState(
        last_reset_date=date.fromisoformat(snapshot["last_reset_date"]),
        daily_pnl=Decimal(snapshot["daily_pnl"]),
        peak_equity=Decimal(snapshot["peak_equity"]),
        start_of_day_equity=Decimal(snapshot["start_of_day_equity"]),
        halted=snapshot["halted"],
        halt_reason=snapshot["halt_reason"],
    )


def save_checkpoint(portfolio: Portfolio, risk_state: RiskState, checkpoint_dir: str = "state") -> None:
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
    save_portfolio_snapshot(portfolio, f"{checkpoint_dir}/portfolio.json")
    save_risk_state(risk_state, f"{checkpoint_dir}/risk_state.json")


def load_checkpoint(checkpoint_dir: str = "state") -> tuple[Portfolio, RiskState]:
    """
    Load both portfolio and risk state from a checkpoint directory.

    Args:
        checkpoint_dir: Directory containing checkpoint files

    Returns:
        Tuple of (Portfolio, RiskState)

    Raises:
        FileNotFoundError: If checkpoint files don't exist
    """
    portfolio = load_portfolio_snapshot(f"{checkpoint_dir}/portfolio.json")
    risk_state = load_risk_state(f"{checkpoint_dir}/risk_state.json")
    return portfolio, risk_state
