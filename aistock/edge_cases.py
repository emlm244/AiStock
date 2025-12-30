"""
Edge Case Handler - Protects FSD bot from unforeseen scenarios.

Handles:
- Missing or incomplete timeframe data
- Extreme market conditions
- Data quality issues
- Conflicting signals across timeframes
- Low liquidity situations
- Circuit breakers and halts
- Network/connection issues
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .data import Bar
from .log_config import configure_logger


@dataclass
class EdgeCaseResult:
    """Result of edge case detection."""

    is_edge_case: bool
    severity: str  # 'low', 'medium', 'high', 'critical'
    action: str  # 'allow', 'warn', 'reduce_size', 'block'
    reason: str
    position_size_multiplier: float  # 0.0 to 1.0
    confidence_adjustment: float  # -1.0 to +1.0


class EdgeCaseHandler:
    """
    Comprehensive edge case detection and handling.

    Philosophy: When in doubt, be conservative. Better to miss a trade
    than to lose money in an unforeseen scenario.
    """

    def __init__(self):
        self.logger = configure_logger('EdgeCaseHandler', structured=True)

    def check_edge_cases(
        self,
        symbol: str,
        bars: list[Bar],
        timeframe_data: dict[str, list[Bar]] | None = None,
        current_time: datetime | None = None,
    ) -> EdgeCaseResult:
        """
        Run comprehensive edge case checks.

        Args:
            symbol: Trading symbol
            bars: Recent bars for primary timeframe
            timeframe_data: Optional dict of {timeframe: bars} for multi-timeframe checks
            current_time: Current timestamp

        Returns:
            EdgeCaseResult with recommended action
        """
        # Check 1: Insufficient data (critical)
        if len(bars) < 3:
            return EdgeCaseResult(
                is_edge_case=True,
                severity='critical',
                action='block',
                reason='Insufficient bars (<3) - cannot analyze safely',
                position_size_multiplier=0.0,
                confidence_adjustment=-1.0,
            )

        # Check 2: Missing timeframe data (if multi-timeframe enabled)
        if timeframe_data:
            missing_tf = self._check_missing_timeframes(timeframe_data)
            if missing_tf['has_missing']:
                return EdgeCaseResult(
                    is_edge_case=True,
                    severity='high',
                    action='reduce_size',
                    reason=f'Missing timeframe data: {missing_tf["missing"]}',
                    position_size_multiplier=0.5,  # Half size
                    confidence_adjustment=-0.2,
                )

        # Check 3: Extreme price volatility (flash crash or circuit breaker)
        extreme_vol = self._check_extreme_volatility(bars)
        if extreme_vol['is_extreme']:
            self.logger.warning(
                'extreme_volatility_detected',
                extra={'symbol': symbol, 'volatility_pct': extreme_vol['volatility_pct']},
            )
            return EdgeCaseResult(
                is_edge_case=True,
                severity='high',
                action='block',
                reason=f'Extreme volatility ({extreme_vol["volatility_pct"]:.1f}%) - possible circuit breaker or flash crash',
                position_size_multiplier=0.0,
                confidence_adjustment=-1.0,
            )

        # Check 4: Stale data (no recent bars)
        if current_time:
            stale_data = self._check_stale_data(bars, current_time)
            if stale_data['is_stale']:
                return EdgeCaseResult(
                    is_edge_case=True,
                    severity='medium',
                    action='block',
                    reason=f'Stale data - last bar is {stale_data["age_minutes"]:.1f} minutes old',
                    position_size_multiplier=0.0,
                    confidence_adjustment=-1.0,
                )

        # Check 5: Zero or negative prices (data corruption)
        bad_prices = self._check_price_validity(bars)
        if bad_prices['has_invalid']:
            return EdgeCaseResult(
                is_edge_case=True,
                severity='critical',
                action='block',
                reason='Invalid prices detected - possible data corruption',
                position_size_multiplier=0.0,
                confidence_adjustment=-1.0,
            )

        # Check 6: Suspicious low volume (illiquid / after-hours)
        low_volume = self._check_low_volume(bars)
        if low_volume['is_suspicious']:
            return EdgeCaseResult(
                is_edge_case=True,
                severity='medium',
                action='reduce_size',
                reason=f'Suspiciously low volume ({low_volume["avg_volume"]:.0f}) - illiquid or after-hours',
                position_size_multiplier=0.3,  # Reduce to 30% size
                confidence_adjustment=-0.3,
            )

        # Check 7: Timeframe synchronization issues
        if timeframe_data and len(timeframe_data) > 1:
            sync_issues = self._check_timeframe_sync(timeframe_data)
            if sync_issues['has_issues']:
                return EdgeCaseResult(
                    is_edge_case=True,
                    severity='low',
                    action='warn',
                    reason=f'Timeframe synchronization issues - {sync_issues["issue"]}',
                    position_size_multiplier=0.8,
                    confidence_adjustment=-0.1,
                )

        # All checks passed
        return EdgeCaseResult(
            is_edge_case=False,
            severity='low',
            action='allow',
            reason='All edge case checks passed',
            position_size_multiplier=1.0,
            confidence_adjustment=0.0,
        )

    def _check_missing_timeframes(self, timeframe_data: dict[str, list[Bar]]) -> dict[str, Any]:
        """Check if any timeframes are missing data."""
        missing: list[str] = []
        for tf, bars in timeframe_data.items():
            if not bars or len(bars) < 5:  # Need minimum 5 bars
                missing.append(tf)

        return {
            'has_missing': len(missing) > 0,
            'missing': missing,
            'count': len(missing),
        }

    def _check_extreme_volatility(self, bars: list[Bar]) -> dict[str, Any]:
        """Check for extreme volatility (flash crash, circuit breaker)."""
        if len(bars) < 2:
            return {'is_extreme': False, 'volatility_pct': 0.0}

        # Check last bar for extreme range
        last_bar = bars[-1]
        bar_range = float(last_bar.high) - float(last_bar.low)
        bar_midpoint = (float(last_bar.high) + float(last_bar.low)) / 2

        if bar_midpoint == 0:
            return {'is_extreme': False, 'volatility_pct': 0.0}

        volatility_pct = (bar_range / bar_midpoint) * 100

        # Extreme if >15% range in a single bar
        is_extreme = volatility_pct > 15.0

        return {'is_extreme': is_extreme, 'volatility_pct': volatility_pct}

    def _check_stale_data(self, bars: list[Bar], current_time: datetime) -> dict[str, Any]:
        """Check if data is stale (no recent updates)."""
        if not bars:
            return {'is_stale': True, 'age_minutes': float('inf')}

        last_bar = bars[-1]

        # Fix timezone mismatch: ensure both have same timezone awareness
        # CRITICAL: If current_time is naive, this is a bug upstream.
        # All callers MUST pass timezone-aware datetimes.
        if current_time.tzinfo is None:
            raise TypeError(
                'EdgeCaseHandler._check_stale_data received naive datetime. '
                'All callers must use datetime.now(timezone.utc) or ensure timezone awareness. '
                'This prevents silent 5-hour errors on non-UTC machines.'
            )

        # If bar is naive, make bar tz-aware (assume UTC)
        if last_bar.timestamp.tzinfo is None:
            from datetime import timezone

            last_bar_timestamp = last_bar.timestamp.replace(tzinfo=timezone.utc)
        else:
            last_bar_timestamp = last_bar.timestamp

        age = current_time - last_bar_timestamp
        age_minutes = age.total_seconds() / 60

        # Stale if last bar is >10 minutes old (for minute-level trading)
        is_stale = age_minutes > 10

        return {'is_stale': is_stale, 'age_minutes': age_minutes}

    def _check_price_validity(self, bars: list[Bar]) -> dict[str, Any]:
        """Check for invalid prices (corruption, bad data)."""
        has_invalid = False

        for bar in bars[-10:]:  # Check last 10 bars
            if float(bar.close) <= 0 or float(bar.open) <= 0:
                has_invalid = True
                break
            if float(bar.high) <= 0 or float(bar.low) <= 0:
                has_invalid = True
                break
            if float(bar.high) < float(bar.low):
                has_invalid = True
                break

        return {'has_invalid': has_invalid}

    def _check_low_volume(self, bars: list[Bar]) -> dict[str, Any]:
        """Check for suspiciously low volume."""
        if len(bars) < 10:
            return {'is_suspicious': False, 'avg_volume': 0}

        # Calculate average volume
        volumes = [bar.volume for bar in bars[-10:]]
        avg_volume = sum(volumes) / len(volumes)

        # Suspicious if average volume < 100 (likely after-hours or illiquid)
        is_suspicious = avg_volume < 100

        return {'is_suspicious': is_suspicious, 'avg_volume': avg_volume}

    def _check_timeframe_sync(self, timeframe_data: dict[str, list[Bar]]) -> dict[str, Any]:
        """Check for timeframe synchronization issues."""
        if len(timeframe_data) < 2:
            return {'has_issues': False, 'issue': None}

        # Check if all timeframes have recent data
        timestamps: dict[str, datetime] = {}
        for tf, bars in timeframe_data.items():
            if bars:
                bar_ts = bars[-1].timestamp
                # Defensive: Normalize naive timestamps to UTC (assume UTC source)
                if bar_ts.tzinfo is None:
                    from datetime import timezone

                    bar_ts = bar_ts.replace(tzinfo=timezone.utc)
                timestamps[tf] = bar_ts

        if not timestamps:
            return {'has_issues': True, 'issue': 'No timestamp data available'}

        # Check if timestamps are within reasonable range
        max_ts = max(timestamps.values())
        min_ts = min(timestamps.values())
        time_spread = (max_ts - min_ts).total_seconds() / 60

        # Issue if timeframes are >30 minutes out of sync
        has_issues = time_spread > 30

        issue = None
        if has_issues:
            issue = f'Timeframes out of sync by {time_spread:.1f} minutes'

        return {'has_issues': has_issues, 'issue': issue}


__all__ = [
    'EdgeCaseHandler',
    'EdgeCaseResult',
]
