from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mandate_research.news import NewsEvent
from mandate_research.signals import (
    Direction,
    PriceBar,
    breakout_volume_signal,
    mean_reversion_signal,
    momentum_signal,
    news_price_confirmation_signal,
    score_news,
)


def bars(closes: list[str], volumes: list[str] | None = None) -> list[PriceBar]:
    start = datetime(2026, 8, 26, 13, 30, tzinfo=timezone.utc)
    volumes = volumes or ["100"] * len(closes)
    return [
        PriceBar(
            timestamp=start + timedelta(minutes=index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("0.5"),
            low=Decimal(close) - Decimal("0.5"),
            close=Decimal(close),
            volume=Decimal(volume),
        )
        for index, (close, volume) in enumerate(zip(closes, volumes))
    ]


def test_momentum_detects_both_directions_and_dead_zone() -> None:
    assert momentum_signal(bars(["100", "101", "102"]), lookback=2).direction is Direction.BUY
    assert momentum_signal(bars(["100", "99", "98"]), lookback=2).direction is Direction.SELL
    assert momentum_signal(bars(["100", "100", "100"]), lookback=2).direction is Direction.FLAT


def test_mean_reversion_is_contrarian() -> None:
    assert mean_reversion_signal(
        bars(["100", "100", "100", "110"]), lookback=4, z_threshold=Decimal("1")
    ).direction is Direction.SELL
    assert mean_reversion_signal(
        bars(["100", "100", "100", "90"]), lookback=4, z_threshold=Decimal("1")
    ).direction is Direction.BUY


def test_breakout_requires_price_and_volume_confirmation() -> None:
    confirmed = breakout_volume_signal(
        bars(["100", "101", "102", "104"], ["100", "100", "100", "200"]),
        lookback=3,
        min_volume_ratio=Decimal("1.5"),
    )
    weak_volume = breakout_volume_signal(
        bars(["100", "101", "102", "104"], ["100", "100", "100", "110"]),
        lookback=3,
        min_volume_ratio=Decimal("1.5"),
    )
    assert confirmed.direction is Direction.BUY
    assert weak_volume.direction is Direction.FLAT


def test_news_score_respects_symbol_and_balances_words() -> None:
    event = NewsEvent(
        "alpaca",
        "1",
        datetime(2026, 8, 26, 13, 30, tzinfo=timezone.utc),
        "AAPL beats estimates",
        "Growth offsets one loss",
        ("AAPL",),
    )
    assert score_news(event, symbol="AAPL") > Decimal("0")
    assert score_news(event, symbol="MSFT") == Decimal("0")


def test_news_signal_requires_matching_price_direction() -> None:
    positive = NewsEvent(
        "alpaca",
        "1",
        datetime(2026, 8, 26, 13, 30, tzinfo=timezone.utc),
        "AAPL beats estimates and raises guidance",
        symbols=("AAPL",),
    )
    confirmed = news_price_confirmation_signal(
        bars(["100", "101", "102", "103"]), [positive], symbol="AAPL", lookback=3
    )
    contradicted = news_price_confirmation_signal(
        bars(["103", "102", "101", "100"]), [positive], symbol="AAPL", lookback=3
    )
    assert confirmed.direction is Direction.BUY
    assert contradicted.direction is Direction.FLAT


def test_future_news_is_excluded_from_signal() -> None:
    future = NewsEvent(
        "alpaca",
        "future",
        datetime(2026, 8, 26, 15, tzinfo=timezone.utc),
        "AAPL beats estimates and raises guidance",
        symbols=("AAPL",),
    )
    result = news_price_confirmation_signal(
        bars(["100", "101", "102", "103"]), [future], symbol="AAPL", lookback=3
    )
    assert result.direction is Direction.FLAT


def test_stale_news_is_excluded_from_signal() -> None:
    stale = NewsEvent(
        "alpaca",
        "stale",
        datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        "AAPL beats estimates and raises guidance",
        symbols=("AAPL",),
    )
    result = news_price_confirmation_signal(
        bars(["100", "101", "102", "103"]), [stale], symbol="AAPL", lookback=3
    )
    assert result.direction is Direction.FLAT
    assert result.rationale == "no recent news"


def test_invalid_signal_thresholds_are_rejected() -> None:
    import pytest

    history = bars(["100", "101", "102", "103"])
    with pytest.raises(ValueError, match="z_threshold"):
        mean_reversion_signal(history, lookback=3, z_threshold=Decimal("0"))
    with pytest.raises(ValueError, match="min_volume_ratio"):
        breakout_volume_signal(history, lookback=3, min_volume_ratio=Decimal("0"))
    with pytest.raises(ValueError, match="threshold_pct"):
        momentum_signal(history, lookback=3, threshold_pct=Decimal("-1"))
