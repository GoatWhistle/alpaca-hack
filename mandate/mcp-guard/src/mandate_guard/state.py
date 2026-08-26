from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class JournalEntry:
    at: datetime
    action: str
    outcome: str
    rationale: str
    details: dict[str, Any] = field(default_factory=dict)


class SessionJournal:
    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def append(
        self, action: str, outcome: str, rationale: str, details: dict[str, Any] | None = None
    ) -> JournalEntry:
        entry = JournalEntry(
            at=datetime.now(timezone.utc),
            action=action,
            outcome=outcome,
            rationale=rationale,
            details=details or {},
        )
        self._entries.append(entry)
        return entry

    def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in self._entries]
