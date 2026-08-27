from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from mandate_research.backtest import compare_strategies
from mandate_research.news import NewsEvent, deduplicate
from mandate_research.signals import (
    PriceBar,
    breakout_volume_signal,
    mean_reversion_signal,
    momentum_signal,
    news_price_confirmation_signal,
)


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
    return NewsEvent(
        source=str(item["source"]),
        external_id=str(item["external_id"]),
        published_at=_datetime(item["published_at"]),
        headline=str(item["headline"]),
        summary=str(item.get("summary", "")),
        symbols=tuple(str(symbol).upper() for symbol in item.get("symbols", [])),
        url=str(item["url"]) if item.get("url") else None,
    )


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload["symbol"]).upper()
    bars = sorted((_bar(item) for item in payload["bars"]), key=lambda bar: bar.timestamp)
    if len(bars) < 22:
        raise ValueError("at least 22 chronological bars are required")
    cutoff = bars[-1].timestamp
    events = [event for event in deduplicate(_news(item) for item in payload.get("news", [])) if event.published_at <= cutoff]

    strategies = {
        "momentum": (lambda window: momentum_signal(window, lookback=5), 6),
        "mean_reversion": (lambda window: mean_reversion_signal(window, lookback=20), 20),
        "breakout_volume": (lambda window: breakout_volume_signal(window, lookback=20), 21),
        "news_price_confirmation": (
            lambda window: news_price_confirmation_signal(
                window,
                events,
                symbol=symbol,
                lookback=3,
            ),
            4,
        ),
    }
    fee_bps = _decimal(payload.get("fee_bps", "1"))
    metrics = compare_strategies(bars, strategies, fee_bps=fee_bps)
    current = {name: strategy(bars) for name, (strategy, _warmup) in strategies.items()}
    return {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "news_events_used": len(events),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare explainable MANDATE signals")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    print(json.dumps(analyze(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
