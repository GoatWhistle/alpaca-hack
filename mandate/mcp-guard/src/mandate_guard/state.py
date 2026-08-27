from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JournalEntry:
    at: datetime
    action: str
    outcome: str
    rationale: str
    details: dict[str, Any] = field(default_factory=dict)


class SessionJournal:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[JournalEntry] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                for line_number, line in enumerate(
                    self.path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    try:
                        item = json.loads(line)
                        self._entries.append(
                            JournalEntry(
                                at=datetime.fromisoformat(item["at"]),
                                action=item["action"],
                                outcome=item["outcome"],
                                rationale=item["rationale"],
                                details=item.get("details", {}),
                            )
                        )
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid journal entry at line {line_number}") from exc

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
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(asdict(entry), default=_json_default, sort_keys=True))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        self._entries.append(entry)
        return entry

    def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in self._entries]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported journal value: {type(value).__name__}")
