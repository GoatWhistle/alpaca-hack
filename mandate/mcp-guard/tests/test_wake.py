from decimal import Decimal

import pytest

from mandate_guard.wake import evaluate_wake_conditions, parse_wake_condition


def test_three_token_condition_parses_and_evaluates() -> None:
    condition = parse_wake_condition("daily_loss_pct > 1.2")
    assert condition.evaluate(Decimal("1.21")) is True
    assert condition.evaluate(Decimal("1.2")) is False


@pytest.mark.parametrize(
    "expression",
    [
        "daily_loss_pct >",
        "unknown_metric > 1",
        "daily_loss_pct != 1",
        "daily_loss_pct > NaN",
    ],
)
def test_invalid_condition_is_rejected(expression: str) -> None:
    with pytest.raises(ValueError):
        parse_wake_condition(expression)


def test_only_available_triggered_metrics_are_returned() -> None:
    triggered = evaluate_wake_conditions(
        ["daily_loss_pct > 1.2", "single_symbol_move_pct > 5"],
        {"daily_loss_pct": Decimal("1.3")},
    )
    assert triggered == [
        {
            "expression": "daily_loss_pct > 1.2",
            "metric": "daily_loss_pct",
            "value": "1.3",
            "threshold": "1.2",
        }
    ]
