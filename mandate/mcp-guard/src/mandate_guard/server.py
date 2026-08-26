from __future__ import annotations

import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mandate_guard.alpaca import AlpacaPaperClient
from mandate_guard.checks import OrderIntent, Side
from mandate_guard.mandate import load_mandate
from mandate_guard.service import GuardService


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


def _build_service() -> GuardService:
    mandate_path = Path(os.environ.get("MANDATE_PATH", "./mandates/example.yaml"))
    mandate = load_mandate(mandate_path)
    broker = AlpacaPaperClient(
        api_key=os.environ.get("ALPACA_API_KEY", ""),
        secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        base_url=os.environ.get("ALPACA_BASE_URL", ""),
    )
    return GuardService(mandate, broker)


def create_server(service: GuardService) -> FastMCP:
    mcp = FastMCP("mandate-guard")

    @mcp.tool(annotations=READ_ONLY)
    def get_mandate() -> dict[str, Any]:
        return service.mandate.model_dump(mode="json")

    @mcp.tool(name="check_order", annotations=READ_ONLY)
    async def check_order_tool(
        symbol: str,
        side: str,
        qty: str,
        order_type: str,
        limit_price: str | None = None,
        instrument: str = "equity",
    ) -> dict[str, Any]:
        order = OrderIntent(
            symbol=symbol,
            side=Side(side),
            qty=Decimal(qty),
            order_type=order_type,
            instrument=instrument,
            limit_price=Decimal(limit_price) if limit_price is not None else None,
        )
        return await service.check(order)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def submit_order_under_mandate(
        symbol: str,
        side: str,
        qty: str,
        order_type: str,
        rationale: str,
        limit_price: str | None = None,
        instrument: str = "equity",
    ) -> dict[str, Any]:
        order = OrderIntent(
            symbol=symbol,
            side=Side(side),
            qty=Decimal(qty),
            order_type=order_type,
            instrument=instrument,
            limit_price=Decimal(limit_price) if limit_price is not None else None,
        )
        return await service.submit(order, rationale=rationale)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def cancel_order(order_id: str, rationale: str) -> dict[str, Any]:
        if not rationale.strip():
            raise ValueError("rationale is required")
        await service.broker.cancel_order(order_id)
        service.journal.append("cancel_order", "submitted", rationale, {"order_id": order_id})
        return {"cancelled": True, "order_id": order_id}

    @mcp.tool(annotations=DESTRUCTIVE)
    async def close_position(symbol: str, qty: str, rationale: str) -> dict[str, Any]:
        return await service.close_position(symbol, Decimal(qty), rationale=rationale)

    @mcp.tool(annotations=READ_ONLY)
    def get_session_state() -> dict[str, Any]:
        return {"journal": service.journal.snapshot()}

    @mcp.tool(annotations=LOCAL_WRITE)
    def park(reason: str, intended_action: str) -> dict[str, Any]:
        return service.park(reason=reason, intended_action=intended_action)

    return mcp


def main() -> None:
    create_server(_build_service()).run()


if __name__ == "__main__":
    main()
