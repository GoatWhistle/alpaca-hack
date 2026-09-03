from __future__ import annotations

import json
import os
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mandate_research.trader_memory import read_active_memory


CONTEXT_SCHEMA = "trader.context.v1"
TIMELINE_SCHEMA = "trader.timeline.v1"
DEFAULT_EVENT_LIMIT = 12
MAX_EVENT_LIMIT = 20
MAX_SUMMARY_CHARS = 400
MAX_MEMORY_ITEMS = 8
MAX_STRATEGY_ACTIONS = 5
MAX_TIMELINE_BYTES = 512 * 1024
TIMELINE_KINDS = {
    "trigger", "news", "reasoning", "tool_call", "tool_result", "hypothesis",
    "critics", "plan", "execution", "risk_exit", "session",
}
TIMELINE_STATUSES = {"ok", "parked", "submitted", "degraded"}


def _bounded_tail(path: Path) -> list[str]:
    with path.open("rb") as timeline:
        timeline.seek(0, os.SEEK_END)
        size = timeline.tell()
        offset = max(0, size - MAX_TIMELINE_BYTES)
        timeline.seek(offset)
        payload = timeline.read(MAX_TIMELINE_BYTES)
    if offset:
        _, separator, payload = payload.partition(b"\n")
        if not separator:
            return []
    return payload.decode("utf-8", errors="replace").splitlines()


def _compact_event(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("schema") != TIMELINE_SCHEMA:
        return None
    sequence = item.get("sequence")
    summary = item.get("summary")
    at = item.get("at")
    kind = item.get("kind")
    status = item.get("status")
    trading_date = item.get("trading_date")
    session_id = item.get("session_id")
    if (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0
        or not isinstance(summary, str) or not summary.strip()
        or not isinstance(at, str) or kind not in TIMELINE_KINDS
        or status not in TIMELINE_STATUSES
        or not isinstance(trading_date, str)
        or (session_id is not None and not isinstance(session_id, str))):
        return None
    try:
        parsed_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        date.fromisoformat(trading_date)
    except ValueError:
        return None
    if parsed_at.tzinfo is None:
        return None
    return {
        "sequence": sequence,
        "at": at,
        "trading_date": trading_date,
        "kind": kind,
        "status": status,
        "session_id": session_id,
        "summary": " ".join(summary.split())[:MAX_SUMMARY_CHARS],
    }


def _compact_strategy(path: Path | None, errors: list[str]) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("runtime_unavailable")
        return None
    strategy = payload.get("active_strategy") if isinstance(payload, dict) else None
    if not isinstance(strategy, dict) or strategy.get("schema") != "trader.strategy.v1":
        return None
    allowed_action_fields = (
        "candidate_id", "symbol", "state", "side", "instrument", "quantity", "notional",
        "reference_price", "atr14", "stop_price", "target_price", "risk_cash", "target_cash",
        "reward_to_risk", "entry", "exit", "thesis", "invalidation", "blockers",
    )
    actions = []
    raw_actions = strategy.get("actions")
    for raw in (raw_actions if isinstance(raw_actions, list) else [])[:MAX_STRATEGY_ACTIONS]:
        if not isinstance(raw, dict):
            continue
        action = {key: raw.get(key) for key in allowed_action_fields}
        action["thesis"] = str(action.get("thesis") or "")[:300]
        action["invalidation"] = str(action.get("invalidation") or "")[:300]
        blockers = action.get("blockers")
        action["blockers"] = [str(item)[:100] for item in blockers[:8]] if isinstance(blockers, list) else []
        actions.append(action)
    return {
        "schema": "trader.strategy.v1",
        "version": strategy.get("version"),
        "updated_at": strategy.get("updated_at"),
        "market_phase": strategy.get("market_phase"),
        "status": strategy.get("status"),
        "reason": str(strategy.get("reason") or "")[:400],
        "focus_candidate_id": strategy.get("focus_candidate_id"),
        "actions": actions,
    }


def read_trader_context(
    timeline_path: str | Path,
    memory_path: str | Path,
    *,
    runtime_path: str | Path | None = None,
    max_events: int = DEFAULT_EVENT_LIMIT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a token-bounded, fail-soft context shared by trader and operator."""
    if isinstance(max_events, bool) or not 1 <= max_events <= MAX_EVENT_LIMIT:
        raise ValueError(f"max_events must be between 1 and {MAX_EVENT_LIMIT}")

    events: deque[dict[str, Any]] = deque(maxlen=max_events)
    path = Path(timeline_path)
    errors: list[str] = []
    if path.exists():
        try:
            for raw_line in _bounded_tail(path):
                try:
                    raw = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    compact = _compact_event(raw)
                    if compact is not None:
                        events.append(compact)
        except OSError:
            errors.append("timeline_unavailable")

    items = list(events)
    current_session_id = next(
        (item["session_id"] for item in reversed(items) if item["session_id"]),
        None,
    )
    captured_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    try:
        active_memory = read_active_memory(memory_path, now=now)
    except OSError:
        active_memory = []
        errors.append("memory_unavailable")
    compact_memory = []
    for item in active_memory[-MAX_MEMORY_ITEMS:]:
        refs = item.get("evidence_refs")
        compact_memory.append({
            "event_id": item.get("event_id"),
            "created_at": item.get("created_at"),
            "expires_at": item.get("expires_at"),
            "hypothesis": str(item.get("hypothesis", ""))[:500],
            "evidence_refs": [str(ref)[:200] for ref in refs[:4]] if isinstance(refs, list) else [],
        })

    strategy = _compact_strategy(Path(runtime_path) if runtime_path is not None else None, errors)
    return {
        "schema": CONTEXT_SCHEMA,
        "captured_at": captured_at,
        "current_session_id": current_session_id,
        "timeline": items,
        "memory": compact_memory,
        "strategy": strategy,
        "errors": errors,
        "contract": {
            "timeline_order": "oldest_to_newest",
            "execution_authority": False,
            "memory_changes_require_approval": True,
            "content_trust": "untrusted_data",
        },
    }
