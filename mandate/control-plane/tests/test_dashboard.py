from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
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
                    "name": "append_trader_memory",
                    "arguments": '{"memory_key":"gap","hypothesis":"confirm gaps"}',
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
    assert items[0]["tool_name"] == "append_trader_memory"
    assert items[0]["arguments"] == {"memory_key": "gap", "hypothesis": "confirm gaps"}
    assert items[0]["thread_id"] == "thread-1"
    assert items[0]["session_id"] == "s-1"


def test_pending_approvals_hide_non_memory_tools() -> None:
    model, _approval, events = _approval_fixtures()
    model["tool_calls"][0]["function"]["name"] = "place_stock_order"
    assert _pending_approvals([_session("s-1")], events, {}) == []


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
        approvals_reader=FakeApprovals({"count": 1, "items": [{
            "session_id": "s-1", "tool_call_id": "c1", "thread_id": "thread-1",
            "tool_name": "append_trader_memory",
        }]}),
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


def test_respond_approval_rejects_non_memory_tool(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL]\nlimits: {}\n", encoding="utf-8")
    app = create_dashboard(
        broker=FakeBroker(),
        approvals_reader=FakeApprovals({"count": 1, "items": [{
            "session_id": "s-1", "tool_call_id": "order-1", "thread_id": "thread-1",
            "tool_name": "place_stock_order",
        }]}),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=tmp_path / "journal.jsonl",
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        response = client.post("/api/approvals/respond", json={
            "session_id": "s-1", "tool_call_id": "order-1", "thread_id": "thread-1",
            "approve": True, "confirmed": True,
        })
    assert response.status_code == 409


def test_trader_timeline_is_cursor_paginated(tmp_path: Path) -> None:
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text("name: test\nuniverse: [AAPL]\nlimits: {}\n", encoding="utf-8")
    journal = tmp_path / "session.jsonl"
    timeline = tmp_path / "trader-timeline.jsonl"
    timeline.write_text(
        "\n".join(
            json.dumps({
                "schema": "trader.timeline.v1",
                "sequence": sequence,
                "at": f"2026-09-02T12:00:0{sequence}+00:00",
                "trading_date": "2026-09-03" if sequence == 4 else "2026-09-02",
                "kind": "plan",
                "status": "ok",
                "session_id": "session-1",
                "summary": f"cycle {sequence}",
                "details": {},
            })
            for sequence in range(1, 5)
        ) + "\n",
        encoding="utf-8",
    )
    app = create_dashboard(
        broker=FakeBroker(),
        dist_path=tmp_path,
        mandate_path=mandate,
        journal_path=journal,
        timeline_path=timeline,
        service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
    )
    with TestClient(app) as client:
        first = client.get("/api/trader/timeline?limit=2")
        assert first.status_code == 200
        assert [item["sequence"] for item in first.json()["items"]] == [1, 2]
        assert first.json()["next_after"] == 2
        second = client.get("/api/trader/timeline?after=2&limit=2")
        assert [item["sequence"] for item in second.json()["items"]] == [3, 4]
        dated = client.get("/api/trader/timeline?trading_date=2026-09-02")
        assert [item["sequence"] for item in dated.json()["items"]] == [1, 2, 3]
        assert client.get("/api/trader/timeline?trading_date=09-02-2026").status_code == 400
        assert client.get("/api/trader/timeline?after=-1").status_code == 400
        assert client.get("/api/trader/stream?after=-1").status_code == 400


class _StubGetResponse:
    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _StubBrokerClient:
    """Answers the five paper reads with canned payloads and records the calls."""

    calls: list[tuple[str, dict]] = []
    payloads: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, path: str, params: dict | None = None):
        _StubBrokerClient.calls.append((path, dict(params or {})))
        key = f"{path}:{(params or {}).get('status', '')}"
        return _StubGetResponse(_StubBrokerClient.payloads[key])


