# backtest.py
"""
Backtesting runner that reuses the same feature and indicator pipeline as live trading.
Ensures backtest results reflect production behavior by sharing code paths.
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# Ensure project root in path
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except NameError:
    project_root = os.getcwd()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

# Import live components (same as live trading)
from config.settings import Settings
from managers.portfolio_manager import PortfolioManager
from managers.risk_manager import RiskManager
from managers.strategy_manager import StrategyManager
from utils.logger import setup_logger
from utils.market_analyzer import MarketRegimeDetector


class BacktestEngine:
    """
    Backtesting engine that replays historical data through live strategy pipeline.
    """

    def __init__(self, settings: Settings, logger=None):
        self.settings = settings
        self.logger = logger or setup_logger('Backtest', 'logs/backtest.log', level='INFO')
        self.error_logger = setup_logger('BacktestError', 'logs/error_logs/errors.log', level='ERROR')

        # Initialize managers (same as live)
        self.portfolio_manager = PortfolioManager(self.settings, self.logger)
        self.risk_manager = RiskManager(self.portfolio_manager, self.settings, self.logger)
        self.regime_detector = MarketRegimeDetector(self.settings, self.logger)
        self.strategy_manager = StrategyManager(
            self.settings, self.portfolio_manager, self.regime_detector, self.logger
        )

        # Backtest-specific state
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.current_positions: dict[str, float] = {}  # {symbol: quantity}

    def load_data(self, data_dir: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """
        Load historical data from CSV files.
        Expected format: timestamp (index), open, high, low, close, volume
        """
        data = {}
        for symbol in symbols:
            # Sanitize filename
            safe_symbol = symbol.replace('/', '_').replace('\\', '_')
            file_path = os.path.join(data_dir, f'{safe_symbol}.csv')

            if not os.path.exists(file_path):
                self.logger.warning(f'Data file not found for {symbol}: {file_path}')
                continue

            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
                # Ensure UTC timezone
                if df.index.tz is None:
                    df.index = pd.to_datetime(df.index, utc=True)
                else:
                    df.index = df.index.tz_convert('UTC')

                # Validate required columns
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    self.error_logger.error(f'Missing required columns in {file_path}: {df.columns}')
                    continue

                # Clean data
                df = df.sort_index()
                df = df[~df.index.duplicated(keep='last')]
                df = df.dropna(subset=required_cols)

                data[symbol] = df
                self.logger.info(f'Loaded {len(df)} bars for {symbol} from {file_path}')
            except Exception as e:
                self.error_logger.error(f'Failed to load data for {symbol} from {file_path}: {e}', exc_info=True)

        return data

    def run(self, data: dict[str, pd.DataFrame], start_date=None, end_date=None) -> dict:
        """
        Run backtest on historical data.

        Args:
            data: Dict of {symbol: DataFrame} with OHLCV data
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dict with backtest results and statistics
        """
        if not data:
            self.logger.error('No data provided for backtest')
            return {}

        # Filter data by date range if specified
        if start_date or end_date:
            for symbol in data:
                df = data[symbol]
                if start_date:
                    df = df[df.index >= pd.Timestamp(start_date, tz='UTC')]
                if end_date:
                    df = df[df.index <= pd.Timestamp(end_date, tz='UTC')]
                data[symbol] = df

        # Get unified timeline (all timestamps across all symbols)
        all_timestamps = set()
        for df in data.values():
            all_timestamps.update(df.index)
        timeline = sorted(all_timestamps)

        self.logger.info(f'Running backtest from {timeline[0]} to {timeline[-1]} ({len(timeline)} bars)')

        # Get minimum data points required
        min_data_points = self.strategy_manager.get_min_data_points()

        # Run backtest
        for i, current_time in enumerate(timeline):
            # Build market data up to current time for each symbol
            market_data_snapshot = {}
            for symbol, df in data.items():
                snapshot = df[df.index <= current_time]
                if len(snapshot) >= min_data_points:
                    market_data_snapshot[symbol] = snapshot

            if not market_data_snapshot:
                continue  # Not enough data yet

            # Update regime detection
            for symbol, df in market_data_snapshot.items():
                self.regime_detector.detect_regime(symbol, df)

            # Check risk halts
            latest_prices = {
                symbol: {'price': df['close'].iloc[-1], 'time': current_time}
                for symbol, df in market_data_snapshot.items()
            }
            self.risk_manager.check_portfolio_risk(latest_prices)

            if self.risk_manager.is_trading_halted():
                continue

            # Evaluate strategies for each symbol
            for symbol, df in market_data_snapshot.items():
                signal, individual_signals = self.strategy_manager.aggregate_signals(symbol, df.copy())

                if signal != 0:
                    self._process_signal(symbol, signal, df, current_time)

            # Record equity at this timestamp
            equity = self.portfolio_manager.get_total_equity()
            self.equity_curve.append(
                {'timestamp': current_time, 'equity': equity, 'drawdown': self.portfolio_manager.get_current_drawdown()}
            )

            # Progress logging
            if i % 1000 == 0:
                self.logger.info(f'Processed {i}/{len(timeline)} bars. Equity: {equity:.2f}')

        # Calculate final statistics
        results = self._calculate_statistics()
        return results

    def _process_signal(self, symbol: str, signal: int, market_data: pd.DataFrame, current_time):
        """Process a trading signal (same logic as live, simplified)."""
        latest_price = market_data['close'].iloc[-1]
        current_position = self.current_positions.get(symbol, 0.0)

        action = 'BUY' if signal == 1 else 'SELL' if signal == -1 else None
        if action is None:
            return

        # Determine if closing, opening, or reversing
        is_closing = (action == 'SELL' and current_position > 0) or (action == 'BUY' and current_position < 0)
        is_opening = np.isclose(current_position, 0.0, atol=1e-6)

        quantity = 0.0
        entry_price = latest_price

        # Simplified position sizing (use live sizing logic)
        if is_closing:
            quantity = abs(current_position)
        elif is_opening:
            # Calculate position size (simplified - no tick constraints in backtest)
            total_equity = self.portfolio_manager.get_total_equity()
            risk_amount = total_equity * self.settings.RISK_PER_TRADE

            # Simple SL calculation
            sl_pct = self.settings.STOP_LOSS_PERCENT if self.settings.STOP_LOSS_TYPE == 'PERCENT' else 0.02
            risk_per_unit = latest_price * sl_pct

            if risk_per_unit > 0:
                quantity = risk_amount / risk_per_unit
                # Cap by max position size
                max_position_value = total_equity * self.settings.MAX_SINGLE_POSITION_PERCENT
                max_quantity = max_position_value / latest_price
                quantity = min(quantity, max_quantity)
            else:
                return
        else:
            return  # Ignore other scenarios

        if quantity <= 0:
            return

        # Execute trade (simulated)
        trade_direction = 1 if action == 'BUY' else -1
        commission = quantity * self.settings.ESTIMATED_COMMISSION_PER_SHARE
        slippage = quantity * self.settings.ESTIMATED_SLIPPAGE_PER_SHARE
        (quantity * entry_price) + commission + slippage

        # Update position
        new_position = current_position + (trade_direction * quantity)
        self.current_positions[symbol] = new_position

        # Calculate PnL if closing
        pnl = 0.0
        if is_closing:
            # Simplified PnL calculation
            avg_entry = self.portfolio_manager.get_avg_entry_price(symbol) or entry_price
            pnl = (entry_price - avg_entry) * quantity * (-1 if current_position < 0 else 1)
            pnl -= commission + slippage
            self.portfolio_manager.update_trade_pnl(symbol, pnl)

        # Update portfolio
        self.portfolio_manager.update_position(symbol, new_position, entry_price, executed_qty=quantity)

        # Record trade
        trade_record = {
            'timestamp': current_time,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'price': entry_price,
            'pnl': pnl,
            'position_after': new_position,
            'equity': self.portfolio_manager.get_total_equity(),
        }
        self.trades.append(trade_record)

        self.logger.debug(f'Trade: {action} {quantity:.4f} {symbol} @ {entry_price:.2f}, PnL: {pnl:.2f}')

    def _calculate_statistics(self) -> dict:
        """Calculate backtest performance statistics."""
        if not self.equity_curve:
            return {}

        equity_df = pd.DataFrame(self.equity_curve).set_index('timestamp')
        trades_df = pd.DataFrame(self.trades)

        initial_equity = self.settings.TOTAL_CAPITAL
        final_equity = equity_df['equity'].iloc[-1]
        total_return = (final_equity - initial_equity) / initial_equity

        # Calculate returns
        equity_df['returns'] = equity_df['equity'].pct_change()

        # Sharpe ratio (annualized, assuming daily data)
        mean_return = equity_df['returns'].mean()
        std_return = equity_df['returns'].std()
        sharpe = (mean_return / std_return) * np.sqrt(252) if std_return > 0 else 0.0

        # Max drawdown
        max_drawdown = equity_df['drawdown'].max()

        # Trade statistics
        num_trades = len(trades_df)
        winning_trades = trades_df[trades_df['pnl'] > 0] if num_trades > 0 else pd.DataFrame()
        losing_trades = trades_df[trades_df['pnl'] < 0] if num_trades > 0 else pd.DataFrame()

        win_rate = len(winning_trades) / num_trades if num_trades > 0 else 0.0
        avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0.0
        avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0.0
        profit_factor = (
            abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum())
            if len(losing_trades) > 0 and losing_trades['pnl'].sum() != 0
            else 0.0
        )

        stats = {
            'initial_equity': initial_equity,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'num_trades': num_trades,
            'win_rate': win_rate,
            'win_rate_pct': win_rate * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'trades': trades_df,
            'equity_curve': equity_df,
        }

        return stats

    def print_results(self, results: dict):
        """Print backtest results to console."""
        if not results:
            print('No results to display')
            return

        print('\n' + '=' * 60)
        print('BACKTEST RESULTS')
        print('=' * 60)
        print(f'Initial Equity:    ${results["initial_equity"]:,.2f}')
        print(f'Final Equity:      ${results["final_equity"]:,.2f}')
        print(f'Total Return:      {results["total_return_pct"]:.2f}%')
        print(f'Sharpe Ratio:      {results["sharpe_ratio"]:.2f}')
        print(f'Max Drawdown:      {results["max_drawdown_pct"]:.2f}%')
        print(f'\nNumber of Trades:  {results["num_trades"]}')
        print(f'Win Rate:          {results["win_rate_pct"]:.2f}%')
        print(f'Avg Win:           ${results["avg_win"]:.2f}')
        print(f'Avg Loss:          ${results["avg_loss"]:.2f}')
        print(f'Profit Factor:     {results["profit_factor"]:.2f}')
        print('=' * 60 + '\n')

    def save_results(self, results: dict, output_dir: str = 'data/backtest_results'):
        """Save backtest results to files."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save trades
        if 'trades' in results and not results['trades'].empty:
            trades_file = os.path.join(output_dir, f'trades_{timestamp}.csv')
            results['trades'].to_csv(trades_file, index=False)
            self.logger.info(f'Saved trades to {trades_file}')

        # Save equity curve
        if 'equity_curve' in results and not results['equity_curve'].empty:
            equity_file = os.path.join(output_dir, f'equity_curve_{timestamp}.csv')
            results['equity_curve'].to_csv(equity_file, index=True)
            self.logger.info(f'Saved equity curve to {equity_file}')

        # Save summary stats
        summary = {k: v for k, v in results.items() if k not in ['trades', 'equity_curve']}
        summary_file = os.path.join(output_dir, f'summary_{timestamp}.txt')
        with open(summary_file, 'w') as f:
            for key, value in summary.items():
                f.write(f'{key}: {value}\n')
        self.logger.info(f'Saved summary to {summary_file}')


