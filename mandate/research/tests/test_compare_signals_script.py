from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_signals.py"
SPEC = importlib.util.spec_from_file_location("compare_signals", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _bars() -> list[dict[str, str]]:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [
        {
            "timestamp": (start + timedelta(days=index)).isoformat(),
            "open": str(Decimal("100") + index),
            "high": str(Decimal("102") + index),
            "low": str(Decimal("99") + index),
            "close": str(Decimal("101") + index),
            "volume": str(Decimal("10000") + index),
        }
        for index in range(24)
    ]


def test_analyze_compares_all_strategies_and_filters_future_news() -> None:
    bars = _bars()
    result = MODULE.analyze(
        {
            "symbol": " aapl ",
            "bars": bars,
            "news": [
                {
                    "source": "sec-edgar",
                    "external_id": "past",
                    "published_at": bars[-2]["timestamp"],
                    "headline": "Profit growth beat",
                    "symbols": [" AAPL ", ""],
                },
                {
                    "source": "rss",
                    "external_id": "future",
                    "published_at": "2027-01-01T00:00:00Z",
                    "headline": "Future leak",
                    "symbols": ["AAPL"],
                },
            ],
        }
    )

    assert result["symbol"] == "AAPL"
    assert result["news_events_used"] == 1
    assert set(result["signals"]) == {
        "momentum",
        "mean_reversion",
            "breakout_volume",
            "news_price_confirmation",
            "regime_ensemble",
        }
    assert set(result["backtest"]) == set(result["signals"])


def test_analyze_keeps_last_eligible_revision_at_cutoff() -> None:
    bars = _bars()
    result = MODULE.analyze(
        {
            "symbol": "AAPL",
            "bars": bars,
            "news": [
                {
                    "source": "wire",
                    "external_id": "same-story",
                    "published_at": bars[-2]["timestamp"],
                    "headline": "Profit growth",
                    "symbols": ["AAPL"],
                },
                {
                    "source": "wire",
                    "external_id": "same-story",
                    "published_at": "2027-01-01T00:00:00Z",
                    "headline": "Future revision",
                    "symbols": ["AAPL"],
                },
            ],
        }
    )

    assert result["news_events_used"] == 1
    assert result["signals"]["news_price_confirmation"]["direction"] == "buy"
