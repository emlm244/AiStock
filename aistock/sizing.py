"""Position sizing helpers."""

from __future__ import annotations

from decimal import Decimal

from .config import RiskLimits


def target_quantity(
    target_weight: Decimal,
    equity: Decimal,
    price: Decimal,
    risk_limits: RiskLimits,
    confidence: float,
) -> Decimal:
    if price == 0:
        return Decimal("0")
    desired_notional = target_weight * equity * Decimal(str(confidence))
    qty = desired_notional / price
    # Cap by per-trade risk if configured
    per_trade_cap = equity * Decimal(str(risk_limits.per_trade_risk_pct))
    if per_trade_cap > 0 and abs(qty * price) > per_trade_cap:
        qty = (per_trade_cap / price) * (1 if qty >= 0 else -1)
    return qty
