from __future__ import annotations

import json

import pytest

from mandate_research.live_sources import collect_official_news, probe_live_sources


ALPACA = json.dumps(
    {
        "news": [
            {
                "id": 1,
                "created_at": "2026-08-27T10:00:00Z",
                "headline": "Apple raises outlook",
                "symbols": ["AAPL"],
            }
        ]
    }
).encode()
SEC = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>sec-1</id><title>8-K - Apple Inc.</title><updated>2026-08-27T10:01:00Z</updated>
<link href="https://www.sec.gov/Archives/test"/></entry></feed>"""
RSS = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>apple-1</id>
<title>Apple product update</title><updated>2026-08-27T10:02:00Z</updated></entry></feed>"""
NVIDIA_RSS = b"""<rss><channel><item><guid>nvda-1</guid><title>NVIDIA product update</title>
<pubDate>Thu, 27 Aug 2026 10:03:00 GMT</pubDate></item></channel></rss>"""


def fake_fetch(url: str, headers: dict[str, str]) -> bytes:
    if "alpaca.markets" in url:
        assert "APCA-API-KEY-ID" in headers
        return ALPACA
    if "sec.gov" in url:
        assert "User-Agent" in headers
        return SEC
    if "apple.com" in url:
        return RSS
    if "nvidia.com" in url:
        return NVIDIA_RSS
    raise AssertionError(f"unexpected URL {url}")


def test_probe_parses_and_scopes_all_three_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    result = probe_live_sources(fetcher=fake_fetch)

    assert result["symbol"] == "AAPL"
    assert set(result["sources"]) == {
        "alpaca",
        "sec_edgar_atom",
        "apple_newsroom_atom",
    }
    assert all(item["status"] == "ok" for item in result["sources"].values())
    assert all(item["events"] == 1 for item in result["sources"].values())
    assert all(item["symbol_bound_events"] == 1 for item in result["sources"].values())


@pytest.mark.parametrize(("symbol", "cik"), [("", "0000320193"), ("AAPL", "320193")])
def test_probe_rejects_ambiguous_source_scope(
    symbol: str, cik: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    with pytest.raises(ValueError):
        probe_live_sources(symbol=symbol, cik=cik, fetcher=fake_fetch)


def test_probe_isolates_one_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")

    def partial_fetch(url: str, headers: dict[str, str]) -> bytes:
        if "sec.gov" in url:
            raise ValueError("blocked fixture")
        return fake_fetch(url, headers)

    result = probe_live_sources(fetcher=partial_fetch)
    assert result["sources"]["alpaca"]["status"] == "ok"
    assert result["sources"]["sec_edgar_atom"]["status"] == "error"
    assert result["sources"]["apple_newsroom_atom"]["status"] == "ok"
    with pytest.raises(RuntimeError, match="strict"):
        probe_live_sources(fetcher=partial_fetch, strict=True)


def test_official_company_feed_is_never_rebound_to_another_issuer() -> None:
    requested_urls: list[str] = []

    def tracking_fetch(url: str, headers: dict[str, str]) -> bytes:
        requested_urls.append(url)
        return fake_fetch(url, headers)

    events, sources = collect_official_news(symbol="NVDA", fetcher=tracking_fetch)

    assert set(sources) == {"sec_edgar_atom", "nvidia_ir_rss"}
    assert all(event.symbols == ("NVDA",) for event in events)
    assert any("nvidia.com" in url for url in requested_urls)
    assert not any("apple.com" in url for url in requested_urls)
