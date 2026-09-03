from __future__ import annotations

import os
import time
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

import httpx

from mandate_research.news import (
    MAX_FEED_BYTES,
    NewsEvent,
    bind_symbol,
    deduplicate,
    parse_alpaca_news,
    parse_atom,
    parse_rss,
    parse_sec_submissions,
)


ALPACA_NEWS_ENDPOINT = "https://data.alpaca.markets/v1beta1/news"
SEC_SUBMISSIONS_ENDPOINT = "https://data.sec.gov/submissions"
APPLE_RSS_ENDPOINT = "https://www.apple.com/newsroom/rss-feed.rss"
NVIDIA_RSS_ENDPOINT = "https://nvidianews.nvidia.com/cats/press_release.xml"
MICROSOFT_RSS_ENDPOINT = "https://blogs.microsoft.com/feed/"
GOOGLE_RSS_ENDPOINT = "https://blog.google/rss/"
AWS_RSS_ENDPOINT = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
META_RSS_ENDPOINT = "https://about.fb.com/news/feed/"
FEDERAL_RESERVE_RSS_ENDPOINT = "https://www.federalreserve.gov/feeds/press_all.xml"
ALLOWED_HOSTS = {
    "data.alpaca.markets",
    "www.sec.gov",
    "data.sec.gov",
    "www.apple.com",
    "nvidianews.nvidia.com",
    "blogs.microsoft.com",
    "blog.google",
    "aws.amazon.com",
    "about.fb.com",
    "www.federalreserve.gov",
}
Fetcher = Callable[[str, dict[str, str]], bytes]
MAX_EVENTS_PER_SOURCE = 20
_SEC_REQUEST_LOCK = Lock()
_SEC_NEXT_REQUEST_AT = 0.0
CIK_BY_SYMBOL = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "GOOG": "0001652044",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "META": "0001326801",
    "AMD": "0000002488",
    "AVGO": "0001730168",
    "ORCL": "0001341439",
    "IBM": "0000051143",
    "PLTR": "0001321655",
    "CRM": "0001108524",
    "ANET": "0001596532",
    "TSM": "0001046179",
    "ASML": "0000937966",
    "ARM": "0001973239",
    "BABA": "0001577552",
    "BIDU": "0001329099",
}


def _alpaca_proxy(url: str) -> str | None:
    """Return the dedicated proxy only for Alpaca-owned HTTPS endpoints."""
    hostname = (urlparse(url).hostname or "").lower()
    if (
        os.environ.get("MANDATE_USE_ALPACA_PROXY", "false").lower() == "true"
        and (hostname == "alpaca.markets" or hostname.endswith(".alpaca.markets"))
    ):
        return os.environ.get("ALPACA_PROXY_URL") or None
    return None


def _request_proxy(url: str) -> str | None:
    """Return a configured proxy only for explicitly enabled HTTPS sources."""
    alpaca_proxy = _alpaca_proxy(url)
    if alpaca_proxy is not None:
        return alpaca_proxy
    hostname = (urlparse(url).hostname or "").lower()
    if (
        os.environ.get("MANDATE_USE_NEWS_PROXY", "false").lower() == "true"
        and hostname == "nvidianews.nvidia.com"
    ):
        return os.environ.get("MANDATE_NEWS_PROXY_URL") or os.environ.get("ALPACA_PROXY_URL") or None
    return None
ISSUER_RSS_BY_SYMBOL = {
    "MSFT": ("microsoft_official_rss", MICROSOFT_RSS_ENDPOINT, "microsoft-official"),
    "GOOG": ("google_official_rss", GOOGLE_RSS_ENDPOINT, "google-official"),
    "GOOGL": ("google_official_rss", GOOGLE_RSS_ENDPOINT, "google-official"),
    "AMZN": ("aws_official_rss", AWS_RSS_ENDPOINT, "aws-official"),
    "META": ("meta_official_rss", META_RSS_ENDPOINT, "meta-official"),
}


