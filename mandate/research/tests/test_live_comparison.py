from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mandate_research.live_comparison import compare_live_signals


NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)


def fake_fetch(url: str, headers: dict[str, str]) -> dict:
    assert headers["APCA-API-KEY-ID"] == "paper-key"
    if "/bars?" in url:
        start = NOW - timedelta(hours=30)
        return {
            "bars": [
                {
                    "t": (start + timedelta(hours=index)).isoformat(),
                    "o": 100 + index,
                    "h": 102 + index,
                    "l": 99 + index,
                    "c": 101 + index,
                    "v": 10_000 + index,
                }
                for index in range(30)
            ]
        }
    if "/news?" in url:
        return {
            "news": [
                {
                    "id": 1,
                    "created_at": (NOW - timedelta(hours=2)).isoformat(),
                    "headline": "Apple raises outlook after profit growth",
                    "symbols": ["AAPL"],
                }
            ]
        }
    raise AssertionError(f"unexpected URL {url}")


def test_live_comparison_uses_real_shape_and_all_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    result = compare_live_signals(now=NOW, fetcher=fake_fetch, fee_bps="2")

    assert result["data"] == {
        "source": "alpaca-iex",
        "bars": 30,
        "news": 1,
        "requested_at": NOW.isoformat(),
    }
    assert result["fee_bps"] == "2"
    assert set(result["backtest"]) == {
        "momentum",
        "mean_reversion",
        "breakout_volume",
        "news_price_confirmation",
    }


def test_live_comparison_follows_bounded_bar_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    start = NOW - timedelta(hours=30)

    def paged_fetch(url: str, headers: dict[str, str]) -> dict:
        if "/news?" in url:
            return {"news": []}
        offset = 15 if "page_token=second" in url else 0
        result = {
            "bars": [
                {
                    "t": (start + timedelta(hours=index)).isoformat(),
                    "o": 100 + index,
                    "h": 102 + index,
                    "l": 99 + index,
                    "c": 101 + index,
                    "v": 10_000 + index,
                }
                for index in range(offset, offset + 15)
            ]
        }
        if offset == 0:
            result["next_page_token"] = "second"
        return result

    result = compare_live_signals(now=NOW, fetcher=paged_fetch)
    assert result["data"]["bars"] == 30
    assert result["as_of"] == (NOW - timedelta(hours=1)).isoformat()
