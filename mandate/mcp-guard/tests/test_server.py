from __future__ import annotations

import asyncio

from mandate_guard.server import create_server
from mandate_guard.service import GuardService
from test_service import FakeBroker


def test_server_exposes_expected_tools_with_explicit_annotations(mandate) -> None:
    server = create_server(GuardService(mandate, FakeBroker()))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "get_mandate",
        "check_order",
        "submit_order_under_mandate",
        "cancel_order",
        "close_position",
        "get_session_state",
        "park",
    }
    assert tools["check_order"].annotations.readOnlyHint is True
    assert tools["submit_order_under_mandate"].annotations.destructiveHint is True
    assert tools["submit_order_under_mandate"].annotations.idempotentHint is True
    assert tools["cancel_order"].annotations.destructiveHint is True
    assert tools["close_position"].annotations.destructiveHint is True
    assert tools["park"].annotations.destructiveHint is False
