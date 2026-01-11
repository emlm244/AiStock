"""
Backtest orchestrator - main coordinator for running backtests.

This module coordinates:
- Data fetching from Massive.com (rate-limited)
- Universe validation for survivorship bias
- Walk-forward validation execution
- Report generation
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from ..calendar import is_within_open_close_buffer
from ..data import Bar
from ..providers.massive import MassiveConfig, MassiveDataProvider
from .config import BacktestPlanConfig, DataFetchStatus, PeriodResult
from .execution import RealisticExecutionModel
from .universe import HistoricalUniverseManager, UniverseValidationResult
from .walkforward import WalkForwardResult, WalkForwardValidator

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    config: BacktestPlanConfig
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None

    # Data status
    data_fetch_status: DataFetchStatus | None = None

    # Universe validation
    universe_validation: UniverseValidationResult | None = None

    # Results
    period_results: list[PeriodResult] = field(default_factory=list)
    walkforward_result: WalkForwardResult | None = None

    # Report
    report: Any = None  # BacktestReport from report.py

    @property
    def elapsed_seconds(self) -> float:
        """Total elapsed time in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    @property
    def success(self) -> bool:
        """Whether the backtest completed successfully."""
        if self.walkforward_result:
            return self.walkforward_result.completed_folds > 0
        return len(self.period_results) > 0


@dataclass
class _ScheduledBacktestOrder:
    symbol: str
    quantity: Decimal
    side: str
    execute_at: datetime
    order_type: str
    slice_index: int
    total_slices: int