def _fetch(url: str, headers: dict[str, str]) -> bytes:
    global _SEC_NEXT_REQUEST_AT
    timeout = max(2.0, min(20.0, float(os.environ.get("MANDATE_DATA_TIMEOUT_SECONDS", "8"))))
    if (urlparse(url).hostname or "").lower() == "data.sec.gov":
        # SEC fair-access guidance caps automated clients at ten requests per
        # second. poll_news fans symbols out concurrently, so serialize starts
        # at eight requests per second and leave headroom for manual probes.
        with _SEC_REQUEST_LOCK:
            delay = _SEC_NEXT_REQUEST_AT - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            _SEC_NEXT_REQUEST_AT = time.monotonic() + 0.125
    response = httpx.get(
        url,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
        proxy=_request_proxy(url),
    )
    response.raise_for_status()
    if response.url.scheme != "https" or response.url.host not in ALLOWED_HOSTS:
        raise ValueError("live source redirected outside the fixed HTTPS allowlist")
    payload = response.content
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError(f"feed exceeds {MAX_FEED_BYTES} bytes")
    return payload


def _source_summary(events: list[NewsEvent]) -> dict[str, Any]:
    unique = deduplicate(events)
    return {
        "events": len(unique),
        "newest": max((event.published_at for event in unique), default=None),
        "unique_content_hashes": len({event.content_hash for event in unique}),
        "symbol_bound_events": sum(bool(event.symbols) for event in unique),
    }


def _probe_source(load: Callable[[], list[NewsEvent]]) -> dict[str, Any]:
    try:
        summary = _source_summary(load())
        if summary["events"] == 0:
            raise RuntimeError("source returned no parseable events")
        return {"status": "ok", **summary}
    except httpx.HTTPStatusError as exc:
        return {"status": "upstream_http_error", "http_status": exc.response.status_code}
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _load_source(
    load: Callable[[], list[NewsEvent]],
) -> tuple[list[NewsEvent], dict[str, Any]]:
    try:
        events = deduplicate(load())[-MAX_EVENTS_PER_SOURCE:]
        summary = _source_summary(events)
        if summary["events"] == 0:
            raise RuntimeError("source returned no parseable events")
        return events, {"status": "ok", **summary}
    except httpx.HTTPStatusError as exc:
        return [], {"status": "upstream_http_error", "http_status": exc.response.status_code}
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        return [], {"status": "error", "error_type": type(exc).__name__}


