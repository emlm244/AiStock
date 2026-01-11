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
class AccountCapabilitiesSettings:
    """Account capabilities sourced from environment variables."""

    account_type: str  # 'cash' or 'margin'
    account_balance: float
    enable_stocks: bool
    enable_etfs: bool
    enable_futures: bool
    enable_options: bool
    allow_extended_hours: bool
    enforce_settlement: bool


@dataclass(frozen=True)
class GuiSettings:
    """GUI settings sourced from environment variables."""

    capital: str
    risk_level: str
    investment_goal: str
    session_time_limit_minutes: str
    max_loss_per_trade_pct: str
    trade_tempo: str
    minimum_balance: str
    minimum_balance_enabled: bool
    max_daily_loss_pct: str
    max_drawdown_pct: str
    max_trades_per_hour: str
    max_trades_per_day: str
    chase_threshold_pct: str
    news_volume_multiplier: str
    end_of_day_minutes: str
    trading_mode: str
    enable_withdrawal: bool
    target_capital: str
    withdrawal_threshold: str
    withdrawal_frequency: str
    enable_eod_flatten: bool
    eod_flatten_time: str


@dataclass(frozen=True)
class RuntimeSettings:
    """Top-level runtime settings consumed by the GUI/headless launchers."""

    log_level: str
    timezone_name: str
    timezone: ZoneInfo
    ibkr: IBKREnvSettings
    account_capabilities: AccountCapabilitiesSettings
    gui_settings: GuiSettings


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

    # Account capabilities
    account_type = (_clean_str(source.get('ACCOUNT_TYPE', 'cash')) or 'cash').lower()
    if account_type not in ('cash', 'margin'):
        account_type = 'cash'  # Default to cash if invalid
    account_balance = _parse_float(source.get('ACCOUNT_BALANCE'), 'ACCOUNT_BALANCE', default=0.0)
    if 'ALLOW_EXTENDED_HOURS' in source:
        allow_extended_hours = _parse_bool(source.get('ALLOW_EXTENDED_HOURS'))
    else:
        allow_extended_hours = _parse_bool(source.get('ENABLE_PREMARKET')) or _parse_bool(
            source.get('ENABLE_AFTERHOURS')
        )

    account_capabilities = AccountCapabilitiesSettings(
        account_type=account_type,
        account_balance=account_balance,
        enable_stocks=_parse_bool(source.get('ENABLE_STOCKS', 'true')),
        enable_etfs=_parse_bool(source.get('ENABLE_ETFS', 'true')),
        enable_futures=_parse_bool(source.get('ENABLE_FUTURES', 'false')),
        enable_options=_parse_bool(source.get('ENABLE_OPTIONS', 'false')),
        allow_extended_hours=allow_extended_hours,
        enforce_settlement=_parse_bool(source.get('ENFORCE_SETTLEMENT', 'true')),
    )

    risk_level = _parse_env_str(source, 'GUI_RISK_LEVEL', 'conservative')
    if risk_level not in {'conservative', 'moderate', 'aggressive'}:
        risk_level = 'conservative'

    investment_goal = _parse_env_str(source, 'GUI_INVESTMENT_GOAL', 'steady_growth')
    if investment_goal not in {'steady_growth', 'quick_gains'}:
        investment_goal = 'steady_growth'

    trade_tempo = _parse_env_str(source, 'GUI_TRADE_TEMPO', 'balanced')
    if trade_tempo not in {'steady', 'balanced', 'fast'}:
        trade_tempo = 'balanced'

    trading_mode = _parse_env_str(source, 'GUI_TRADING_MODE', 'ibkr_paper').lower()
    if trading_mode not in {'ibkr_paper', 'ibkr_live'}:
        trading_mode = 'ibkr_paper'

    withdrawal_frequency = _parse_env_str(source, 'GUI_WITHDRAWAL_FREQUENCY', 'Daily')
    if withdrawal_frequency.lower() not in {'daily', 'weekly', 'monthly'}:
        withdrawal_frequency = 'Daily'
    else:
        withdrawal_frequency = withdrawal_frequency.title()

    gui_settings = GuiSettings(
        capital=_parse_env_str(source, 'GUI_CAPITAL', '200'),
        risk_level=risk_level,
        investment_goal=investment_goal,
        session_time_limit_minutes=_parse_env_str(source, 'GUI_SESSION_TIME_LIMIT_MINUTES', '240'),
        max_loss_per_trade_pct=_parse_env_str(source, 'GUI_MAX_LOSS_PER_TRADE_PCT', '5'),
        trade_tempo=trade_tempo,
        minimum_balance=_parse_env_str(source, 'GUI_MINIMUM_BALANCE', '100'),
        minimum_balance_enabled=_parse_bool(source.get('GUI_MINIMUM_BALANCE_ENABLED', 'true')),
        max_daily_loss_pct=_parse_env_str(source, 'GUI_MAX_DAILY_LOSS_PCT', '5'),
        max_drawdown_pct=_parse_env_str(source, 'GUI_MAX_DRAWDOWN_PCT', '15'),
        max_trades_per_hour=_parse_env_str(source, 'GUI_MAX_TRADES_PER_HOUR', '20'),
        max_trades_per_day=_parse_env_str(source, 'GUI_MAX_TRADES_PER_DAY', '100'),
        chase_threshold_pct=_parse_env_str(source, 'GUI_CHASE_THRESHOLD_PCT', '5'),
        news_volume_multiplier=_parse_env_str(source, 'GUI_NEWS_VOLUME_MULTIPLIER', '5'),
        end_of_day_minutes=_parse_env_str(source, 'GUI_END_OF_DAY_MINUTES', '30'),
        trading_mode=trading_mode,
        enable_withdrawal=_parse_bool(source.get('GUI_ENABLE_WITHDRAWAL', 'false')),
        target_capital=_parse_env_str(source, 'GUI_TARGET_CAPITAL', '200'),
        withdrawal_threshold=_parse_env_str(source, 'GUI_WITHDRAWAL_THRESHOLD', '5000'),
        withdrawal_frequency=withdrawal_frequency,
        enable_eod_flatten=_parse_bool(source.get('GUI_ENABLE_EOD_FLATTEN', 'false')),
        eod_flatten_time=_parse_env_str(source, 'GUI_EOD_FLATTEN_TIME', '15:45'),
    )

    return RuntimeSettings(
        log_level=log_level,
        timezone_name=tz_name,
        timezone=timezone,
        ibkr=ibkr,
        account_capabilities=account_capabilities,
        gui_settings=gui_settings,
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


def _parse_env_str(env: Mapping[str, str], key: str, default: str) -> str:
    value = _clean_str(env.get(key))
    return value if value is not None else default


def _parse_float(raw: str | None, key: str, default: float = 0.0) -> float:
    cleaned = _clean_str(raw)
    if cleaned is None:
        return default
    try:
        value = float(cleaned)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be a number, got {raw!r}') from None
    if value < 0:
        raise ValueError(f'{key} must be non-negative, got {value}')
    return value


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


def _parse_bool(raw: str | None) -> bool:
    """Parse a boolean value from environment variable."""
    if raw is None:
        return False
    cleaned = raw.strip().lower()
    return cleaned in ('true', '1', 'yes', 'on')


def update_dotenv_file(updates: Mapping[str, str], path: Path = Path('.env')) -> None:
    """Update or append .env values while preserving unrelated lines."""
    if not updates:
        return

    lines: list[str]
    if path.exists():
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            lines = []
    else:
        lines = []

    seen: set[str] = set()
    updated_lines: list[str] = []
    for line in lines:
        key, prefix = _extract_env_key(line)
        if key and key in updates:
            updated_lines.append(f'{prefix}{key}={updates[key]}')
            seen.add(key)
        else:
            updated_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            updated_lines.append(f'{key}={value}')

    content = '\n'.join(updated_lines).rstrip('\n') + '\n'
    path.write_text(content, encoding='utf-8')


def _extract_env_key(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        return None, ''
    prefix = ''
    if stripped.startswith('export '):
        prefix = 'export '
        stripped = stripped[len('export ') :].lstrip()
    if '=' not in stripped:
        return None, prefix
    key = stripped.split('=', 1)[0].strip()
    if not key:
        return None, prefix
    return key, prefix


def _load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f'TIMEZONE {name!r} is not recognised by zoneinfo') from exc
    except Exception as exc:  # pragma: no cover - defensive catch
        raise ValueError(f'Unable to load timezone {name!r}: {exc}') from exc