class BacktestOrchestrator:
    """
    Main orchestrator for running backtests.

    Coordinates:
    - Data fetching from Massive.com (respecting rate limits)
    - Universe validation for survivorship bias
    - Walk-forward validation
    - Report generation

    Example usage:
    ```python
    massive_config = MassiveConfig(api_key='...')
    plan = BacktestPlanConfig(
        symbols=['AAPL', 'MSFT'],
        start_date=date(2023, 1, 1),
        end_date=date(2024, 12, 31),
        walkforward=WalkForwardConfig(),
    )

    orchestrator = BacktestOrchestrator(plan, massive_config)
    result = orchestrator.run_backtest()
    ```
    """

    def __init__(
        self,
        config: BacktestPlanConfig,
        massive_config: MassiveConfig,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            config: Backtest plan configuration.
            massive_config: Massive.com API configuration.
        """
        self._config = config
        self._massive_config = massive_config
        self._provider = MassiveDataProvider(massive_config)
        self._universe_mgr = HistoricalUniverseManager()
        self._exec_model = RealisticExecutionModel(config.execution)
        self._scheduled_orders: list[_ScheduledBacktestOrder] = []

        # Ensure output directory exists
        Path(config.output_dir).mkdir(parents=True, exist_ok=True)

    def prefetch_data(
        self,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DataFetchStatus:
        """
        Pre-fetch all required data from Massive.com.

        This method respects the 5 calls/minute rate limit and reports
        progress. For large symbol lists, this can take significant time.

        Args:
            symbols: Symbols to fetch. Uses config symbols if not provided.
            start_date: Start date. Uses config if not provided.
            end_date: End date. Uses config if not provided.

        Returns:
            DataFetchStatus with results.
        """
        symbols = symbols or self._config.symbols
        start = start_date or self._config.start_date
        end = end_date or self._config.end_date

        if not start or not end:
            raise ValueError('Start and end dates are required')

        status = DataFetchStatus(
            success=True,
            symbols_requested=len(symbols),
        )

        start_time = time.time()

        # Estimate fetch time
        estimate = self._provider.estimate_fetch_time(symbols, start, end)
        logger.info(
            f'Prefetching data for {len(symbols)} symbols: {start} to {end}\n'
            f'Cached: {estimate["cached_symbols"]}, To fetch: {estimate["symbols_to_fetch"]}\n'
            f'Estimated API calls: {estimate["estimated_api_calls"]}\n'
            f'Estimated time: {estimate["estimated_minutes"]:.1f} minutes'
        )

        status.symbols_cached = estimate['cached_symbols']

        # Fetch each symbol
        for i, symbol in enumerate(symbols):
            logger.info(f'[{i + 1}/{len(symbols)}] Fetching {symbol}...')

            result = self._provider.fetch_bars(
                symbol=symbol,
                start_date=start,
                end_date=end,
                timespan='minute',
                use_cache=self._config.use_cache,
            )

            if result.success:
                status.symbols_fetched += 1
                status.api_calls_used += result.api_calls_used
                if result.from_cache:
                    logger.info(f'  {symbol}: {len(result.data)} bars (from cache)')
                else:
                    logger.info(f'  {symbol}: {len(result.data)} bars (fetched)')
            else:
                status.errors.append(f'{symbol}: {result.error}')
                logger.error(f'  {symbol}: FAILED - {result.error}')

        status.elapsed_seconds = time.time() - start_time
        status.success = len(status.errors) == 0

        logger.info(
            f'Data prefetch complete: {status.symbols_fetched}/{status.symbols_requested} symbols, '
            f'{status.api_calls_used} API calls, {status.elapsed_minutes:.1f} min'
        )

        return status

    def validate_universe(
        self,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> UniverseValidationResult:
        """
        Validate the backtest universe for survivorship bias.

        Args:
            symbols: Symbols to validate. Uses config if not provided.
            start_date: Start date. Uses config if not provided.
            end_date: End date. Uses config if not provided.

        Returns:
            UniverseValidationResult with validation details.
        """
        symbols = symbols or self._config.symbols
        start = start_date or self._config.start_date
        end = end_date or self._config.end_date

        if not start or not end:
            raise ValueError('Start and end dates are required')

        logger.info(f'Validating universe of {len(symbols)} symbols for {start} to {end}')

        # Load lifecycle data from Massive.com
        self._universe_mgr.load_from_massive(self._provider)

        # Validate
        result = self._universe_mgr.validate_backtest_universe(symbols, start, end)

        if result.is_valid:
            logger.info(f'Universe validation PASSED: {result.valid_symbols}/{result.total_symbols} valid')
        else:
            logger.warning(
                f'Universe validation FAILED: {result.invalid_symbols} symbols have issues\n'
                f'Symbols to exclude: {result.symbols_to_exclude}'
            )

        if result.warnings:
            for warning in result.warnings[:5]:  # Show first 5 warnings
                logger.warning(f'  {warning}')
            if len(result.warnings) > 5:
                logger.warning(f'  ... and {len(result.warnings) - 5} more warnings')

        return result

    def run_backtest(self) -> BacktestResult:
        """
        Run the complete backtest.

        This is the main entry point that:
        1. Prefetches data from Massive.com
        2. Validates the universe for survivorship bias
        3. Runs walk-forward validation (if configured)
        4. Generates reports

        Returns:
            BacktestResult with all results.
        """
        result = BacktestResult(config=self._config)

        logger.info('=' * 60)
        logger.info('BACKTEST STARTING')
        logger.info(f'Symbols: {self._config.symbols}')
        logger.info(f'Period: {self._config.start_date} to {self._config.end_date}')
        logger.info(f'Walk-forward: {self._config.walkforward is not None}')
        logger.info('=' * 60)

        # Step 1: Prefetch data
        logger.info('Step 1: Prefetching data...')
        result.data_fetch_status = self.prefetch_data()

        if not result.data_fetch_status.success:
            logger.error('Data prefetch failed. Aborting backtest.')
            result.end_time = datetime.now(timezone.utc)
            return result

        # Step 2: Validate universe
        if self._config.validate_universe:
            logger.info('Step 2: Validating universe...')
            result.universe_validation = self.validate_universe()

            if not result.universe_validation.is_valid and self._config.exclude_survivorship_bias:
                # Filter out invalid symbols
                valid_symbols = result.universe_validation.get_valid_symbols()
                if not valid_symbols:
                    logger.error('No valid symbols after survivorship bias filtering. Aborting.')
                    result.end_time = datetime.now(timezone.utc)
                    return result

                logger.warning(f'Filtered symbols from {len(self._config.symbols)} to {len(valid_symbols)}')
                self._config.symbols = valid_symbols

        # Step 3: Run backtest
        if self._config.walkforward:
            logger.info('Step 3: Running walk-forward validation...')
            result.walkforward_result = self._run_walkforward()
        else:
            logger.info('Step 3: Running single-period backtest...')
            period_result = self._run_single_period(
                self._config.start_date,
                self._config.end_date,
            )
            result.period_results.append(period_result)

        # Step 4: Generate report
        if self._config.generate_report:
            logger.info('Step 4: Generating report...')
            from .report import generate_backtest_report

            result.report = generate_backtest_report(result, self._config.output_dir)

        result.end_time = datetime.now(timezone.utc)

        logger.info('=' * 60)
        logger.info(f'BACKTEST COMPLETE in {result.elapsed_seconds:.1f}s')
        if result.walkforward_result:
            logger.info(
                f'Walk-forward: IS Sharpe={result.walkforward_result.in_sample_sharpe:.2f}, '
                f'OOS Sharpe={result.walkforward_result.out_of_sample_sharpe:.2f}, '
                f'Overfitting={result.walkforward_result.overfitting_ratio:.2f}'
            )
        logger.info('=' * 60)

        return result

    def _run_walkforward(self) -> WalkForwardResult:
        """Run walk-forward validation."""
        if not self._config.walkforward or not self._config.start_date or not self._config.end_date:
            raise ValueError('Walk-forward config and dates are required')

        validator = WalkForwardValidator(self._config.walkforward)

        # Generate folds
        folds = validator.generate_folds(
            self._config.start_date,
            self._config.end_date,
        )

        logger.info(f'Generated {len(folds)} walk-forward folds')

        # Calculate final holdout dates
        final_holdout_dates = None
        if self._config.walkforward.enable_final_holdout:
            holdout_start = self._config.end_date - timedelta(days=self._config.walkforward.final_holdout_days)
            final_holdout_dates = (holdout_start, self._config.end_date)

        # Run validation
        def strategy_runner(start: date, end: date, is_training: bool) -> PeriodResult:
            return self._run_single_period(start, end, is_training=is_training)

        return validator.run_validation(folds, strategy_runner, final_holdout_dates)

    def _run_single_period(
        self,
        start_date: date | None,
        end_date: date | None,
        is_training: bool = False,
    ) -> PeriodResult:
        """
        Run backtest for a single period.

        Args:
            start_date: Period start.
            end_date: Period end.
            is_training: Whether this is a training period (for walk-forward).

        Returns:
            PeriodResult with metrics.
        """
        if not start_date or not end_date:
            raise ValueError('Start and end dates are required')

        result = PeriodResult(
            start_date=start_date,
            end_date=end_date,
            is_train=is_training,
        )

        # Load data from cache
        bars = self._load_bars_from_cache(start_date, end_date)
        if not bars:
            logger.warning(f'No bars loaded for period {start_date} to {end_date}')
            return result

        logger.debug(f'Loaded {len(bars)} bars for {start_date} to {end_date}')

        # Run through the trading logic
        # This is a simplified simulation - in production, you'd use SessionFactory
        try:
            result = self._simulate_trading(bars, result)
        except Exception as e:
            logger.error(f'Trading simulation failed: {e}')

        return result

    def _load_bars_from_cache(self, start_date: date, end_date: date) -> list[Bar]:
        """Load bars from the Massive cache for all symbols."""
        cache = self._provider._get_cache()
        all_bars: list[Bar] = []

        for symbol in self._config.symbols:
            symbol_bars = cache.load_bars(symbol, start_date, end_date, 'minute')
            all_bars.extend(symbol_bars)

        # Sort by timestamp
        all_bars.sort(key=lambda b: b.timestamp)
        return all_bars

    def _simulate_trading(self, bars: list[Bar], result: PeriodResult) -> PeriodResult:
        """
        Simulate trading on the given bars.

        This is a simplified simulation. For full FSD integration,
        use SessionFactory to create a complete trading session.
        """
        from ..config import FSDConfig
        from ..fsd import FSD
        from ..portfolio import Portfolio

        # Initialize components
        fsd_config = self._config.fsd_config or FSDConfig()
        fsd = FSD(fsd_config)
        portfolio = Portfolio(initial_cash=self._config.initial_capital)

        # Group bars by symbol and timestamp
        bars_by_timestamp: dict[datetime, dict[str, Bar]] = {}
        for bar in bars:
            if bar.timestamp not in bars_by_timestamp:
                bars_by_timestamp[bar.timestamp] = {}
            bars_by_timestamp[bar.timestamp][bar.symbol] = bar

        # Simulate trading
        equity_curve: list[tuple[date, Decimal]] = []
        trades: list[dict] = []
        history_by_symbol: dict[str, list[Bar]] = defaultdict(list)

        sorted_timestamps = sorted(bars_by_timestamp.keys())

        for i, timestamp in enumerate(sorted_timestamps):
            symbol_bars = bars_by_timestamp[timestamp]

            for symbol, bar in symbol_bars.items():
                history = history_by_symbol[symbol]
                history.append(bar)
                scheduled_trades = self._process_scheduled_orders(symbol, bar, portfolio)
                if scheduled_trades:
                    trades.extend(scheduled_trades)
                    result.total_trades += len(scheduled_trades)

                # Get FSD decision
                # Build a simple state from the bar
                state = self._build_state_from_bar(bar, portfolio, symbol)

                # Get action from FSD
                action = fsd.decide(symbol, state)

                # Execute action
                if action != 'HOLD':
                    trade_results = self._execute_action(action, symbol, bar, portfolio, history)
                    if trade_results:
                        trades.extend(trade_results)
                        result.total_trades += len(trade_results)

            # Record equity at end of day
            if (
                i == len(sorted_timestamps) - 1
                or timestamp.date() != sorted_timestamps[min(i + 1, len(sorted_timestamps) - 1)].date()
            ):
                equity = portfolio.total_equity(
                    {
                        s: float(bars_by_timestamp[timestamp].get(s, bars[-1]).close)
                        for s in self._config.symbols
                        if s in bars_by_timestamp[timestamp]
                    }
                )
                equity_curve.append((timestamp.date(), Decimal(str(equity))))

        # Calculate metrics
        if equity_curve:
            result.equity_curve = equity_curve
            initial_equity = float(self._config.initial_capital)
            final_equity = float(equity_curve[-1][1])
            result.total_return = Decimal(str(final_equity - initial_equity))
            result.total_return_pct = (final_equity - initial_equity) / initial_equity

            # Calculate Sharpe ratio (simplified)
            if len(equity_curve) > 1:
                returns = [
                    (float(equity_curve[i][1]) - float(equity_curve[i - 1][1])) / float(equity_curve[i - 1][1])
                    for i in range(1, len(equity_curve))
                ]
                if returns:
                    import statistics

                    mean_return = statistics.mean(returns)
                    std_return = statistics.stdev(returns) if len(returns) > 1 else 1
                    if std_return > 0:
                        result.sharpe_ratio = (mean_return * 252**0.5) / (std_return * 252**0.5)

                    # Calculate Sortino ratio (uses downside deviation only)
                    negative_returns = [r for r in returns if r < 0]
                    if negative_returns and len(negative_returns) > 1:
                        downside_std = statistics.stdev(negative_returns)
                        if downside_std > 0:
                            result.sortino_ratio = (mean_return * 252**0.5) / (downside_std * 252**0.5)
                    elif mean_return > 0:
                        # No negative returns - infinite Sortino (cap at 10)
                        result.sortino_ratio = 10.0

            # Calculate max drawdown from equity curve
            if len(equity_curve) > 1:
                peak = float(equity_curve[0][1])
                max_dd = 0.0
                for _, equity_val in equity_curve:
                    equity_float = float(equity_val)
                    if equity_float > peak:
                        peak = equity_float
                    if peak > 0:
                        drawdown = (peak - equity_float) / peak
                        max_dd = max(max_dd, drawdown)
                result.max_drawdown_pct = max_dd

                # Calculate Calmar ratio (annualized return / max drawdown)
                if max_dd > 0 and len(equity_curve) > 1:
                    # Annualize the return based on trading days
                    trading_days = len(equity_curve)
                    annualized_return = result.total_return_pct * (252 / trading_days) if trading_days > 0 else 0
                    result.calmar_ratio = annualized_return / max_dd if max_dd > 0 else 0.0

        # Calculate win rate
        if trades:
            winning_trades = sum(1 for t in trades if t.get('pnl', 0) > 0)
            result.win_rate = winning_trades / len(trades)
            result.trades = trades

        return result

    def _build_state_from_bar(
        self,
        bar: Bar,
        portfolio: Any,
        symbol: str,
    ) -> dict[str, Any]:
        """Build a state dictionary from bar data."""
        position = portfolio.get_position(symbol)
        position_qty = float(position.quantity) if position else 0

        return {
            'price': float(bar.close),
            'volume': bar.volume,
            'high': float(bar.high),
            'low': float(bar.low),
            'open': float(bar.open),
            'position': position_qty,
            'equity': float(portfolio.cash),
        }

    def _should_avoid_open_close(self, timestamp: datetime) -> bool:
        execution = self._exec_model.config
        return is_within_open_close_buffer(
            timestamp,
            execution.avoid_open_minutes,
            execution.avoid_close_minutes,
            exchange='NYSE',
        )

    @staticmethod
    def _estimate_spread_bps(bar: Bar) -> Decimal:
        if bar.close <= 0:
            return Decimal('0')
        spread = bar.high - bar.low
        return (spread / bar.close) * Decimal('10000')

    def _compute_limit_price(self, side: str, price: Decimal, bar: Bar) -> Decimal:
        execution = self._exec_model.config
        spread_bps = self._estimate_spread_bps(bar)
        offset_bps = max(Decimal(str(execution.limit_offset_bps)), spread_bps / Decimal('2'))
        offset = price * (offset_bps / Decimal('10000'))
        return price + offset if side == 'buy' else price - offset

    @staticmethod
    def _build_vwap_weights(history: list[Bar], slices: int) -> list[float]:
        if slices <= 1:
            return [1.0]
        if len(history) < slices:
            return [1.0 / slices] * slices
        volumes = [bar.volume for bar in history[-slices:]]
        total = sum(volumes)
        if total <= 0:
            return [1.0 / slices] * slices
        return [vol / total for vol in volumes]

    def _build_sliced_orders(
        self,
        symbol: str,
        total_qty: Decimal,
        side: str,
        start_time: datetime,
        window_minutes: int,
        weights: list[float],
    ) -> list[_ScheduledBacktestOrder]:
        slices = max(1, len(weights))
        if slices == 1:
            weights = [1.0]
        total_weight = sum(weights) or 1.0
        normalized = [w / total_weight for w in weights]
        total_seconds = max(0, window_minutes) * 60
        step = total_seconds / max(slices - 1, 1)

        scheduled: list[_ScheduledBacktestOrder] = []
        allocated = Decimal('0')
        for idx, weight in enumerate(normalized, start=1):
            if idx == slices:
                slice_qty = total_qty - allocated
            else:
                slice_qty = (total_qty * Decimal(str(weight))).quantize(Decimal('0.00001'))
            if slice_qty <= 0:
                continue
            allocated += slice_qty
            execute_at = start_time + timedelta(seconds=step * (idx - 1))
            scheduled.append(
                _ScheduledBacktestOrder(
                    symbol=symbol,
                    quantity=slice_qty,
                    side=side,
                    execute_at=execute_at,
                    order_type='limit',
                    slice_index=idx,
                    total_slices=slices,
                )
            )
        return scheduled

    def _plan_execution_orders(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        timestamp: datetime,
        history: list[Bar],
    ) -> list[_ScheduledBacktestOrder]:
        execution = self._exec_model.config
        style = execution.execution_style.lower().strip()

        if style == 'adaptive':
            style = self._choose_execution_style(quantity, history)

        if style == 'market':
            return [
                _ScheduledBacktestOrder(
                    symbol=symbol,
                    quantity=quantity,
                    side=side,
                    execute_at=timestamp,
                    order_type='market',
                    slice_index=1,
                    total_slices=1,
                )
            ]

        if style == 'twap':
            slices = max(1, execution.twap_slices)
            window_minutes = max(0, execution.twap_window_minutes)
            weights = [1.0 / slices] * slices
            return self._build_sliced_orders(symbol, quantity, side, timestamp, window_minutes, weights)

        if style == 'vwap':
            slices = max(1, execution.vwap_slices)
            window_minutes = max(0, execution.vwap_window_minutes)
            weights = self._build_vwap_weights(history, slices)
            return self._build_sliced_orders(symbol, quantity, side, timestamp, window_minutes, weights)

        return [
            _ScheduledBacktestOrder(
                symbol=symbol,
                quantity=quantity,
                side=side,
                execute_at=timestamp,
                order_type='limit',
                slice_index=1,
                total_slices=1,
            )
        ]

    def _choose_execution_style(self, total_qty: Decimal, history: list[Bar]) -> str:
        if not history:
            return 'limit'
        sample = history[-20:]
        avg_volume = sum(bar.volume for bar in sample) / len(sample) if sample else 0
        if avg_volume <= 0:
            return 'limit'
        volume_ratio = float(total_qty) / avg_volume
        spread_bps = float(self._estimate_spread_bps(sample[-1]))
        if volume_ratio >= 0.05 or spread_bps >= 80.0:
            return 'twap'
        if volume_ratio >= 0.02 or spread_bps >= 30.0:
            return 'vwap'
        return 'limit'

    def _process_scheduled_orders(
        self,
        symbol: str,
        bar: Bar,
        portfolio: Any,
    ) -> list[dict]:
        due: list[_ScheduledBacktestOrder] = []
        remaining: list[_ScheduledBacktestOrder] = []
        for scheduled in self._scheduled_orders:
            if scheduled.symbol == symbol and scheduled.execute_at <= bar.timestamp:
                due.append(scheduled)
            else:
                remaining.append(scheduled)
        self._scheduled_orders = remaining

        trades: list[dict] = []
        for scheduled in due:
            if self._should_avoid_open_close(bar.timestamp):
                self._scheduled_orders.append(scheduled)
                continue
            trade = self._submit_scheduled_order(scheduled, bar, portfolio)
            if trade:
                trades.append(trade)
        return trades

    def _submit_scheduled_order(
        self,
        scheduled: _ScheduledBacktestOrder,
        bar: Bar,
        portfolio: Any,
    ) -> dict | None:
        from ..execution import OrderSide

        side = OrderSide.BUY if scheduled.side == 'buy' else OrderSide.SELL
        order_type = OrderType.MARKET if scheduled.order_type == 'market' else OrderType.LIMIT
        limit_price = None
        if order_type == OrderType.LIMIT:
            limit_price = self._compute_limit_price(scheduled.side, bar.close, bar)

        order = Order(
            symbol=scheduled.symbol,
            quantity=scheduled.quantity,
            side=side,
            order_type=order_type,
            limit_price=limit_price,
        )

        fill_result = self._exec_model.calculate_fill(order, bar)
        if not fill_result:
            return None

        signed_qty = fill_result.fill_quantity if side == OrderSide.BUY else -fill_result.fill_quantity
        portfolio.update_position(
            symbol=scheduled.symbol,
            quantity_delta=signed_qty,
            price=fill_result.fill_price,
            commission=fill_result.costs.commission,
        )

        return {
            'timestamp': bar.timestamp.isoformat(),
            'symbol': scheduled.symbol,
            'action': 'SLICE',
            'side': side.value,
            'quantity': float(fill_result.fill_quantity),
            'price': float(fill_result.fill_price),
            'costs': float(fill_result.costs.total),
            'pnl': 0,
        }

    def _execute_action(
        self,
        action: str,
        symbol: str,
        bar: Bar,
        portfolio: Any,
        history: list[Bar],
    ) -> list[dict]:
        """Execute a trading action."""
        from ..execution import Order, OrderSide, OrderType

        if action == 'HOLD':
            return []

        # Determine order side and quantity
        position = portfolio.get_position(symbol)
        position_qty = float(position.quantity) if position else 0

        if action == 'BUY':
            # Buy if no position
            if position_qty >= 0:
                order_qty = max(1, int(float(portfolio.cash) * 0.1 / float(bar.close)))
                side = OrderSide.BUY
            else:
                return None
        elif action == 'SELL':
            # Sell if long position
            if position_qty > 0:
                order_qty = int(position_qty)
                side = OrderSide.SELL
            else:
                return None
        elif action == 'INCREASE':
            # Increase position
            order_qty = max(1, int(float(portfolio.cash) * 0.05 / float(bar.close)))
            side = OrderSide.BUY
        elif action == 'DECREASE':
            # Decrease position
            if position_qty > 1:
                order_qty = int(position_qty * 0.5)
                side = OrderSide.SELL
            else:
                return []
        else:
            return []

        side_label = 'buy' if side == OrderSide.BUY else 'sell'
        scheduled_orders = self._plan_execution_orders(
            symbol=symbol,
            side=side_label,
            quantity=Decimal(str(order_qty)),
            timestamp=bar.timestamp,
            history=history,
        )
        if scheduled_orders:
            self._scheduled_orders.extend(scheduled_orders)
        return self._process_scheduled_orders(symbol, bar, portfolio)

    def get_status(self) -> dict[str, Any]:
        """Get current orchestrator status."""
        rate_stats = self._provider.get_rate_limiter_stats()
        universe_stats = self._universe_mgr.get_stats()

        return {
            'config': {
                'symbols': self._config.symbols,
                'start_date': str(self._config.start_date),
                'end_date': str(self._config.end_date),
                'walkforward_enabled': self._config.walkforward is not None,
            },
            'rate_limiter': rate_stats,
            'universe_manager': universe_stats,
        }
