# utils/data_quality.py

"""
Data Quality Validation and Anomaly Detection

Validates market data integrity and detects anomalies that could
indicate data feed issues or require intervention.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz


class DataQualityIssue:
    """Represents a data quality issue"""

    SEVERITY_INFO = 'INFO'
    SEVERITY_WARNING = 'WARNING'
    SEVERITY_CRITICAL = 'CRITICAL'

    def __init__(self, symbol: str, issue_type: str, severity: str, message: str, suggestion: str = ''):
        self.symbol = symbol
        self.issue_type = issue_type
        self.severity = severity
        self.message = message
        self.suggestion = suggestion
        self.timestamp = datetime.now(pytz.utc)

    def __repr__(self):
        return f'[{self.severity}] {self.symbol}: {self.issue_type} - {self.message}'


class DataQualityValidator:
    """Validates market data quality and detects anomalies"""

    def __init__(self, logger=None):
        self.logger = logger
        self.issues: list[DataQualityIssue] = []

    def validate_bar_data(self, symbol: str, df: pd.DataFrame, settings=None) -> list[DataQualityIssue]:
        """
        Comprehensive validation of bar/candlestick data

        Args:
            symbol: Trading symbol
            df: DataFrame with OHLCV columns and datetime index
            settings: Settings object for thresholds

        Returns:
            List of data quality issues found
        """
        self.issues = []

        if df is None or df.empty:
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'EMPTY_DATA',
                    DataQualityIssue.SEVERITY_CRITICAL,
                    'DataFrame is empty or None',
                    'Check data feed connection and historical data request',
                )
            )
            return self.issues

        # Run all validation checks
        self._check_required_columns(symbol, df)
        self._check_data_types(symbol, df)
        self._check_missing_values(symbol, df)
        self._check_ohlc_consistency(symbol, df)
        self._check_negative_values(symbol, df)
        self._check_zero_values(symbol, df)
        self._check_price_spikes(symbol, df)
        self._check_volume_anomalies(symbol, df)
        self._check_duplicate_timestamps(symbol, df)
        self._check_time_gaps(symbol, df, settings)
        self._check_stale_data(symbol, df, settings)

        return self.issues

    def _check_required_columns(self, symbol: str, df: pd.DataFrame):
        """Check if required columns are present"""
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'MISSING_COLUMNS',
                    DataQualityIssue.SEVERITY_CRITICAL,
                    f'Missing required columns: {", ".join(missing_columns)}',
                    'Ensure data source provides OHLCV format',
                )
            )

    def _check_data_types(self, symbol: str, df: pd.DataFrame):
        """Check if columns have appropriate data types"""
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']

        for col in numeric_columns:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                self.issues.append(
                    DataQualityIssue(
                        symbol,
                        'INVALID_DATA_TYPE',
                        DataQualityIssue.SEVERITY_CRITICAL,
                        f"Column '{col}' is not numeric (type: {df[col].dtype})",
                        'Convert data to numeric type or check data parsing',
                    )
                )

        # Check index is datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'INVALID_INDEX',
                    DataQualityIssue.SEVERITY_CRITICAL,
                    'Index is not DatetimeIndex',
                    'Ensure timestamp column is set as index with proper datetime format',
                )
            )

    def _check_missing_values(self, symbol: str, df: pd.DataFrame):
        """Check for missing/NaN values"""
        critical_columns = ['open', 'high', 'low', 'close']

        for col in critical_columns:
            if col in df.columns:
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    nan_pct = (nan_count / len(df)) * 100
                    severity = DataQualityIssue.SEVERITY_CRITICAL if nan_pct > 5 else DataQualityIssue.SEVERITY_WARNING

                    self.issues.append(
                        DataQualityIssue(
                            symbol,
                            'MISSING_VALUES',
                            severity,
                            f"Column '{col}' has {nan_count} NaN values ({nan_pct:.1f}%)",
                            'Fill or remove NaN values. Consider forward-fill for OHLC data.',
                        )
                    )

    def _check_ohlc_consistency(self, symbol: str, df: pd.DataFrame):
        """Check if OHLC relationships are valid"""
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            return

        # High should be >= all other prices
        high_violations = ((df['high'] < df['open']) | (df['high'] < df['low']) | (df['high'] < df['close'])).sum()

        if high_violations > 0:
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'OHLC_INCONSISTENCY',
                    DataQualityIssue.SEVERITY_CRITICAL,
                    f'{high_violations} bars have HIGH below other prices',
                    'Check data source integrity. This indicates corrupted data.',
                )
            )

        # Low should be <= all other prices
        low_violations = ((df['low'] > df['open']) | (df['low'] > df['high']) | (df['low'] > df['close'])).sum()

        if low_violations > 0:
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'OHLC_INCONSISTENCY',
                    DataQualityIssue.SEVERITY_CRITICAL,
                    f'{low_violations} bars have LOW above other prices',
                    'Check data source integrity. This indicates corrupted data.',
                )
            )

    def _check_negative_values(self, symbol: str, df: pd.DataFrame):
        """Check for negative prices or volumes"""
        price_columns = ['open', 'high', 'low', 'close']

        for col in price_columns:
            if col in df.columns:
                negative_count = (df[col] < 0).sum()
                if negative_count > 0:
                    self.issues.append(
                        DataQualityIssue(
                            symbol,
                            'NEGATIVE_PRICE',
                            DataQualityIssue.SEVERITY_CRITICAL,
                            f"Column '{col}' has {negative_count} negative values",
                            'Prices cannot be negative. Check data source or parsing logic.',
                        )
                    )

        if 'volume' in df.columns:
            negative_volume = (df['volume'] < 0).sum()
            if negative_volume > 0:
                self.issues.append(
                    DataQualityIssue(
                        symbol,
                        'NEGATIVE_VOLUME',
                        DataQualityIssue.SEVERITY_WARNING,
                        f'Volume has {negative_volume} negative values',
                        'Volume should be non-negative. Set negative values to 0.',
                    )
                )

    def _check_zero_values(self, symbol: str, df: pd.DataFrame):
        """Check for suspicious zero values"""
        price_columns = ['open', 'high', 'low', 'close']

        for col in price_columns:
            if col in df.columns:
                zero_count = (df[col] == 0).sum()
                if zero_count > 0:
                    zero_pct = (zero_count / len(df)) * 100
                    severity = DataQualityIssue.SEVERITY_CRITICAL if zero_pct > 1 else DataQualityIssue.SEVERITY_WARNING

                    self.issues.append(
                        DataQualityIssue(
                            symbol,
                            'ZERO_PRICE',
                            severity,
                            f"Column '{col}' has {zero_count} zero values ({zero_pct:.1f}%)",
                            'Zero prices indicate missing or invalid data. Remove or interpolate.',
                        )
                    )

    def _check_price_spikes(self, symbol: str, df: pd.DataFrame, spike_threshold: float = 0.20):
        """Detect abnormal price spikes that may indicate bad data"""
        if 'close' not in df.columns or len(df) < 2:
            return

        # Calculate percentage change
        pct_change = df['close'].pct_change().abs()

        # Detect spikes greater than threshold (default 20%)
        spikes = pct_change > spike_threshold
        spike_count = spikes.sum()

        if spike_count > 0:
            max_spike = pct_change.max()
            severity = DataQualityIssue.SEVERITY_WARNING if spike_count < 5 else DataQualityIssue.SEVERITY_CRITICAL

            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'PRICE_SPIKE',
                    severity,
                    f'{spike_count} bars with price changes >{spike_threshold:.0%} (max: {max_spike:.1%})',
                    'Large price spikes may indicate bad ticks or flash crashes. Review manually.',
                )
            )

    def _check_volume_anomalies(self, symbol: str, df: pd.DataFrame):
        """Detect volume anomalies"""
        if 'volume' not in df.columns or len(df) < 10:
            return

        # Skip if all volumes are zero (some instruments might not report volume)
        if (df['volume'] == 0).all():
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'NO_VOLUME_DATA',
                    DataQualityIssue.SEVERITY_INFO,
                    'All volume values are zero',
                    'This symbol may not provide volume data. This is normal for some forex pairs.',
                )
            )
            return

        # Calculate volume statistics
        mean_vol = df['volume'].mean()
        std_vol = df['volume'].std()

        if mean_vol > 0 and std_vol > 0:
            # Detect extreme volume spikes (>5 standard deviations)
            z_scores = np.abs((df['volume'] - mean_vol) / std_vol)
            extreme_count = (z_scores > 5).sum()

            if extreme_count > 0:
                max_z = z_scores.max()
                self.issues.append(
                    DataQualityIssue(
                        symbol,
                        'VOLUME_ANOMALY',
                        DataQualityIssue.SEVERITY_INFO,
                        f'{extreme_count} bars with extreme volume (max Z-score: {max_z:.1f})',
                        'Extreme volume can indicate news events or data errors. Review manually.',
                    )
                )

    def _check_duplicate_timestamps(self, symbol: str, df: pd.DataFrame):
        """Check for duplicate timestamp entries"""
        if not isinstance(df.index, pd.DatetimeIndex):
            return

        duplicates = df.index.duplicated().sum()

        if duplicates > 0:
            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'DUPLICATE_TIMESTAMPS',
                    DataQualityIssue.SEVERITY_WARNING,
                    f'{duplicates} duplicate timestamps found',
                    "Remove duplicates using drop_duplicates() or keep='last'",
                )
            )

    def _check_time_gaps(self, symbol: str, df: pd.DataFrame, settings=None):
        """Check for unusual gaps in timestamp sequence"""
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
            return

        # Calculate time differences
        time_diffs = df.index.to_series().diff()

        # Expected interval (mode of time differences)
        expected_interval = time_diffs.mode()[0] if not time_diffs.mode().empty else pd.Timedelta(minutes=1)

        # Allow gaps up to 3x the expected interval (accounts for market closes, etc.)
        max_allowed_gap = expected_interval * 3

        # Find large gaps
        large_gaps = time_diffs > max_allowed_gap
        gap_count = large_gaps.sum()

        if gap_count > 0:
            max_gap = time_diffs.max()
            severity = DataQualityIssue.SEVERITY_INFO if gap_count < 3 else DataQualityIssue.SEVERITY_WARNING

            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'TIME_GAPS',
                    severity,
                    f'{gap_count} large time gaps found (max: {max_gap}, expected: {expected_interval})',
                    'Time gaps may indicate market closures, data feed interruptions, or missing data.',
                )
            )

    def _check_stale_data(self, symbol: str, df: pd.DataFrame, settings=None):
        """Check if latest data is too old"""
        if not isinstance(df.index, pd.DatetimeIndex) or df.empty:
            return

        latest_timestamp = df.index[-1]

        # Ensure timezone awareness
        if latest_timestamp.tzinfo is None:
            latest_timestamp = pytz.utc.localize(latest_timestamp)
        else:
            latest_timestamp = latest_timestamp.astimezone(pytz.utc)

        now_utc = datetime.now(pytz.utc)
        age = now_utc - latest_timestamp

        # Define staleness thresholds
        max_age_seconds = getattr(settings, 'MAX_DATA_STALENESS_SECONDS', 60) if settings else 60
        max_age_threshold = timedelta(seconds=max_age_seconds)

        if age > max_age_threshold:
            severity = (
                DataQualityIssue.SEVERITY_CRITICAL if age.total_seconds() > 300 else DataQualityIssue.SEVERITY_WARNING
            )

            self.issues.append(
                DataQualityIssue(
                    symbol,
                    'STALE_DATA',
                    severity,
                    f'Latest data is {age.total_seconds():.0f} seconds old (threshold: {max_age_seconds}s)',
                    'Check if market is open and data feed is active. May need to restart subscription.',
                )
            )

    def get_critical_issues(self) -> list[DataQualityIssue]:
        """Get only critical issues"""
        return [issue for issue in self.issues if issue.severity == DataQualityIssue.SEVERITY_CRITICAL]

    def get_warnings(self) -> list[DataQualityIssue]:
        """Get only warnings"""
        return [issue for issue in self.issues if issue.severity == DataQualityIssue.SEVERITY_WARNING]

    def has_critical_issues(self) -> bool:
        """Check if any critical issues were found"""
        return len(self.get_critical_issues()) > 0

    def print_report(self, symbol: str):
        """Print a formatted data quality report"""
        if not self.issues:
            print(f'\n✓ [{symbol}] Data quality validation passed - no issues found.\n')
            return

        print(f'\n{"=" * 70}')
        print(f' DATA QUALITY REPORT: {symbol}')
        print(f'{"=" * 70}\n')

        # Group by severity
        critical = self.get_critical_issues()
        warnings = self.get_warnings()
        info = [i for i in self.issues if i.severity == DataQualityIssue.SEVERITY_INFO]

        if critical:
            print(f'🔴 CRITICAL ISSUES ({len(critical)}):')
            for issue in critical:
                print(f'   ✗ {issue.issue_type}: {issue.message}')
                if issue.suggestion:
                    print(f'     💡 {issue.suggestion}')
            print()

        if warnings:
            print(f'🟡 WARNINGS ({len(warnings)}):')
            for issue in warnings:
                print(f'   ⚠ {issue.issue_type}: {issue.message}')
                if issue.suggestion:
                    print(f'     💡 {issue.suggestion}')
            print()

        if info:
            print(f'ℹ️  INFORMATION ({len(info)}):')
            for issue in info:
                print(f'   ℹ {issue.issue_type}: {issue.message}')
            print()

        print(f'{"=" * 70}\n')


def validate_market_data(
    symbol: str, df: pd.DataFrame, settings=None, logger=None
) -> tuple[bool, list[DataQualityIssue]]:
    """
    Convenience function to validate market data

    Returns:
        (is_safe_to_trade, list_of_issues)
    """
    validator = DataQualityValidator(logger)
    issues = validator.validate_bar_data(symbol, df, settings)

    # Safe to trade if no critical issues
    is_safe = not validator.has_critical_issues()

    return is_safe, issues
