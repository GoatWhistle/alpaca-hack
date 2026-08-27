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


def _bars(count: int = 24) -> list[dict[str, str]]:
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
        for index in range(count)
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
                    "llm_score": "0.8",
                    "llm_confidence": "0.9",
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
    assert result["slippage_bps"] == "2"
    assert result["chronological_holdout"]["parameters_frozen"] is True
    assert set(result["chronological_holdout"]["selected_parameters"]) == {
        "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation"
    }


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
                    "llm_score": "0.8",
                    "llm_confidence": "0.9",
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


def test_walk_forward_selection_cannot_see_holdout_prices() -> None:
    original = _bars(45)
    changed_tail = [dict(bar) for bar in original]
    for index in range(30, 45):
        close = Decimal("300") - Decimal(index * 3)
        changed_tail[index].update({
            "open": str(close + Decimal("1")),
            "high": str(close + Decimal("2")),
            "low": str(close - Decimal("2")),
            "close": str(close),
        })

    original_result = MODULE.analyze({"symbol": "AAPL", "bars": original, "news": []})
    changed_result = MODULE.analyze({"symbol": "AAPL", "bars": changed_tail, "news": []})

    assert (
        original_result["chronological_holdout"]["selected_parameters"]
        == changed_result["chronological_holdout"]["selected_parameters"]
    )
    assert (
        original_result["chronological_holdout"]["test"]
        != changed_result["chronological_holdout"]["test"]
    )
