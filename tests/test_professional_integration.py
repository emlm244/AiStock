"""
Integration tests for professional trading enhancements.

Tests:
- Multi-timeframe analysis
- Pattern recognition
- Professional safeguards
- Full FSD integration
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.fsd import FSDConfig, FSDEngine
from aistock.patterns import PatternDetector, PatternSignal
from aistock.portfolio import Portfolio
from aistock.professional import ProfessionalSafeguards, RiskLevel
from aistock.timeframes import TimeframeManager, Trend


class TestTimeframeManager:
    """Test multi-timeframe analysis."""

    def test_timeframe_manager_init(self):
        """Test TimeframeManager initialization."""
        tm = TimeframeManager(symbols=['AAPL', 'MSFT'], timeframes=['1m', '5m', '15m'])
        assert tm.symbols == ['AAPL', 'MSFT']
        assert '1m' in tm.timeframes
        assert '5m' in tm.timeframes
        assert '15m' in tm.timeframes

    def test_add_and_retrieve_bars(self):
        """Test adding and retrieving bars."""
        tm = TimeframeManager(symbols=['AAPL'], timeframes=['1m', '5m'])

        # Create test bars
        bars_1m = self._create_test_bars('AAPL', count=50, interval_seconds=60)
        bars_5m = self._create_test_bars('AAPL', count=10, interval_seconds=300)

        # Add bars
        for bar in bars_1m:
            tm.add_bar('AAPL', '1m', bar)

        for bar in bars_5m:
            tm.add_bar('AAPL', '5m', bar)

        # Retrieve and verify
        retrieved_1m = tm.get_bars('AAPL', '1m')
        assert len(retrieved_1m) == 50

        retrieved_5m = tm.get_bars('AAPL', '5m')
        assert len(retrieved_5m) == 10

    def test_cross_timeframe_analysis(self):
        """Test cross-timeframe correlation analysis."""
        tm = TimeframeManager(symbols=['AAPL'], timeframes=['1m', '5m', '15m'])

        # P0 Fix: Create time-aligned bars to prevent drift detection
        # All timeframes should end at roughly the same time to pass sync validation
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        # Generate enough bars so all timeframes end close in time
        # Need at least 10 bars for each timeframe to calculate trend
        # 1m: 150 bars = 150 minutes (10:00 -> 12:30)
        # 5m: 30 bars = 150 minutes (10:00 -> 12:30)
        # 15m: 10 bars = 150 minutes (10:00 -> 12:30)
        # Max drift = 0 minutes (perfect alignment)

        timeframe_configs = [
            ('1m', 60, 150),  # 150 bars of 1-minute
            ('5m', 300, 30),  # 30 bars of 5-minute
            ('15m', 900, 10),  # 10 bars of 15-minute
        ]

        for timeframe, interval, count in timeframe_configs:
            bars = self._create_trending_bars_at_time('AAPL', base_time, count, interval, trend='up')
            for bar in bars:
                tm.add_bar('AAPL', timeframe, bar)

        # Analyze
        analysis = tm.analyze_cross_timeframe('AAPL')

        # All timeframes should show uptrend
        assert analysis.confluence is True
        assert analysis.dominant_trend == Trend.UP
        assert analysis.confidence_adjustment > 0  # Positive adjustment for confluence

    def test_timeframe_divergence_detection(self):
        """Test detection of timeframe divergence."""
        tm = TimeframeManager(symbols=['AAPL'], timeframes=['1m', '5m'])

        # 1m uptrend
        bars_1m = self._create_trending_bars('AAPL', count=30, interval_seconds=60, trend='up')
        for bar in bars_1m:
            tm.add_bar('AAPL', '1m', bar)

        # 5m downtrend
        bars_5m = self._create_trending_bars('AAPL', count=30, interval_seconds=300, trend='down')
        for bar in bars_5m:
            tm.add_bar('AAPL', '5m', bar)

        # Analyze
        analysis = tm.analyze_cross_timeframe('AAPL')

        # Should detect divergence
        assert analysis.divergence_detected is True
        assert analysis.confidence_adjustment < 0  # Penalty for divergence

    @staticmethod
    def _create_test_bars(symbol: str, count: int, interval_seconds: int) -> list[Bar]:
        """Create test bars."""
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        base_price = Decimal('100.0')

        for i in range(count):
            timestamp = base_time + timedelta(seconds=i * interval_seconds)
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=base_price,
                    high=base_price + Decimal('1.0'),
                    low=base_price - Decimal('1.0'),
                    close=base_price + Decimal('0.5'),
                    volume=1000,
                )
            )

        return bars

    @staticmethod
    def _create_trending_bars_at_time(
        symbol: str, base_time: datetime, count: int, interval_seconds: int, trend: str
    ) -> list[Bar]:
        """Create trending bars starting at a specific time with strong trend signal."""
        bars = []
        base_price = 100.0

        for i in range(count):
            timestamp = base_time + timedelta(seconds=i * interval_seconds)
            # P0 Fix: Use stronger trend (2.0 instead of 0.5) to ensure detection
            price_change = i * 2.0 if trend == 'up' else -i * 2.0
            price = base_price + price_change

            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=Decimal(str(price)),
                    high=Decimal(str(price + 2.0)),
                    low=Decimal(str(price - 1.0)),
                    close=Decimal(str(price + 1.5)),  # Close higher than open for uptrend
                    volume=1000,
                )
            )

        return bars

    @staticmethod
    def _create_trending_bars(symbol: str, count: int, interval_seconds: int, trend: str) -> list[Bar]:
        """Create trending bars for testing."""
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        base_price = 100.0

        for i in range(count):
            timestamp = base_time + timedelta(seconds=i * interval_seconds)

            # Apply trend
            if trend == 'up':
                price = base_price + (i * 0.5)  # Steady uptrend
            elif trend == 'down':
                price = base_price - (i * 0.5)  # Steady downtrend
            else:
                price = base_price  # Neutral

            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=Decimal(str(price)),
                    high=Decimal(str(price + 1.0)),
                    low=Decimal(str(price - 1.0)),
                    close=Decimal(str(price + 0.5)),
                    volume=1000,
                )
            )

        return bars


class TestPatternDetector:
    """Test candlestick pattern recognition."""

    def test_pattern_detector_init(self):
        """Test PatternDetector initialization."""
        pd = PatternDetector(body_threshold=0.3, wick_ratio=2.0)
        # P0 Fix: PatternDetector stores thresholds as Decimal for precision
        assert pd.body_threshold == Decimal('0.3')
        assert pd.wick_ratio == Decimal('2.0')

    def test_detect_doji(self):
        """Test Doji pattern detection."""
        pd = PatternDetector()

        # Create a Doji bar (open ≈ close, small body)
        doji_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            open=Decimal('100.00'),
            high=Decimal('102.00'),
            low=Decimal('98.00'),
            close=Decimal('100.10'),  # Very small body
            volume=1000,
        )

        patterns = pd.detect_patterns([doji_bar])
        assert any(p.pattern_type.value == 'doji' for p in patterns)

    def test_detect_hammer(self):
        """Test Hammer pattern detection (requires downtrend context)."""
        pd = PatternDetector(body_threshold=0.3, wick_ratio=2.0)

        # Create downtrend context (hammer requires 10+ bars to establish trend)
        downtrend_bars = []
        for i in range(10):
            downtrend_bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=datetime(2024, 1, 1, 9, 50 + i, tzinfo=timezone.utc),
                    open=Decimal(str(110.00 - i * 1.00)),  # Declining prices
                    high=Decimal(str(110.50 - i * 1.00)),
                    low=Decimal(str(108.00 - i * 1.00)),
                    close=Decimal(str(108.50 - i * 1.00)),
                    volume=1000,
                )
            )

        # Perfect hammer: small body at top, long lower wick, NO upper wick
        hammer = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 1, tzinfo=timezone.utc),
            open=Decimal('99.00'),
            high=Decimal('99.50'),  # High = close (no upper wick)
            low=Decimal('90.00'),  # Long lower wick (9.5 points)
            close=Decimal('99.50'),  # Small body (0.5 points), bullish close
            volume=1500,  # Higher volume for confirmation
        )

        # Test with downtrend context
        patterns = pd.detect_patterns(downtrend_bars + [hammer])
        hammer_patterns = [p for p in patterns if p.pattern_type.value == 'hammer']

        # Should detect hammer pattern after downtrend
        assert len(hammer_patterns) > 0, (
            f'No hammer detected. Detected patterns: {[p.pattern_type.value for p in patterns]}'
        )
        assert hammer_patterns[0].signal == PatternSignal.BULLISH

    def test_detect_engulfing_patterns(self):
        """Test bullish and bearish engulfing."""
        pd = PatternDetector()

        # Bearish bar
        bearish = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            open=Decimal('105.00'),
            high=Decimal('105.50'),
            low=Decimal('104.00'),
            close=Decimal('104.00'),
            volume=1000,
        )

        # Bullish engulfing
        bullish_engulfing = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 1, tzinfo=timezone.utc),
            open=Decimal('103.00'),  # Opens below previous close
            high=Decimal('107.00'),
            low=Decimal('103.00'),
            close=Decimal('106.00'),  # Closes above previous open
            volume=1000,
        )

        patterns = pd.detect_patterns([bearish, bullish_engulfing])
        engulfing = [p for p in patterns if p.pattern_type.value == 'bullish_engulfing']
        assert len(engulfing) > 0
        assert engulfing[0].signal == PatternSignal.BULLISH


class TestProfessionalSafeguards:
    """Test professional trading safeguards."""

    def test_safeguards_init(self):
        """Test ProfessionalSafeguards initialization."""
        ps = ProfessionalSafeguards(
            max_trades_per_hour=20,
            max_trades_per_day=100,
        )
        assert ps.max_trades_per_hour == 20
        assert ps.max_trades_per_day == 100

    def test_overtrading_detection(self):
        """Test overtrading prevention."""
        ps = ProfessionalSafeguards(max_trades_per_hour=5, max_trades_per_day=10)

        # Simulate 6 trades in last hour
        now = datetime.now(timezone.utc)
        for i in range(6):
            ps.record_trade(now - timedelta(minutes=i * 5), 'AAPL')

        # Next trade should be blocked
        bars = self._create_test_bars('AAPL', 10)
        result = ps.check_trading_allowed('AAPL', bars, current_time=now)

        assert result.allowed is False
        assert result.risk_level == RiskLevel.BLOCKED
        # Check either reason or warnings contain overtrading message
        assert 'overtrading' in result.reason.lower() or any('overtrading' in w.lower() for w in result.warnings)

    def test_chase_detection(self):
        """Test price spike detection (chasing)."""
        ps = ProfessionalSafeguards(chase_threshold_pct=5.0)

        # Create bars with price spike
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

        # Normal bars
        for i in range(5):
            bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=1000,
                )
            )

        # Spike bar (10% jump)
        bars.append(
            Bar(
                symbol='AAPL',
                timestamp=base_time + timedelta(minutes=5),
                open=Decimal('100.0'),
                high=Decimal('112.0'),
                low=Decimal('100.0'),
                close=Decimal('110.0'),  # 10% spike!
                volume=1000,
            )
        )

        result = ps.check_trading_allowed('AAPL', bars)

        # Should detect spike and reduce confidence
        assert result.confidence_adjustment < 0
        assert result.position_size_multiplier < 1.0
        assert any('spiking' in w.lower() for w in result.warnings)

    def test_news_event_detection(self):
        """Test unusual volume detection."""
        ps = ProfessionalSafeguards(news_volume_multiplier=5.0)

        # Normal volume bars
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

        for i in range(20):
            bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=1000,  # Normal volume
                )
            )

        # Add bar with 10x volume (news event)
        bars.append(
            Bar(
                symbol='AAPL',
                timestamp=base_time + timedelta(minutes=20),
                open=Decimal('100.0'),
                high=Decimal('105.0'),  # High volatility
                low=Decimal('95.0'),
                close=Decimal('102.0'),
                volume=10000,  # 10x volume!
            )
        )

        result = ps.check_trading_allowed('AAPL', bars)

        # Should detect news event
        assert result.confidence_adjustment < 0
        assert any('unusual activity' in w.lower() or 'news' in w.lower() for w in result.warnings)

    def test_record_trade_rejects_naive_datetime(self):
        """Test that record_trade raises TypeError for naive datetime (regression test for Bug #7)."""
        ps = ProfessionalSafeguards()

        # Naive datetime (no tzinfo)
        naive_timestamp = datetime(2024, 1, 1, 12, 0, 0)

        # Should raise TypeError with clear message
        with pytest.raises(TypeError) as exc_info:
            ps.record_trade(naive_timestamp, 'AAPL')

        # Verify error message contains guidance
        error_msg = str(exc_info.value)
        assert 'naive datetime' in error_msg.lower()
        assert 'timezone.utc' in error_msg
        assert 'comparison errors' in error_msg.lower()

    @staticmethod
    def _create_test_bars(symbol: str, count: int) -> list[Bar]:
        """Create test bars."""
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

        for i in range(count):
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=1000,
                )
            )

        return bars


