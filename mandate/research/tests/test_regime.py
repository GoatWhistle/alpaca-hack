from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mandate_research.regime import classify_market_regime, weighted_ensemble
from mandate_research.signals import Direction, PriceBar, TradeSignal


def _bars(closes: list[Decimal]) -> list[PriceBar]:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [
        PriceBar(start + timedelta(hours=index), close, close + 1, close - 1, close, Decimal("1000"))
        for index, close in enumerate(closes)
    ]


def test_regime_distinguishes_trend_and_range() -> None:
    trend = classify_market_regime(_bars([Decimal(100 + index) for index in range(30)]))
    ranged = classify_market_regime(_bars([Decimal("100") + Decimal(index % 2) for index in range(30)]))
    assert trend["regime"] == "trend"
    assert trend["direction"] == "up"
    assert trend["strategy_weights"]["momentum"] == "0.45"
    assert trend["risk_off"] is False
    assert ranged["regime"] == "range"
    assert ranged["strategy_weights"]["mean_reversion"] == "0.45"


def test_weighted_ensemble_changes_with_regime_weights() -> None:
    at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    signals = {
        "momentum": TradeSignal(Direction.BUY, Decimal("1"), "m", at),
        "mean_reversion": TradeSignal(Direction.SELL, Decimal("1"), "r", at),
        "breakout_volume": TradeSignal(Direction.FLAT, Decimal("0"), "b", at),
        "news_price_confirmation": TradeSignal(Direction.FLAT, Decimal("0"), "n", at),
    }
    trend = weighted_ensemble(signals, {"momentum": "0.7", "mean_reversion": "0.1"})
    ranged = weighted_ensemble(signals, {"momentum": "0.1", "mean_reversion": "0.7"})
    assert trend.direction is Direction.BUY
    assert ranged.direction is Direction.SELL
