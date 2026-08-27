from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mandate_research.signals import PriceBar
from mandate_research.sizing import average_true_range, calculate_position_size


def _bars() -> list[PriceBar]:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [
        PriceBar(start + timedelta(hours=index), Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"), Decimal("1000"))
        for index in range(15)
    ]


def test_atr_and_position_size_are_deterministic_and_headroom_bounded() -> None:
    atr = average_true_range(_bars())
    assert atr == Decimal("3")
    result = calculate_position_size(
        equity=Decimal("100000"), price=Decimal("100"), atr14=atr,
        signal_strength=Decimal("0.8"), risk_budget_pct=Decimal("0.5"),
        atr_multiplier=Decimal("2"), position_headroom_pct=Decimal("10"),
        gross_headroom_pct=Decimal("4"),
    )
    assert result["risk_qty"] == 66
    assert result["headroom_qty"] == 40
    assert result["qty"] == 40
    assert result["binding_constraint"] == "mandate_headroom"


def test_position_size_fails_closed_on_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        calculate_position_size(
            equity=Decimal("100"), price=Decimal("0"), atr14=Decimal("1"),
            signal_strength=Decimal("1"), position_headroom_pct=Decimal("1"),
            gross_headroom_pct=Decimal("1"),
        )
