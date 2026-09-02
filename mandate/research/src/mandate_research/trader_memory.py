from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


MEMORY_SCHEMA = "trader.memory.v1"
MEMORY_KEY_MAX = 80
HYPOTHESIS_MAX = 500
MAX_EVIDENCE_REFS = 12
MAX_TTL_HOURS = 168


def _clean_text(value: str, *, label: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise ValueError(f"{label} must contain 1..{limit} characters")
    return normalized


def _event_id(memory_key: str) -> str:
    return hashlib.sha256(f"operator|{memory_key}".encode()).hexdigest()


def read_active_memory(path: str | Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    memory_path = Path(path)
    if not memory_path.exists():
        return []
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    active: list[dict[str, Any]] = []
    for line in memory_path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            # A killed append may leave a partial JSONL tail. Memory is advisory;
            # keep valid immutable events available instead of taking the MCP down.
            continue
        if not isinstance(item, dict) or item.get("schema") != MEMORY_SCHEMA:
            continue
        try:
            expires_at = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if expires_at.astimezone(timezone.utc) > checked_at:
            active.append(item)
    return active


def append_operator_memory(
    path: str | Path,
    *,
    memory_key: str,
    hypothesis: str,
    evidence_refs: Sequence[str],
    ttl_hours: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = _clean_text(memory_key, label="memory_key", limit=MEMORY_KEY_MAX)
    statement = _clean_text(hypothesis, label="hypothesis", limit=HYPOTHESIS_MAX)
    if isinstance(ttl_hours, bool) or not 1 <= ttl_hours <= MAX_TTL_HOURS:
        raise ValueError(f"ttl_hours must be between 1 and {MAX_TTL_HOURS}")
    if not 1 <= len(evidence_refs) <= MAX_EVIDENCE_REFS:
        raise ValueError(f"evidence_refs must contain 1..{MAX_EVIDENCE_REFS} items")
    evidence = [
        _clean_text(str(value), label="evidence ref", limit=300)
        for value in evidence_refs
    ]
    memory_path = Path(path)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    event_id = _event_id(key)
    if memory_path.exists():
        for item in read_active_memory(memory_path, now=datetime.min.replace(tzinfo=timezone.utc)):
            if item.get("event_id") == event_id:
                return item
    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event = {
        "schema": MEMORY_SCHEMA,
        "event_id": event_id,
        "cycle_id": f"operator:{key}",
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(hours=ttl_hours)).isoformat(),
        "hypothesis": statement,
        "evidence_refs": evidence,
    }
    separator = b""
    if memory_path.exists() and memory_path.stat().st_size > 0:
        with memory_path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            if existing.read(1) != b"\n":
                separator = b"\n"
    descriptor = os.open(memory_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        os.write(descriptor, separator + encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return event
