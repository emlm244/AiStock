"""
Transaction cost sensitivity analysis for backtest robustness.

P1 Enhancement: Stress test strategy performance across commission/slippage ranges.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import BacktestConfig, EngineConfig
from .data import Bar
from .engine import BacktestRunner


@dataclass
class SensitivityPoint:
    """Single point in sensitivity grid."""
    commission: float
    slippage_bps: float
    total_return: Decimal
    sharpe: float
    sortino: float
    max_drawdown: Decimal
    total_trades: int
    win_rate: float


@dataclass
class SensitivityAnalysis:
    """Results of transaction cost sensitivity sweep."""
    grid: list[SensitivityPoint]
    base_commission: float
    base_slippage_bps: float

    def summary_stats(self) -> dict[str, float]:
        """Compute stability metrics across grid."""
        returns = [float(pt.total_return) for pt in self.grid]
        sharpes = [pt.sharpe for pt in self.grid]

        return {
            "return_mean": sum(returns) / len(returns) if returns else 0.0,
            "return_std": (
                (sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / len(returns)) ** 0.5
                if returns
                else 0.0
            ),
            "return_min": min(returns) if returns else 0.0,
            "return_max": max(returns) if returns else 0.0,
            "sharpe_mean": sum(sharpes) / len(sharpes) if sharpes else 0.0,
            "sharpe_std": (
                (sum((s - sum(sharpes) / len(sharpes)) ** 2 for s in sharpes) / len(sharpes)) ** 0.5
                if sharpes
                else 0.0
            ),
            "sharpe_min": min(sharpes) if sharpes else 0.0,
            "sharpe_max": max(sharpes) if sharpes else 0.0,
        }

    def is_robust(self, sharpe_threshold: float = 0.5, return_threshold: float = 0.0) -> bool:
        """
        Check if strategy is robust to transaction costs.

        Returns True if ALL grid points exceed thresholds.
        """
        for point in self.grid:
            if point.sharpe < sharpe_threshold:
                return False
            if float(point.total_return) < return_threshold:
                return False
        return True


def run_sensitivity_analysis(
    config: BacktestConfig,
    override_data: dict[str, list[Bar]] | None = None,
    commission_range: tuple[float, float, float] = (0.5, 5.0, 1.0),
    slippage_range: tuple[float, float, float] = (2.0, 20.0, 5.0),
) -> SensitivityAnalysis:
    """
    Run backtest across transaction cost grid.

    P1 Enhancement: Comprehensive sensitivity analysis.

    Args:
        config: Base backtest configuration
        override_data: Optional pre-loaded data (avoids repeated CSV reads)
        commission_range: (min, max, step) for commission per trade
        slippage_range: (min, max, step) for slippage in basis points

    Returns:
        SensitivityAnalysis with grid results and summary stats

    Example:
        >>> analysis = run_sensitivity_analysis(
        ...     config,
        ...     commission_range=(0.5, 5.0, 1.0),  # $0.50 to $5.00 by $1.00
        ...     slippage_range=(2.0, 20.0, 5.0),   # 2bps to 20bps by 5bps
        ... )
        >>> print(analysis.summary_stats())
        >>> assert analysis.is_robust(sharpe_threshold=0.5)
    """
    comm_min, comm_max, comm_step = commission_range
    slip_min, slip_max, slip_step = slippage_range

    grid: list[SensitivityPoint] = []
    base_commission = config.engine.commission_per_trade
    base_slippage_bps = config.engine.slippage_bps

    commission = comm_min
    while commission <= comm_max + 1e-9:
        slippage = slip_min
        while slippage <= slip_max + 1e-9:
            # Create modified config
            test_config = BacktestConfig(
                data=config.data,
                engine=EngineConfig(
                    risk=config.engine.risk,
                    strategy=config.engine.strategy,
                    data_quality=config.engine.data_quality,
                    initial_equity=config.engine.initial_equity,
                    commission_per_trade=commission,  # Vary
                    slippage_bps=slippage,  # Vary
                    reporting_currency=config.engine.reporting_currency,
                    clock_timezone=config.engine.clock_timezone,
                ),
                execution=config.execution,
                broker=config.broker,
                run_mode=config.run_mode,
            )

            # Run backtest
            runner = BacktestRunner(test_config)
            result = runner.run(override_data=override_data)

            # Record point
            grid.append(
                SensitivityPoint(
                    commission=commission,
                    slippage_bps=slippage,
                    total_return=result.total_return,
                    sharpe=result.metrics.get("sharpe", 0.0),
                    sortino=result.metrics.get("sortino", 0.0),
                    max_drawdown=result.max_drawdown,
                    total_trades=result.metrics.get("total_trades", 0),
                    win_rate=result.win_rate,
                )
            )

            slippage += slip_step
        commission += comm_step

    return SensitivityAnalysis(
        grid=grid,
        base_commission=base_commission,
        base_slippage_bps=base_slippage_bps,
    )


def print_sensitivity_report(analysis: SensitivityAnalysis) -> None:
    """
    Print formatted sensitivity analysis report.

    Example output:
        Transaction Cost Sensitivity Analysis
        =====================================
        Base: Commission=$1.00, Slippage=5.0bps

        Grid Results (12 scenarios):
        Comm=$0.50, Slip=2bps: Return=5.2%, Sharpe=1.23
        ...

        Summary Statistics:
        Return: mean=3.1%, std=1.2%, min=1.5%, max=5.2%
        Sharpe: mean=0.89, std=0.31, min=0.42, max=1.23
        Robust: YES (all points > 0.5 Sharpe, > 0% return)
    """
    print("Transaction Cost Sensitivity Analysis")
    print("=" * 50)
    print(f"Base: Commission=${analysis.base_commission:.2f}, Slippage={analysis.base_slippage_bps:.1f}bps\n")

    print(f"Grid Results ({len(analysis.grid)} scenarios):")
    for pt in analysis.grid:
        print(
            f"  Comm=${pt.commission:.2f}, Slip={pt.slippage_bps:.0f}bps: "
            f"Return={float(pt.total_return):>6.2%}, Sharpe={pt.sharpe:>5.2f}, "
            f"Trades={pt.total_trades}, WinRate={pt.win_rate:>5.1%}"
        )

    stats = analysis.summary_stats()
    print("\nSummary Statistics:")
    print(f"  Return: mean={stats['return_mean']:>5.2%}, std={stats['return_std']:>5.2%}, "
          f"min={stats['return_min']:>5.2%}, max={stats['return_max']:>5.2%}")
    print(f"  Sharpe: mean={stats['sharpe_mean']:>5.2f}, std={stats['sharpe_std']:>5.2f}, "
          f"min={stats['sharpe_min']:>5.2f}, max={stats['sharpe_max']:>5.2f}")

    robust = analysis.is_robust(sharpe_threshold=0.5, return_threshold=0.0)
    print(f"\nRobust: {'YES' if robust else 'NO'} (threshold: Sharpe>0.5, Return>0%)")
