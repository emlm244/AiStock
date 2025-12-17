"""
Runtime settings helpers for environment-driven configuration.

Motivation:
- Consolidate IBKR credential/host/port parsing
- Fail fast when required variables are missing or malformed
- Surface timezone + log-level knobs advertised in `.env.example`
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class IBKREnvSettings:
    """IBKR connection/runtime knobs sourced from environment variables."""

    host: str
    paper_port: int
    live_port: int
    account_id: str | None
    client_id: int | None

    def require_credentials(self) -> tuple[str, int]:
        """Return validated (account_id, client_id) or raise if missing."""
        if not self.account_id:
            raise ValueError('IBKR_ACCOUNT_ID must be set in .env to use IBKR trading modes.')
        if self.client_id is None:
            raise ValueError('IBKR_CLIENT_ID must be set in .env to use IBKR trading modes.')
        return self.account_id, self.client_id


@dataclass(frozen=True)
class RuntimeSettings:
    """Top-level runtime settings consumed by the GUI/headless launchers."""

    log_level: str
    timezone_name: str
    timezone: ZoneInfo
    ibkr: IBKREnvSettings


def load_runtime_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    """
    Parse runtime settings from environment variables.

    Args:
        env: Optional mapping for testability. Defaults to os.environ.
    """
    source = _apply_dotenv_overrides(os.environ) if env is None else env

    host = _clean_str(source.get('IBKR_TWS_HOST', '127.0.0.1')) or '127.0.0.1'
    paper_port = _parse_port(
        source.get('IBKR_PAPER_PORT') or source.get('IBKR_TWS_PORT') or '7497',
        'IBKR_PAPER_PORT/IBKR_TWS_PORT',
    )
    live_port = _parse_port(source.get('IBKR_LIVE_PORT', '7496'), 'IBKR_LIVE_PORT')

    account_id = _clean_str(source.get('IBKR_ACCOUNT_ID'))
    client_id = _parse_optional_int(source.get('IBKR_CLIENT_ID'), 'IBKR_CLIENT_ID')

    tz_name = _clean_str(source.get('TIMEZONE', 'America/New_York')) or 'America/New_York'
    timezone = _load_timezone(tz_name)

    log_level = (_clean_str(source.get('LOG_LEVEL', 'INFO')) or 'INFO').upper()

    ibkr = IBKREnvSettings(
        host=host,
        paper_port=paper_port,
        live_port=live_port,
        account_id=account_id,
        client_id=client_id,
    )

    return RuntimeSettings(
        log_level=log_level,
        timezone_name=tz_name,
        timezone=timezone,
        ibkr=ibkr,
    )


def _apply_dotenv_overrides(env: Mapping[str, str]) -> Mapping[str, str]:
    """
    Load `.env` from the current working directory (if present) and apply it as defaults.

    This keeps explicit environment variables authoritative while matching the repo's
    `.env.example` workflow (copy to `.env` and run without manually exporting vars).
    """
    dotenv = _load_dotenv_file(Path('.env'))
    if not dotenv:
        return env
    merged = dict(env)
    for key, value in dotenv.items():
        merged.setdefault(key, value)
    return merged


def _load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('export '):
            stripped = stripped[len('export ') :].lstrip()
        if '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if not key:
            continue
        parsed_value = _parse_dotenv_value(value)
        parsed[key] = parsed_value
    return parsed


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ''
    quote = value[0]
    if quote in {'"', "'"}:
        if len(value) >= 2 and value[-1] == quote:
            return value[1:-1]
        return value[1:]

    for idx, char in enumerate(value):
        if char == '#' and idx > 0 and value[idx - 1].isspace():
            value = value[:idx].rstrip()
            break
    return value


def _clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _parse_port(raw: str, key: str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be an integer, got {raw!r}') from None
    if not 1 <= port <= 65535:
        raise ValueError(f'{key} must be between 1 and 65535, got {port}')
    return port


def _parse_optional_int(raw: str | None, key: str) -> int | None:
    cleaned = _clean_str(raw)
    if cleaned is None:
        return None
    try:
        value = int(cleaned)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be an integer, got {raw!r}') from None
    if value < 0:
        raise ValueError(f'{key} must be non-negative, got {value}')
    return value


def _load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f'TIMEZONE {name!r} is not recognised by zoneinfo') from exc
    except Exception as exc:  # pragma: no cover - defensive catch
        raise ValueError(f'Unable to load timezone {name!r}: {exc}') from exc
