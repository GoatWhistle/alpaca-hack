from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from starlette.testclient import TestClient

from mandate_guard.dashboard import _wire_payload, build_snapshot, create_dashboard


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
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"version": 2, "enabled": True}), encoding="utf-8")
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    alerts = tmp_path / "alerts.jsonl"
    alerts.write_text(json.dumps({"kind": "news", "headline": "Test"}) + "\n", encoding="utf-8")

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_guard.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            guard=FakeGuard(),
            mandate_path=mandate,
            journal_path=journal,
            trajectory_path=trajectory,
            runtime_path=runtime,
            alerts_path=alerts,
            service_urls={"trueforge": "http://local:8790", "guard": "http://local:8010"},
        )
    )
    assert result["source"] == "live"
    assert result["paper_only"] is True
    assert result["mandate"]["mandate"]["name"] == "test-mandate"
    assert result["session"]["account"]["equity"] == "100000"
    assert result["autonomy"]["trajectory"]["version"] == 2
    assert result["autonomy"]["runtime"]["status"] == "running"
    assert result["autonomy"]["alerts"][0]["headline"] == "Test"
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


def test_wire_payload_normalizes_typed_mcp_values() -> None:
    at = datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc)
    assert _wire_payload({"at": at, "equity": Decimal("100000.00"), "items": (at,)}) == {
        "at": "2026-08-27T13:30:00+00:00",
        "equity": "100000.00",
        "items": ["2026-08-27T13:30:00+00:00"],
    }


def test_trajectory_update_requires_confirmation_and_cannot_expand_universe(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL, SPY]\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    trajectory = tmp_path / "trajectory.json"
    alerts = tmp_path / "alerts.jsonl"
    app = create_dashboard(
        guard=FakeGuard(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=journal,
        trajectory_path=trajectory,
        alerts_path=alerts,
        service_urls={"trueforge": "http://local:8790", "guard": "http://local:8010"},
    )
    with TestClient(app) as client:
        assert client.post("/api/trajectory", json={"symbols": ["AAPL"]}).status_code == 409
        response = client.post(
            "/api/trajectory",
            json={"confirmed": True, "symbols": ["AAPL"], "news_poll_seconds": 30},
        )
        assert response.status_code == 200
        assert response.json()["news_poll_seconds"] == 30
        denied = client.post(
            "/api/trajectory", json={"confirmed": True, "symbols": ["TSLA"]}
        )
        assert denied.status_code == 400
        assert "cannot expand mandate universe" in denied.json()["error"]
