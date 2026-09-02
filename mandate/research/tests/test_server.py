from __future__ import annotations

import asyncio

from mandate_research.server import create_server


def test_research_mcp_has_only_bounded_read_only_tools() -> None:
    server = create_server(
        compare=lambda **_: {}, probe=lambda **_: {}, monitor=lambda **_: {}, evaluate=lambda **_: {},
        gate=lambda **_: {}, run_exits=lambda _positions: {},
    )
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == {
        "probe_news_sources",
        "gate_news_llm",
        "list_trader_memory",
        "get_trader_context",
        "append_trader_memory",
        "compare_live_signals",
        "get_market_monitoring",
        "evaluate_trajectory",
        "evaluate_position_exits",
    }
    assert all(tool.annotations is not None for tool in tools.values())
    assert all(
        tool.annotations.readOnlyHint is (tool.name != "append_trader_memory")
        for tool in tools.values()
    )
    assert all(tool.annotations.destructiveHint is False for tool in tools.values())


def test_research_mcp_delegates_with_bounded_arguments() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def compare(**kwargs: object) -> dict[str, object]:
        calls.append(("compare", kwargs))
        return {"kind": "comparison"}

    def probe(**kwargs: object) -> dict[str, object]:
        calls.append(("probe", kwargs))
        return {"kind": "probe"}

    def evaluate(**kwargs: object) -> dict[str, object]:
        calls.append(("evaluate", kwargs))
        return {"kind": "decision-math"}

    def gate(**kwargs: object) -> dict[str, object]:
        calls.append(("gate", kwargs))
        return {"kind": "llm-gate"}

    server = create_server(compare=compare, probe=probe, evaluate=evaluate, gate=gate)
    probe_result = asyncio.run(server.call_tool("probe_news_sources", {"symbol": "NVDA"}))
    compare_result = asyncio.run(
        server.call_tool("compare_live_signals", {"symbol": "AAPL", "fee_bps": "2"})
    )
    evaluate_result = asyncio.run(
        server.call_tool("evaluate_trajectory", {"symbols": "AAPL,SPY", "fee_bps": "2"})
    )
    gate_result = asyncio.run(server.call_tool(
        "gate_news_llm", {
            "headline": "Beat but guidance cut", "source": "wire", "external_id": "42",
            "published_at": "2026-09-02T12:00:00Z", "symbol": "AAPL",
        }
    ))

    assert probe_result[1] == {"kind": "probe"}
    assert compare_result[1] == {"kind": "comparison"}
    assert evaluate_result[1] == {"kind": "decision-math"}
    assert gate_result[1] == {"kind": "llm-gate"}
    assert calls == [
        ("probe", {"symbol": "NVDA", "strict": False}),
        ("compare", {"symbol": "AAPL", "fee_bps": "2"}),
        (
            "evaluate",
            {
                "symbols": ["AAPL", "SPY"],
                "fee_bps": "2",
                "max_spread_bps": "35",
                "min_relative_volume": "0.25",
                "single_symbol_move_pct": "4",
                "regular_hours_only": True,
                "equity": "",
                "risk_budget_pct": "0.35",
                "atr_multiplier": "1.5",
                "position_headroom_pct": "",
                "gross_headroom_pct": "",
                "adaptive_weights_json": "{}",
                "priority_symbols_csv": "",
                "research_limit": 8,
                "compact_output": False,
            },
        ),
        ("gate", {
            "headline": "Beat but guidance cut", "source": "wire", "external_id": "42",
            "published_at": "2026-09-02T12:00:00Z", "summary": "", "symbol": "AAPL",
        }),
    ]


def test_position_exits_tool_parses_json_and_delegates() -> None:
    def run_exits(positions: list[dict]) -> dict[str, object]:
        return {"received": positions}

    server = create_server(run_exits=run_exits)
    result = asyncio.run(server.call_tool(
        "evaluate_position_exits",
        {"positions_json": '[{"symbol": "NVDA", "qty": "-10", "avg_entry_price": "100"}]'},
    ))
    assert result[1] == {
        "received": [{"symbol": "NVDA", "qty": "-10", "avg_entry_price": "100"}]
    }

    import pytest
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("evaluate_position_exits", {"positions_json": "{not json"}))


def test_operator_memory_tools_share_the_append_only_contract(tmp_path) -> None:
    path = tmp_path / "trader-memory.jsonl"
    server = create_server(trader_memory_path=path)

    appended = asyncio.run(server.call_tool("append_trader_memory", {
        "memory_key": "gap-risk",
        "hypothesis": "Wait for price confirmation after large opening gaps.",
        "evidence_refs_json": '["operator:review:7"]',
        "ttl_hours": 24,
    }))
    active = asyncio.run(server.call_tool("list_trader_memory", {}))

    assert appended[1]["schema"] == "trader.memory.v1"
    assert active[1]["schema"] == "trader.memory.page.v1"
    assert active[1]["items"] == [appended[1]]


def test_operator_context_is_compact_and_tracks_latest_session(tmp_path) -> None:
    timeline = tmp_path / "trader-timeline.jsonl"
    memory = tmp_path / "trader-memory.jsonl"
    timeline.write_text("\n".join([
        "{broken",
        '{"schema":"trader.timeline.v1","sequence":1,"at":"2026-09-02T10:00:00Z","trading_date":"2026-09-02","kind":"plan","status":"ok","session_id":"trader-1","summary":"  First   plan  ","details":{"large":"ignored"}}',
        '{"schema":"trader.timeline.v1","sequence":2,"at":"2026-09-02T10:01:00Z","trading_date":"2026-09-02","kind":"execution","status":"submitted","session_id":"trader-2","summary":"Second event","details":{}}',
    ]), encoding="utf-8")
    server = create_server(trader_timeline_path=timeline, trader_memory_path=memory)

    result = asyncio.run(server.call_tool("get_trader_context", {"max_events": 1}))[1]

    assert result["schema"] == "trader.context.v1"
    assert result["current_session_id"] == "trader-2"
    assert result["timeline"] == [{
        "sequence": 2,
        "at": "2026-09-02T10:01:00Z",
        "trading_date": "2026-09-02",
        "kind": "execution",
        "status": "submitted",
        "session_id": "trader-2",
        "summary": "Second event",
    }]
    assert result["contract"]["execution_authority"] is False


def test_operator_context_skips_malformed_tail_and_memory_fields(tmp_path) -> None:
    timeline = tmp_path / "trader-timeline.jsonl"
    memory = tmp_path / "trader-memory.jsonl"
    timeline.write_bytes(
        b'\xff{"schema":"trader.timeline.v1","sequence":true,"at":"bad",'
        b'"trading_date":"bad","kind":"unknown","status":"ok","summary":"bad"}\n'
        b'{"schema":"trader.timeline.v1","sequence":3,"at":"2026-09-02T10:02:00Z",'
        b'"trading_date":"2026-09-02","kind":"session","status":"ok",'
        b'"session_id":null,"summary":"healthy"}\n'
    )
    memory.write_text(
        '{"schema":"trader.memory.v1","event_id":"m1","created_at":"2026-09-02T10:00:00+00:00",'
        '"expires_at":"2099-09-02T10:00:00+00:00","hypothesis":"data","evidence_refs":null}\n',
        encoding="utf-8",
    )
    server = create_server(trader_timeline_path=timeline, trader_memory_path=memory)

    result = asyncio.run(server.call_tool("get_trader_context", {}))[1]

    assert [item["sequence"] for item in result["timeline"]] == [3]
    assert result["memory"][0]["evidence_refs"] == []
