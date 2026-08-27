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
    _fetch,
    collect_official_news,
)
from mandate_research.llm_news import MAX_ITEMS as MAX_LLM_BATCH_ITEMS, score_news_batch_llm
from mandate_research.news import MAX_FEED_BYTES, deduplicate, parse_alpaca_news


ALPACA_BARS_ENDPOINT = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
JsonFetcher = Callable[[str, dict[str, str]], dict[str, Any]]
NewsScorer = Callable[..., list[dict[str, Any]]]


def _fetch_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = httpx.get(url, headers=headers, timeout=20, follow_redirects=False)
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
    news_scorer: NewsScorer = score_news_batch_llm,
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
    events = deduplicate([*alpaca_events, *official_events])
    scored_events = []
    scoring_available = 0
    for start_index in range(0, len(events), MAX_LLM_BATCH_ITEMS):
        chunk = events[start_index : start_index + MAX_LLM_BATCH_ITEMS]
        scores = news_scorer(chunk, symbol=normalized)
        if len(scores) != len(chunk):
            raise ValueError("news scorer must return exactly one result per event")
        for event, score in zip(chunk, scores):
            if score.get("available") is True:
                scoring_available += 1
            scored_events.append(replace(event, metadata={
                **event.metadata,
                "llm_score": str(score.get("score", "0")),
                "llm_confidence": str(score.get("confidence", "0")),
                "llm_reason": str(score.get("reason", "")),
                "llm_event_type": str(score.get("event_type", "other")),
                "llm_horizon": str(score.get("horizon", "intraday")),
            }))
    events = scored_events
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
                "llm_score": event.metadata.get("llm_score", "0"),
                "llm_confidence": event.metadata.get("llm_confidence", "0"),
                "llm_reason": event.metadata.get("llm_reason", ""),
                "llm_event_type": event.metadata.get("llm_event_type", "other"),
                "llm_horizon": event.metadata.get("llm_horizon", "intraday"),
            }
            for event in events
        ],
    }
    result = analyze(payload)
    return {
        "data": {
            "source": "alpaca-iex",
            "bars": len(raw_bars),
            "news": len(events),
            "news_llm_scored": scoring_available,
            "news_sources": {
                "alpaca": {"status": "ok", "events": len(alpaca_events)},
                **official_sources,
            },
            "requested_at": checked_at.isoformat(),
        },
        **result,
    }
