from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mandate_research.features import (
    macd_histogram,
    realized_volatility,
    relative_strength_index,
    relative_strength_vs_benchmark,
    top_of_book_imbalance,
)
from mandate_research.signals import PriceBar


def _bars(values: list[int]) -> list[PriceBar]:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [
        PriceBar(
            start + timedelta(hours=index), Decimal(value), Decimal(value + 1),
            Decimal(value - 1), Decimal(value), Decimal("1000"),
        )
        for index, value in enumerate(values)
    ]


def test_feature_factory_is_bounded_and_deterministic() -> None:
    rising = _bars(list(range(100, 145)))
    benchmark = _bars(list(range(100, 145, 1)))
    assert relative_strength_index(rising) == Decimal("100")
    assert macd_histogram(rising).is_finite()
    assert realized_volatility(rising) > 0
    assert relative_strength_vs_benchmark(rising, benchmark) == 0
    assert top_of_book_imbalance(Decimal("300"), Decimal("100")) == Decimal("0.5")


def test_quote_imbalance_handles_empty_book() -> None:
    assert top_of_book_imbalance(Decimal("0"), Decimal("0")) == 0