def collect_official_news(
    *,
    symbol: str,
    cik: str | None = None,
    fetcher: Fetcher = _fetch,
    strict: bool = False,
) -> tuple[list[NewsEvent], dict[str, dict[str, Any]]]:
    """Load only issuer-attributable official feeds for one symbol.

    A company feed is never rebound to a different issuer. SEC is included only
    when a ten-digit CIK is explicitly supplied or known in the fixed mapping.
    Individual upstream failures remain isolated and visible in provenance.
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol cannot be blank")
    resolved_cik = cik or CIK_BY_SYMBOL.get(normalized_symbol)
    if resolved_cik is not None and (not resolved_cik.isdigit() or len(resolved_cik) != 10):
        raise ValueError("CIK must contain exactly 10 digits")

    loaders: dict[str, Callable[[], list[NewsEvent]]] = {}
    if resolved_cik is not None:
        sec_url = f"{SEC_SUBMISSIONS_ENDPOINT}/CIK{resolved_cik}.json"
        loaders["sec_edgar_atom"] = lambda: bind_symbol(
            parse_sec_submissions(
                fetcher(
                    sec_url,
                    {
                        "User-Agent": os.environ.get(
                            "MANDATE_SEC_USER_AGENT",
                            "MandateResearch/1.0 (+https://alpaca.miposts.com)",
                        ),
                        "Accept": "application/json",
                    },
                )
            ),
            normalized_symbol,
        )
    if normalized_symbol == "AAPL":
        loaders["apple_newsroom_atom"] = lambda: bind_symbol(
            parse_atom(
                fetcher(APPLE_RSS_ENDPOINT, {"User-Agent": "MANDATE research probe"}),
                source="apple-newsroom",
            ),
            "AAPL",
        )
    elif normalized_symbol == "NVDA":
        loaders["nvidia_ir_rss"] = lambda: bind_symbol(
            parse_rss(
                fetcher(NVIDIA_RSS_ENDPOINT, {"User-Agent": "MANDATE research probe"}),
                source="nvidia-ir",
            ),
            "NVDA",
        )
    issuer_rss = ISSUER_RSS_BY_SYMBOL.get(normalized_symbol)
    if issuer_rss is not None:
        name, endpoint, source = issuer_rss
        loaders[name] = lambda endpoint=endpoint, source=source: bind_symbol(
            parse_rss(
                fetcher(endpoint, {"User-Agent": "MANDATE research probe"}),
                source=source,
            ),
            normalized_symbol,
        )
    if normalized_symbol == "SPY":
        loaders["federal_reserve_rss"] = lambda: bind_symbol(
            parse_rss(
                fetcher(FEDERAL_RESERVE_RSS_ENDPOINT, {"User-Agent": "MANDATE research probe"}),
                source="federal-reserve",
            ),
            "SPY",
        )

    events: list[NewsEvent] = []
    sources: dict[str, dict[str, Any]] = {}
    for name, loader in loaders.items():
        loaded, status = _load_source(loader)
        events.extend(loaded)
        sources[name] = status
    if strict and any(status["status"] != "ok" for status in sources.values()):
        raise RuntimeError("one or more live sources failed strict probing")
    return deduplicate(events), sources


def probe_live_sources(
    *,
    symbol: str = "AAPL",
    cik: str | None = None,
    fetcher: Fetcher = _fetch,
    strict: bool = False,
) -> dict[str, Any]:
    _events, sources = collect_live_news(
        symbol=symbol,
        cik=cik,
        fetcher=fetcher,
        strict=strict,
    )
    return {
        "symbol": symbol.strip().upper(),
        "checked_at": datetime.now().astimezone(),
        "sources": sources,
    }


def collect_live_news(
    *,
    symbol: str = "AAPL",
    cik: str | None = None,
    fetcher: Fetcher = _fetch,
    strict: bool = False,
) -> tuple[list[NewsEvent], dict[str, dict[str, Any]]]:
    """Collect bounded attributable events for alerting as untrusted data."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol cannot be blank")
    alpaca_key = os.environ.get("ALPACA_API_KEY", "")
    alpaca_secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not alpaca_key or not alpaca_secret:
        raise ValueError("Alpaca paper/data credentials are required")

    alpaca_url = f"{ALPACA_NEWS_ENDPOINT}?{urlencode({'symbols': normalized_symbol, 'limit': 20, 'sort': 'desc'})}"
    official_events, official_sources = collect_official_news(
        symbol=normalized_symbol,
        cik=cik,
        fetcher=fetcher,
        strict=False,
    )
    alpaca_events, alpaca_status = _load_source(
        lambda: parse_alpaca_news(
            fetcher(
                alpaca_url,
                {
                    "APCA-API-KEY-ID": alpaca_key,
                    "APCA-API-SECRET-KEY": alpaca_secret,
                    "Accept": "application/json",
                },
            )
        )
    )
    sources = {
        "alpaca": alpaca_status,
        **official_sources,
    }
    if strict and any(summary["status"] != "ok" for summary in sources.values()):
        raise RuntimeError("one or more live sources failed strict probing")
    scoped_alpaca = [event for event in alpaca_events if normalized_symbol in event.symbols]
    return deduplicate([*scoped_alpaca, *official_events]), sources
