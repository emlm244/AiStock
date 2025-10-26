"""
Order idempotency utilities for preventing duplicate submissions.

P0 Fix: Ensures restart after partial order submission doesn't duplicate orders.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict


class OrderIdempotencyTracker:
    """
    Track submitted client order IDs to prevent duplicate submissions.

    Persists to disk so that restarts can resume without duplication.
    """

    _SCHEMA_VERSION = 2

    def __init__(self, storage_path: str = "state/submitted_orders.json"):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._submitted_ids: Dict[str, int] = {}
        self._load_from_disk()

    # ------------------------------------------------------------------
    def _load_from_disk(self) -> None:
        """Load previously submitted order IDs from persistent storage."""
        path = Path(self.storage_path)
        if not path.exists():
            return

        with path.open("r") as handle:
            data = json.load(handle)

        submitted_payload = data.get("submitted_ids", [])
        with self._lock:
            self._submitted_ids.clear()
            if submitted_payload and isinstance(submitted_payload[0], dict):
                for entry in submitted_payload:
                    cid = entry.get("id")
                    timestamp_ms = entry.get("timestamp_ms")
                    if isinstance(cid, str) and isinstance(timestamp_ms, int):
                        self._submitted_ids[cid] = timestamp_ms
            else:
                # Legacy v1 format: plain list of ids without timestamps
                for cid in submitted_payload:
                    if isinstance(cid, str):
                        self._submitted_ids[cid] = self._extract_timestamp_ms(cid)

    def _write_locked(self) -> None:
        """Persist submitted order IDs to disk (expects lock to be held)."""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = [
            {"id": cid, "timestamp_ms": ts}
            for cid, ts in sorted(self._submitted_ids.items(), key=lambda item: (item[1], item[0]))
        ]
        payload: Dict[str, Any] = {
            "version": self._SCHEMA_VERSION,
            "submitted_ids": serialisable,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        with path.open("w") as handle:
            json.dump(payload, handle, indent=2)

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_quantity(quantity: Decimal | float | int | str | None) -> str:
        if quantity is None:
            return "0"
        if isinstance(quantity, Decimal):
            value = quantity
        else:
            try:
                value = Decimal(str(quantity))
            except InvalidOperation:
                value = Decimal("0")
        return format(value.normalize() if value != 0 else value, "f")

    @staticmethod
    def _extract_timestamp_ms(client_order_id: str) -> int:
        """
        Parse the millisecond timestamp embedded in the client order ID.
        Defaults to 0 if the format is unexpected.
        """
        parts = client_order_id.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
        return 0

    # ------------------------------------------------------------------
    def generate_client_order_id(
        self,
        symbol: str,
        timestamp: datetime,
        quantity: Decimal | float | int | str | None = None,
    ) -> str:
        """
        Generate a deterministic client order ID for idempotency.

        Format: SYMBOL_TIMESTAMPMS_HASH12
        """
        ts_unix_ms = int(timestamp.timestamp() * 1000)
        qty_str = self._normalise_quantity(quantity)
        payload = f"{symbol.upper()}|{ts_unix_ms}|{qty_str}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
        return f"{symbol.upper()}_{ts_unix_ms}_{digest}"

    def is_duplicate(self, client_order_id: str) -> bool:
        """Check if this client order ID has already been submitted."""
        with self._lock:
            return client_order_id in self._submitted_ids

    def mark_submitted(self, client_order_id: str) -> None:
        """
        Mark a client order ID as submitted and persist to disk.

        Should be called immediately before broker.submit() to ensure
        idempotency across crashes.
        """
        timestamp_ms = self._extract_timestamp_ms(client_order_id)
        with self._lock:
            self._submitted_ids[client_order_id] = timestamp_ms
            self._write_locked()

    def clear_old_ids(self, retention_count: int = 10000) -> None:
        """
        Clear old submitted order IDs to prevent unbounded growth.

        Keeps only the most recent N IDs. Should be called periodically
        (e.g., daily during risk reset).
        """
        with self._lock:
            if len(self._submitted_ids) <= retention_count:
                return
            sorted_items = sorted(self._submitted_ids.items(), key=lambda item: (item[1], item[0]))
            self._submitted_ids = dict(sorted_items[-retention_count:])
            self._write_locked()

    def count_submitted(self) -> int:
        """Return the total number of tracked submitted order IDs."""
        with self._lock:
            return len(self._submitted_ids)
