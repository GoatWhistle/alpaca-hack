from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from mandate_research.comparison import analyze
from mandate_research.live_sources import (
    ALPACA_NEWS_ENDPOINT,
    Fetcher,
    _alpaca_proxy,
    _fetch,
    collect_official_news,
)
from mandate_research.llm_news import MAX_ITEMS as MAX_LLM_BATCH_ITEMS, gate_news_batch_llm
from mandate_research.news import MAX_FEED_BYTES, deduplicate, parse_alpaca_news
from mandate_research.news_graph import NewsGraphStore


ALPACA_BARS_ENDPOINT = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
JsonFetcher = Callable[[str, dict[str, str]], dict[str, Any]]
NewsGate = Callable[..., list[dict[str, Any]]]


def _default_news_graph_path() -> str:
    mandate_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.environ.get(
        "MANDATE_NEWS_GRAPH_PATH",
        os.path.join(mandate_root, "logs", "news-graph.sqlite3"),
    )


def _fetch_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    timeout = max(2.0, min(20.0, float(os.environ.get("MANDATE_DATA_TIMEOUT_SECONDS", "8"))))
    response = httpx.get(
        url,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
        proxy=_alpaca_proxy(url),
    )
    response.raise_for_status()
    if len(response.content) > MAX_FEED_BYTES:
        raise ValueError(f"payload exceeds {MAX_FEED_BYTES} bytes")
    decoded = response.json()
    if not isinstance(decoded, dict):
        raise ValueError("Alpaca data response must be an object")
    return decoded


def _paginated_bars(
    url: str, headers: dict[str, str], fetcher: JsonFetcher
) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    next_url = url
    for _page in range(10):
        payload = fetcher(next_url, headers)
        page_bars = payload.get("bars", [])
        if not isinstance(page_bars, list) or any(not isinstance(item, dict) for item in page_bars):
            raise ValueError("Alpaca bars response must contain an object list")
        bars.extend(page_bars)
        token = payload.get("next_page_token")
        if token is None:
            return bars
        normalized_token = str(token)
        if not normalized_token or normalized_token in seen_tokens:
            raise ValueError("Alpaca bars pagination token is empty or repeated")
        seen_tokens.add(normalized_token)
        next_url = f"{url}&{urlencode({'page_token': normalized_token})}"
    raise ValueError("Alpaca bars pagination exceeds 10 pages")


def compare_live_signals(
    *,
    symbol: str = "AAPL",
    now: datetime | None = None,
    fetcher: JsonFetcher = _fetch_json,
    source_fetcher: Fetcher = _fetch,
    fee_bps: str = "1",
    news_gate: NewsGate = gate_news_batch_llm,
    news_store: NewsGraphStore | None = None,
) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol cannot be blank")
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise ValueError("Alpaca paper/data credentials are required")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must include a timezone")
    start = checked_at.astimezone(timezone.utc) - timedelta(days=45)
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }
    bars_url = ALPACA_BARS_ENDPOINT.format(symbol=normalized) + "?" + urlencode(
        {
            "timeframe": "1Hour",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": checked_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "limit": 1000,
            "adjustment": "all",
            "feed": "iex",
            "sort": "asc",
        }
    )
    news_url = f"{ALPACA_NEWS_ENDPOINT}?{urlencode({'symbols': normalized, 'limit': 50, 'sort': 'desc'})}"
    raw_bars = _paginated_bars(bars_url, headers, fetcher)
    alpaca_events = parse_alpaca_news(fetcher(news_url, headers))
    official_events, official_sources = collect_official_news(
        symbol=normalized,
        fetcher=source_fetcher,
        strict=False,
    )
    news_cutoff = checked_at.astimezone(timezone.utc) - timedelta(hours=24)
    events = [
        event for event in deduplicate([*alpaca_events, *official_events])
        if news_cutoff <= event.published_at <= checked_at
    ]
    collected_events = events
    passed_events = []
    gate_errors = 0
    active_store = news_store
    if active_store is None and news_gate is gate_news_batch_llm:
        active_store = NewsGraphStore(_default_news_graph_path())
    for start_index in range(0, len(events), MAX_LLM_BATCH_ITEMS):
        chunk = events[start_index : start_index + MAX_LLM_BATCH_ITEMS]
        decisions = (
            news_gate(chunk, symbol=normalized, store=active_store)
            if active_store is not None
            else news_gate(chunk, symbol=normalized)
        )
        if len(decisions) != len(chunk):
            raise ValueError("news gate must return exactly one result per event")
        for event, decision in zip(chunk, decisions):
            if decision.get("schema") == "news.gate.error.v1":
                gate_errors += 1
                continue
            if decision.get("decision") != "PASS":
                continue
            passed_events.append(replace(event, metadata={
                **event.metadata,
                "llm_gate_reason": str(decision.get("reason", "")),
                "llm_gate_decision": "PASS",
            }))
    events = passed_events
    payload = {
        "symbol": normalized,
        "fee_bps": fee_bps,
        "slippage_bps": "2",
        "news_max_age_hours": "24",
        "bars": [
            {
                "timestamp": item["t"],
                "open": item["o"],
                "high": item["h"],
                "low": item["l"],
                "close": item["c"],
                "volume": item["v"],
            }
            for item in raw_bars
        ],
        "news": [
            {
                "source": event.source,
                "external_id": event.external_id,
                "published_at": event.published_at.isoformat(),
                "headline": event.headline,
                "summary": event.summary,
                "symbols": event.symbols,
                "url": event.url,
                "llm_gate_reason": event.metadata.get("llm_gate_reason", ""),
                "llm_gate_decision": event.metadata.get("llm_gate_decision", "PASS"),
            }
            for event in events
        ],
    }
    result = analyze(payload)
    return {
        "data": {
            "source": "alpaca-iex",
            "bars": len(raw_bars),
            "news_collected": len(collected_events),
            "news_passed": len(events),
            "news_skipped": len(collected_events) - len(events) - gate_errors,
            "news_llm_gated": len(collected_events) - gate_errors,
            "news_gate_errors": gate_errors,
            "news_sources": {
                "alpaca": {"status": "ok", "events": len(alpaca_events)},
                **official_sources,
            },
            "requested_at": checked_at.isoformat(),
        },
        **result,
    }
