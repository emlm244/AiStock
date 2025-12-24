"""
Audit and state management utilities for the automation pipeline.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import TypeAlias, cast

from .logging import configure_logger

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list['JSONValue'] | dict[str, 'JSONValue']


def _load_json_record(line: str) -> dict[str, JSONValue] | None:
    try:
        payload = cast(object, json.loads(line))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, JSONValue], payload)


@dataclass(frozen=True)
class AuditConfig:
    """
    Central configuration for audit and state artefacts.

    Attributes:
        log_path: Append-only JSONL log recording high-level events.
        state_root: Root directory used by :class:`StateStore`.
    """

    log_path: str = 'state/audit_log.jsonl'
    state_root: str = 'state/archive'


class AuditLogger:
    """
    Append-only logger with hash chaining for tamper-evident records.
    """

    def __init__(self, config: AuditConfig):
        self.config = config
        self.log_path = Path(config.log_path).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = configure_logger('AuditLogger', structured=True)

    def append(
        self,
        action: str,
        actor: str,
        *,
        details: Mapping[str, JSONValue] | None = None,
        artefacts: Mapping[str, str] | None = None,
    ) -> dict[str, JSONValue]:
        details_payload: dict[str, JSONValue] = dict(details) if details else {}
        artefacts_payload: dict[str, JSONValue] = cast(dict[str, JSONValue], dict(artefacts)) if artefacts else {}
        record: dict[str, JSONValue] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'actor': actor,
            'details': details_payload,
            'artefacts': artefacts_payload,
            'prev_hash': self._last_hash(),
        }
        record['hash'] = self._compute_hash(record)
        with self.log_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write('\n')
        self.logger.info('audit_event', extra={'action': action, 'actor': actor})
        return record

    def tail(self, limit: int = 10) -> list[dict[str, JSONValue]]:
        if not self.log_path.exists():
            return []
        with self.log_path.open('r', encoding='utf-8') as handle:
            lines = handle.readlines()[-limit:]
        entries: list[dict[str, JSONValue]] = []
        for line in lines:
            if not line.strip():
                continue
            entry = _load_json_record(line)
            if entry:
                entries.append(entry)
        return entries

    def _last_hash(self) -> str:
        if not self.log_path.exists():
            return '0'
        # Read last line efficiently
        with self.log_path.open('rb') as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return '0'
            buffer = bytearray()
            pointer = handle.tell() - 1
            while pointer >= 0:
                handle.seek(pointer)
                char = handle.read(1)
                if char == b'\n' and buffer:
                    break
                buffer.extend(char)
                pointer -= 1
            last_line = bytes(reversed(buffer)).decode('utf-8').strip()
            if not last_line:
                return '0'
            try:
                record = _load_json_record(last_line)
                if not record:
                    return '0'
                hash_value = record.get('hash')
                return hash_value if isinstance(hash_value, str) else '0'
            except json.JSONDecodeError:
                return '0'

    @staticmethod
    def _compute_hash(record: Mapping[str, JSONValue]) -> str:
        payload = json.dumps(record, sort_keys=True, default=str).encode('utf-8')
        return sha256(payload).hexdigest()


class StateStore:
    """
    Utility for persisting artefacts into versioned state directories.
    """

    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        step: str,
        name: str,
        payload: object,
        *,
        suffix: str | None = None,
    ) -> Path:
        timestamp = datetime.now(timezone.utc)
        day_dir = self.root / timestamp.strftime('%Y-%m-%d') / step
        day_dir.mkdir(parents=True, exist_ok=True)
        base = timestamp.strftime('%H%M%S')
        suffix = suffix or self._infer_suffix(payload)
        target = day_dir / f'{base}_{name}{suffix}'
        self._write_payload(target, payload)
        return target

    def latest(self, step: str) -> Path | None:
        step_dir = self.root.glob('*/' + step)
        candidates: list[Path] = []
        for directory in step_dir:
            candidates.extend(sorted(directory.glob('*')))
        return max(candidates) if candidates else None

    @staticmethod
    def _infer_suffix(payload: object) -> str:
        if isinstance(payload, (dict, list)):
            return '.json'
        if isinstance(payload, bytes):
            return '.bin'
        return '.txt'

    @staticmethod
    def _write_payload(target: Path, payload: object) -> None:
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        elif isinstance(payload, (dict, list)):
            with target.open('w', encoding='utf-8') as handle:
                json.dump(payload, handle, indent=2)
        else:
            with target.open('w', encoding='utf-8') as handle:
                handle.write(str(payload))


class AlertDispatcher:
    """
    Simple dispatcher that records alerts for downstream integration.
    """

    def __init__(self):
        self.logger = configure_logger('Alerts', structured=True)
        self._subscriptions: list[Callable[[str, dict[str, JSONValue]], None]] = []

    def subscribe(self, handler: Callable[[str, dict[str, JSONValue]], None]) -> None:
        """Subscribe a handler function to receive alerts."""
        self._subscriptions.append(handler)

    def notify(self, channel: str, payload: dict[str, JSONValue]) -> None:
        event = {'channel': channel, 'payload': payload, 'timestamp': datetime.now(timezone.utc).isoformat()}
        self.logger.info('alert', extra=event)
        for handler in self._subscriptions:
            handler(channel, payload)


class ComplianceReporter:
    """
    Produce summaries from recent audit events.
    """

    def __init__(self, audit_logger: AuditLogger):
        self.audit_logger = audit_logger

    def build_summary(self, limit: int = 20) -> dict[str, JSONValue]:
        entries = self.audit_logger.tail(limit=limit)
        entries_payload: list[JSONValue] = cast(list[JSONValue], list(entries))
        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'entries': entries_payload,
            'count': len(entries),
        }


__all__ = [
    'AlertDispatcher',
    'AuditConfig',
    'AuditLogger',
    'ComplianceReporter',
    'StateStore',
]