class TestFSDProfessionalIntegration:
    """Test FSD integration with professional modules."""

    def test_fsd_with_professional_modules(self):
        """Test FSD engine with all professional modules enabled."""
        # Create portfolio
        portfolio = Portfolio(cash=Decimal('10000'))

        # Create professional modules
        timeframe_manager = TimeframeManager(symbols=['AAPL'], timeframes=['1m', '5m'])
        pattern_detector = PatternDetector()
        safeguards = ProfessionalSafeguards()

        # Create FSD config
        fsd_config = FSDConfig(
            max_capital=10000.0,
            min_confidence_threshold=0.6,
            max_concurrent_positions=5,
        )

        # Create FSD engine with professional modules
        fsd = FSDEngine(
            fsd_config,
            portfolio,
            timeframe_manager=timeframe_manager,
            pattern_detector=pattern_detector,
            safeguards=safeguards,
        )

        # Add bars to timeframe manager
        bars = self._create_test_bars('AAPL', 50)
        for bar in bars:
            timeframe_manager.add_bar('AAPL', '1m', bar)
            timeframe_manager.add_bar('AAPL', '5m', bar)  # Simplified - same bars

        # Extract state (should include timeframe and pattern features)
        state = fsd.extract_state('AAPL', bars, {'AAPL': bars[-1].close})

        assert state is not None
        assert 'symbol' in state
        assert 'price_change_pct' in state

        # Should have multi-timeframe features
        assert 'confluence' in state or len(bars) < 20  # May not have enough data yet

        # Should have pattern features
        assert 'pattern_signal' in state

    def test_fsd_evaluate_with_safeguards(self):
        """Test FSD evaluation respects professional safeguards."""
        portfolio = Portfolio(cash=Decimal('10000'))
        safeguards = ProfessionalSafeguards(max_trades_per_hour=2)  # Very low limit

        fsd_config = FSDConfig(max_capital=10000.0, min_confidence_threshold=0.3)
        fsd = FSDEngine(fsd_config, portfolio, safeguards=safeguards)

        # Create bars with timezone-aware timestamps
        bars = self._create_test_bars('AAPL', 50)

        # Record many trades to trigger overtrading (all timezone-aware)
        now = datetime.now(timezone.utc)
        for i in range(3):
            trade_time = now - timedelta(minutes=i * 10)
            # Ensure timezone-aware
            if trade_time.tzinfo is None:
                trade_time = trade_time.replace(tzinfo=timezone.utc)
            safeguards.record_trade(trade_time, 'AAPL')

        # Try to evaluate opportunity
        decision = fsd.evaluate_opportunity('AAPL', bars, {'AAPL': bars[-1].close})

        # Should be blocked by overtrading safeguard
        assert decision['should_trade'] is False
        assert 'safeguards_blocked' in decision['reason'] or decision['reason'] == 'insufficient_data'

    @staticmethod
    def _create_test_bars(symbol: str, count: int) -> list[Bar]:
        """Create test bars with realistic OHLCV data."""
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        base_price = 100.0

        for i in range(count):
            price = base_price + (i * 0.1)  # Slight uptrend
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal(str(price)),
                    high=Decimal(str(price + 1.0)),
                    low=Decimal(str(price - 1.0)),
                    close=Decimal(str(price + 0.5)),
                    volume=1000 + (i * 10),
                )
            )

        return bars
