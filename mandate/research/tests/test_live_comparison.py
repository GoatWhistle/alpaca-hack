from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mandate_research.live_comparison import compare_live_signals


NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
SEC = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>sec-1</id><title>8-K - Apple Inc.</title><updated>2026-08-27T09:00:00Z</updated>
</entry></feed>"""
APPLE = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>apple-1</id>
<title>Apple product update</title><updated>2026-08-27T09:30:00Z</updated></entry></feed>"""


def fake_fetch(url: str, headers: dict[str, str]) -> dict:
    assert headers["APCA-API-KEY-ID"] == "paper-key"
    if "/bars?" in url:
        start = NOW - timedelta(hours=60)
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
                for index in range(60)
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


def fake_source_fetch(url: str, headers: dict[str, str]) -> bytes:
    if "sec.gov" in url:
        return SEC
    if "apple.com" in url:
        return APPLE
    raise AssertionError(f"unexpected source URL {url}")


def fake_news_scorer(events, *, symbol: str) -> list[dict]:
    return [{
        "available": True, "score": "0.8", "confidence": "0.9", "reason": "material guidance",
        "event_type": "guidance", "horizon": "multiday", "novelty_48h": "0.8",
    } for _event in events]


def test_live_comparison_uses_real_shape_and_all_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    result = compare_live_signals(
        now=NOW,
        fetcher=fake_fetch,
        source_fetcher=fake_source_fetch,
        fee_bps="2",
        news_scorer=fake_news_scorer,
    )

    assert result["data"]["source"] == "alpaca-iex"
    assert result["data"]["bars"] == 60
    assert result["data"]["news"] == 3
    assert result["data"]["requested_at"] == NOW.isoformat()
    assert set(result["data"]["news_sources"]) == {
        "alpaca",
        "sec_edgar_atom",
        "apple_newsroom_atom",
    }
    assert result["fee_bps"] == "2"
    assert set(result["backtest"]) == {
        "momentum",
        "mean_reversion",
        "breakout_volume",
        "news_price_confirmation",
        "rsi_reversion",
        "macd_trend",
        "volatility_adjusted_momentum",
        "regime_ensemble",
    }


def test_live_comparison_follows_bounded_bar_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    start = NOW - timedelta(hours=60)

    def paged_fetch(url: str, headers: dict[str, str]) -> dict:
        if "/news?" in url:
            return {"news": []}
        offset = 30 if "page_token=second" in url else 0
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
                for index in range(offset, offset + 30)
            ]
        }
        if offset == 0:
            result["next_page_token"] = "second"
        return result

    result = compare_live_signals(
        now=NOW,
        fetcher=paged_fetch,
        source_fetcher=fake_source_fetch,
        news_scorer=fake_news_scorer,
    )
    assert result["data"]["bars"] == 60
    assert result["as_of"] == (NOW - timedelta(hours=1)).isoformat()
