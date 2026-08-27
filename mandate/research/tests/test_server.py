from __future__ import annotations

import asyncio

from mandate_research.server import create_server


def test_research_mcp_has_only_bounded_read_only_tools() -> None:
    server = create_server(
        compare=lambda **_: {}, probe=lambda **_: {}, monitor=lambda **_: {}, evaluate=lambda **_: {}
    )
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == {
        "probe_news_sources", "compare_live_signals", "get_market_monitoring", "evaluate_trajectory"
    }
    assert all(tool.annotations is not None for tool in tools.values())
    assert all(tool.annotations.readOnlyHint is True for tool in tools.values())
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

    server = create_server(compare=compare, probe=probe, evaluate=evaluate)
    probe_result = asyncio.run(server.call_tool("probe_news_sources", {"symbol": "NVDA"}))
    compare_result = asyncio.run(
        server.call_tool("compare_live_signals", {"symbol": "AAPL", "fee_bps": "2"})
    )
    evaluate_result = asyncio.run(
        server.call_tool("evaluate_trajectory", {"symbols": "AAPL,SPY", "fee_bps": "2"})
    )

    assert probe_result[1] == {"kind": "probe"}
    assert compare_result[1] == {"kind": "comparison"}
    assert evaluate_result[1] == {"kind": "decision-math"}
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
                "single_symbol_move_pct": "5",
                "regular_hours_only": True,
                "equity": "",
                "risk_budget_pct": "0.25",
                "atr_multiplier": "2",
                "position_headroom_pct": "",
                "gross_headroom_pct": "",
            },
        ),
    ]
