from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from mandate_guard.alpaca import AccountSnapshot, MarketClock
from mandate_guard.checks import OrderIntent, PendingOrder, Position, Side
from mandate_guard.mandate import Mandate
from mandate_guard.service import GuardService


class FakeBroker:
    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}
        self.orders_today = 0
        self.price = Decimal("100")
        self.submitted = []
        self.pending_orders: tuple[PendingOrder, ...] = ()
        self.market_open = True
        self.last_since: datetime | None = None
        self.closed = []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(Decimal("10000"), Decimal("10000"), "ACTIVE")

    async def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    async def count_orders_since(self, since: datetime) -> int:
        self.last_since = since
        return self.orders_today

    async def get_open_orders(self) -> tuple[PendingOrder, ...]:
        return self.pending_orders

    async def get_market_clock(self) -> MarketClock:
        return MarketClock(datetime(2026, 8, 26, 14, tzinfo=timezone.utc), self.market_open)

    async def get_latest_trade_price(self, symbol: str) -> Decimal:
        return self.price

    async def submit_order(self, order: OrderIntent, *, client_order_id: str):
        self.submitted.append((order, client_order_id))
        self.orders_today += 1
        return {"id": "paper-order-1", "status": "accepted"}

    async def cancel_order(self, order_id: str) -> None:
        return None

    async def close_position(self, symbol: str, qty: Decimal):
        self.closed.append((symbol, qty))
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


def test_pending_orders_are_included_in_fresh_submit_check(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    broker.pending_orders = (PendingOrder("AAPL", Side.BUY, Decimal("5"), Decimal("100")),)
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("6"), "limit", limit_price=Decimal("100"))
    result = asyncio.run(service.submit(order, rationale="second entry", now=market_open))
    assert result["submitted"] is False
    assert broker.submitted == []


def test_concurrent_submissions_are_serialized(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.orders_today = 19
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    async def submit_twice():
        return await asyncio.gather(
            service.submit(order, rationale="first", now=market_open),
            service.submit(order, rationale="second", now=market_open),
        )

    results = asyncio.run(submit_twice())
    assert [result["submitted"] for result in results].count(True) == 1
    assert len(broker.submitted) == 1


def test_exchange_clock_closure_denies_weekday_order(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.market_open = False
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    result = asyncio.run(service.submit(order, rationale="holiday", now=market_open))
    assert result["submitted"] is False
    assert any(breach["rule"] == "session" for breach in result["breaches"])


def test_order_day_starts_at_new_york_midnight(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    asyncio.run(service.check(order, now=market_open))
    assert broker.last_since == datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)


def test_close_position_is_checked_against_mandate(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("5"), Decimal("100"))
    service = GuardService(mandate, broker)
    denied = asyncio.run(
        service.close_position("AAPL", Decimal("1"), rationale="reduce risk", now=market_open)
    )
    assert denied["submitted"] is False
    assert any(breach["rule"] == "order_type" for breach in denied["breaches"])
    assert broker.closed == []


def test_close_position_submits_only_when_market_close_is_authorized(
    mandate: Mandate, market_open: datetime
) -> None:
    authorized = mandate.model_copy(update={"order_types": ["limit", "market"]})
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("5"), Decimal("100"))
    service = GuardService(authorized, broker)
    result = asyncio.run(
        service.close_position("AAPL", Decimal("2"), rationale="reduce risk", now=market_open)
    )
    assert result["submitted"] is True
    assert broker.closed == [("AAPL", Decimal("2"))]
