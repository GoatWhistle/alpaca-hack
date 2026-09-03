from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mandate_research.live_sources import collect_live_news
from mandate_research.llm_news import MAX_ITEMS, gate_news_batch_llm
from mandate_research.news import NewsEvent
from mandate_research.news_graph import (
    NewsGraphStore,
    import_legacy_alerts_once,
    import_legacy_news,
    legacy_news_event,
    story_id_for,
)


MAX_POLL_EVENTS = 80
NEWS_LOOKBACK_HOURS = 72


def _bounded_recent_events(events: list[NewsEvent], *, now: datetime) -> list[NewsEvent]:
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
    recent = [event for event in events if event.published_at >= cutoff]
    return sorted(
        recent,
        key=lambda item: (item.published_at, item.source, item.external_id, item.content_hash),
    )[-MAX_POLL_EVENTS:]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _event_payload(event: NewsEvent, gate: dict[str, Any]) -> dict[str, Any]:
    envelope = legacy_news_event(event)
    return {
        "key": f"{event.source}:{envelope['event_id']}",
        "event_id": envelope["event_id"],
        "story_id": story_id_for(event.source, event.external_id),
        "source": event.source,
        "external_id": event.external_id,
        "published_at": event.published_at.isoformat(),
        "headline": event.headline,
        "summary": event.summary,
        "symbols": list(event.symbols),
        "url": event.url,
        "content_hash": envelope["content_hash"],
        "gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect bounded news events for MANDATE autonomy")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    parser.add_argument(
        "--news-graph",
        default=os.environ.get(
            "MANDATE_NEWS_GRAPH_PATH",
            str(Path(__file__).resolve().parents[2] / "logs" / "news-graph.sqlite3"),
        ),
        help="Persistent SQLite news graph path",
    )
    args = parser.parse_args()
    symbols = list(dict.fromkeys(item.strip().upper() for item in args.symbols.split(",") if item.strip()))
    if not symbols:
        raise ValueError("at least one symbol is required")

    events: dict[str, NewsEvent] = {}
    source_health: dict[str, Any] = {}
    # Each symbol is isolated and upstream requests are I/O-bound. Running the
    # full bounded universe concurrently keeps a 30-second monitoring cadence
    # from turning into several serial timeout windows.
    with ThreadPoolExecutor(max_workers=min(20, len(symbols))) as executor:
        loaded_by_symbol = list(
            executor.map(lambda symbol: collect_live_news(symbol=symbol, strict=False), symbols)
        )
    for symbol, (loaded, sources) in zip(symbols, loaded_by_symbol, strict=True):
        source_health[symbol] = sources
        for event in loaded:
            key = f"{event.source}:{event.external_id}:{event.content_hash}"
            events[key] = event
    ordered_events = _bounded_recent_events(list(events.values()), now=datetime.now(timezone.utc))
    store = NewsGraphStore(args.news_graph)
    legacy_import = import_legacy_alerts_once(
        store,
        os.environ.get(
            "MANDATE_ALERTS_PATH",
            str(Path(__file__).resolve().parents[2] / "logs" / "news-alerts.jsonl"),
        ),
    )
    # Materialize the complete graph before deriving request IDs. Otherwise a
    # later duplicate can change source_count and force already-gated events
    # through the model again on the next poll.
    import_legacy_news(store, ordered_events)
    chunks = [
        ordered_events[index:index + MAX_ITEMS]
        for index in range(0, len(ordered_events), MAX_ITEMS)
    ]
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(chunks)))) as executor:
        gated_chunks = list(executor.map(
            lambda chunk: gate_news_batch_llm(
                chunk, target_symbols=symbols, store=store,
            ),
            chunks,
        ))
    gates = [gate for chunk in gated_chunks for gate in chunk]
    if len(gates) != len(ordered_events):
        raise RuntimeError("news gate result count does not match collected events")
    ordered = [_event_payload(event, gate) for event, gate in zip(ordered_events, gates, strict=True)]
    passed = [event for event in ordered if event["gate"].get("decision") == "PASS"]
    gate_errors = [event["gate"] for event in ordered if event["gate"].get("schema") == "news.gate.error.v1"]
    print(
        json.dumps(
            {
                "schema": "news.poll.v2",
                "checked_at": datetime.now().astimezone().isoformat(),
                "symbols": symbols,
                "events": ordered,
                "passed_events": passed,
                "gate_errors": gate_errors,
                "graph_counts": store.counts(),
                "legacy_import": legacy_import,
                "sources": source_health,
            },
            ensure_ascii=False,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
