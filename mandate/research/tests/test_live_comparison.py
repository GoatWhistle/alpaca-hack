from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from mandate_research import live_comparison
from mandate_research.live_comparison import _fetch_json, compare_live_signals


NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
SEC = json.dumps({
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {"recent": {
        "form": ["8-K"],
        "accessionNumber": ["0000320193-26-000002"],
        "acceptanceDateTime": ["2026-08-27T09:00:00Z"],
        "primaryDocument": ["aapl-8k.htm"],
        "primaryDocDescription": ["Current report"],
        "items": ["2.02"],
    }},
}).encode()
APPLE = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>apple-1</id>
<title>Apple product update</title><updated>2026-08-27T09:30:00Z</updated></entry></feed>"""


def test_market_get_retries_one_transient_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_USE_ALPACA_PROXY", "false")
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/test")
    calls = 0

    def get(*_args, **_kwargs) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("transient", request=request)
        return httpx.Response(200, request=request, json={"ok": True})

    monkeypatch.setattr(live_comparison.httpx, "get", get)
    monkeypatch.setattr(live_comparison.time, "sleep", lambda _seconds: None)
    assert _fetch_json(str(request.url), {}) == {"ok": True}
    assert calls == 2


def test_market_get_does_not_retry_nontransient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_USE_ALPACA_PROXY", "false")
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/test")
    calls = 0

    def get(*_args, **_kwargs) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request, json={"message": "not found"})

    monkeypatch.setattr(live_comparison.httpx, "get", get)
    with pytest.raises(httpx.HTTPStatusError):
        _fetch_json(str(request.url), {})
    assert calls == 1


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
                },
                {
                    "id": 2,
                    "created_at": (NOW - timedelta(days=2)).isoformat(),
                    "headline": "Stale item must not consume LLM scoring",
                    "symbols": ["AAPL"],
                },
            ]
        }
    raise AssertionError(f"unexpected URL {url}")


def fake_source_fetch(url: str, headers: dict[str, str]) -> bytes:
    if "sec.gov" in url:
        return SEC
    if "apple.com" in url:
        return APPLE
    raise AssertionError(f"unexpected source URL {url}")


def fake_news_gate(events, *, symbol: str) -> list[dict]:
    assert all(NOW - timedelta(hours=24) <= event.published_at <= NOW for event in events)
    return [{
        "available": True, "reason": "material guidance", "decision": "PASS",
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
        news_gate=fake_news_gate,
    )

    assert result["data"]["source"] == "alpaca-iex"
    assert result["data"]["bars"] == 60
    assert result["data"]["news_collected"] == 3
    assert result["data"]["news_passed"] == 3
    assert result["data"]["news_llm_gated"] == 3
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
        news_gate=fake_news_gate,
    )
    assert result["data"]["bars"] == 60
    assert result["as_of"] == (NOW - timedelta(hours=1)).isoformat()
