from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mandate_guard.dashboard import build_snapshot


class FakeGuard:
    async def read(self):
        return (
            {
                "mandate": {"name": "test-mandate", "limits": {}},
                "usage": {},
                "headroom": {},
                "market_is_open": True,
                "wake_triggers": [],
                "active_predecisions": [],
            },
            {
                "account": {"equity": "100000"},
                "positions": {},
                "pending_orders": [],
                "journal": [],
            },
        )


class OfflineGuard:
    async def read(self):
        raise ConnectionError("offline")


def _files(tmp_path: Path) -> tuple[Path, Path]:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: cached-mandate\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    journal.write_text(
        json.dumps(
            {
                "at": "2026-08-27T12:00:00+00:00",
                "action": "park",
                "outcome": "parked",
                "rationale": "test",
                "details": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return mandate, journal


def test_snapshot_prefers_live_guard_data(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_guard.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            guard=FakeGuard(),
            mandate_path=mandate,
            journal_path=journal,
            service_urls={"trueforge": "http://local:8790", "guard": "http://local:8010"},
        )
    )
    assert result["source"] == "live"
    assert result["paper_only"] is True
    assert result["mandate"]["mandate"]["name"] == "test-mandate"
    assert result["session"]["account"]["equity"] == "100000"
    assert not result["errors"]


def test_snapshot_falls_back_to_local_evidence(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)

    async def offline(name: str, url: str):
        return {"name": name, "url": url, "ok": False}

    monkeypatch.setattr("mandate_guard.dashboard._service_status", offline)
    result = asyncio.run(
        build_snapshot(
            guard=OfflineGuard(),
            mandate_path=mandate,
            journal_path=journal,
            service_urls={"trueforge": "http://local:8790", "guard": "http://local:8010"},
        )
    )
    assert result["source"] == "degraded"
    assert result["mandate"]["mandate"]["name"] == "cached-mandate"
    assert result["session"]["journal"][0]["outcome"] == "parked"
    assert result["errors"] == ["guard unavailable: ConnectionError"]
