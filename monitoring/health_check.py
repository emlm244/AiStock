# monitoring/health_check.py

"""
Health Check HTTP Server

Provides HTTP endpoints for monitoring bot health and metrics:
- GET /health - Health status (healthy/degraded/unhealthy)
- GET /metrics - Prometheus metrics
- GET /status - Detailed JSON status
"""

import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from flask import Flask, jsonify, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


class HealthCheckServer:
    """
    HTTP server for health checks and monitoring

    Runs in a background thread to avoid blocking the main trading loop
    """

    def __init__(
        self,
        port: int = 9090,
        host: str = '0.0.0.0',
        logger: Optional[logging.Logger] = None
    ):
        self.port = port
        self.host = host
        self.logger = logger or logging.getLogger(__name__)

        # Flask app
        self.app = Flask(__name__)
        self.app.logger.setLevel(logging.WARNING)  # Reduce Flask logging noise

        # Health status tracking
        self.bot_running = False
        self.api_connected = False
        self.trading_halted = False
        self.last_heartbeat = None
        self.bot_reference = None
        self.metrics_collector = None

        # Setup routes
        self._setup_routes()

        # Server thread
        self.server_thread = None
        self.is_running = False

    def _setup_routes(self):
        """Setup Flask routes"""

        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint - returns simple status"""
            status = self._determine_health_status()

            response = {
                'status': status,
                'timestamp': datetime.now().isoformat()
            }

            # Set HTTP status code based on health
            http_code = 200 if status == 'healthy' else (503 if status == 'unhealthy' else 500)

            return jsonify(response), http_code

        @self.app.route('/metrics', methods=['GET'])
        def metrics():
            """Prometheus metrics endpoint"""
            if self.metrics_collector is None:
                return Response(
                    "# Metrics collector not initialized\n",
                    mimetype=CONTENT_TYPE_LATEST
                )

            try:
                # Generate Prometheus format metrics
                metrics_output = generate_latest()
                return Response(metrics_output, mimetype=CONTENT_TYPE_LATEST)
            except Exception as e:
                self.logger.error(f"Error generating metrics: {e}")
                return Response(
                    f"# Error generating metrics: {e}\n",
                    mimetype=CONTENT_TYPE_LATEST
                ), 500

        @self.app.route('/status', methods=['GET'])
        def status():
            """Detailed status endpoint - returns comprehensive JSON"""
            try:
                detailed_status = self._get_detailed_status()
                return jsonify(detailed_status), 200
            except Exception as e:
                self.logger.error(f"Error getting detailed status: {e}")
                return jsonify({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }), 500

        @self.app.route('/ping', methods=['GET'])
        def ping():
            """Simple ping endpoint"""
            return jsonify({'ping': 'pong', 'timestamp': datetime.now().isoformat()}), 200

    def _determine_health_status(self) -> str:
        """
        Determine overall health status

        Returns:
            'healthy', 'degraded', or 'unhealthy'
        """
        # Unhealthy: Bot stopped or API disconnected
        if not self.bot_running:
            return 'unhealthy'

        if not self.api_connected:
            return 'unhealthy'

        # Check heartbeat (if bot hasn't updated in 60 seconds, something's wrong)
        if self.last_heartbeat:
            seconds_since_heartbeat = (datetime.now() - self.last_heartbeat).total_seconds()
            if seconds_since_heartbeat > 120:  # 2 minutes
                return 'unhealthy'

        # Degraded: Trading halted but otherwise operational
        if self.trading_halted:
            return 'degraded'

        # Healthy: All systems operational
        return 'healthy'

    def _get_detailed_status(self) -> Dict[str, Any]:
        """Get comprehensive status information"""
        status = {
            'health_status': self._determine_health_status(),
            'timestamp': datetime.now().isoformat(),
            'bot': {
                'running': self.bot_running,
                'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            },
            'api': {
                'connected': self.api_connected,
            },
            'trading': {
                'halted': self.trading_halted,
            }
        }

        # Add bot-specific info if available
        if self.bot_reference:
            try:
                # Add portfolio info
                if hasattr(self.bot_reference, 'portfolio_manager'):
                    pm = self.bot_reference.portfolio_manager
                    status['portfolio'] = {
                        'total_equity': getattr(pm, 'total_equity', 0),
                        'daily_pnl': getattr(pm, 'daily_pnl', 0),
                        'open_positions': len(getattr(pm, 'open_positions', {})),
                    }

                # Add performance info
                if hasattr(self.bot_reference, 'performance_tracker'):
                    pt = self.bot_reference.performance_tracker
                    status['performance'] = {
                        'total_trades': getattr(pt, 'total_trades', 0),
                        'win_rate': getattr(pt, 'win_rate', 0),
                        'sharpe_ratio': getattr(pt, 'sharpe_ratio', 0),
                    }

                # Add mode info
                if hasattr(self.bot_reference, 'settings'):
                    settings = self.bot_reference.settings
                    status['config'] = {
                        'mode': getattr(settings, 'TRADING_MODE_TYPE', 'unknown'),
                        'symbols': getattr(settings, 'TRADE_INSTRUMENTS', []),
                        'timeframe': getattr(settings, 'TIMEFRAME', 'unknown'),
                    }

            except Exception as e:
                self.logger.error(f"Error getting bot details: {e}")
                status['bot']['error'] = str(e)

        return status

    def set_bot_reference(self, bot):
        """Set reference to the main trading bot for detailed status"""
        self.bot_reference = bot

    def set_metrics_collector(self, metrics_collector):
        """Set reference to metrics collector"""
        self.metrics_collector = metrics_collector

    def update_status(
        self,
        bot_running: Optional[bool] = None,
        api_connected: Optional[bool] = None,
        trading_halted: Optional[bool] = None
    ):
        """Update health status flags"""
        if bot_running is not None:
            self.bot_running = bot_running

        if api_connected is not None:
            self.api_connected = api_connected

        if trading_halted is not None:
            self.trading_halted = trading_halted

        # Update heartbeat
        self.last_heartbeat = datetime.now()

    def start(self):
        """Start the health check server in a background thread"""
        if self.is_running:
            self.logger.warning("Health check server already running")
            return

        def run_server():
            try:
                self.logger.info(f"Starting health check server on {self.host}:{self.port}")
                # Disable Flask dev server reload to avoid threading issues
                self.app.run(
                    host=self.host,
                    port=self.port,
                    debug=False,
                    use_reloader=False,
                    threaded=True
                )
            except Exception as e:
                self.logger.error(f"Health check server error: {e}", exc_info=True)

        self.server_thread = threading.Thread(target=run_server, daemon=True, name="HealthCheckServer")
        self.server_thread.start()
        self.is_running = True

        self.logger.info(f"Health check server started at http://{self.host}:{self.port}")
        self.logger.info(f"  - Health: http://{self.host}:{self.port}/health")
        self.logger.info(f"  - Metrics: http://{self.host}:{self.port}/metrics")
        self.logger.info(f"  - Status: http://{self.host}:{self.port}/status")

    def stop(self):
        """Stop the health check server"""
        if not self.is_running:
            return

        self.is_running = False
        self.logger.info("Health check server stopped")

    def heartbeat(self):
        """Update last heartbeat timestamp"""
        self.last_heartbeat = datetime.now()
