from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from mandate_research.news import (
    MAX_FEED_BYTES,
    NewsEvent,
    bind_symbol,
    deduplicate,
    parse_alpaca_news,
    parse_atom,
    parse_rss,
    parse_sec_atom,
)


ALPACA_NEWS_ENDPOINT = "https://data.alpaca.markets/v1beta1/news"
SEC_ATOM_ENDPOINT = "https://www.sec.gov/cgi-bin/browse-edgar"
APPLE_RSS_ENDPOINT = "https://www.apple.com/newsroom/rss-feed.rss"
NVIDIA_RSS_ENDPOINT = "https://nvidianews.nvidia.com/cats/press_release.xml"
ALLOWED_HOSTS = {
    "data.alpaca.markets",
    "www.sec.gov",
    "www.apple.com",
    "nvidianews.nvidia.com",
}
Fetcher = Callable[[str, dict[str, str]], bytes]


def _fetch(url: str, headers: dict[str, str]) -> bytes:
    response = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
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


def probe_live_sources(
    *,
    symbol: str = "AAPL",
    cik: str = "0000320193",
    fetcher: Fetcher = _fetch,
    strict: bool = False,
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol cannot be blank")
    if not cik.isdigit() or len(cik) != 10:
        raise ValueError("CIK must contain exactly 10 digits")
    alpaca_key = os.environ.get("ALPACA_API_KEY", "")
    alpaca_secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not alpaca_key or not alpaca_secret:
        raise ValueError("Alpaca paper/data credentials are required")

    alpaca_url = f"{ALPACA_NEWS_ENDPOINT}?{urlencode({'symbols': normalized_symbol, 'limit': 20, 'sort': 'desc'})}"
    sec_url = f"{SEC_ATOM_ENDPOINT}?{urlencode({'action': 'getcompany', 'CIK': cik, 'type': '8-K', 'owner': 'exclude', 'count': 40, 'output': 'atom'})}"
    sources = {
        "alpaca": _probe_source(
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
        ),
        "sec_edgar_atom": _probe_source(
            lambda: bind_symbol(
                parse_sec_atom(
                    fetcher(
                        sec_url,
                        {
                            "User-Agent": os.environ.get(
                                "MANDATE_SEC_USER_AGENT",
                                "MANDATE research probe github.com/GoatWhistle/harness-hack",
                            ),
                            "Accept": "application/atom+xml",
                        },
                    )
                ),
                normalized_symbol,
            )
        ),
        "company_newsroom_atom": _probe_source(
            lambda: bind_symbol(
                parse_atom(
                    fetcher(APPLE_RSS_ENDPOINT, {"User-Agent": "MANDATE research probe"}),
                    source="apple-newsroom",
                ),
                normalized_symbol,
            )
        ),
        "company_ir_rss": _probe_source(
            lambda: bind_symbol(
                parse_rss(
                    fetcher(NVIDIA_RSS_ENDPOINT, {"User-Agent": "MANDATE research probe"}),
                    source="nvidia-ir",
                ),
                "NVDA",
            )
        ),
    }
    if strict and any(summary["status"] != "ok" for summary in sources.values()):
        raise RuntimeError("one or more live sources failed strict probing")
    return {
        "symbol": normalized_symbol,
        "checked_at": datetime.now().astimezone(),
        "sources": sources,
    }
