from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mandate_research.news import NewsEvent, clean_text


EVENT_SCHEMA = "news.event.v1"
GATE_REQUEST_SCHEMA = "news.gate.request.v1"
GATE_RESPONSE_SCHEMA = "news.gate.response.v1"
GATE_ERROR_SCHEMA = "news.gate.error.v1"
RELATED_WINDOW = timedelta(hours=72)
RELATED_JACCARD_THRESHOLD = 0.65
MAX_GATE_HEADLINE_CHARS = 400
MAX_GATE_SUMMARY_CHARS = 1_200
MAX_GATE_REASON_CHARS = 160

# Deliberately small and fixed: changing this set changes graph topology.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "will", "with",
})


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    current_event_id TEXT,
    first_seen_at TEXT NOT NULL,
    UNIQUE(source, external_id),
    FOREIGN KEY(current_event_id) REFERENCES revisions(event_id)
);

CREATE TABLE IF NOT EXISTS revisions (
    event_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    published_at TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    url TEXT,
    metadata_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(story_id, content_hash),
    FOREIGN KEY(story_id) REFERENCES stories(story_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS revisions_story_published
ON revisions(story_id, published_at DESC, event_id DESC);

CREATE TABLE IF NOT EXISTS story_relations (
    left_story_id TEXT NOT NULL,
    right_story_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK(relation IN ('DUPLICATE_OF', 'RELATED_TO')),
    reason TEXT NOT NULL,
    similarity REAL NOT NULL,
    PRIMARY KEY(left_story_id, right_story_id),
    CHECK(left_story_id < right_story_id),
    FOREIGN KEY(left_story_id) REFERENCES stories(story_id) ON DELETE CASCADE,
    FOREIGN KEY(right_story_id) REFERENCES stories(story_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate_requests (
    request_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    model TEXT NOT NULL,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES revisions(event_id) ON DELETE CASCADE,
    FOREIGN KEY(story_id) REFERENCES stories(story_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate_attempts (
    request_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('PENDING', 'COMPLETED', 'ERROR')),
    reason TEXT,
    decision TEXT CHECK(decision IN ('PASS', 'SKIP') OR decision IS NULL),
    error_type TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1)),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY(request_id, attempt_no),
    FOREIGN KEY(request_id) REFERENCES gate_requests(request_id) ON DELETE CASCADE,
    CHECK(
        (state = 'COMPLETED' AND decision IS NOT NULL AND error_type IS NULL AND retryable = 0)
        OR (state = 'ERROR' AND decision IS NULL AND error_type IS NOT NULL)
        OR (state = 'PENDING' AND decision IS NULL AND error_type IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class IngestResult:
    story_id: str
    event_id: str
    story_created: bool
    revision_created: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_utc(value: Any, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _symbols(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("symbols must be an array")
    return tuple(sorted({str(value).strip().upper() for value in values if str(value).strip()}))


def _metadata(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    return {str(key): str(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}


def _normalized_content(headline: str, summary: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", f"{headline} {summary}".lower()))


def _normalized_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _headline_tokens(headline: str) -> frozenset[str]:
    return frozenset(
        token for token in re.findall(r"[a-z0-9]+", headline.lower())
        if token not in STOPWORDS
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def story_id_for(source: str, external_id: str) -> str:
    return _sha256(clean_text(source), clean_text(external_id))


def content_hash_for(payload: Mapping[str, Any]) -> str:
    content = {
        "published_at": payload["published_at"],
        "headline": payload["headline"],
        "summary": payload["summary"],
        "symbols": payload["symbols"],
        "url": payload["url"],
        "metadata": payload["metadata"],
    }
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def event_id_for(source: str, external_id: str, content_hash: str) -> str:
    return _sha256(clean_text(source), clean_text(external_id), content_hash)


def legacy_news_event(event: NewsEvent) -> dict[str, Any]:
    """Convert the pre-graph ``NewsEvent`` into an idempotent news.event.v1 envelope."""
    payload: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "source": clean_text(event.source),
        "external_id": clean_text(event.external_id),
        "published_at": event.published_at.astimezone(timezone.utc).isoformat(),
        "headline": clean_text(event.headline),
        "summary": clean_text(event.summary),
        "symbols": list(_symbols(list(event.symbols))),
        "url": str(event.url).strip() if event.url else None,
        "metadata": _metadata(event.metadata),
    }
    content_hash = content_hash_for(payload)
    payload["content_hash"] = content_hash
    payload["event_id"] = event_id_for(payload["source"], payload["external_id"], content_hash)
    return payload


def gate_request_id_for(body: Mapping[str, Any], *, model: str) -> str:
    if not model.strip():
        raise ValueError("model cannot be blank")
    return _sha256(GATE_REQUEST_SCHEMA, model, _canonical_json(body))


def gate_request_for_event(
    event: NewsEvent,
    *,
    target_symbols: Sequence[str],
    model: str,
    source_count: int = 1,
) -> dict[str, Any]:
    symbols = list(_symbols(list(target_symbols)))
    if not symbols:
        raise ValueError("target_symbols cannot be empty")
    if source_count < 1:
        raise ValueError("source_count must be positive")
    body = {
        "story_id": story_id_for(event.source, event.external_id),
        "target_symbols": symbols,
        "published_at": event.published_at.astimezone(timezone.utc).isoformat(),
        "source_count": source_count,
        "headline": clean_text(event.headline)[:MAX_GATE_HEADLINE_CHARS],
        "summary": clean_text(event.summary)[:MAX_GATE_SUMMARY_CHARS],
    }
    return {
        "schema": GATE_REQUEST_SCHEMA,
        "request_id": gate_request_id_for(body, model=model),
        **body,
    }


def _validated_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != EVENT_SCHEMA:
        raise ValueError(f"schema must be {EVENT_SCHEMA}")
    source = clean_text(value.get("source", ""))
    external_id = clean_text(value.get("external_id", ""))
    headline = clean_text(value.get("headline", ""))
    if not source or not external_id or not headline:
        raise ValueError("source, external_id, and headline are required")
    payload: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "source": source,
        "external_id": external_id,
        "published_at": _iso_utc(value.get("published_at"), "published_at"),
        "headline": headline,
        "summary": clean_text(value.get("summary", "")),
        "symbols": list(_symbols(value.get("symbols", []))),
        "url": str(value["url"]).strip() if value.get("url") else None,
        "metadata": _metadata(value.get("metadata")),
    }
    content_hash = content_hash_for(payload)
    expected_event_id = event_id_for(source, external_id, content_hash)
    if value.get("content_hash") != content_hash:
        raise ValueError("content_hash does not match normalized event content")
    if value.get("event_id") != expected_event_id:
        raise ValueError("event_id does not match source|external_id|content_hash")
    payload["content_hash"] = content_hash
    payload["event_id"] = expected_event_id
    return payload


class NewsGraphStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            connection.close()
            raise RuntimeError("news graph requires SQLite WAL mode")
        return connection

    def ingest(self, value: Mapping[str, Any]) -> IngestResult:
        event = _validated_event(value)
        story_id = story_id_for(event["source"], event["external_id"])
        now = _utc_now()
        with self._connect() as connection:
            # Serialize the read-before-insert section across evaluator
            # subprocesses. WAL permits concurrent readers, but not concurrent
            # writers racing on the same deterministic event id.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json, story_id FROM revisions WHERE event_id = ?",
                (event["event_id"],),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != _canonical_json(event) or existing["story_id"] != story_id:
                    raise ValueError("event_id was already ingested with a different payload")
                return IngestResult(story_id, event["event_id"], False, False)

            story_created = connection.execute(
                "SELECT 1 FROM stories WHERE story_id = ?", (story_id,)
            ).fetchone() is None
            if story_created:
                connection.execute(
                    "INSERT INTO stories(story_id, source, external_id, first_seen_at) VALUES (?, ?, ?, ?)",
                    (story_id, event["source"], event["external_id"], now),
                )
            connection.execute(
                """
                INSERT INTO revisions(
                    event_id, story_id, content_hash, published_at, headline, summary,
                    symbols_json, url, metadata_json, payload_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"], story_id, event["content_hash"], event["published_at"],
                    event["headline"], event["summary"], _canonical_json(event["symbols"]),
                    event["url"], _canonical_json(event["metadata"]), _canonical_json(event), now,
                ),
            )
            current = connection.execute(
                """
                SELECT event_id FROM revisions WHERE story_id = ?
                ORDER BY published_at DESC, event_id DESC LIMIT 1
                """,
                (story_id,),
            ).fetchone()
            connection.execute(
                "UPDATE stories SET current_event_id = ? WHERE story_id = ?",
                (current["event_id"], story_id),
            )
            self._refresh_story_relations(connection, story_id)
        return IngestResult(story_id, event["event_id"], story_created, True)

    def _refresh_story_relations(self, connection: sqlite3.Connection, story_id: str) -> None:
        """Recompute only edges touching the changed story (O(stories), not O(stories²))."""
        current = connection.execute(
            """
            SELECT s.story_id, r.published_at, r.headline, r.summary, r.url
            FROM stories s JOIN revisions r ON r.event_id = s.current_event_id
            WHERE s.story_id = ?
            """,
            (story_id,),
        ).fetchone()
        if current is None:
            raise KeyError(story_id)
        others = connection.execute(
            """
            SELECT s.story_id, r.published_at, r.headline, r.summary, r.url
            FROM stories s JOIN revisions r ON r.event_id = s.current_event_id
            WHERE s.story_id != ? ORDER BY s.story_id
            """,
            (story_id,),
        ).fetchall()
        connection.execute(
            "DELETE FROM story_relations WHERE left_story_id = ? OR right_story_id = ?",
            (story_id, story_id),
        )
        for other in others:
            left, right = (current, other) if story_id < other["story_id"] else (other, current)
            left_content = _normalized_content(left["headline"], left["summary"])
            right_content = _normalized_content(right["headline"], right["summary"])
            same_content = bool(left_content) and left_content == right_content
            left_url = _normalized_url(left["url"])
            right_url = _normalized_url(right["url"])
            same_url = bool(left_url and right_url and left_url == right_url)
            if same_content or same_url:
                reason = "same_normalized_content" if same_content else "same_url"
                connection.execute(
                    "INSERT INTO story_relations VALUES (?, ?, 'DUPLICATE_OF', ?, 1.0)",
                    (left["story_id"], right["story_id"], reason),
                )
                continue
            left_time = datetime.fromisoformat(left["published_at"])
            right_time = datetime.fromisoformat(right["published_at"])
            if abs(left_time - right_time) > RELATED_WINDOW:
                continue
            similarity = _jaccard(
                _headline_tokens(left["headline"]), _headline_tokens(right["headline"]),
            )
            if similarity >= RELATED_JACCARD_THRESHOLD:
                connection.execute(
                    "INSERT INTO story_relations VALUES (?, ?, 'RELATED_TO', ?, ?)",
                    (
                        left["story_id"], right["story_id"],
                        f"headline_jaccard_{similarity:.6f}", round(similarity, 6),
                    ),
                )

    def revision(self, event_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json, story_id FROM revisions WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return {**json.loads(row["payload_json"]), "story_id": row["story_id"]}

    def relations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM story_relations ORDER BY left_story_id, right_story_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("stories", "revisions", "story_relations", "gate_requests", "gate_attempts")
            }

    def _duplicate_source_count(self, connection: sqlite3.Connection, story_id: str) -> int:
        rows = connection.execute(
            """
            SELECT left_story_id, right_story_id FROM story_relations
            WHERE relation = 'DUPLICATE_OF'
            """
        ).fetchall()
        adjacent: dict[str, set[str]] = {}
        for row in rows:
            adjacent.setdefault(row["left_story_id"], set()).add(row["right_story_id"])
            adjacent.setdefault(row["right_story_id"], set()).add(row["left_story_id"])
        seen = {story_id}
        pending = [story_id]
        while pending:
            for candidate in adjacent.get(pending.pop(), set()) - seen:
                seen.add(candidate)
                pending.append(candidate)
        placeholders = ",".join("?" for _ in seen)
        return int(connection.execute(
            f"SELECT COUNT(DISTINCT source) FROM stories WHERE story_id IN ({placeholders})",
            tuple(sorted(seen)),
        ).fetchone()[0])

    def prepare_gate_request(
        self,
        event_id: str,
        *,
        target_symbols: Sequence[str],
        model: str,
    ) -> dict[str, Any]:
        symbols = list(_symbols(list(target_symbols)))
        if not symbols:
            raise ValueError("target_symbols cannot be empty")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.event_id, r.story_id, r.published_at, r.headline, r.summary
                FROM revisions r WHERE r.event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            source_count = self._duplicate_source_count(connection, row["story_id"])
            body = {
                "story_id": row["story_id"],
                "target_symbols": symbols,
                "published_at": row["published_at"],
                "source_count": source_count,
                "headline": clean_text(row["headline"])[:MAX_GATE_HEADLINE_CHARS],
                "summary": clean_text(row["summary"])[:MAX_GATE_SUMMARY_CHARS],
            }
            request_id = gate_request_id_for(body, model=model)
            request = {
                "schema": GATE_REQUEST_SCHEMA,
                "request_id": request_id,
                **body,
            }
            connection.execute(
                """
                INSERT OR IGNORE INTO gate_requests(
                    request_id, event_id, story_id, model, request_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (request_id, event_id, row["story_id"], model, _canonical_json(request), _utc_now()),
            )
        return request

    def completed_gate_response(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT reason, decision FROM gate_attempts
                WHERE request_id = ? AND state = 'COMPLETED'
                ORDER BY attempt_no DESC LIMIT 1
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "schema": GATE_RESPONSE_SCHEMA,
            "request_id": request_id,
            "reason": row["reason"],
            "decision": row["decision"],
        }

    def latest_gate_error(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT attempt_no, reason, error_type, retryable, finished_at FROM gate_attempts
                WHERE request_id = ? AND state = 'ERROR'
                ORDER BY attempt_no DESC LIMIT 1
                """,
                (request_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def begin_gate_attempt(self, request_id: str) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM gate_requests WHERE request_id = ?", (request_id,)
            ).fetchone() is None:
                raise KeyError(request_id)
            attempt_no = int(connection.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM gate_attempts WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO gate_attempts(request_id, attempt_no, state, started_at)
                VALUES (?, ?, 'PENDING', ?)
                """,
                (request_id, attempt_no, _utc_now()),
            )
        return attempt_no

    def complete_gate_attempt(
        self, request_id: str, attempt_no: int, *, reason: str, decision: str
    ) -> None:
        bounded_reason = clean_text(reason)[:MAX_GATE_REASON_CHARS]
        normalized_decision = decision.strip().upper()
        if not bounded_reason or normalized_decision not in {"PASS", "SKIP"}:
            raise ValueError("completed gate requires reason and PASS|SKIP decision")
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE gate_attempts SET state = 'COMPLETED', reason = ?, decision = ?,
                    retryable = 0, finished_at = ?
                WHERE request_id = ? AND attempt_no = ? AND state = 'PENDING'
                """,
                (bounded_reason, normalized_decision, _utc_now(), request_id, attempt_no),
            ).rowcount
        if changed != 1:
            raise ValueError("gate attempt is not pending")

    def fail_gate_attempt(
        self,
        request_id: str,
        attempt_no: int,
        *,
        reason: str,
        error_type: str,
        retryable: bool = True,
    ) -> None:
        bounded_reason = clean_text(reason)[:MAX_GATE_REASON_CHARS] or "gate unavailable"
        bounded_type = clean_text(error_type)[:80] or "GateError"
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE gate_attempts SET state = 'ERROR', reason = ?, error_type = ?,
                    retryable = ?, finished_at = ?
                WHERE request_id = ? AND attempt_no = ? AND state = 'PENDING'
                """,
                (bounded_reason, bounded_type, int(retryable), _utc_now(), request_id, attempt_no),
            ).rowcount
        if changed != 1:
            raise ValueError("gate attempt is not pending")

    def gate_attempts(self, request_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_no, state, reason, decision, error_type, retryable
                FROM gate_attempts WHERE request_id = ? ORDER BY attempt_no
                """,
                (request_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def migration(self, name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT applied_at, details_json FROM migrations WHERE name = ?", (name,),
            ).fetchone()
        return (
            {"name": name, "applied_at": row["applied_at"], "details": json.loads(row["details_json"])}
            if row is not None else None
        )

    def mark_migration(self, name: str, details: Mapping[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO migrations(name, applied_at, details_json) VALUES (?, ?, ?)",
                (name, _utc_now(), _canonical_json(dict(details))),
            )


def import_legacy_news(store: NewsGraphStore, events: Iterable[NewsEvent]) -> list[IngestResult]:
    """Import old in-memory events through the same news.event.v1 validation path."""
    return [store.ingest(legacy_news_event(event)) for event in events]


def import_legacy_alerts_once(store: NewsGraphStore, path: str | Path) -> dict[str, Any]:
    """One-shot import of the former news-alert JSONL projection."""
    migration_name = "legacy-news-alerts-v1"
    previous = store.migration(migration_name)
    if previous is not None:
        return {"status": "already_applied", **previous["details"]}
    alerts_path = Path(path)
    imported = 0
    skipped = 0
    if alerts_path.exists():
        for line in alerts_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or item.get("kind") != "news":
                    skipped += 1
                    continue
                event = NewsEvent(
                    source=str(item["source"]),
                    external_id=str(item["external_id"]),
                    published_at=datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00")),
                    headline=str(item["headline"]),
                    summary=str(item.get("summary", "")),
                    symbols=tuple(str(value) for value in item.get("symbols", [])),
                    url=str(item["url"]) if item.get("url") else None,
                )
                store.ingest(legacy_news_event(event))
                imported += 1
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                skipped += 1
    details = {"imported": imported, "skipped": skipped}
    store.mark_migration(migration_name, details)
    return {"status": "applied", **details}
