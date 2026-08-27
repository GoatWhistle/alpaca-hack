from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from mandate_guard.mandate import Mandate, load_mandate


def valid_data() -> dict:
    return {
        "name": "test",
        "universe": [" aapl ", "MSFT"],
        "instruments": ["equity"],
        "order_types": ["limit"],
        "session": "regular_hours_only",
        "limits": {
            "max_position_pct": "10",
            "max_gross_exposure_pct": "60",
            "max_daily_loss_pct": "2",
            "max_orders_per_day": 20,
        },
        "expires": "2099-01-01T00:00:00Z",
    }


def test_normalizes_symbols() -> None:
    assert Mandate.model_validate(valid_data()).universe == ["AAPL", "MSFT"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("universe", []), ("universe", ["AAPL", "aapl"]), ("order_types", ["limit", "limit"])],
)
def test_rejects_empty_or_duplicate_lists(field: str, value: list[str]) -> None:
    data = valid_data()
    data[field] = value
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


@pytest.mark.parametrize("percentage", ["-0.01", "100.01"])
def test_rejects_percentage_outside_range(percentage: str) -> None:
    data = valid_data()
    data["limits"]["max_daily_loss_pct"] = percentage
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


def test_rejects_position_limit_above_gross_limit() -> None:
    data = valid_data()
    data["limits"]["max_position_pct"] = "61"
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


@pytest.mark.parametrize("expires", ["2020-01-01T00:00:00Z", "2099-01-01T00:00:00"])
def test_rejects_past_or_naive_expiry(expires: str) -> None:
    data = deepcopy(valid_data())
    data["expires"] = expires
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


def test_rejects_unknown_fields() -> None:
    data = valid_data()
    data["allow_live_trading"] = True
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


@pytest.mark.parametrize("unsupported", ["stop", "stop_limit", "trailing_stop"])
def test_rejects_order_types_without_complete_submission_contract(unsupported: str) -> None:
    data = valid_data()
    data["order_types"] = [unsupported]
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


@pytest.mark.parametrize(
    "directive",
    [
        {
            "when": "any_breach_requiring_override > 0",
            "then": "park_new_orders",
            "reason": "not observable before evaluation",
        },
        {
            "when": "daily_loss_pct >= 1",
            "then": "halve_order",
            "reason": "unsupported action",
        },
    ],
)
def test_rejects_unenforceable_predecisions(directive: dict[str, str]) -> None:
    data = valid_data()
    data["predecided"] = [directive]
    with pytest.raises(ValidationError):
        Mandate.model_validate(data)


def test_repository_example_mandate_loads() -> None:
    path = Path(__file__).parents[2] / "mandates" / "example.yaml"
    mandate = load_mandate(path)
    assert len(mandate.predecided) == 2


def test_risk_reducing_market_close_requires_explicit_opt_in() -> None:
    mandate = Mandate.model_validate(valid_data())
    assert mandate.allow_risk_reducing_market_close is False


def test_short_positions_require_explicit_opt_in() -> None:
    mandate = Mandate.model_validate(valid_data())
    assert mandate.allow_short_positions is False
