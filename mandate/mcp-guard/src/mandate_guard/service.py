from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import asdict
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any, Protocol

from mandate_guard.alpaca import AccountSnapshot, MarketClock, PortfolioSnapshot
from mandate_guard.checks import (
    NEW_YORK,
    CheckResult,
    Breach,
    OrderIntent,
    PendingOrder,
    Portfolio,
    Position,
    calculate_risk_usage,
    check_expiry,
    check_order,
    check_session_window,
)
from mandate_guard.mandate import Mandate, Predecision
from mandate_guard.state import SessionJournal
from mandate_guard.wake import evaluate_wake_conditions
from mandate_guard.wake import parse_wake_condition


class PaperBroker(Protocol):
    async def get_account(self) -> AccountSnapshot: ...
    async def get_positions(self) -> dict[str, Position]: ...
    async def count_orders_since(self, since: datetime) -> int: ...
    async def get_open_orders(self) -> tuple[PendingOrder, ...]: ...
    async def get_market_clock(self) -> MarketClock: ...
    async def get_latest_trade_price(self, symbol: str) -> Decimal: ...
    async def submit_order(self, order: OrderIntent, *, client_order_id: str) -> Any: ...
    async def find_order_by_client_id(self, client_order_id: str) -> Any | None: ...
    async def get_order_by_id(self, order_id: str) -> Any: ...
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
        result = check_order(
            self.mandate,
            portfolio,
            order,
            reference_price,
            now=checked_at,
            market_is_open=market_clock.is_open,
        )
        metrics = self._observable_metrics(snapshot)
        predecided_breaches = tuple(
            Breach(
                rule="predecided",
                limit=directive.when,
                projected=directive.then,
                headroom=directive.reason,
            )
            for directive in self._active_predecisions(metrics)
        )
        if predecided_breaches:
            result = CheckResult(
                allowed=False,
                breaches=(*result.breaches, *predecided_breaches),
                projection=result.projection,
            )
        return result, snapshot

    @staticmethod
    def _observable_metrics(snapshot: PortfolioSnapshot) -> dict[str, Decimal]:
        daily_pnl = snapshot.account.equity - snapshot.account.last_equity
        return {
            "daily_loss_pct": max(-daily_pnl, Decimal("0"))
            / snapshot.account.equity
            * Decimal("100"),
            "single_symbol_move_pct": max(
                (abs(position.change_today_pct) for position in snapshot.positions.values()),
                default=Decimal("0"),
            ),
        }

    def _active_predecisions(self, metrics: dict[str, Decimal]) -> list[Predecision]:
        active: list[Predecision] = []
        for directive in self.mandate.predecided:
            condition = parse_wake_condition(directive.when)
            if condition.evaluate(metrics[condition.metric]):
                active.append(directive)
        return active

    async def check(self, order: OrderIntent, *, now: datetime | None = None) -> dict[str, Any]:
        result, snapshot = await self.evaluate(order, now=now)
        return {
            **asdict(result),
            "portfolio_before": {
                "equity": str(snapshot.account.equity),
                "orders_today": snapshot.orders_today,
            },
            "portfolio_after": {
                "symbol": order.symbol,
                "projected_qty": str(result.projection.projected_qty),
                "position_pct": str(result.projection.position_pct),
                "gross_exposure_pct": str(result.projection.gross_exposure_pct),
                "reference_price": str(result.projection.price),
            },
        }

    async def session_state(self, *, now: datetime | None = None) -> dict[str, Any]:
        checked_at = now or datetime.now(timezone.utc)
        snapshot, market_clock = await asyncio.gather(
            self._snapshot(checked_at), self.broker.get_market_clock()
        )
        gross = sum((abs(position.market_value) for position in snapshot.positions.values()), Decimal("0"))
        daily_pnl = snapshot.account.equity - snapshot.account.last_equity
        return {
            "as_of": checked_at.isoformat(),
            "account": {
                "status": snapshot.account.status,
                "equity": str(snapshot.account.equity),
                "daily_pnl": str(daily_pnl),
                "gross_exposure_pct": str(gross / snapshot.account.equity * Decimal("100")),
            },
            "market": {
                "is_open": market_clock.is_open,
                "clock_timestamp": market_clock.timestamp.isoformat(),
            },
            "positions": {
                symbol: {
                    "qty": str(position.qty),
                    "market_price": str(position.market_price),
                    "market_value": str(position.market_value),
                }
                for symbol, position in sorted(snapshot.positions.items())
            },
            "orders_today": snapshot.orders_today,
            "pending_orders": [asdict(order) for order in snapshot.pending_orders],
            "journal": self.journal.snapshot(),
        }

    async def mandate_state(self, *, now: datetime | None = None) -> dict[str, Any]:
        checked_at = now or datetime.now(timezone.utc)
        snapshot, market_clock = await asyncio.gather(
            self._snapshot(checked_at), self.broker.get_market_clock()
        )
        metrics = self._observable_metrics(snapshot)
        daily_loss_pct = metrics["daily_loss_pct"]
        portfolio = Portfolio(
            equity=snapshot.account.equity,
            positions=snapshot.positions,
            pending_orders=snapshot.pending_orders,
            realized_pnl_today=snapshot.account.equity - snapshot.account.last_equity,
            orders_today=snapshot.orders_today,
        )
        usage = calculate_risk_usage(portfolio)
        limits = self.mandate.limits
        wake_metrics = {
            **metrics,
            "any_breach_requiring_override": Decimal(
                any(entry["outcome"] == "denied" for entry in self.journal.snapshot())
            ),
        }
        return {
            "mandate": self.mandate.model_dump(mode="json"),
            "as_of": checked_at.isoformat(),
            "market_is_open": market_clock.is_open,
            "usage": {
                "max_position_pct": str(usage.max_position_pct),
                "gross_exposure_pct": str(usage.gross_exposure_pct),
                "daily_loss_pct": str(daily_loss_pct),
                "orders_today": snapshot.orders_today,
            },
            "headroom": {
                "max_position_pct": str(limits.max_position_pct - usage.max_position_pct),
                "max_gross_exposure_pct": str(
                    limits.max_gross_exposure_pct - usage.gross_exposure_pct
                ),
                "max_daily_loss_pct": str(limits.max_daily_loss_pct - daily_loss_pct),
                "max_orders_per_day": limits.max_orders_per_day - snapshot.orders_today,
            },
            "wake_triggers": evaluate_wake_conditions(self.mandate.wake_me_if, wake_metrics),
            "active_predecisions": [
                directive.model_dump(mode="json")
                for directive in self._active_predecisions(metrics)
            ],
        }

    async def submit(
        self,
        order: OrderIntent,
        *,
        rationale: str,
        intent_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not rationale.strip():
            raise ValueError("rationale is required")
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", intent_id) is None:
            raise ValueError("intent_id must be 1-64 safe identifier characters")
        # This intentionally does not accept a prior CheckResult. The broker state is
        # fetched again immediately before every irreversible action.
        async with self._submit_lock:
            digest = hashlib.sha256(f"{self.mandate.name}:{intent_id}".encode()).hexdigest()[:24]
            client_order_id = f"mandate-{digest}"
            existing = await self.broker.find_order_by_client_id(client_order_id)
            if existing is not None:
                self.journal.append(
                    "submit_order",
                    "deduplicated",
                    rationale,
                    {"client_order_id": client_order_id, "intent_id": intent_id},
                )
                return {
                    "submitted": True,
                    "deduplicated": True,
                    "client_order_id": client_order_id,
                    "broker": existing,
                }
            result, _snapshot = await self.evaluate(order, now=now)
            if not result.allowed:
                details = {"order": asdict(order), "breaches": [asdict(item) for item in result.breaches]}
                self.journal.append("submit_order", "denied", rationale, details)
                return {"submitted": False, **asdict(result)}

            response = await self.broker.submit_order(order, client_order_id=client_order_id)
            self.journal.append(
                "submit_order",
                "submitted",
                rationale,
                {
                    "client_order_id": client_order_id,
                    "intent_id": intent_id,
                    "order": asdict(order),
                },
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
            if not self.mandate.allow_risk_reducing_market_close:
                self.journal.append("close_position", "denied", rationale, {"rule": "risk_close"})
                return {
                    "submitted": False,
                    "breaches": [
                        {
                            "rule": "allow_risk_reducing_market_close",
                            "limit": "true",
                            "projected": "false",
                            "headroom": "not-authorized",
                        }
                    ],
                }
            checked_at = now or datetime.now(timezone.utc)
            market_clock = await self.broker.get_market_clock()
            breaches = tuple(
                breach
                for breach in (
                    check_session_window(
                        self.mandate, checked_at, market_is_open=market_clock.is_open
                    ),
                    check_expiry(self.mandate, checked_at),
                )
                if breach is not None
            )
            if breaches:
                details = {
                    "symbol": symbol.upper(),
                    "qty": str(qty),
                    "breaches": [asdict(item) for item in breaches],
                }
                self.journal.append("close_position", "denied", rationale, details)
                return {"submitted": False, "breaches": [asdict(item) for item in breaches]}
            response = await self.broker.close_position(symbol, qty)
            self.journal.append(
                "close_position", "submitted", rationale, {"symbol": symbol.upper(), "qty": str(qty)}
            )
            return {"submitted": True, "broker": response}

    async def cancel_order(self, order_id: str, *, rationale: str) -> dict[str, Any]:
        if not order_id.strip() or not rationale.strip():
            raise ValueError("order_id and rationale are required")
        async with self._submit_lock:
            order = await self.broker.get_order_by_id(order_id)
            client_order_id = str(order.get("client_order_id", ""))
            created_by_guard = any(
                entry["action"] == "submit_order"
                and entry["outcome"] == "submitted"
                and entry["details"].get("client_order_id") == client_order_id
                for entry in self.journal.snapshot()
            )
            if not client_order_id.startswith("mandate-") or not created_by_guard:
                details = {
                    "order_id": order_id,
                    "client_order_id": client_order_id,
                    "reason": "order was not created by this guard journal",
                }
                self.journal.append("cancel_order", "parked", rationale, details)
                return {"cancelled": False, "parked": True, **details}
            await self.broker.cancel_order(order_id)
            self.journal.append(
                "cancel_order",
                "submitted",
                rationale,
                {"order_id": order_id, "client_order_id": client_order_id},
            )
            return {
                "cancelled": True,
                "order_id": order_id,
                "client_order_id": client_order_id,
            }

    def park(self, *, reason: str, intended_action: str) -> dict[str, Any]:
        if not reason.strip() or not intended_action.strip():
            raise ValueError("reason and intended_action are required")
        entry = self.journal.append("park", "parked", reason, {"intended_action": intended_action})
        return asdict(entry)