def _broker_payloads() -> dict[str, object]:
    return {
        "/v2/account:": {
            "status": "ACTIVE", "equity": "90410.95", "last_equity": "94880.21",
            "buying_power": "290522.03", "options_approved_level": 3,
        },
        "/v2/positions:": [
            {
                "symbol": "AMD", "qty": "-27", "side": "short", "asset_class": "us_equity",
                "current_price": "456.87", "market_value": "-12335.38",
                "avg_entry_price": "460.86", "unrealized_pl": "107.84",
                "unrealized_plpc": "0.0087", "qty_available": "-27",
            },
            {
                "symbol": "NVDA260909C00222500", "qty": "7", "asset_class": "us_option",
                "current_price": "6.15", "market_value": "4305", "avg_entry_price": "3.9",
                "unrealized_pl": "1575", "unrealized_plpc": "0.5769",
            },
        ],
        "/v2/orders:all": [
            {"submitted_at": "2026-09-02T14:07:37.123456789Z"},
            {"submitted_at": "2026-09-02T03:30:00Z"},
        ],
        "/v2/orders:open": [
            {
                "id": "o-1", "symbol": "META", "side": "buy", "qty": "9", "filled_qty": "0",
                "type": "limit", "order_class": "simple", "limit_price": "598.81",
                "status": "new", "submitted_at": "2026-09-02T14:12:56Z",
                "asset_class": "us_equity", "legs": None,
                "extra_alpaca_field": "must not leak",
            },
            {
                "id": "o-2", "symbol": "", "side": "buy", "qty": "6", "filled_qty": "0",
                "type": "limit", "order_class": "mleg", "limit_price": "2.41",
                "status": "new", "submitted_at": "2026-09-02T14:04:44Z",
                "legs": [{"symbol": "NVDA260909C00222500"}, {"symbol": "NVDA260909C00230000"}],
            },
        ],
        "/v2/clock:": {"is_open": True, "timestamp": "2026-09-02T10:15:00-04:00"},
    }


