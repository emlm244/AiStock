#!/usr/bin/env python3
"""
Sample Backtest Runner

Creates a sample backtest using the corrected TradingEngine to demonstrate
the proper P&L calculation and serve as a reference implementation.

This script:
1. Generates synthetic market data
2. Runs a simple strategy (buy-hold-sell)
3. Outputs results with correct P&L calculation
4. Can be used to validate the P&L fix
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aistock.engine import TradingEngine  # noqa: E402


class SampleBar(TypedDict):
    timestamp: datetime
    price: Decimal


class SampleTrade(TypedDict):
    timestamp: str
    symbol: str
    quantity: float
    price: float
    realised_pnl: float


class SampleValidation(TypedDict):
    expected_pnl: float
    actual_pnl: float
    match: bool


class SampleBacktestResult(TypedDict):
    timestamp: str
    symbols: list[str]
    initial_capital: float
    final_equity: float
    total_return: float
    num_trades: int
    realized_pnl: float
    trades: list[SampleTrade]
    validation: SampleValidation


def generate_sample_bars() -> list[SampleBar]:
    """Generate sample price data."""
    start_date = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)

    bars: list[SampleBar] = []
    price = Decimal('100.00')

    for i in range(10):
        timestamp = start_date + timedelta(minutes=i)

        # Simple price pattern: goes up then down
        if i < 5:
            price += Decimal('2.00')  # Price rises to 110
        else:
            price -= Decimal('1.00')  # Price falls to 105

        bars.append({'timestamp': timestamp, 'price': price})

    return bars


def run_sample_backtest() -> SampleBacktestResult:
    """Run sample backtest with corrected P&L calculation."""
    print('Running sample backtest with corrected TradingEngine...')

    # Initialize engine
    engine = TradingEngine(initial_cash=Decimal('100000'))

    # Generate data
    bars = generate_sample_bars()

    # Execute simple strategy: buy at start, sell at end
    print(f'\nInitial capital: ${engine.cash}')

    # Bar 0: Buy 100 shares at $102
    engine.execute_trade(
        symbol='AAPL',
        quantity=Decimal('100'),
        price=bars[0]['price'],
        timestamp=bars[0]['timestamp'],
    )
    print(f'\n{bars[0]["timestamp"]} - BUY 100 AAPL @ ${bars[0]["price"]} (Cost basis: ${engine.cost_basis["AAPL"]})')

    # Bar 4: Sell 50 shares at $110 (profit = (110-102)*50 = $400)
    trade2 = engine.execute_trade(
        symbol='AAPL',
        quantity=Decimal('-50'),
        price=bars[4]['price'],
        timestamp=bars[4]['timestamp'],
    )
    print(
        f'{bars[4]["timestamp"]} - SELL 50 AAPL @ ${bars[4]["price"]} '
        f'-> P&L: ${trade2.realised_pnl} (Cost basis still: ${engine.cost_basis["AAPL"]})'
    )

    # Bar 9: Sell remaining 50 shares at $105 (profit = (105-102)*50 = $150)
    trade3 = engine.execute_trade(
        symbol='AAPL',
        quantity=Decimal('-50'),
        price=bars[9]['price'],
        timestamp=bars[9]['timestamp'],
    )
    print(
        f'{bars[9]["timestamp"]} - SELL 50 AAPL @ ${bars[9]["price"]} -> P&L: ${trade3.realised_pnl} (Position closed)'
    )

    # Calculate total P&L
    total_pnl = sum((t.realised_pnl for t in engine.trades if t.realised_pnl != 0), Decimal('0'))
    expected_pnl = Decimal('400') + Decimal('150')  # $550

    print(f'\n{"=" * 60}')
    print('BACKTEST RESULTS:')
    print(f'{"=" * 60}')
    print(f'Total trades: {len(engine.trades)}')
    print(f'Total realized P&L: ${total_pnl}')
    print(f'Expected P&L: ${expected_pnl}')
    print(f'Match: {"[OK] CORRECT" if total_pnl == expected_pnl else "[ERROR] MISMATCH"}')
    print(f'Final cash: ${engine.cash}')
    print(f'Total return: {((engine.cash - engine.initial_cash) / engine.initial_cash * 100):.2f}%')

    # Create result JSON
    result: SampleBacktestResult = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbols': ['AAPL'],
        'initial_capital': float(engine.initial_cash),
        'final_equity': float(engine.cash),
        'total_return': float((engine.cash - engine.initial_cash) / engine.initial_cash),
        'num_trades': len(engine.trades),
        'realized_pnl': float(total_pnl),
        'trades': [
            {
                'timestamp': t.timestamp.isoformat(),
                'symbol': t.symbol,
                'quantity': float(t.quantity),
                'price': float(t.price),
                'realised_pnl': float(t.realised_pnl),
            }
            for t in engine.trades
        ],
        'validation': {
            'expected_pnl': float(expected_pnl),
            'actual_pnl': float(total_pnl),
            'match': total_pnl == expected_pnl,
        },
    }

    return result


def main() -> int:
    # Run backtest
    result = run_sample_backtest()

    # Save result
    output_dir = Path('backtest_results')
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'sample_backtest_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f'\nResult saved to: {output_file}')

    # Validation
    if result['validation']['match']:
        print('\n[OK] P&L calculation is CORRECT!')
        return 0
    else:
        print(
            '\n[ERROR] P&L calculation mismatch! '
            f'Expected ${result["validation"]["expected_pnl"]}, '
            f'got ${result["validation"]["actual_pnl"]}'
        )
        return 1


if __name__ == '__main__':
    exit(main())
