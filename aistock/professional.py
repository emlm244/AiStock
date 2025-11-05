"""
Professional Trading Safeguards Module.

Anti-mistake mechanisms used by professional traders:
- Overtrading prevention
- Chase detection (don't buy spikes)
- News event detection (unusual volatility)
- End-of-day protection
- Timeframe divergence warnings
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from .calendar import nyse_trading_hours
from .data import Bar
from .logging import configure_logger


class RiskLevel(str, Enum):
    """Risk level for trading decisions."""

    SAFE = 'safe'
    CAUTION = 'caution'
    HIGH_RISK = 'high_risk'
    BLOCKED = 'blocked'


@dataclass
class TradingSafeguardResult:
    """Result of professional trading safeguard checks."""

    allowed: bool
    risk_level: RiskLevel
    confidence_adjustment: float  # -1.0 to +1.0
    position_size_multiplier: float  # 0.0 to 1.0
    warnings: list[str]
    reason: str


class ProfessionalSafeguards:
    """
    Professional trading safeguards to prevent costly mistakes.

    Used by professional traders to avoid common pitfalls:
    - Overtrading (too many trades = high fees + emotional decisions)
    - Chasing (buying spikes = bad entries)
    - News events (high volatility = unpredictable)
    - End-of-day risks (market closing soon)
    - Timeframe divergence (conflicting signals)
    """

    def __init__(
        self,
        max_trades_per_hour: int = 20,
        max_trades_per_day: int = 100,
        chase_threshold_pct: float = 5.0,
        news_volume_multiplier: float = 5.0,
        end_of_day_minutes: int = 30,
    ):
        """
        Initialize professional safeguards.

        Args:
            max_trades_per_hour: Maximum trades per hour (overtrading limit)
            max_trades_per_day: Maximum trades per day
            chase_threshold_pct: Price spike percentage considered "chasing"
            news_volume_multiplier: Volume multiplier indicating news event
            end_of_day_minutes: Minutes before close to stop new positions
        """
        self.max_trades_per_hour = max_trades_per_hour
        self.max_trades_per_day = max_trades_per_day
        self.chase_threshold_pct = chase_threshold_pct
        self.news_volume_multiplier = news_volume_multiplier
        self.end_of_day_minutes = end_of_day_minutes

        self.logger = configure_logger('ProfessionalSafeguards', structured=True)

        # Trade tracking
        self._trade_times: deque[datetime] = deque(maxlen=1000)
        self._symbol_trade_times: dict[str, deque[datetime]] = defaultdict(lambda: deque(maxlen=100))

    def check_trading_allowed(
        self,
        symbol: str,
        bars: list[Bar],
        current_time: datetime | None = None,
        timeframe_divergence: bool = False,
    ) -> TradingSafeguardResult:
        """
        Run all professional safeguard checks.

        Args:
            symbol: Trading symbol
            bars: Recent bars for analysis
            current_time: Current timestamp (None = use now)
            timeframe_divergence: Whether timeframes disagree

        Returns:
            TradingSafeguardResult with allowed/blocked decision
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        warnings: list[str] = []
        confidence_adjustment = 0.0
        position_size_multiplier = 1.0
        risk_level = RiskLevel.SAFE

        # Check 1: Overtrading prevention
        overtrading_result = self._check_overtrading(current_time)
        if not overtrading_result['allowed']:
            return TradingSafeguardResult(
                allowed=False,
                risk_level=RiskLevel.BLOCKED,
                confidence_adjustment=-1.0,
                position_size_multiplier=0.0,
                warnings=[str(overtrading_result['reason'])],
                reason='overtrading_blocked',
            )
        if overtrading_result['warning']:
            warning_msg = overtrading_result['warning']
            if isinstance(warning_msg, str):
                warnings.append(warning_msg)
            confidence_adjustment -= 0.1
            risk_level = RiskLevel.CAUTION

        # Check 2: Chase detection (price spiking)
        if len(bars) >= 5:
            chase_result = self._check_price_spike(bars)
            if chase_result['is_spike']:
                warning_msg = chase_result['warning']
                if isinstance(warning_msg, str):
                    warnings.append(warning_msg)
                confidence_adjustment -= 0.2
                position_size_multiplier *= 0.5  # Half position size
                risk_level = RiskLevel.HIGH_RISK
                self.logger.warning(
                    'chase_detected',
                    extra={
                        'symbol': symbol,
                        'spike_pct': chase_result['spike_pct'],
                        'warning': chase_result['warning'],
                    },
                )

        # Check 3: News event detection (unusual volume/volatility)
        if len(bars) >= 20:
            news_result = self._check_news_event(bars)
            if news_result['likely_news']:
                warning_msg = news_result['warning']
                if isinstance(warning_msg, str):
                    warnings.append(warning_msg)
                confidence_adjustment -= 0.15
                position_size_multiplier *= 0.6
                risk_level = RiskLevel.HIGH_RISK
                self.logger.warning(
                    'news_event_detected',
                    extra={
                        'symbol': symbol,
                        'volume_ratio': news_result['volume_ratio'],
                        'warning': news_result['warning'],
                    },
                )

        # Check 4: End-of-day protection
        end_of_day_result = self._check_end_of_day(current_time)
        if end_of_day_result['block_new_positions']:
            return TradingSafeguardResult(
                allowed=False,
                risk_level=RiskLevel.BLOCKED,
                confidence_adjustment=-1.0,
                position_size_multiplier=0.0,
                warnings=[str(end_of_day_result['reason'])],
                reason='end_of_day_blocked',
            )
        if end_of_day_result['warning']:
            warning_msg2 = end_of_day_result['warning']
            if isinstance(warning_msg2, str):
                warnings.append(warning_msg2)
            confidence_adjustment -= 0.2
            risk_level = RiskLevel.CAUTION

        # Check 5: Timeframe divergence warning
        if timeframe_divergence:
            warnings.append('Timeframe divergence detected - conflicting signals!')
            confidence_adjustment -= 0.2
            position_size_multiplier *= 0.7
            risk_level = RiskLevel.HIGH_RISK

        # Determine if trade is allowed (blocked cases returned earlier)
        allowed = True

        return TradingSafeguardResult(
            allowed=allowed,
            risk_level=risk_level,
            confidence_adjustment=max(-1.0, confidence_adjustment),
            position_size_multiplier=max(0.0, min(1.0, position_size_multiplier)),
            warnings=warnings,
            reason='safeguards_passed' if allowed else 'safeguards_blocked',
        )

    def _check_overtrading(self, current_time: datetime) -> dict[str, object]:
        """Check if trader is overtrading."""
        # Ensure current_time is timezone-aware
        if current_time.tzinfo is None:
            from datetime import timezone as tz

            current_time = current_time.replace(tzinfo=tz.utc)

        # Remove old trade times (older than 1 day)
        cutoff_day = current_time - timedelta(days=1)
        cutoff_hour = current_time - timedelta(hours=1)

        # Clean up old trades
        while self._trade_times and self._trade_times[0] < cutoff_day:
            self._trade_times.popleft()

        # Count trades in last hour
        trades_last_hour = sum(1 for t in self._trade_times if t >= cutoff_hour)

        # Count trades today
        trades_today = len(self._trade_times)

        # Block if exceeded limits
        if trades_last_hour >= self.max_trades_per_hour:
            return {
                'allowed': False,
                'warning': None,
                'reason': f'Overtrading: {trades_last_hour} trades in last hour (max {self.max_trades_per_hour})',
            }

        if trades_today >= self.max_trades_per_day:
            return {
                'allowed': False,
                'warning': None,
                'reason': f'Daily trade limit reached: {trades_today}/{self.max_trades_per_day}',
            }

        # Warn if approaching limits
        warning = None
        if trades_last_hour >= self.max_trades_per_hour * 0.8:
            warning = f'Approaching overtrading limit: {trades_last_hour}/{self.max_trades_per_hour} trades/hour'
        elif trades_today >= self.max_trades_per_day * 0.9:
            warning = f'Approaching daily limit: {trades_today}/{self.max_trades_per_day} trades'

        return {'allowed': True, 'warning': warning, 'reason': None}

    def _check_price_spike(self, bars: list[Bar]) -> dict[str, object]:
        """Check if price is spiking (chasing detection)."""
        if len(bars) < 5:
            return {'is_spike': False, 'warning': None, 'spike_pct': 0.0}

        # Compare recent bar to 5-bar average
        recent_bar = bars[-1]
        prev_bars = bars[-6:-1]

        avg_price = sum(float(bar.close) for bar in prev_bars) / len(prev_bars)
        current_price = float(recent_bar.close)

        if avg_price == 0:
            return {'is_spike': False, 'warning': None, 'spike_pct': 0.0}

        spike_pct = ((current_price - avg_price) / avg_price) * 100

        is_spike = abs(spike_pct) > self.chase_threshold_pct

        warning = None
        if is_spike:
            direction = 'up' if spike_pct > 0 else 'down'
            warning = f"Price spiking {direction} {abs(spike_pct):.1f}% - don't chase! Wait for pullback."

        return {'is_spike': is_spike, 'warning': warning, 'spike_pct': spike_pct}

    def _check_news_event(self, bars: list[Bar]) -> dict[str, object]:
        """Check for unusual volume/volatility (likely news event)."""
        if len(bars) < 20:
            return {'likely_news': False, 'warning': None, 'volume_ratio': 1.0}

        # Recent volume vs average
        recent_volume = bars[-1].volume
        avg_volume = sum(bar.volume for bar in bars[-20:-1]) / 19 if len(bars) > 1 else 1

        if avg_volume == 0:
            return {'likely_news': False, 'warning': None, 'volume_ratio': 1.0}

        volume_ratio = recent_volume / avg_volume

        # Recent volatility
        recent_range = float(bars[-1].high) - float(bars[-1].low)
        avg_range = sum(float(bar.high) - float(bar.low) for bar in bars[-10:-1]) / 9 if len(bars) > 1 else 1
        volatility_ratio = recent_range / avg_range if avg_range > 0 else 1.0

        # News event if volume is extreme AND price is jumping
        likely_news = volume_ratio > self.news_volume_multiplier and volatility_ratio > 2.0

        warning = None
        if likely_news:
            warning = f'Unusual activity detected (volume {volume_ratio:.1f}x average) - possible news event!'

        return {'likely_news': likely_news, 'warning': warning, 'volume_ratio': volume_ratio}

    def _check_end_of_day(self, current_time: datetime) -> dict[str, object]:
        """Check if close to market close (avoid new positions)."""
        # Get market close time for today
        try:
            _open, close = nyse_trading_hours(current_time)
        except Exception:
            # If error getting hours, assume not end of day
            return {'block_new_positions': False, 'warning': None, 'reason': None}

        # Convert close time to datetime
        close_datetime = current_time.replace(hour=close.hour, minute=close.minute, second=0, microsecond=0)

        # Calculate minutes until close
        time_until_close = close_datetime - current_time
        minutes_until_close = time_until_close.total_seconds() / 60

        # Block if within end_of_day_minutes of close
        if minutes_until_close <= self.end_of_day_minutes and minutes_until_close > 0:
            if minutes_until_close <= 15:
                # Hard block within 15 minutes
                return {
                    'block_new_positions': True,
                    'warning': None,
                    'reason': f'Market closes in {int(minutes_until_close)} minutes - no new positions',
                }
            else:
                # Soft warning
                return {
                    'block_new_positions': False,
                    'warning': f'Market closes in {int(minutes_until_close)} minutes - consider avoiding new positions',
                    'reason': None,
                }

        return {'block_new_positions': False, 'warning': None, 'reason': None}

    def record_trade(self, timestamp: datetime, symbol: str) -> None:
        """
        Record a trade for overtrading detection.

        Args:
            timestamp: Trade timestamp (must be timezone-aware)
            symbol: Trading symbol

        Raises:
            TypeError: If timestamp is naive (tzinfo is None)
        """
        if timestamp.tzinfo is None:
            raise TypeError(
                'ProfessionalSafeguards.record_trade received naive datetime. '
                'All callers must use datetime.now(timezone.utc) or ensure timezone awareness. '
                'This prevents comparison errors with timezone-aware timestamps.'
            )

        self._trade_times.append(timestamp)
        self._symbol_trade_times[symbol].append(timestamp)

        self.logger.debug(
            'trade_recorded',
            extra={
                'symbol': symbol,
                'timestamp': timestamp.isoformat(),
                'total_trades': len(self._trade_times),
            },
        )

    def get_trade_statistics(self, hours: int = 24) -> dict[str, object]:
        """
        Get trading statistics for monitoring.

        Args:
            hours: Hours to look back

        Returns:
            Dictionary with trade statistics
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent_trades = [t for t in self._trade_times if t >= cutoff]

        return {
            'total_trades': len(recent_trades),
            'trades_last_hour': sum(1 for t in recent_trades if t >= datetime.now(timezone.utc) - timedelta(hours=1)),
            'trades_today': sum(1 for t in recent_trades if t.date() == datetime.now(timezone.utc).date()),
            'max_trades_per_hour': self.max_trades_per_hour,
            'max_trades_per_day': self.max_trades_per_day,
            'utilization_pct': (len(recent_trades) / self.max_trades_per_day) * 100,
        }


__all__ = [
    'ProfessionalSafeguards',
    'TradingSafeguardResult',
    'RiskLevel',
]
