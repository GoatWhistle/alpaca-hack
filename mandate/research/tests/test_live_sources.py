from __future__ import annotations

import json

import pytest

from mandate_research.live_sources import CIK_BY_SYMBOL, collect_live_news, collect_official_news, probe_live_sources


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
SEC = json.dumps(
    {
        "cik": "320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K"],
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                "acceptanceDateTime": ["2026-08-26T10:00:00Z", "2026-08-27T10:01:00Z"],
                "filingDate": ["2026-08-26", "2026-08-27"],
                "primaryDocument": ["aapl-10q.htm", "aapl-8k.htm"],
                "primaryDocDescription": ["Quarterly report", "Current report"],
                "items": ["", "2.02,9.01"],
            }
        },
    }
).encode()
RSS = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>apple-1</id>
<title>Apple product update</title><updated>2026-08-27T10:02:00Z</updated></entry></feed>"""
NVIDIA_RSS = b"""<rss><channel><item><guid>nvda-1</guid><title>NVIDIA product update</title>
<pubDate>Thu, 27 Aug 2026 10:03:00 GMT</pubDate></item></channel></rss>"""
GENERIC_RSS = b"""<rss><channel><item><guid>official-1</guid><title>Official update</title>
<description>Primary-source company or macro news.</description>
<pubDate>Thu, 27 Aug 2026 10:04:00 GMT</pubDate></item></channel></rss>"""


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
    if any(host in url for host in (
        "blogs.microsoft.com", "blog.google", "aws.amazon.com", "about.fb.com", "federalreserve.gov"
    )):
        return GENERIC_RSS
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


def test_collect_live_news_returns_bounded_attributable_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    events, sources = collect_live_news(fetcher=fake_fetch)

    assert set(sources) == {"alpaca", "sec_edgar_atom", "apple_newsroom_atom"}
    assert {event.source for event in events} == {"alpaca", "sec-edgar", "apple-newsroom"}
    assert all(event.symbols == ("AAPL",) for event in events)
    assert all(event.content_hash for event in events)


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


@pytest.mark.parametrize(
    ("symbol", "source_name", "event_source"),
    [
        ("MSFT", "microsoft_official_rss", "microsoft-official"),
        ("GOOGL", "google_official_rss", "google-official"),
        ("AMZN", "aws_official_rss", "aws-official"),
        ("META", "meta_official_rss", "meta-official"),
        ("SPY", "federal_reserve_rss", "federal-reserve"),
    ],
)
def test_additional_official_feeds_are_attributable(
    symbol: str, source_name: str, event_source: str
) -> None:
    events, sources = collect_official_news(symbol=symbol, fetcher=fake_fetch)

    assert sources[source_name]["status"] == "ok"
    matching = [event for event in events if event.source == event_source]
    assert matching
    assert all(event.symbols == (symbol,) for event in matching)


def test_sec_mapping_covers_every_traded_issuer() -> None:
    expected = {
        "AAPL", "MSFT", "NVDA", "GOOG", "GOOGL", "AMZN", "META", "AMD", "AVGO",
        "ORCL", "IBM", "PLTR", "CRM", "ANET", "TSM", "ASML", "ARM", "BABA", "BIDU",
    }
    assert expected <= set(CIK_BY_SYMBOL)
    assert all(cik.isdigit() and len(cik) == 10 for cik in CIK_BY_SYMBOL.values())
