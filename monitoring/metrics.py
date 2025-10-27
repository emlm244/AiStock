"""
Prometheus metrics collection for AiStock trading bot.
"""

import time
from functools import wraps

from prometheus_client import Counter, Gauge, Histogram, Info


class MetricsCollector:
    """
    Centralized metrics collection using Prometheus client.

    Metrics Categories:
    - Trading: Orders, fills, P&L
    - System: Latency, errors, connections
    - Risk: Drawdown, exposure, limits
    """

    # Trading Metrics
    trades_total = Counter('aistock_trades_total', 'Total number of trades executed', ['symbol', 'action', 'strategy'])

    orders_placed = Counter('aistock_orders_placed_total', 'Total orders placed', ['symbol', 'order_type'])

    orders_filled = Counter('aistock_orders_filled_total', 'Total orders filled', ['symbol'])

    orders_rejected = Counter('aistock_orders_rejected_total', 'Total orders rejected', ['symbol', 'reason'])

    # P&L Metrics
    realized_pnl = Gauge('aistock_realized_pnl', 'Cumulative realized P&L', ['symbol'])

    unrealized_pnl = Gauge('aistock_unrealized_pnl', 'Current unrealized P&L', ['symbol'])

    daily_pnl = Gauge('aistock_daily_pnl', 'Daily P&L')

    # Portfolio Metrics
    portfolio_equity = Gauge('aistock_portfolio_equity', 'Total portfolio equity')

    portfolio_drawdown = Gauge('aistock_portfolio_drawdown_pct', 'Current portfolio drawdown percentage')

    position_size = Gauge('aistock_position_size', 'Current position size', ['symbol'])

    # System Metrics
    api_calls_total = Counter('aistock_api_calls_total', 'Total API calls made', ['endpoint', 'status'])

    api_errors_total = Counter('aistock_api_errors_total', 'Total API errors', ['error_code'])

    order_placement_latency = Histogram(
        'aistock_order_placement_latency_seconds',
        'Order placement latency in seconds',
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
    )

    strategy_evaluation_time = Histogram(
        'aistock_strategy_evaluation_seconds',
        'Time to evaluate all strategies for a symbol',
        ['symbol'],
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
    )

    data_processing_latency = Histogram(
        'aistock_data_processing_latency_seconds', 'Data processing latency', buckets=[0.001, 0.005, 0.01, 0.05, 0.1]
    )

    # Connection Status
    api_connected = Gauge('aistock_api_connected', 'API connection status (1=connected, 0=disconnected)')

    # Data Metrics
    ticks_processed_total = Counter('aistock_ticks_processed_total', 'Total ticks processed', ['symbol'])

    bars_generated_total = Counter('aistock_bars_generated_total', 'Total bars generated', ['symbol'])

    # Risk Metrics
    trading_halted = Gauge('aistock_trading_halted', 'Trading halt status (1=halted, 0=active)')

    risk_limit_breaches = Counter('aistock_risk_limit_breaches_total', 'Total risk limit breaches', ['limit_type'])

    # Application Info
    app_info = Info('aistock_application', 'Application metadata')

    # Uptime
    uptime_seconds = Gauge('aistock_uptime_seconds', 'Application uptime in seconds')

    @classmethod
    def record_trade(cls, symbol: str, action: str, strategy: str):
        """Record a trade execution."""
        cls.trades_total.labels(symbol=symbol, action=action, strategy=strategy).inc()

    @classmethod
    def record_order_placed(cls, symbol: str, order_type: str):
        """Record an order placement."""
        cls.orders_placed.labels(symbol=symbol, order_type=order_type).inc()

    @classmethod
    def record_order_filled(cls, symbol: str):
        """Record an order fill."""
        cls.orders_filled.labels(symbol=symbol).inc()

    @classmethod
    def record_order_rejected(cls, symbol: str, reason: str):
        """Record an order rejection."""
        cls.orders_rejected.labels(symbol=symbol, reason=reason).inc()

    @classmethod
    def update_portfolio_metrics(cls, equity: float, drawdown_pct: float, daily_pnl: float):
        """Update portfolio-level metrics."""
        cls.portfolio_equity.set(equity)
        cls.portfolio_drawdown.set(drawdown_pct)
        cls.daily_pnl.set(daily_pnl)

    @classmethod
    def update_position(cls, symbol: str, size: float):
        """Update position size metric."""
        cls.position_size.labels(symbol=symbol).set(size)

    @classmethod
    def update_pnl(cls, symbol: str, realized: float, unrealized: float):
        """Update P&L metrics."""
        cls.realized_pnl.labels(symbol=symbol).set(realized)
        cls.unrealized_pnl.labels(symbol=symbol).set(unrealized)

    @classmethod
    def record_api_call(cls, endpoint: str, status: str):
        """Record an API call."""
        cls.api_calls_total.labels(endpoint=endpoint, status=status).inc()

    @classmethod
    def record_api_error(cls, error_code: str):
        """Record an API error."""
        cls.api_errors_total.labels(error_code=error_code).inc()

    @classmethod
    def set_connection_status(cls, connected: bool):
        """Update API connection status."""
        cls.api_connected.set(1 if connected else 0)

    @classmethod
    def set_trading_halted(cls, halted: bool):
        """Update trading halt status."""
        cls.trading_halted.set(1 if halted else 0)

    @classmethod
    def record_risk_breach(cls, limit_type: str):
        """Record a risk limit breach."""
        cls.risk_limit_breaches.labels(limit_type=limit_type).inc()

    @classmethod
    def record_tick(cls, symbol: str):
        """Record a tick processed."""
        cls.ticks_processed_total.labels(symbol=symbol).inc()

    @classmethod
    def record_bar(cls, symbol: str):
        """Record a bar generated."""
        cls.bars_generated_total.labels(symbol=symbol).inc()

    @classmethod
    def set_app_info(cls, version: str, mode: str, instruments: str):
        """Set application metadata."""
        cls.app_info.info({'version': version, 'mode': mode, 'instruments': instruments})

    @classmethod
    def update_uptime(cls, uptime: float):
        """Update application uptime."""
        cls.uptime_seconds.set(uptime)

    @staticmethod
    def time_it(metric: Histogram):
        """
        Decorator to measure function execution time.

        Usage:
            @MetricsCollector.time_it(MetricsCollector.order_placement_latency)
            def place_order(...):
                ...
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start_time
                    metric.observe(duration)

            return wrapper

        return decorator
