from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mandate_research.trader_memory import append_operator_memory, read_active_memory


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def test_operator_memory_is_idempotent_append_only_and_expires(tmp_path) -> None:
    path = tmp_path / "trader-memory.jsonl"
    first = append_operator_memory(
        path,
        memory_key="opening-gap-risk",
        hypothesis="Opening gaps above 3% need confirmation before entry.",
        evidence_refs=["operator:postmortem:42"],
        ttl_hours=24,
        now=NOW,
    )
    replay = append_operator_memory(
        path,
        memory_key="opening-gap-risk",
        hypothesis="Opening gaps above 3% need confirmation before entry.",
        evidence_refs=["operator:postmortem:42"],
        ttl_hours=24,
        now=NOW + timedelta(minutes=1),
    )

    assert replay == first
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert read_active_memory(path, now=NOW + timedelta(hours=23)) == [first]
    assert read_active_memory(path, now=NOW + timedelta(hours=25)) == []


def test_memory_reader_skips_corrupt_records_without_hiding_valid_events(tmp_path) -> None:
    path = tmp_path / "trader-memory.jsonl"
    event = append_operator_memory(
        path,
        memory_key="valid-event",
        hypothesis="Valid evidence remains readable after a partial append.",
        evidence_refs=["operator:test"],
        ttl_hours=24,
        now=NOW,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"schema":"trader.memory.v1"')
    assert read_active_memory(path, now=NOW) == [event]
    second = append_operator_memory(
        path,
        memory_key="second-valid-event",
        hypothesis="A later append remains a separate valid JSONL record.",
        evidence_refs=["operator:test:2"],
        ttl_hours=24,
        now=NOW,
    )
    assert read_active_memory(path, now=NOW) == [event, second]
