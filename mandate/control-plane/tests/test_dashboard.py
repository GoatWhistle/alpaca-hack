from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from starlette.testclient import TestClient

from mandate_control.dashboard import (
    TrueForgeApprovalsReader,
    _approval_turn_body,
    _pending_approvals,
    _wire_payload,
    build_snapshot,
    create_dashboard,
)


class FakeBroker:
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


class OfflineBroker:
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


def test_snapshot_prefers_live_broker_data(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"version": 2, "enabled": True}), encoding="utf-8")
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    alerts = tmp_path / "alerts.jsonl"
    alerts.write_text(json.dumps({"kind": "news", "headline": "Test"}) + "\n", encoding="utf-8")

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_control.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            broker=FakeBroker(),
            mandate_path=mandate,
            journal_path=journal,
            trajectory_path=trajectory,
            runtime_path=runtime,
            alerts_path=alerts,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
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

    monkeypatch.setattr("mandate_control.dashboard._service_status", offline)
    result = asyncio.run(
        build_snapshot(
            broker=OfflineBroker(),
            mandate_path=mandate,
            journal_path=journal,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["source"] == "degraded"
    assert result["mandate"]["mandate"]["name"] == "cached-mandate"
    assert result["session"]["journal"][0]["outcome"] == "parked"
    assert result["errors"] == ["paper broker unavailable: ConnectionError"]


def test_wire_payload_normalizes_typed_mcp_values() -> None:
    at = datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc)
    assert _wire_payload({"at": at, "equity": Decimal("100000.00"), "items": (at,)}) == {
        "at": "2026-08-27T13:30:00+00:00",
        "equity": "100000.00",
        "items": ["2026-08-27T13:30:00+00:00"],
    }


def test_trajectory_update_requires_confirmation_and_can_expand_universe(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL, SPY]\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    trajectory = tmp_path / "trajectory.json"
    alerts = tmp_path / "alerts.jsonl"
    app = create_dashboard(
        broker=FakeBroker(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=journal,
        trajectory_path=trajectory,
        alerts_path=alerts,
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        assert client.post("/api/trajectory", json={"symbols": ["AAPL"]}).status_code == 409
        response = client.post(
            "/api/trajectory",
            json={"confirmed": True, "symbols": ["AAPL"], "news_poll_seconds": 30},
        )
        assert response.status_code == 200
        assert response.json()["news_poll_seconds"] == 30
        expanded = client.post(
            "/api/trajectory", json={"confirmed": True, "symbols": ["TSLA"]}
        )
        assert expanded.status_code == 200
        assert expanded.json()["symbols"] == ["TSLA"]


class FakeApprovals:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def read(self):
        return self.payload


def _session(session_id: str) -> dict:
    return {
        "id": session_id,
        "title": "session",
        "updated_at": "2026-08-28T10:00:00Z",
        "agent": {"name": "mandate-paper-agent"},
    }


def _approval_fixtures() -> tuple[dict, dict, dict]:
    model_message = {
        "id": "evt-model-1",
        "type": "model.message",
        "tool_calls": [
            {
                "id": "call-1",
                "function": {
                    "name": "place_stock_order",
                    "arguments": '{"symbol":"NVDA","side":"buy","qty":"3"}',
                },
            }
        ],
    }
    approval = {
        "id": "evt-approval-1",
        "type": "tool.approval_required",
        "thread_id": "thread-1",
        "created_at": "2026-08-28T10:01:00Z",
        "tool_calls": [{"id": "call-1", "source_event_id": "evt-model-1"}],
    }
    return model_message, approval, {
        "s-1": [
            {"event": model_message, "turn_id": "t-1"},
            {"event": approval, "turn_id": "t-1"},
        ]
    }


def test_pending_approvals_resolve_tool_name_and_arguments() -> None:
    _model, _approval, events = _approval_fixtures()
    items = _pending_approvals([_session("s-1")], events, {})
    assert len(items) == 1
    assert items[0]["tool_call_id"] == "call-1"
    assert items[0]["tool_name"] == "place_stock_order"
    assert items[0]["arguments"] == {"symbol": "NVDA", "side": "buy", "qty": "3"}
    assert items[0]["thread_id"] == "thread-1"
    assert items[0]["session_id"] == "s-1"


def test_pending_approvals_exclude_answered_and_executed_calls() -> None:
    _model, _approval, events = _approval_fixtures()
    answered_turns = {
        "s-1": [
            {
                "input": [
                    {
                        "type": "user.tool_approval",
                        "thread_id": "thread-1",
                        "tool_call_id": "call-1",
                        "approval": {"status": "deny", "reason": "too large"},
                    }
                ]
            }
        ]
    }
    assert _pending_approvals([_session("s-1")], events, answered_turns) == []
    executed_events = {
        "s-1": [
            *events["s-1"],
            {"event": {"type": "tool.response", "tool_call_id": "call-1"}, "turn_id": "t-2"},
        ]
    }
    assert _pending_approvals([_session("s-1")], executed_events, {}) == []


def test_pending_approvals_skip_sessions_without_approval_events() -> None:
    items = _pending_approvals(
        [_session("s-1")],
        {"s-1": [{"event": {"type": "model.message", "id": "evt-model-1"}, "turn_id": "t-1"}]},
        {},
    )
    assert items == []


def test_snapshot_includes_approvals_payload(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_control.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            broker=FakeBroker(),
            mandate_path=mandate,
            journal_path=journal,
            approvals_reader=FakeApprovals({"count": 1, "items": [{"tool_call_id": "call-1"}]}),
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["approvals"]["count"] == 1
    assert result["approvals"]["items"][0]["tool_call_id"] == "call-1"
    assert not result["errors"]


def test_approvals_reader_fails_soft_when_trueforge_is_down() -> None:
    reader = TrueForgeApprovalsReader("http://127.0.0.1:9", timeout=0.2)
    result = asyncio.run(reader.read())
    assert result["count"] == 0
    assert result["items"] == []
    assert "error" in result


def test_approval_turn_body_allow_and_deny() -> None:
    allow = _approval_turn_body(thread_id="th", tool_call_id="c1", approve=True)
    assert allow["previous_turn_id"] == "auto"
    assert allow["input"][0]["thread_id"] == "th"
    assert allow["input"][0]["tool_call_id"] == "c1"
    assert allow["input"][0]["approval"] == {"status": "allow"}
    deny = _approval_turn_body(thread_id="th", tool_call_id="c1", approve=False, reason="breach")
    assert deny["input"][0]["approval"] == {"status": "deny", "reason": "breach"}


class _StubResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _StubClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url: str, json: dict):
        _StubClient.last_url, _StubClient.last_json = url, json
        return _StubResponse(200)


def test_respond_approval_forwards_human_decision_to_trueforge(tmp_path: Path, monkeypatch) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL]\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    app = create_dashboard(
        broker=FakeBroker(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=journal,
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    monkeypatch.setattr("mandate_control.dashboard.httpx.AsyncClient", _StubClient)
    with TestClient(app) as client:
        unconfirmed = client.post(
            "/api/approvals/respond",
            json={"session_id": "s-1", "tool_call_id": "c1", "thread_id": "t", "approve": True},
        )
        assert unconfirmed.status_code == 409
        invalid = client.post(
            "/api/approvals/respond",
            json={"session_id": "../escape", "tool_call_id": "c1", "thread_id": "t", "approve": True, "confirmed": True},
        )
        assert invalid.status_code == 400
        ok = client.post(
            "/api/approvals/respond",
            json={
                "session_id": "s-1",
                "tool_call_id": "c1",
                "thread_id": "thread-1",
                "approve": False,
                "reason": "breach of max position",
                "confirmed": True,
            },
        )
        assert ok.status_code == 200
        assert _StubClient.last_url == "/api/v1/sessions/s-1/turns"
        assert _StubClient.last_json["input"][0]["approval"] == {
            "status": "deny",
            "reason": "breach of max position",
        }
        assert _StubClient.last_json["previous_turn_id"] == "auto"


def test_simulated_rehearsal_requires_manual_approval_and_never_calls_broker(
    tmp_path: Path, monkeypatch
) -> None:
    now = [datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr("mandate_control.demo._utcnow", lambda: now[0])
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL, NVDA, SPY]\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"execution_mode": "approval"}), encoding="utf-8")
    demo = tmp_path / "demo.json"
    app = create_dashboard(
        broker=FakeBroker(),
        approvals_reader=FakeApprovals({"count": 0, "items": []}),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=journal,
        trajectory_path=trajectory,
        demo_path=demo,
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        assert client.post("/api/demo", json={"enabled": True}).status_code == 409
        assert client.post("/api/demo", json={"enabled": True, "confirmed": True}).status_code == 200
        snapshot = client.get("/api/snapshot").json()
        assert snapshot["demo"] == {"enabled": True, "kind": "simulated", "complete": False}
        assert snapshot["approvals"]["count"] == 1
        pending = snapshot["approvals"]["items"][0]
        assert pending["session_id"] == "demo-safety"
        approved = client.post(
            "/api/approvals/respond",
            json={
                "session_id": "demo-safety",
                "tool_call_id": pending["tool_call_id"],
                "thread_id": pending["thread_id"],
                "approve": True,
                "confirmed": True,
            },
        )
        assert approved.status_code == 200
        after = client.get("/api/snapshot").json()
        assert Decimal(after["session"]["account"]["daily_pnl"]) == 0
        assert "NVDA" in after["session"]["positions"]
        assert after["session"]["journal"][0]["outcome"] == "submitted"
        now[0] += timedelta(seconds=30)
        moving = client.get("/api/snapshot").json()
        moving_pnl = Decimal(moving["session"]["account"]["daily_pnl"])
        assert moving_pnl > 0
        now[0] += timedelta(seconds=30)
        settled = client.get("/api/snapshot").json()
        assert Decimal(settled["session"]["account"]["daily_pnl"]) > moving_pnl
        blocked_auto = client.post(
            "/api/trajectory",
            json={"execution_mode": "auto_paper", "confirmed": True},
        )
        assert blocked_auto.status_code == 409


def test_simulated_rehearsal_cannot_start_in_auto_mode(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL]\nlimits: {}\n", encoding="utf-8")
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"execution_mode": "auto_paper"}), encoding="utf-8")
    app = create_dashboard(
        broker=FakeBroker(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=tmp_path / "journal.jsonl",
        trajectory_path=trajectory,
        demo_path=tmp_path / "demo.json",
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        response = client.post("/api/demo", json={"enabled": True, "confirmed": True})
        assert response.status_code == 409
        assert "manual approval" in response.json()["error"]


def test_demo_profile_cannot_change_production_trajectory(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL]\nlimits: {}\n", encoding="utf-8")
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"execution_mode": "approval"}), encoding="utf-8")
    app = create_dashboard(
        broker=FakeBroker(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=tmp_path / "journal.jsonl",
        trajectory_path=trajectory,
        demo_path=tmp_path / "demo.json",
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        snapshot = client.get("/api/snapshot", headers={"X-Operator-User": "demo"}).json()
        assert snapshot["agent_url"] == ""
        assert all(service["url"] == "" for service in snapshot["services"])
        assert snapshot["session"]["positions"] == {}
        assert snapshot["session"]["journal"] == []
        response = client.post(
            "/api/trajectory",
            headers={"X-Operator-User": "demo"},
            json={"execution_mode": "auto_paper", "confirmed": True},
        )
        assert response.status_code == 403
        assert json.loads(trajectory.read_text(encoding="utf-8"))["execution_mode"] == "approval"
