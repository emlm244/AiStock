# database/models.py

"""
Database Models for Trade Persistence

SQLAlchemy models for storing:
- Trade history
- Performance metrics
- Parameter change history
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

Base = declarative_base()


class Trade(Base):
    """Trade execution record"""

    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY or SELL
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    strategy = Column(String(50), nullable=True)
    order_id = Column(Integer, nullable=True)
    commission = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default='open')  # open, closed, cancelled
    exit_timestamp = Column(DateTime, nullable=True)
    hold_time_seconds = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f'<Trade(id={self.id}, symbol={self.symbol}, action={self.action}, pnl={self.pnl})>'


class PerformanceMetric(Base):
    """Daily/periodic performance metrics"""

    __tablename__ = 'performance_metrics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, index=True)
    total_equity = Column(Float, nullable=False)
    daily_pnl = Column(Float, nullable=True)
    daily_pnl_percent = Column(Float, nullable=True)
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    avg_win = Column(Float, nullable=True)
    avg_loss = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    open_positions = Column(Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<PerformanceMetric(date={self.date}, equity={self.total_equity}, sharpe={self.sharpe_ratio})>'


class ParameterHistory(Base):
    """History of parameter changes (for audit trail)"""

    __tablename__ = 'parameter_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    parameter_name = Column(String(100), nullable=False, index=True)
    old_value = Column(String(500), nullable=True)
    new_value = Column(String(500), nullable=False)
    changed_by = Column(String(50), nullable=False)  # AI, User, System
    reason = Column(Text, nullable=True)
    mode = Column(String(20), nullable=True)  # autonomous, expert

    def __repr__(self):
        return f'<ParameterHistory(param={self.parameter_name}, changed_by={self.changed_by})>'


class OptimizationRun(Base):
    """Record of AI optimization runs"""

    __tablename__ = 'optimization_runs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    optimization_type = Column(String(50), nullable=False)  # parameter, strategy_selection, position_sizing
    parameters_before = Column(JSON, nullable=True)
    parameters_after = Column(JSON, nullable=True)
    score_before = Column(Float, nullable=True)
    score_after = Column(Float, nullable=True)
    improvement_pct = Column(Float, nullable=True)
    iteration_count = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)

    def __repr__(self):
        return f'<OptimizationRun(type={self.optimization_type}, improvement={self.improvement_pct}%)>'


class DatabaseManager:
    """
    Database manager for persisting trades and performance data
    """

    def __init__(self, db_url: str = 'sqlite:///data/trading_bot.db', logger: Optional[logging.Logger] = None):
        self.db_url = db_url
        self.logger = logger or logging.getLogger(__name__)

        # Create engine
        self.engine = create_engine(db_url, echo=False)

        # Create tables
        Base.metadata.create_all(self.engine)

        # Session factory
        self.SessionLocal = sessionmaker(bind=self.engine)

        self.logger.info(f'Database initialized: {db_url}')

    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()

    def record_trade(self, trade_data: dict) -> bool:
        """
        Record a trade to the database

        Args:
            trade_data: Dictionary with trade information

        Returns:
            True if successful
        """
        session = self.get_session()
        try:
            trade = Trade(
                timestamp=trade_data.get('timestamp', datetime.now()),
                symbol=trade_data['symbol'],
                action=trade_data['action'],
                quantity=trade_data['quantity'],
                entry_price=trade_data.get('entry_price', 0),
                exit_price=trade_data.get('exit_price'),
                stop_loss=trade_data.get('stop_loss'),
                take_profit=trade_data.get('take_profit'),
                pnl=trade_data.get('pnl'),
                pnl_percent=trade_data.get('pnl_percent'),
                strategy=trade_data.get('strategy'),
                order_id=trade_data.get('order_id'),
                commission=trade_data.get('commission'),
                status=trade_data.get('status', 'open'),
                exit_timestamp=trade_data.get('exit_timestamp'),
                hold_time_seconds=trade_data.get('hold_time_seconds'),
                notes=trade_data.get('notes'),
            )

            session.add(trade)
            session.commit()

            self.logger.debug(f'Trade recorded: {trade}')
            return True

        except Exception as e:
            session.rollback()
            self.logger.error(f'Error recording trade: {e}', exc_info=True)
            return False

        finally:
            session.close()

    def record_performance(self, perf_data: dict) -> bool:
        """Record daily performance metrics"""
        session = self.get_session()
        try:
            metric = PerformanceMetric(
                date=perf_data.get('date', datetime.now()),
                total_equity=perf_data['total_equity'],
                daily_pnl=perf_data.get('daily_pnl'),
                daily_pnl_percent=perf_data.get('daily_pnl_percent'),
                total_trades=perf_data.get('total_trades', 0),
                winning_trades=perf_data.get('winning_trades', 0),
                losing_trades=perf_data.get('losing_trades', 0),
                win_rate=perf_data.get('win_rate'),
                sharpe_ratio=perf_data.get('sharpe_ratio'),
                max_drawdown=perf_data.get('max_drawdown'),
                avg_win=perf_data.get('avg_win'),
                avg_loss=perf_data.get('avg_loss'),
                profit_factor=perf_data.get('profit_factor'),
                open_positions=perf_data.get('open_positions', 0),
            )

            session.add(metric)
            session.commit()

            self.logger.debug(f'Performance metric recorded: {metric}')
            return True

        except Exception as e:
            session.rollback()
            self.logger.error(f'Error recording performance: {e}', exc_info=True)
            return False

        finally:
            session.close()

    def record_parameter_change(self, change_data: dict) -> bool:
        """Record a parameter change"""
        session = self.get_session()
        try:
            param_change = ParameterHistory(
                timestamp=change_data.get('timestamp', datetime.now()),
                parameter_name=change_data['parameter_name'],
                old_value=str(change_data.get('old_value')),
                new_value=str(change_data['new_value']),
                changed_by=change_data.get('changed_by', 'System'),
                reason=change_data.get('reason'),
                mode=change_data.get('mode'),
            )

            session.add(param_change)
            session.commit()

            return True

        except Exception as e:
            session.rollback()
            self.logger.error(f'Error recording parameter change: {e}', exc_info=True)
            return False

        finally:
            session.close()

    def record_optimization(self, opt_data: dict) -> bool:
        """Record an optimization run"""
        session = self.get_session()
        try:
            opt_run = OptimizationRun(
                timestamp=opt_data.get('timestamp', datetime.now()),
                optimization_type=opt_data['optimization_type'],
                parameters_before=opt_data.get('parameters_before'),
                parameters_after=opt_data.get('parameters_after'),
                score_before=opt_data.get('score_before'),
                score_after=opt_data.get('score_after'),
                improvement_pct=opt_data.get('improvement_pct'),
                iteration_count=opt_data.get('iteration_count'),
                success=opt_data.get('success', True),
                error_message=opt_data.get('error_message'),
            )

            session.add(opt_run)
            session.commit()

            return True

        except Exception as e:
            session.rollback()
            self.logger.error(f'Error recording optimization: {e}', exc_info=True)
            return False

        finally:
            session.close()

    def get_recent_trades(self, limit: int = 100, symbol: Optional[str] = None) -> list:
        """Get recent trades"""
        session = self.get_session()
        try:
            query = session.query(Trade).order_by(Trade.timestamp.desc())

            if symbol:
                query = query.filter(Trade.symbol == symbol)

            trades = query.limit(limit).all()
            return [self._trade_to_dict(t) for t in trades]

        finally:
            session.close()

    def _trade_to_dict(self, trade: Trade) -> dict:
        """Convert Trade object to dictionary"""
        return {
            'id': trade.id,
            'timestamp': trade.timestamp,
            'symbol': trade.symbol,
            'action': trade.action,
            'quantity': trade.quantity,
            'entry_price': trade.entry_price,
            'exit_price': trade.exit_price,
            'pnl': trade.pnl,
            'pnl_percent': trade.pnl_percent,
            'strategy': trade.strategy,
            'status': trade.status,
        }
