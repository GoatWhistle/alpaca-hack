from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from mandate_research.backtest import compare_strategies
from mandate_research.news import NewsEvent, deduplicate
from mandate_research.regime import classify_market_regime, weighted_ensemble
from mandate_research.signals import (
    PriceBar,
    breakout_volume_signal,
    mean_reversion_signal,
    momentum_signal,
    news_price_confirmation_signal,
)
from mandate_research.sizing import average_true_range


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def _bar(item: dict[str, Any]) -> PriceBar:
    return PriceBar(
        timestamp=_datetime(item["timestamp"]),
        open=_decimal(item["open"]),
        high=_decimal(item["high"]),
        low=_decimal(item["low"]),
        close=_decimal(item["close"]),
        volume=_decimal(item["volume"]),
    )


def _news(item: dict[str, Any]) -> NewsEvent:
    symbols = tuple(
        normalized
        for symbol in item.get("symbols", [])
        if (normalized := str(symbol).strip().upper())
    )
    return NewsEvent(
        source=str(item["source"]),
        external_id=str(item["external_id"]),
        published_at=_datetime(item["published_at"]),
        headline=str(item["headline"]),
        summary=str(item.get("summary", "")),
        symbols=symbols,
        url=str(item["url"]) if item.get("url") else None,
    )


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload["symbol"]).strip().upper()
    if not symbol:
        raise ValueError("symbol cannot be blank")
    bars = sorted((_bar(item) for item in payload["bars"]), key=lambda bar: bar.timestamp)
    if len(bars) < 22:
        raise ValueError("at least 22 chronological bars are required")
    cutoff = bars[-1].timestamp
    all_eligible_events = [
        event
        for event in (_news(item) for item in payload.get("news", []))
        if event.published_at <= cutoff
    ]
    news_max_age_hours = _decimal(payload.get("news_max_age_hours", "24"))
    if not Decimal("0") < news_max_age_hours <= Decimal("8760"):
        raise ValueError("news_max_age_hours must be between 0 and 8760")
    max_news_age = timedelta(
        microseconds=int(news_max_age_hours * Decimal("3600000000"))
    )
    current_events = deduplicate(
        event for event in all_eligible_events if event.published_at >= cutoff - max_news_age
    )

    strategies: dict[str, tuple[Any, int]] = {
        "momentum": (lambda window: momentum_signal(window, lookback=5), 6),
        "mean_reversion": (lambda window: mean_reversion_signal(window, lookback=20), 20),
        "breakout_volume": (lambda window: breakout_volume_signal(window, lookback=20), 21),
        "news_price_confirmation": (
            lambda window: news_price_confirmation_signal(
                window,
                all_eligible_events,
                symbol=symbol,
                lookback=3,
                max_news_age=max_news_age,
            ),
            4,
        ),
    }
    def regime_ensemble(window: list[PriceBar]) -> Any:
        component_signals = {
            name: strategy(window)
            for name, (strategy, _warmup) in strategies.items()
            if name != "regime_ensemble"
        }
        regime = classify_market_regime(window)
        return weighted_ensemble(component_signals, regime["strategy_weights"])

    strategies["regime_ensemble"] = (regime_ensemble, 21)
    fee_bps = _decimal(payload.get("fee_bps", "1"))
    slippage_bps = _decimal(payload.get("slippage_bps", "1"))
    metrics = compare_strategies(
        bars, strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
        liquidate_at_end=True,
    )
    split = max(22, int(len(bars) * 2 / 3))
    holdout: dict[str, Any] = {"status": "insufficient_history"}
    if split < len(bars):
        train_metrics = compare_strategies(
            bars[:split], strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
            liquidate_at_end=True,
        )
        test_metrics = compare_strategies(
            bars, strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
            evaluation_start=split, liquidate_at_end=True,
        )
        holdout = {
            "status": "ok",
            "train_bars": split,
            "test_bars": len(bars) - split,
            "parameters_frozen": True,
            "train": {
                name: {key: str(value) for key, value in asdict(result).items()}
                for name, result in train_metrics.items()
            },
            "test": {
                name: {key: str(value) for key, value in asdict(result).items()}
                for name, result in test_metrics.items()
            },
        }
    current = {name: strategy(bars) for name, (strategy, _warmup) in strategies.items()}
    regime = classify_market_regime(bars)
    atr14 = average_true_range(bars)
    return {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "news_events_used": len(current_events),
        "news_max_age_hours": str(news_max_age_hours),
        "fee_bps": str(fee_bps),
        "slippage_bps": str(slippage_bps),
        "cost_model": "fee plus explicit spread-crossing slippage on entries, changes, and final exit",
        "chronological_holdout": holdout,
        "risk": {
            "atr14": str(atr14),
            "atr_pct": str((atr14 / bars[-1].close * Decimal("100")).quantize(Decimal("0.0001"))),
            "market_regime": regime,
        },
        "signals": {
            name: {
                "direction": signal.direction.value,
                "strength": str(signal.strength),
                "rationale": signal.rationale,
            }
            for name, signal in current.items()
        },
        "backtest": {
            name: {key: str(value) for key, value in asdict(result).items()}
            for name, result in metrics.items()
        },
    }
