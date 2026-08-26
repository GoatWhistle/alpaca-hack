from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from mandate_guard.alpaca import AccountSnapshot
from mandate_guard.checks import OrderIntent, Position, Side
from mandate_guard.mandate import Mandate
from mandate_guard.service import GuardService


class FakeBroker:
    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}
        self.orders_today = 0
        self.price = Decimal("100")
        self.submitted = []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(Decimal("10000"), Decimal("10000"), "ACTIVE")

    async def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    async def count_orders_since(self, since: datetime) -> int:
        return self.orders_today

    async def get_latest_trade_price(self, symbol: str) -> Decimal:
        return self.price

    async def submit_order(self, order: OrderIntent, *, client_order_id: str):
        self.submitted.append((order, client_order_id))
        return {"id": "paper-order-1", "status": "accepted"}

    async def cancel_order(self, order_id: str) -> None:
        return None

    async def close_position(self, symbol: str, qty: Decimal):
        return {"id": "close-1"}


def test_submit_rechecks_fresh_state_after_dry_run(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("10"), "limit", limit_price=Decimal("100"))

    dry_run = asyncio.run(service.check(order, now=market_open))
    assert dry_run["allowed"] is True

    broker.positions["AAPL"] = Position(Decimal("1"), Decimal("100"))
    submitted = asyncio.run(service.submit(order, rationale="breakout", now=market_open))
    assert submitted["submitted"] is False
    assert broker.submitted == []
    assert service.journal.snapshot()[0]["outcome"] == "denied"


def test_submit_allowed_order_uses_auditable_client_id(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("5"), "limit", limit_price=Decimal("100"))
    result = asyncio.run(service.submit(order, rationale="confirmed momentum", now=market_open))
    assert result["submitted"] is True
    assert result["client_order_id"].startswith("mandate-")
    assert len(broker.submitted) == 1
    assert service.journal.snapshot()[0]["rationale"] == "confirmed momentum"


def test_park_is_recorded(mandate: Mandate) -> None:
    service = GuardService(mandate, FakeBroker())
    result = service.park(reason="outside universe", intended_action="buy TSLA")
    assert result["outcome"] == "parked"
    assert service.journal.snapshot()[0]["details"]["intended_action"] == "buy TSLA"
