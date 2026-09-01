from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from mandate_research.live_sources import collect_live_news


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _event_payload(event: Any) -> dict[str, Any]:
    return {
        "key": f"{event.source}:{event.external_id}:{event.content_hash}",
        "source": event.source,
        "external_id": event.external_id,
        "published_at": event.published_at.isoformat(),
        "headline": event.headline,
        "summary": event.summary,
        "symbols": list(event.symbols),
        "url": event.url,
        "content_hash": event.content_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect bounded news events for MANDATE autonomy")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    args = parser.parse_args()
    symbols = list(dict.fromkeys(item.strip().upper() for item in args.symbols.split(",") if item.strip()))
    if not symbols:
        raise ValueError("at least one symbol is required")

    events: dict[str, dict[str, Any]] = {}
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
            payload = _event_payload(event)
            events[payload["key"]] = payload
    ordered = sorted(events.values(), key=lambda item: (item["published_at"], item["key"]))
    print(
        json.dumps(
            {
                "checked_at": datetime.now().astimezone().isoformat(),
                "symbols": symbols,
                "events": ordered,
                "sources": source_health,
            },
            ensure_ascii=False,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
