from decimal import Decimal

import pytest

from mandate_guard.checks import Side
from mandate_guard.state import SessionJournal


def test_jsonl_journal_survives_process_recreation(tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    first = SessionJournal(path)
    first.append(
        "submit_order",
        "denied",
        "limit breach",
        {"qty": Decimal("1.25"), "side": Side.BUY},
    )

    restored = SessionJournal(path)
    assert len(restored.snapshot()) == 1
    assert restored.snapshot()[0]["rationale"] == "limit breach"
    assert restored.snapshot()[0]["details"] == {"qty": "1.25", "side": "buy"}


def test_corrupt_journal_fails_closed(tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"action":"missing fields"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        SessionJournal(path)
