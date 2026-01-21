"""
Realistic execution model for backtesting.

Provides more accurate transaction cost modeling than simple fixed slippage:
- Size-dependent slippage (larger orders incur more slippage)
- Volume-based fill constraints (can't fill more than X% of bar volume)
- Bid-ask spread simulation
- Market impact modeling (temporary + permanent)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import Bar
    from ..execution import Order

from .config import RealisticExecutionConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionCosts:
    """Breakdown of execution costs for a trade."""

    slippage: Decimal = field(default_factory=lambda: Decimal('0'))
    spread_cost: Decimal = field(default_factory=lambda: Decimal('0'))
    temporary_impact: Decimal = field(default_factory=lambda: Decimal('0'))
    permanent_impact: Decimal = field(default_factory=lambda: Decimal('0'))
    commission: Decimal = field(default_factory=lambda: Decimal('0'))

    @property
    def total(self) -> Decimal:
        """Total execution cost."""
        return self.slippage + self.spread_cost + self.temporary_impact + self.commission

    @property
    def total_impact_bps(self) -> float:
        """Total impact in basis points (requires price context)."""
        return 0.0  # Calculated externally


@dataclass
class FillResult:
    """Result of a fill calculation."""

    fill_price: Decimal
    fill_quantity: Decimal
    is_partial: bool
    costs: ExecutionCosts
    reason: str = ''


class RealisticExecutionModel:
    """
    Enhanced execution model with realistic costs and constraints.

    This model improves on the simplified PaperBroker execution by:
    1. Applying size-dependent slippage (larger orders = more slippage)
    2. Constraining fills to a fraction of bar volume
    3. Simulating bid-ask spread costs
    4. Modeling market impact (temporary and permanent)

    The formulas are based on industry-standard transaction cost models
    (e.g., Almgren-Chriss, square-root impact models).
    """

    def __init__(self, config: RealisticExecutionConfig | None = None) -> None:
        """
        Initialize the execution model.

        Args:
            config: Execution configuration. Uses defaults if not provided.
        """
        execution_config = config or RealisticExecutionConfig()
        execution_config.validate()
        self.config = execution_config

    def calculate_slippage(
        self,
        order_quantity: Decimal,
        bar: Bar,
        is_buy: bool,
    ) -> Decimal:
        """
        Calculate size-dependent slippage.

        Slippage formula:
            slippage_bps = base_slippage + (order_size / bar_volume) * size_impact_factor * 100

        The slippage increases with order size relative to bar volume,
        capped at max_slippage_bps.

        Args:
            order_quantity: Number of shares/contracts.
            bar: Current bar data.
            is_buy: Whether this is a buy order.

        Returns:
            Slippage amount as a price adjustment.
        """
        if bar.volume == 0:
            # Zero volume - use maximum slippage
            slippage_bps = Decimal(str(self.config.max_slippage_bps))
        else:
            # Calculate volume fraction
            volume_fraction = float(abs(order_quantity)) / bar.volume

            # Size-dependent slippage
            additional_bps = volume_fraction * self.config.size_impact_factor * 100

            total_bps = min(
                self.config.base_slippage_bps + additional_bps,
                self.config.max_slippage_bps,
            )
            slippage_bps = Decimal(str(total_bps))

        # Convert to price adjustment
        slippage_price = bar.close * slippage_bps / Decimal('10000')

        # Slippage is adverse (against the trader)
        return slippage_price if is_buy else -slippage_price

    def calculate_fill_quantity(
        self,
        order_quantity: Decimal,
        bar: Bar,
    ) -> tuple[Decimal, bool]:
        """
        Calculate fill quantity based on volume constraints.

        Prevents unrealistic fills that exceed available liquidity.
        Fill is limited to max_volume_participation of bar volume.

        Args:
            order_quantity: Requested order quantity.
            bar: Current bar data.

        Returns:
            Tuple of (fill_quantity, is_partial).
        """
        if not self.config.enable_volume_fill_limits:
            return (abs(order_quantity), False)

        # Skip low volume bars
        if bar.volume < self.config.min_bar_volume:
            logger.debug(f'Bar volume {bar.volume} below minimum {self.config.min_bar_volume}')
            return (Decimal('0'), True)

        # Calculate maximum fill based on volume participation
        max_fill = Decimal(str(bar.volume * self.config.max_volume_participation))
        requested = abs(order_quantity)

        if requested <= max_fill:
            return (requested, False)

        # Partial fill
        fill_qty = max_fill
        is_partial = True

        logger.debug(
            f'Volume constraint: requested {requested}, max fill {max_fill} '
            f'({self.config.max_volume_participation * 100}% of {bar.volume})'
        )

        return (fill_qty, is_partial)

    def estimate_spread(self, bar: Bar) -> Decimal:
        """
        Estimate bid-ask spread from bar data.

        For EOD/minute data without actual quotes, we estimate spread
        based on the bar's price range (high-low).

        Args:
            bar: Current bar data.

        Returns:
            Estimated spread (in price units, not percentage).
        """
        if not self.config.use_dynamic_spread:
            return bar.close * Decimal(str(self.config.spread_estimate_bps / 10000))

        # Dynamic spread based on bar range
        bar_range = bar.high - bar.low
        if bar_range == 0:
            # Flat bar - use default spread
            return bar.close * Decimal(str(self.config.spread_estimate_bps / 10000))

        # Spread is a fraction of the bar range
        spread = bar_range * Decimal(str(self.config.spread_volatility_factor))

        # Ensure minimum spread
        min_spread = bar.close * Decimal(str(self.config.spread_estimate_bps / 10000))
        return max(spread, min_spread)

    def calculate_spread_cost(
        self,
        order_quantity: Decimal,
        bar: Bar,
        is_buy: bool,
    ) -> Decimal:
        """
        Calculate the cost of crossing the bid-ask spread.

        When buying, you pay the ask (mid + half spread).
        When selling, you receive the bid (mid - half spread).

        Args:
            order_quantity: Number of shares/contracts.
            bar: Current bar data.
            is_buy: Whether this is a buy order.

        Returns:
            Spread cost (always positive).
        """
        spread = self.estimate_spread(bar)
        half_spread = spread / Decimal('2')

        # Cost per share is half the spread
        cost_per_share = half_spread

        return abs(order_quantity) * cost_per_share

    def calculate_market_impact(
        self,
        order_quantity: Decimal,
        bar: Bar,
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate temporary and permanent market impact.

        Uses a square-root model common in transaction cost analysis:
            impact = sigma * sqrt(Q/V) * factor

        Where:
            sigma = volatility (approximated from bar range)
            Q = order quantity
            V = bar volume

        Args:
            order_quantity: Number of shares/contracts.
            bar: Current bar data.

        Returns:
            Tuple of (temporary_impact, permanent_impact) in price units.
        """
        if not self.config.enable_market_impact or bar.volume == 0:
            return (Decimal('0'), Decimal('0'))

        # Volume fraction
        volume_fraction = float(abs(order_quantity)) / max(bar.volume, 1)

        # Square-root of volume fraction
        sqrt_fraction = math.sqrt(volume_fraction)

        # Volatility proxy from bar range
        bar_range = float(bar.high - bar.low)
        volatility = bar_range / float(bar.close) if bar.close > 0 else 0.01

        # Temporary impact (recovers after trade)
        temp_impact = float(bar.close) * volatility * sqrt_fraction * self.config.temporary_impact_factor

        # Permanent impact (persists in the market)
        perm_impact = float(bar.close) * volatility * sqrt_fraction * self.config.permanent_impact_factor

        return (Decimal(str(temp_impact)), Decimal(str(perm_impact)))

    def calculate_commission(self, order_quantity: Decimal) -> Decimal:
        """
        Calculate commission for a trade.

        Args:
            order_quantity: Number of shares/contracts.

        Returns:
            Commission amount.
        """
        commission = abs(order_quantity) * self.config.commission_per_share
        return max(commission, self.config.min_commission)

    def calculate_fill(
        self,
        order: Order,
        bar: Bar,
    ) -> FillResult | None:
        """
        Calculate complete fill result for an order.

        This is the main method that combines all execution cost components:
        1. Volume-constrained fill quantity
        2. Size-dependent slippage
        3. Bid-ask spread cost
        4. Market impact
        5. Commission

        Args:
            order: Order to fill.
            bar: Current bar data.

        Returns:
            FillResult if order can be filled, None otherwise.
        """
        from ..execution import OrderSide, OrderType

        # Check symbol match
        if order.symbol != bar.symbol:
            return None

        is_buy = order.side == OrderSide.BUY

        # Determine base price based on order type
        if order.order_type == OrderType.MARKET:
            base_price = bar.close
        elif order.order_type == OrderType.LIMIT:
            # Check if limit price would fill
            if is_buy:
                if order.limit_price is None or bar.low > order.limit_price:
                    return None  # Would not fill
                base_price = min(bar.close, order.limit_price)
            else:
                if order.limit_price is None or bar.high < order.limit_price:
                    return None  # Would not fill
                base_price = max(bar.close, order.limit_price)
        elif order.order_type == OrderType.STOP:
            # Check if stop triggered
            if is_buy:
                if order.stop_price is None or bar.high < order.stop_price:
                    return None  # Not triggered
                base_price = bar.close
            else:
                if order.stop_price is None or bar.low > order.stop_price:
                    return None  # Not triggered
                base_price = bar.close
        else:
            base_price = bar.close

        # Calculate fill quantity (may be partial due to volume constraints)
        remaining = order.remaining_quantity if order.remaining_quantity is not None else order.quantity
        fill_qty, is_partial = self.calculate_fill_quantity(remaining, bar)

        if fill_qty <= 0:
            return None  # Cannot fill

        # Calculate execution costs
        slippage = self.calculate_slippage(fill_qty, bar, is_buy)
        spread_cost = self.calculate_spread_cost(fill_qty, bar, is_buy)
        temp_impact, perm_impact = self.calculate_market_impact(fill_qty, bar)
        commission = self.calculate_commission(fill_qty)

        # Calculate final fill price
        # Slippage and half the impact are applied to price
        price_impact = slippage
        if is_buy:
            price_impact += temp_impact / Decimal('2')  # Half of temp impact
        else:
            price_impact -= temp_impact / Decimal('2')

        fill_price = base_price + price_impact

        costs = ExecutionCosts(
            slippage=abs(slippage * fill_qty),
            spread_cost=spread_cost,
            temporary_impact=abs(temp_impact * fill_qty),
            permanent_impact=abs(perm_impact * fill_qty),
            commission=commission,
        )

        return FillResult(
            fill_price=fill_price,
            fill_quantity=fill_qty,
            is_partial=is_partial,
            costs=costs,
            reason='volume_constraint' if is_partial else 'full_fill',
        )

    def simulate_execution(
        self,
        order: Order,
        bars: list[Bar],
    ) -> list[FillResult]:
        """
        Simulate order execution across multiple bars.

        For orders that cannot be fully filled in one bar (due to volume
        constraints), this method simulates filling across subsequent bars.

        Args:
            order: Order to execute.
            bars: List of bars to attempt execution.

        Returns:
            List of FillResult for each partial fill.
        """
        results: list[FillResult] = []
        remaining = order.quantity

        for bar in bars:
            if remaining <= 0:
                break

            # Create a temporary order with remaining quantity
            from ..execution import Order as OrderClass

            temp_order = OrderClass(
                symbol=order.symbol,
                quantity=remaining,
                side=order.side,
                order_type=order.order_type,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
            )

            result = self.calculate_fill(temp_order, bar)
            if result:
                results.append(result)
                remaining -= result.fill_quantity

        return results

    def get_cost_breakdown(
        self,
        fills: list[FillResult],
    ) -> dict[str, Decimal]:
        """
        Get total cost breakdown across multiple fills.

        Args:
            fills: List of FillResult objects.

        Returns:
            Dictionary with total costs by category.
        """
        breakdown = {
            'slippage': Decimal('0'),
            'spread_cost': Decimal('0'),
            'temporary_impact': Decimal('0'),
            'permanent_impact': Decimal('0'),
            'commission': Decimal('0'),
            'total': Decimal('0'),
        }

        for fill in fills:
            breakdown['slippage'] += fill.costs.slippage
            breakdown['spread_cost'] += fill.costs.spread_cost
            breakdown['temporary_impact'] += fill.costs.temporary_impact
            breakdown['permanent_impact'] += fill.costs.permanent_impact
            breakdown['commission'] += fill.costs.commission

        breakdown['total'] = (
            breakdown['slippage'] + breakdown['spread_cost'] + breakdown['temporary_impact'] + breakdown['commission']
        )

        return breakdown