def test_alpaca_reader_projects_positions_orders_and_total_pnl(tmp_path: Path, monkeypatch) -> None:
    from mandate_control.dashboard import AlpacaPaperReader

    mandate, journal = _files(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.delenv("MANDATE_USE_ALPACA_PROXY", raising=False)
    monkeypatch.delenv("MANDATE_STARTING_EQUITY", raising=False)
    monkeypatch.setattr("mandate_control.dashboard.httpx.AsyncClient", _StubBrokerClient)
    _StubBrokerClient.calls = []
    _StubBrokerClient.payloads = _broker_payloads()
    fixed_now = datetime(2026, 9, 2, 14, 20, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr("mandate_control.dashboard.datetime", _FixedDatetime)

    reader = AlpacaPaperReader(mandate, journal)
    mandate_state, session = asyncio.run(reader.read())

    account = session["account"]
    assert account["equity"] == "90410.95"
    assert account["starting_equity"] == "100000"
    assert account["total_pnl"] == "-9589.05"
    assert account["total_pnl_pct"] == "-9.59"
    assert account["daily_pnl"] == "-4469.26"
    assert account["options_approved_level"] == 3

    amd = session["positions"]["AMD"]
    assert amd["side"] == "short"
    assert amd["asset_class"] == "us_equity"
    assert amd["unrealized_pl"] == "107.84"
    assert amd["unrealized_plpc"] == "0.0087"
    assert amd["qty_available"] == "-27"
    call = session["positions"]["NVDA260909C00222500"]
    assert call["asset_class"] == "us_option"
    assert call["side"] == "long"
    assert "qty_available" not in call

    pending = session["pending_orders"]
    assert pending[0] == {
        "id": "o-1", "symbol": "META", "side": "buy", "qty": "9", "filled_qty": "0",
        "type": "limit", "order_class": "simple", "limit_price": "598.81", "status": "new",
        "submitted_at": "2026-09-02T14:12:56Z", "legs": 0, "asset_class": "us_equity",
    }
    assert pending[1]["legs"] == 2
    assert pending[1]["asset_class"] == "us_equity"
    assert "extra_alpaca_field" not in pending[0]

    # 03:30Z is the previous New York trading date; only the 14:07Z order counts.
    assert session["orders_today"] == 1
    assert mandate_state["usage"]["orders_today"] == 1
    all_orders = next(params for path, params in _StubBrokerClient.calls if params.get("status") == "all")
    assert all_orders["after"] == "2026-09-02T04:00:00+00:00"
    open_orders = next(params for path, params in _StubBrokerClient.calls if params.get("status") == "open")
    assert open_orders["nested"] == "true"


def test_alpaca_reader_shares_one_read_per_cache_window(tmp_path: Path, monkeypatch) -> None:
    from mandate_control.dashboard import AlpacaPaperReader

    mandate, journal = _files(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.delenv("MANDATE_USE_ALPACA_PROXY", raising=False)
    monkeypatch.setattr("mandate_control.dashboard.httpx.AsyncClient", _StubBrokerClient)
    _StubBrokerClient.calls = []
    _StubBrokerClient.payloads = _broker_payloads()

    reader = AlpacaPaperReader(mandate, journal, cache_seconds=60.0)

    async def concurrent():
        return await asyncio.gather(reader.read(), reader.read(), reader.read())

    results = asyncio.run(concurrent())
    assert len(_StubBrokerClient.calls) == 5
    assert results[0] is results[1] is results[2]
    asyncio.run(reader.read())
    assert len(_StubBrokerClient.calls) == 5

    uncached = AlpacaPaperReader(mandate, journal, cache_seconds=0.0)
    asyncio.run(uncached.read())
    asyncio.run(uncached.read())
    assert len(_StubBrokerClient.calls) == 15


def test_snapshot_marks_stale_runner_heartbeat(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"version": 2, "news_poll_seconds": 30}), encoding="utf-8")
    runtime = tmp_path / "runtime.json"
    stale_beat = "2026-09-02T15:10:41.630Z"
    runtime.write_text(json.dumps({"status": "running", "heartbeat_at": stale_beat}), encoding="utf-8")

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
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["autonomy"]["runtime"]["status"] == "running"
    assert result["autonomy"]["runtime"]["stale"] is True
    assert result["autonomy"]["runtime"]["stale_seconds"] > 120
    assert result["autonomy"]["runtime"]["stale_threshold_seconds"] == 120

    fresh = datetime.now(timezone.utc).isoformat()
    runtime.write_text(json.dumps({"status": "running", "heartbeat_at": fresh}), encoding="utf-8")
    result = asyncio.run(
        build_snapshot(
            broker=FakeBroker(),
            mandate_path=mandate,
            journal_path=journal,
            trajectory_path=trajectory,
            runtime_path=runtime,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["autonomy"]["runtime"]["stale"] is False
    assert result["autonomy"]["runtime"]["stale_seconds"] <= 5

    runtime.unlink()
    result = asyncio.run(
        build_snapshot(
            broker=FakeBroker(),
            mandate_path=mandate,
            journal_path=journal,
            trajectory_path=trajectory,
            runtime_path=runtime,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["autonomy"]["runtime"]["status"] == "not_started"
    assert result["autonomy"]["runtime"]["stale"] is False


def test_journal_tolerates_partial_tail_and_reports_bad_lines(tmp_path: Path, monkeypatch) -> None:
    from mandate_control.dashboard import _read_journal

    mandate, journal = _files(tmp_path)
    good = json.dumps({"at": "2026-09-02T14:00:00+00:00", "action": "submit_order",
                       "outcome": "filled", "rationale": "ok", "details": {}})
    journal.write_text(good + "\n" + "{not json}\n" + good + "\n" + '{"at": "2026-09-02T14:0',
                       encoding="utf-8")
    errors: list[str] = []
    entries = _read_journal(journal, errors=errors)
    assert len(entries) == 2
    assert errors == ["session.jsonl: skipped 1 unreadable line(s)"]

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_control.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            broker=OfflineBroker(),
            mandate_path=mandate,
            journal_path=journal,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert len(result["session"]["journal"]) == 2
    assert "session.jsonl: skipped 1 unreadable line(s)" in result["errors"]


def test_snapshot_ships_only_the_outcome_scorecard(tmp_path: Path, monkeypatch) -> None:
    mandate, journal = _files(tmp_path)
    outcomes = tmp_path / "forward-outcomes.json"
    outcomes.write_text(json.dumps({
        "updated_at": "2026-09-02T14:00:00+00:00",
        "records": [{"session_id": "s", "prices": {"AAPL": "1"}}] * 50,
        "scorecard": {"momentum": {"observations": 12}},
    }), encoding="utf-8")

    async def online(name: str, url: str):
        return {"name": name, "url": url, "ok": True}

    monkeypatch.setattr("mandate_control.dashboard._service_status", online)
    result = asyncio.run(
        build_snapshot(
            broker=FakeBroker(),
            mandate_path=mandate,
            journal_path=journal,
            outcomes_path=outcomes,
            service_urls={"trueforge": "http://local:8790", "broker": "http://local:8010"},
        )
    )
    assert result["autonomy"]["outcomes"] == {
        "updated_at": "2026-09-02T14:00:00+00:00",
        "scorecard": {"momentum": {"observations": 12}},
    }
