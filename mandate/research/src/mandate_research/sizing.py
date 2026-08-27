from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Any, Sequence

from mandate_research.signals import PriceBar


ZERO = Decimal("0")
ONE = Decimal("1")


def average_true_range(bars: Sequence[PriceBar], *, period: int = 14) -> Decimal:
    """Return Wilder-compatible simple ATR over the latest complete true ranges."""
    if period < 1:
        raise ValueError("ATR period must be positive")
    if len(bars) <= period:
        raise ValueError(f"ATR{period} requires at least {period + 1} bars")
    ranges = []
    for previous, current in zip(bars[-period - 1 : -1], bars[-period:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(ranges, ZERO) / Decimal(period)


def calculate_position_size(
    *,
    equity: Decimal,
    price: Decimal,
    atr14: Decimal,
    signal_strength: Decimal,
    risk_budget_pct: Decimal = Decimal("0.25"),
    atr_multiplier: Decimal = Decimal("2"),
    position_headroom_pct: Decimal,
    gross_headroom_pct: Decimal,
) -> dict[str, Any]:
    """Size whole shares by ATR risk, then cap notional by both mandate headrooms."""
    if equity <= ZERO or price <= ZERO or atr14 <= ZERO:
        raise ValueError("equity, price, and ATR must be positive")
    if not ZERO <= signal_strength <= ONE:
        raise ValueError("signal_strength must be between 0 and 1")
    if risk_budget_pct <= ZERO or atr_multiplier <= ZERO:
        raise ValueError("risk budget and ATR multiplier must be positive")
    risk_cash = equity * risk_budget_pct / Decimal("100") * signal_strength
    stop_distance = atr14 * atr_multiplier
    risk_qty = (risk_cash / stop_distance).to_integral_value(rounding=ROUND_FLOOR)
    headroom_pct = max(ZERO, min(position_headroom_pct, gross_headroom_pct))
    headroom_notional = equity * headroom_pct / Decimal("100")
    headroom_qty = (headroom_notional / price).to_integral_value(rounding=ROUND_FLOOR)
    quantity = max(ZERO, min(risk_qty, headroom_qty))
    binding_constraint = "mandate_headroom" if headroom_qty < risk_qty else "atr_risk_budget"
    if signal_strength == ZERO:
        binding_constraint = "flat_signal"
    elif headroom_qty == ZERO:
        binding_constraint = "no_mandate_headroom"
    return {
        "qty": int(quantity),
        "risk_cash": str(risk_cash.quantize(Decimal("0.01"))),
        "stop_distance": str(stop_distance.quantize(Decimal("0.0001"))),
        "risk_qty": int(risk_qty),
        "headroom_qty": int(headroom_qty),
        "headroom_notional": str(headroom_notional.quantize(Decimal("0.01"))),
        "binding_constraint": binding_constraint,
    }