def main():
    """Main entry point for backtesting."""
    parser = argparse.ArgumentParser(description='Run backtest on historical data')
    parser.add_argument(
        '--data-dir', type=str, default='data/live_data', help='Directory containing historical CSV files'
    )
    parser.add_argument(
        '--symbols',
        type=str,
        required=True,
        help='Comma-separated list of symbols to backtest (e.g., "BTC/USD,ETH/USD")',
    )
    parser.add_argument('--start-date', type=str, default=None, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None, help='End date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', type=str, default='data/backtest_results', help='Directory to save results')

    args = parser.parse_args()

    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(',')]

    # Setup
    logger = setup_logger('BacktestMain', 'logs/backtest.log', level='INFO')
    settings = Settings()

    # Override settings for backtest mode
    settings.TRADE_INSTRUMENTS = symbols
    settings.DATA_SOURCE = 'historical'

    # Create engine
    engine = BacktestEngine(settings, logger)

    # Load data
    logger.info(f'Loading data for symbols: {symbols} from {args.data_dir}')
    data = engine.load_data(args.data_dir, symbols)

    if not data:
        logger.error('No data loaded. Exiting.')
        return 1

    # Run backtest
    logger.info('Starting backtest...')
    results = engine.run(data, start_date=args.start_date, end_date=args.end_date)

    if not results:
        logger.error('Backtest failed to produce results')
        return 1

    # Display and save results
    engine.print_results(results)
    engine.save_results(results, args.output_dir)

    logger.info('Backtest complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
