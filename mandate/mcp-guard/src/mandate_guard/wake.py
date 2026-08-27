from __future__ import annotations

import operator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Sequence


KNOWN_METRICS = {
    "daily_loss_pct",
    "single_symbol_move_pct",
    "any_breach_requiring_override",
}
OPERATORS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


@dataclass(frozen=True)
class WakeCondition:
    metric: str
    operator: str
    threshold: Decimal

    def evaluate(self, value: Decimal) -> bool:
        return OPERATORS[self.operator](value, self.threshold)


def parse_wake_condition(expression: str) -> WakeCondition:
    parts = expression.split()
    if len(parts) != 3:
        raise ValueError("wake condition must be: metric operator number")
    metric, comparison, raw_threshold = parts
    if metric not in KNOWN_METRICS:
        raise ValueError(f"unknown wake metric: {metric}")
    if comparison not in OPERATORS:
        raise ValueError(f"unsupported wake operator: {comparison}")
    try:
        threshold = Decimal(raw_threshold)
    except InvalidOperation as exc:
        raise ValueError("wake threshold must be a decimal number") from exc
    if not threshold.is_finite():
        raise ValueError("wake threshold must be finite")
    return WakeCondition(metric, comparison, threshold)


def evaluate_wake_conditions(
    expressions: Sequence[str], metrics: Mapping[str, Decimal]
) -> list[dict[str, str]]:
    triggered: list[dict[str, str]] = []
    for expression in expressions:
        condition = parse_wake_condition(expression)
        value = metrics.get(condition.metric)
        if value is not None and condition.evaluate(value):
            triggered.append(
                {
                    "expression": expression,
                    "metric": condition.metric,
                    "value": str(value),
                    "threshold": str(condition.threshold),
                }
            )
    return triggered
