from __future__ import annotations

import asyncio
from pathlib import Path

from mandate_guard.autonomy import AutonomyStore
from mandate_guard.server import create_server
from mandate_guard.service import GuardService
from test_service import FakeBroker


def test_server_exposes_expected_tools_with_explicit_annotations(mandate, tmp_path: Path) -> None:
    server = create_server(
        GuardService(mandate, FakeBroker()),
        autonomy_store=AutonomyStore(tmp_path / "trajectory.json", tmp_path / "alerts.jsonl"),
    )
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "get_mandate",
        "check_order",
        "submit_order_under_mandate",
        "cancel_order",
        "close_position",
        "get_session_state",
        "get_autonomy_state",
        "update_trajectory",
        "park",
    }
    assert tools["check_order"].annotations.readOnlyHint is True
    assert tools["submit_order_under_mandate"].annotations.destructiveHint is True
    assert tools["submit_order_under_mandate"].annotations.idempotentHint is True
    assert tools["cancel_order"].annotations.destructiveHint is True
    assert tools["close_position"].annotations.destructiveHint is True
    assert tools["get_autonomy_state"].annotations.readOnlyHint is True
    assert tools["update_trajectory"].annotations.destructiveHint is False
    assert tools["park"].annotations.destructiveHint is False
