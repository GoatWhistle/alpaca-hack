from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any, Protocol

from mandate_guard.alpaca import AccountSnapshot, MarketClock, PortfolioSnapshot
from mandate_guard.checks import (
    NEW_YORK,
    CheckResult,
    OrderIntent,
    PendingOrder,
    Portfolio,
    Position,
    Side,
    check_order,
)
from mandate_guard.mandate import Mandate
from mandate_guard.state import SessionJournal


class PaperBroker(Protocol):
    async def get_account(self) -> AccountSnapshot: ...
    async def get_positions(self) -> dict[str, Position]: ...
    async def count_orders_since(self, since: datetime) -> int: ...
    async def get_open_orders(self) -> tuple[PendingOrder, ...]: ...
    async def get_market_clock(self) -> MarketClock: ...
    async def get_latest_trade_price(self, symbol: str) -> Decimal: ...
    async def submit_order(self, order: OrderIntent, *, client_order_id: str) -> Any: ...
    async def cancel_order(self, order_id: str) -> None: ...
    async def close_position(self, symbol: str, qty: Decimal) -> Any: ...


class GuardService:
    def __init__(self, mandate: Mandate, broker: PaperBroker, journal: SessionJournal | None = None) -> None:
        self.mandate = mandate
        self.broker = broker
        self.journal = journal or SessionJournal()
        self._submit_lock = asyncio.Lock()

    async def _snapshot(self, now: datetime) -> PortfolioSnapshot:
        market_date = now.astimezone(NEW_YORK).date()
        start_of_day = datetime.combine(market_date, time.min, tzinfo=NEW_YORK).astimezone(timezone.utc)
        account, positions, orders_today, pending_orders = await asyncio.gather(
            self.broker.get_account(),
            self.broker.get_positions(),
            self.broker.count_orders_since(start_of_day),
            self.broker.get_open_orders(),
        )
        if account.status.upper() != "ACTIVE":
            raise RuntimeError("Alpaca paper account is not active")
        return PortfolioSnapshot(account, positions, orders_today, pending_orders)

    async def evaluate(self, order: OrderIntent, *, now: datetime | None = None) -> tuple[CheckResult, PortfolioSnapshot]:
        checked_at = now or datetime.now(timezone.utc)
        snapshot, latest_price, market_clock = await asyncio.gather(
            self._snapshot(checked_at),
            self.broker.get_latest_trade_price(order.symbol),
            self.broker.get_market_clock(),
        )
        reference_price = max(latest_price, order.limit_price or latest_price)
        # Equity-to-last-equity includes unrealized movement, so it is more conservative
        # than pretending we know realized P&L from an incomplete broker snapshot.
        daily_pnl = snapshot.account.equity - snapshot.account.last_equity
        portfolio = Portfolio(
            equity=snapshot.account.equity,
            positions=snapshot.positions,
            pending_orders=snapshot.pending_orders,
            realized_pnl_today=daily_pnl,
            orders_today=snapshot.orders_today,
        )
        return (
            check_order(
                self.mandate,
                portfolio,
                order,
                reference_price,
                now=checked_at,
                market_is_open=market_clock.is_open,
            ),
            snapshot,
        )

    async def check(self, order: OrderIntent, *, now: datetime | None = None) -> dict[str, Any]:
        result, snapshot = await self.evaluate(order, now=now)
        return {
            **asdict(result),
            "portfolio_before": {
                "equity": str(snapshot.account.equity),
                "orders_today": snapshot.orders_today,
            },
        }

    async def submit(
        self, order: OrderIntent, *, rationale: str, now: datetime | None = None
    ) -> dict[str, Any]:
        if not rationale.strip():
            raise ValueError("rationale is required")
        # This intentionally does not accept a prior CheckResult. The broker state is
        # fetched again immediately before every irreversible action.
        async with self._submit_lock:
            result, _snapshot = await self.evaluate(order, now=now)
            if not result.allowed:
                details = {"order": asdict(order), "breaches": [asdict(item) for item in result.breaches]}
                self.journal.append("submit_order", "denied", rationale, details)
                return {"submitted": False, **asdict(result)}

            client_order_id = f"mandate-{uuid.uuid4().hex[:20]}"
            response = await self.broker.submit_order(order, client_order_id=client_order_id)
            self.journal.append(
                "submit_order",
                "submitted",
                rationale,
                {"client_order_id": client_order_id, "order": asdict(order)},
            )
            return {"submitted": True, "client_order_id": client_order_id, "broker": response}

    async def close_position(
        self, symbol: str, qty: Decimal, *, rationale: str, now: datetime | None = None
    ) -> dict[str, Any]:
        if not rationale.strip() or qty <= 0:
            raise ValueError("positive qty and rationale are required")
        async with self._submit_lock:
            positions = await self.broker.get_positions()
            position = positions.get(symbol.upper())
            if position is None or qty > abs(position.qty):
                raise ValueError("close quantity exceeds the current position")
            side = Side.SELL if position.qty > 0 else Side.BUY
            intent = OrderIntent(symbol, side, qty, "market")
            result, _snapshot = await self.evaluate(intent, now=now)
            if not result.allowed:
                details = {"order": asdict(intent), "breaches": [asdict(item) for item in result.breaches]}
                self.journal.append("close_position", "denied", rationale, details)
                return {"submitted": False, **asdict(result)}
            response = await self.broker.close_position(symbol, qty)
            self.journal.append(
                "close_position", "submitted", rationale, {"symbol": symbol.upper(), "qty": str(qty)}
            )
            return {"submitted": True, "broker": response}

    def park(self, *, reason: str, intended_action: str) -> dict[str, Any]:
        if not reason.strip() or not intended_action.strip():
            raise ValueError("reason and intended_action are required")
        entry = self.journal.append("park", "parked", reason, {"intended_action": intended_action})
        return asdict(entry)
