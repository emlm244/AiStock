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
from typing import cast

from .audit import JSONValue


class OrderIdempotencyTracker:
    """
    Track submitted client order IDs to prevent duplicate submissions.

    Persists to disk so that restarts can resume without duplication.
    """

    _SCHEMA_VERSION = 2

    def __init__(
        self,
        storage_path: str = 'state/submitted_orders.json',
        expiration_minutes: int = 5,
    ):
        """
        Initialize idempotency tracker with time-boxed duplicate prevention.

        Args:
            storage_path: Path to persist submitted order IDs
            expiration_minutes: How long to remember submitted IDs (default: 5 min)
                               After this window, IDs are considered stale and can be
                               resubmitted (allows safe restart retries)
        """
        self.storage_path = storage_path
        self.expiration_ms = expiration_minutes * 60 * 1000  # Convert to milliseconds
        self._lock = threading.Lock()
        self._submitted_ids: dict[str, int] = {}
        self._load_from_disk()
        # Clean up stale entries on startup
        self.clear_stale_ids()

    # ------------------------------------------------------------------
    def _load_from_disk(self) -> None:
        """Load previously submitted order IDs from persistent storage (thread-safe)."""
        # Acquire lock BEFORE file I/O to prevent race conditions
        with self._lock:
            path = Path(self.storage_path)
            backup_path = path.with_suffix('.backup')
            if not path.exists() and not backup_path.exists():
                return

            def _load_json(target: Path) -> object | None:
                try:
                    with target.open('r', encoding='utf-8') as handle:
                        return cast(object, json.load(handle))
                except (OSError, json.JSONDecodeError):
                    return None

            data: object | None = _load_json(path)
            restored_from_backup = False
            if data is None and backup_path.exists():
                data = _load_json(backup_path)
                restored_from_backup = data is not None

            if not isinstance(data, dict):
                self._submitted_ids.clear()
                return
            payload = cast(dict[str, object], data)

            if restored_from_backup:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open('w', encoding='utf-8') as handle:
                        json.dump(payload, handle, indent=2)
                except OSError:
                    pass

            submitted_payload_obj = payload.get('submitted_ids', [])
            submitted_payload: list[object] = (
                cast(list[object], submitted_payload_obj) if isinstance(submitted_payload_obj, list) else []
            )
            self._submitted_ids.clear()
            if submitted_payload and isinstance(submitted_payload[0], dict):
                for entry_obj in submitted_payload:
                    if not isinstance(entry_obj, dict):
                        continue
                    entry = cast(dict[str, object], entry_obj)
                    cid = entry.get('id')
                    timestamp_ms = entry.get('timestamp_ms')
                    if isinstance(cid, str) and isinstance(timestamp_ms, int):
                        self._submitted_ids[cid] = timestamp_ms
            else:
                # Legacy v1 format: plain list of ids without timestamps
                for cid_obj in submitted_payload:
                    if isinstance(cid_obj, str):
                        self._submitted_ids[cid_obj] = self._extract_timestamp_ms(cid_obj)

    def _write_locked(self) -> None:
        """Persist submitted order IDs to disk (expects lock to be held)."""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialisable: list[JSONValue] = [
            {'id': cid, 'timestamp_ms': ts}
            for cid, ts in sorted(self._submitted_ids.items(), key=lambda item: (item[1], item[0]))
        ]
        payload: dict[str, JSONValue] = {
            'version': self._SCHEMA_VERSION,
            'submitted_ids': serialisable,
            'last_updated': datetime.now(timezone.utc).isoformat(),
        }
        temp_path = path.with_suffix('.tmp')
        backup_path = path.with_suffix('.backup')
        try:
            with temp_path.open('w', encoding='utf-8') as handle:
                json.dump(payload, handle, indent=2)

            if path.exists():
                path.replace(backup_path)

            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_quantity(quantity: Decimal | float | int | str | None) -> str:
        if quantity is None:
            return '0'
        if isinstance(quantity, Decimal):
            value = quantity
        else:
            try:
                value = Decimal(str(quantity))
            except InvalidOperation:
                value = Decimal('0')
        return format(value.normalize() if value != 0 else value, 'f')

    @staticmethod
    def _extract_timestamp_ms(client_order_id: str) -> int:
        """
        Parse the millisecond timestamp embedded in the client order ID.
        Defaults to 0 if the format is unexpected.
        """
        parts = client_order_id.split('_')
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
        payload = f'{symbol.upper()}|{ts_unix_ms}|{qty_str}'
        digest = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]
        return f'{symbol.upper()}_{ts_unix_ms}_{digest}'

    def is_duplicate(self, client_order_id: str) -> bool:
        """
        Check if this client order ID was submitted recently (within expiration window).

        Returns:
            True if the ID was submitted within expiration_minutes, False otherwise
        """
        with self._lock:
            if client_order_id not in self._submitted_ids:
                return False

            # Check if the entry is still fresh (within expiration window)
            submitted_ts_ms = self._submitted_ids[client_order_id]
            current_ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            age_ms = current_ts_ms - submitted_ts_ms

            return age_ms < self.expiration_ms

    def mark_submitted(self, client_order_id: str) -> None:
        """
        Mark a client order ID as submitted and persist to disk.

        Should be called AFTER successful broker.submit() to record acceptance.
        Time-boxed: entries expire after expiration_minutes, allowing safe retries.

        CRITICAL: Stores actual submission time (now), NOT bar timestamp.
        This ensures TTL works correctly for delayed/backfilled bars.
        """
        # Use actual submission time, not bar timestamp
        submission_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with self._lock:
            self._submitted_ids[client_order_id] = submission_time_ms
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

    def clear_submitted(self, client_order_id: str) -> None:
        """
        Remove a client order ID from submitted tracking.

        Used for rollback when broker.submit() fails after mark_submitted().
        """
        with self._lock:
            if client_order_id in self._submitted_ids:
                del self._submitted_ids[client_order_id]
                self._write_locked()

    def clear_stale_ids(self) -> int:
        """
        Remove all submitted IDs older than expiration_minutes.

        Called on startup to clean up entries from previous sessions.
        Allows safe retry of orders that were marked submitted but may
        never have reached the broker (e.g., crash during mark_submitted).

        Returns:
            Number of stale IDs removed
        """
        current_ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with self._lock:
            stale_ids = [
                cid for cid, ts_ms in self._submitted_ids.items() if (current_ts_ms - ts_ms) >= self.expiration_ms
            ]

            for cid in stale_ids:
                del self._submitted_ids[cid]

            if stale_ids:
                self._write_locked()

            return len(stale_ids)

    def count_submitted(self) -> int:
        """Return the total number of tracked submitted order IDs."""
        with self._lock:
            return len(self._submitted_ids)
