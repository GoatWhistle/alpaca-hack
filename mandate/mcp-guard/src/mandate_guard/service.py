from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from mandate_guard.alpaca import AccountSnapshot, MarketClock, PortfolioSnapshot
from mandate_guard.checks import (
    NEW_YORK,
    Breach,
    CheckResult,
    OrderIntent,
    PendingOrder,
    Portfolio,
    Position,
    calculate_risk_usage,
    check_expiry,
    check_order,
    check_session_window,
)
from mandate_guard.mandate import Mandate, Predecision, load_mandate
from mandate_guard.state import SessionJournal
from mandate_guard.wake import evaluate_wake_conditions, parse_wake_condition


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
    def __init__(
        self,
        mandate: Mandate,
        broker: PaperBroker,
        journal: SessionJournal | None = None,
        mandate_path: str | Path | None = None,
    ) -> None:
        self.mandate = mandate
        self.broker = broker
        self.journal = journal or SessionJournal()
        self.mandate_path = Path(mandate_path) if mandate_path is not None else None
        self._submit_lock = asyncio.Lock()

    def _current_mandate(self) -> Mandate:
        # The human edits this server-side file; the agent has no reload or write tool.
        # Reloading on every policy operation avoids stale authority. Invalid or partial
        # content raises before any irreversible action and therefore fails closed.
        return load_mandate(self.mandate_path) if self.mandate_path is not None else self.mandate

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

    async def evaluate(
        self,
        order: OrderIntent,
        *,
        now: datetime | None = None,
    ) -> tuple[CheckResult, PortfolioSnapshot]:
        return await self._evaluate_with_mandate(order, self._current_mandate(), now=now)

    async def _evaluate_with_mandate(
        self,
        order: OrderIntent,
        mandate: Mandate,
        *,
        now: datetime | None = None,
    ) -> tuple[CheckResult, PortfolioSnapshot]:
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
            mandate,
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
            for directive in self._active_predecisions(mandate, metrics)
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

    @staticmethod
    def _active_predecisions(
        mandate: Mandate, metrics: dict[str, Decimal]
    ) -> list[Predecision]:
        active: list[Predecision] = []
        for directive in mandate.predecided:
            condition = parse_wake_condition(directive.when)
            if condition.evaluate(metrics[condition.metric]):
                active.append(directive)
        return active

    @staticmethod
    def _canonical_order(order: OrderIntent) -> dict[str, str | None]:
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": format(order.qty.normalize(), "f"),
            "order_type": order.order_type,
            "instrument": order.instrument,
            "limit_price": (
                format(order.limit_price.normalize(), "f")
                if order.limit_price is not None
                else None
            ),
        }

    @classmethod
    def _order_fingerprint(cls, order: OrderIntent) -> str:
        encoded = json.dumps(cls._canonical_order(order), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _mandate_fingerprint(mandate: Mandate) -> str:
        encoded = json.dumps(
            mandate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _intent_records(self, intent_id: str) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.journal.snapshot()
            if entry["action"] == "submit_order"
            and entry["details"].get("intent_id") == intent_id
        ]

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
        active_mandate = self._current_mandate()
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
        limits = active_mandate.limits
        wake_metrics = {
            **metrics,
            "any_breach_requiring_override": Decimal(
                any(entry["outcome"] == "denied" for entry in self.journal.snapshot())
            ),
        }
        return {
            "mandate": active_mandate.model_dump(mode="json"),
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
            "wake_triggers": evaluate_wake_conditions(active_mandate.wake_me_if, wake_metrics),
            "active_predecisions": [
                directive.model_dump(mode="json")
                for directive in self._active_predecisions(active_mandate, metrics)
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
            active_mandate = self._current_mandate()
            digest = hashlib.sha256(f"{active_mandate.name}:{intent_id}".encode()).hexdigest()[:24]
            client_order_id = f"mandate-{digest}"
            canonical_order = self._canonical_order(order)
            order_fingerprint = self._order_fingerprint(order)
            mandate_fingerprint = self._mandate_fingerprint(active_mandate)
            records = self._intent_records(intent_id)
            binding_records = [
                entry
                for entry in records
                if entry["outcome"]
                in {"prepared", "submitted", "submitted_reconciled", "denied"}
            ]
            bound_mandate_fingerprint = next(
                (
                    entry["details"].get("mandate_fingerprint")
                    for entry in binding_records
                    if entry["details"].get("mandate_fingerprint")
                ),
                mandate_fingerprint,
            )
            if any(entry["outcome"] == "denied" for entry in binding_records):
                return {
                    "submitted": False,
                    "denied_final": True,
                    "client_order_id": client_order_id,
                    "reason": "this intent_id was previously denied",
                }
            if any(
                entry["details"].get("order_fingerprint") != order_fingerprint
                for entry in binding_records
            ):
                self.journal.append(
                    "submit_order",
                    "conflict",
                    rationale,
                    {
                        "client_order_id": client_order_id,
                        "intent_id": intent_id,
                        "order": canonical_order,
                        "order_fingerprint": order_fingerprint,
                        "mandate_fingerprint": mandate_fingerprint,
                    },
                )
                return {
                    "submitted": False,
                    "intent_conflict": True,
                    "client_order_id": client_order_id,
                    "reason": "intent_id is already bound to different order terms",
                }
            existing = await self.broker.find_order_by_client_id(client_order_id)
            if existing is not None:
                if not binding_records:
                    self.journal.append(
                        "submit_order",
                        "parked",
                        rationale,
                        {
                            "client_order_id": client_order_id,
                            "intent_id": intent_id,
                            "reason": "broker order has no durable guard provenance",
                            "mandate_fingerprint": mandate_fingerprint,
                        },
                    )
                    return {
                        "submitted": False,
                        "parked": True,
                        "client_order_id": client_order_id,
                        "reason": "existing broker order is not proven by the guard journal",
                    }
                if not any(
                    entry["outcome"] in {"submitted", "submitted_reconciled"}
                    for entry in binding_records
                ):
                    self.journal.append(
                        "submit_order",
                        "submitted_reconciled",
                        rationale,
                        {
                            "client_order_id": client_order_id,
                            "intent_id": intent_id,
                            "order": canonical_order,
                            "order_fingerprint": order_fingerprint,
                            "mandate_fingerprint": bound_mandate_fingerprint,
                        },
                    )
                self.journal.append(
                    "submit_order",
                    "deduplicated",
                    rationale,
                    {
                        "client_order_id": client_order_id,
                        "intent_id": intent_id,
                        "order_fingerprint": order_fingerprint,
                        "mandate_fingerprint": bound_mandate_fingerprint,
                    },
                )
                return {
                    "submitted": True,
                    "deduplicated": True,
                    "client_order_id": client_order_id,
                    "mandate_fingerprint": bound_mandate_fingerprint,
                    "broker": existing,
                }
            result, _snapshot = await self._evaluate_with_mandate(
                order, active_mandate, now=now
            )
            if not result.allowed:
                details = {
                    "client_order_id": client_order_id,
                    "intent_id": intent_id,
                    "order": canonical_order,
                    "order_fingerprint": order_fingerprint,
                    "mandate_fingerprint": mandate_fingerprint,
                    "breaches": [asdict(item) for item in result.breaches],
                }
                self.journal.append("submit_order", "denied", rationale, details)
                return {
                    "submitted": False,
                    "mandate_fingerprint": mandate_fingerprint,
                    **asdict(result),
                }

            if not any(entry["outcome"] == "prepared" for entry in binding_records):
                self.journal.append(
                    "submit_order",
                    "prepared",
                    rationale,
                    {
                        "client_order_id": client_order_id,
                        "intent_id": intent_id,
                        "order": canonical_order,
                        "order_fingerprint": order_fingerprint,
                        "mandate_fingerprint": mandate_fingerprint,
                    },
                )
            response = await self.broker.submit_order(order, client_order_id=client_order_id)
            self.journal.append(
                "submit_order",
                "submitted",
                rationale,
                {
                    "client_order_id": client_order_id,
                    "intent_id": intent_id,
                    "order": canonical_order,
                    "order_fingerprint": order_fingerprint,
                    "mandate_fingerprint": mandate_fingerprint,
                },
            )
            return {
                "submitted": True,
                "client_order_id": client_order_id,
                "mandate_fingerprint": mandate_fingerprint,
                "broker": response,
            }

    async def close_position(
        self, symbol: str, qty: Decimal, *, rationale: str, now: datetime | None = None
    ) -> dict[str, Any]:
        if not rationale.strip() or qty <= 0:
            raise ValueError("positive qty and rationale are required")
        async with self._submit_lock:
            active_mandate = self._current_mandate()
            positions = await self.broker.get_positions()
            position = positions.get(symbol.upper())
            if position is None or qty > abs(position.qty):
                raise ValueError("close quantity exceeds the current position")
            if not active_mandate.allow_risk_reducing_market_close:
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
                        active_mandate, checked_at, market_is_open=market_clock.is_open
                    ),
                    check_expiry(active_mandate, checked_at),
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
                and entry["outcome"] in {"submitted", "submitted_reconciled"}
                and entry["details"].get("client_order_id") == client_order_id
                for entry in self.journal.snapshot()
            )
            prepared_record = next(
                (
                    entry
                    for entry in self.journal.snapshot()
                    if entry["action"] == "submit_order"
                    and entry["outcome"] == "prepared"
                    and entry["details"].get("client_order_id") == client_order_id
                ),
                None,
            )
            if not created_by_guard and prepared_record is not None:
                self.journal.append(
                    "submit_order",
                    "submitted_reconciled",
                    rationale,
                    {
                        **prepared_record["details"],
                        "broker_order_id": order_id,
                    },
                )
                created_by_guard = True
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
