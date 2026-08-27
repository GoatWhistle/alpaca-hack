from __future__ import annotations

# This module intentionally has no broker or MCP dependency.

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping


MAX_FEED_BYTES = 1_000_000
MAX_TEXT_CHARS = 4_000


class NewsParseError(ValueError):
    """A feed is malformed or violates an input boundary."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True)
class NewsEvent:
    source: str
    external_id: str
    published_at: datetime
    headline: str
    summary: str = ""
    symbols: tuple[str, ...] = ()
    url: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        if not self.source or not self.external_id or not self.headline:
            raise ValueError("source, external_id, and headline are required")


def _bounded_payload(payload: str | bytes) -> str:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > MAX_FEED_BYTES:
        raise NewsParseError(f"feed exceeds {MAX_FEED_BYTES} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NewsParseError("feed must be UTF-8") from exc


def clean_text(value: Any) -> str:
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:MAX_TEXT_CHARS]


def _parse_datetime(value: str) -> datetime:
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(candidate)
        except (TypeError, ValueError) as exc:
            raise NewsParseError(f"invalid publication timestamp: {candidate!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NewsParseError("publication timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalize_symbols(values: Iterable[Any]) -> tuple[str, ...]:
    symbols = {str(value).strip().upper() for value in values if str(value).strip()}
    return tuple(sorted(symbols))


def _hash_event(source: str, external_id: str, headline: str) -> str:
    canonical = json.dumps([source, external_id, headline], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event(
    *,
    source: str,
    external_id: Any,
    published_at: str,
    headline: Any,
    summary: Any = "",
    symbols: Iterable[Any] = (),
    url: Any = None,
    metadata: Mapping[str, str] | None = None,
) -> NewsEvent:
    safe_headline = clean_text(headline)
    safe_id = clean_text(external_id)
    if not safe_headline or not safe_id:
        raise NewsParseError("news item is missing an id or headline")
    return NewsEvent(
        source=source,
        external_id=safe_id,
        published_at=_parse_datetime(published_at),
        headline=safe_headline,
        summary=clean_text(summary),
        symbols=_normalize_symbols(symbols),
        url=str(url).strip() if url else None,
        metadata=dict(metadata or {}),
        content_hash=_hash_event(source, safe_id, safe_headline),
    )


def parse_alpaca_news(payload: str | bytes | Mapping[str, Any] | list[Any]) -> list[NewsEvent]:
    if isinstance(payload, (str, bytes)):
        try:
            decoded = json.loads(_bounded_payload(payload))
        except json.JSONDecodeError as exc:
            raise NewsParseError("invalid Alpaca JSON") from exc
    else:
        decoded = payload

    items = decoded.get("news", []) if isinstance(decoded, Mapping) else decoded
    if not isinstance(items, list):
        raise NewsParseError("Alpaca payload must contain a news list")

    events: list[NewsEvent] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise NewsParseError("Alpaca news item must be an object")
        events.append(
            _event(
                source="alpaca",
                external_id=item.get("id"),
                published_at=str(item.get("created_at") or item.get("updated_at") or ""),
                headline=item.get("headline"),
                summary=item.get("summary", ""),
                symbols=item.get("symbols", ()),
                url=item.get("url"),
                metadata={"author": clean_text(item.get("author", ""))},
            )
        )
    return events


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _entry_link(element: ET.Element) -> str | None:
    for child in element:
        if _local_name(child.tag) == "link":
            return child.attrib.get("href") or (child.text or "").strip() or None
    return None


def parse_atom(payload: str | bytes, *, source: str) -> list[NewsEvent]:
    text = _bounded_payload(payload)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise NewsParseError("invalid Atom XML") from exc

    events: list[NewsEvent] = []
    for entry in (element for element in root.iter() if _local_name(element.tag) == "entry"):
        categories = [
            child.attrib.get("term", "")
            for child in entry
            if _local_name(child.tag) == "category" and child.attrib.get("term")
        ]
        events.append(
            _event(
                source=source,
                external_id=_child_text(entry, "id"),
                published_at=_child_text(entry, "updated"),
                headline=_child_text(entry, "title"),
                summary=_child_text(entry, "summary") or _child_text(entry, "content"),
                url=_entry_link(entry),
                metadata={"categories": ",".join(categories)},
            )
        )
    return events


def parse_sec_atom(payload: str | bytes) -> list[NewsEvent]:
    try:
        return parse_atom(payload, source="sec-edgar")
    except NewsParseError as exc:
        if str(exc) == "invalid Atom XML":
            raise NewsParseError("invalid SEC Atom XML") from exc
        raise


def parse_rss(payload: str | bytes, *, source: str) -> list[NewsEvent]:
    text = _bounded_payload(payload)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise NewsParseError("invalid RSS XML") from exc

    events: list[NewsEvent] = []
    for item in (element for element in root.iter() if _local_name(element.tag) == "item"):
        headline = _child_text(item, "title")
        url = _child_text(item, "link") or None
        external_id = _child_text(item, "guid") or url or headline
        published = _child_text(item, "pubDate") or _child_text(item, "date")
        symbols = [
            child.attrib.get("ticker", "")
            for child in item
            if _local_name(child.tag) == "category" and child.attrib.get("ticker")
        ]
        events.append(
            _event(
                source=source,
                external_id=external_id,
                published_at=published,
                headline=headline,
                summary=_child_text(item, "description"),
                symbols=symbols,
                url=url,
            )
        )
    return events


def deduplicate(events: Iterable[NewsEvent]) -> list[NewsEvent]:
    unique: dict[tuple[str, str], NewsEvent] = {}
    for event in events:
        key = (event.source, event.external_id)
        previous = unique.get(key)
        if previous is None or event.published_at > previous.published_at:
            unique[key] = event
    return sorted(unique.values(), key=lambda event: event.published_at)


def bind_symbol(events: Iterable[NewsEvent], symbol: str) -> list[NewsEvent]:
    """Attach an explicit issuer mapping to a company-specific feed."""
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol cannot be blank")
    return [
        NewsEvent(
            source=event.source,
            external_id=event.external_id,
            published_at=event.published_at,
            headline=event.headline,
            summary=event.summary,
            symbols=tuple(sorted(set(event.symbols) | {normalized})),
            url=event.url,
            metadata=event.metadata,
            content_hash=event.content_hash,
        )
        for event in events
    ]
