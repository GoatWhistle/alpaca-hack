from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from mandate_research.news import NewsEvent
from mandate_research.news_graph import (
    NewsGraphStore,
    import_legacy_alerts_once,
    import_legacy_news,
    legacy_news_event,
)


NOW = datetime(2026, 9, 2, 14, 30, tzinfo=timezone.utc)


def _event(
    source: str,
    external_id: str,
    headline: str,
    *,
    published_at: datetime = NOW,
    summary: str = "",
    url: str | None = None,
) -> NewsEvent:
    return NewsEvent(
        source=source,
        external_id=external_id,
        published_at=published_at,
        headline=headline,
        summary=summary,
        symbols=("AAPL",),
        url=url,
    )


def test_store_uses_wal_and_explicit_schema(tmp_path) -> None:
    path = tmp_path / "news.db"
    NewsGraphStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "stories", "revisions", "story_relations", "gate_requests", "gate_attempts",
    } <= tables


def test_news_event_v1_ingest_is_idempotent_and_revisions_are_immutable(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    first_envelope = legacy_news_event(_event("alpaca", "42", "Original headline"))
    first = store.ingest(first_envelope)
    replay = store.ingest(first_envelope)
    revised = store.ingest(legacy_news_event(_event(
        "alpaca",
        "42",
        "Corrected headline",
        published_at=NOW + timedelta(minutes=2),
    )))

    assert first.story_created is True and first.revision_created is True
    assert first.story_id == hashlib.sha256(b"alpaca|42").hexdigest()
    assert first.event_id == hashlib.sha256(
        f"alpaca|42|{first_envelope['content_hash']}".encode()
    ).hexdigest()
    assert replay.story_id == first.story_id
    assert replay.event_id == first.event_id
    assert replay.story_created is False and replay.revision_created is False
    assert revised.story_id == first.story_id
    assert revised.event_id != first.event_id
    assert store.counts()["stories"] == 1
    assert store.counts()["revisions"] == 2

    corrupted = dict(first_envelope, headline="Different payload")
    with pytest.raises(ValueError, match="content_hash"):
        store.ingest(corrupted)


def test_concurrent_idempotent_ingest_is_serialized(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    envelope = legacy_news_event(_event("alpaca", "concurrent", "Concurrent headline"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.ingest(envelope), range(24)))

    assert sum(result.revision_created for result in results) == 1
    assert store.counts()["stories"] == 1
    assert store.counts()["revisions"] == 1


def test_exact_content_or_url_creates_duplicate_relation_without_merging(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    left = store.ingest(legacy_news_event(_event(
        "alpaca", "a", "Apple announces a new AI accelerator", summary="Ships next month",
    )))
    right = store.ingest(legacy_news_event(_event(
        "issuer-rss", "b", "APPLE announces: a new AI accelerator!", summary="Ships next month.",
    )))
    third = store.ingest(legacy_news_event(_event(
        "sec", "c", "Form 8-K filed", url="HTTPS://EXAMPLE.TEST/item/1/?b=2&a=1#top",
    )))
    fourth = store.ingest(legacy_news_event(_event(
        "wire", "d", "Regulatory filing available", url="https://example.test/item/1?a=1&b=2",
    )))

    assert len({left.story_id, right.story_id, third.story_id, fourth.story_id}) == 4
    assert store.counts()["stories"] == 4
    duplicates = [item for item in store.relations() if item["relation"] == "DUPLICATE_OF"]
    assert {(item["reason"], item["similarity"]) for item in duplicates} == {
        ("same_normalized_content", 1.0),
        ("same_url", 1.0),
    }

    request = store.prepare_gate_request(left.event_id, target_symbols=["aapl"], model="glm-test")
    assert request["source_count"] == 2
    assert request["story_id"] == left.story_id


def test_related_uses_72h_window_and_point_65_jaccard_without_merging(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    left = store.ingest(legacy_news_event(_event(
        "alpaca", "a", "Apple launches AI chip platform for data centers",
    )))
    right = store.ingest(legacy_news_event(_event(
        "wire", "b", "Apple launches new AI chip platform for global data centers",
        published_at=NOW + timedelta(hours=72),
    )))
    late = store.ingest(legacy_news_event(_event(
        "late-wire", "c", "Apple launches AI chip platform for data centers worldwide",
        published_at=NOW + timedelta(hours=72, seconds=1),
    )))

    related = [item for item in store.relations() if item["relation"] == "RELATED_TO"]
    related_pairs = [
        {item["left_story_id"], item["right_story_id"]}
        for item in related
    ]
    assert {left.story_id, right.story_id} in related_pairs
    assert {left.story_id, late.story_id} not in related_pairs
    assert all(item["similarity"] >= 0.65 for item in related)
    assert store.counts()["stories"] == 3


def test_legacy_import_reuses_news_event_v1_path_and_bounds_gate_envelope(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    event = _event("legacy", "1", "H" * 1_000, summary="S" * 2_000)
    first = import_legacy_news(store, [event])[0]
    second = import_legacy_news(store, [event])[0]
    request = store.prepare_gate_request(
        first.event_id,
        target_symbols=[" aapl ", "AAPL"],
        model="glm-test",
    )

    assert second.revision_created is False
    assert request["schema"] == "news.gate.request.v1"
    assert len(request["headline"]) == 400
    assert len(request["summary"]) == 1_200
    assert request["target_symbols"] == ["AAPL"]
    assert list(request) == [
        "schema", "request_id", "story_id", "target_symbols", "published_at",
        "source_count", "headline", "summary",
    ]


def test_legacy_alert_jsonl_import_runs_once(tmp_path) -> None:
    store = NewsGraphStore(tmp_path / "news.db")
    alerts = tmp_path / "news-alerts.jsonl"
    alerts.write_text(
        json.dumps({
            "kind": "news", "source": "legacy", "external_id": "42",
            "published_at": NOW.isoformat(), "headline": "Legacy headline",
            "summary": "Imported once", "symbols": ["AAPL"], "url": None,
        }) + "\n" + json.dumps({"kind": "delivery", "count": 1}) + "\n",
        encoding="utf-8",
    )

    first = import_legacy_alerts_once(store, alerts)
    second = import_legacy_alerts_once(store, alerts)

    assert first == {"status": "applied", "imported": 1, "skipped": 1}
    assert second == {"status": "already_applied", "imported": 1, "skipped": 1}
    assert store.counts()["stories"] == 1
