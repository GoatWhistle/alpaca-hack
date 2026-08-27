from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from mandate_guard.alpaca import AccountSnapshot, MarketClock
from mandate_guard.checks import OrderIntent, PendingOrder, Position, Side
from mandate_guard.mandate import Mandate, Predecision
from mandate_guard.service import GuardService
from mandate_guard.state import SessionJournal


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
        self.cancelled: list[str] = []
        self.external_orders: dict[str, dict[str, str]] = {}
        self.equity = Decimal("10000")
        self.last_equity = Decimal("10000")

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(self.equity, self.last_equity, "ACTIVE")

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

    async def find_order_by_client_id(self, client_order_id: str):
        for _order, submitted_id in self.submitted:
            if submitted_id == client_order_id:
                return {"id": "paper-order-1", "client_order_id": submitted_id}
        return None

    async def get_order_by_id(self, order_id: str):
        if order_id in self.external_orders:
            return self.external_orders[order_id]
        for _order, client_order_id in self.submitted:
            if order_id == "paper-order-1":
                return {"id": order_id, "client_order_id": client_order_id}
        raise ValueError("unknown order")

    async def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    async def close_position(self, symbol: str, qty: Decimal):
        self.closed.append((symbol, qty))
        return {"id": "close-1"}


def _write_mandate(path: Path, mandate: Mandate) -> None:
    path.write_text(
        yaml.safe_dump(mandate.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


def test_check_hot_reloads_human_mandate_without_restart(
    mandate: Mandate, market_open: datetime, tmp_path: Path
) -> None:
    mandate_path = tmp_path / "mandate.yaml"
    _write_mandate(mandate_path, mandate)
    service = GuardService(mandate, FakeBroker(), mandate_path=mandate_path)
    aapl = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    assert asyncio.run(service.check(aapl, now=market_open))["allowed"] is True

    _write_mandate(mandate_path, mandate.model_copy(update={"universe": ["MSFT"]}))
    reloaded = asyncio.run(service.check(aapl, now=market_open))

    assert reloaded["allowed"] is False
    assert any(breach["rule"] == "universe" for breach in reloaded["breaches"])


def test_invalid_hot_reloaded_mandate_fails_closed_before_broker_access(
    mandate: Mandate, market_open: datetime, tmp_path: Path
) -> None:
    mandate_path = tmp_path / "mandate.yaml"
    _write_mandate(mandate_path, mandate)
    broker = FakeBroker()
    service = GuardService(mandate, broker, mandate_path=mandate_path)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    mandate_path.write_text("limits: [partially-written", encoding="utf-8")

    with pytest.raises((ValueError, yaml.YAMLError)):
        asyncio.run(service.check(order, now=market_open))

    assert broker.last_since is None
    assert broker.submitted == []


def test_submit_rechecks_fresh_state_after_dry_run(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("10"), "limit", limit_price=Decimal("100"))

    dry_run = asyncio.run(service.check(order, now=market_open))
    assert dry_run["allowed"] is True

    broker.positions["AAPL"] = Position(Decimal("1"), Decimal("100"))
    submitted = asyncio.run(
        service.submit(order, rationale="breakout", intent_id="dry-run-race", now=market_open)
    )
    assert submitted["submitted"] is False
    assert broker.submitted == []
    assert service.journal.snapshot()[0]["outcome"] == "denied"


def test_check_returns_guard_computed_portfolio_after(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("2"), Decimal("100"))
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("3"), "limit", limit_price=Decimal("100"))

    result = asyncio.run(service.check(order, now=market_open))

    assert result["portfolio_after"] == {
        "symbol": "AAPL",
        "projected_qty": "5",
        "position_pct": "5.00",
        "gross_exposure_pct": "5.00",
        "reference_price": "100",
    }


def test_submit_allowed_order_uses_auditable_client_id(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("5"), "limit", limit_price=Decimal("100"))
    result = asyncio.run(
        service.submit(order, rationale="confirmed momentum", intent_id="aapl-entry-1", now=market_open)
    )
    assert result["submitted"] is True
    assert result["client_order_id"].startswith("mandate-")
    assert len(result["mandate_fingerprint"]) == 64
    assert len(broker.submitted) == 1
    assert service.journal.snapshot()[0]["rationale"] == "confirmed momentum"
    assert {
        entry["details"]["mandate_fingerprint"] for entry in service.journal.snapshot()
    } == {result["mandate_fingerprint"]}


def test_hot_reloaded_mandate_versions_are_distinguishable_in_audit_log(
    mandate: Mandate, market_open: datetime, tmp_path: Path
) -> None:
    mandate_path = tmp_path / "mandate.yaml"
    _write_mandate(mandate_path, mandate)
    service = GuardService(mandate, FakeBroker(), mandate_path=mandate_path)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    first = asyncio.run(
        service.submit(order, rationale="first policy", intent_id="policy-v1", now=market_open)
    )
    tighter_limits = mandate.limits.model_copy(update={"max_orders_per_day": 10})
    _write_mandate(mandate_path, mandate.model_copy(update={"limits": tighter_limits}))
    second = asyncio.run(
        service.submit(order, rationale="second policy", intent_id="policy-v2", now=market_open)
    )

    assert first["submitted"] is True
    assert second["submitted"] is True
    assert first["mandate_fingerprint"] != second["mandate_fingerprint"]


def test_retry_keeps_durable_client_id_after_mandate_rename(
    mandate: Mandate, market_open: datetime, tmp_path: Path
) -> None:
    mandate_path = tmp_path / "mandate.yaml"
    _write_mandate(mandate_path, mandate)
    broker = FakeBroker()
    service = GuardService(mandate, broker, mandate_path=mandate_path)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    first = asyncio.run(
        service.submit(order, rationale="original", intent_id="rename-safe", now=market_open)
    )
    _write_mandate(mandate_path, mandate.model_copy(update={"name": "renamed-mandate"}))
    retry = asyncio.run(
        service.submit(order, rationale="retry", intent_id="rename-safe", now=market_open)
    )

    assert retry["submitted"] is True
    assert retry["deduplicated"] is True
    assert retry["client_order_id"] == first["client_order_id"]
    assert len(broker.submitted) == 1


def test_conflicting_durable_client_ids_fail_closed(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    journal = SessionJournal()
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    fingerprint = GuardService._order_fingerprint(order)
    for client_order_id in ("mandate-first", "mandate-second"):
        journal.append(
            "submit_order",
            "prepared",
            "corrupt provenance fixture",
            {
                "intent_id": "conflicting-provenance",
                "client_order_id": client_order_id,
                "order_fingerprint": fingerprint,
            },
        )
    service = GuardService(mandate, broker, journal)

    with pytest.raises(RuntimeError, match="conflicting durable client order IDs"):
        asyncio.run(
            service.submit(
                order,
                rationale="must fail closed",
                intent_id="conflicting-provenance",
                now=market_open,
            )
        )

    assert broker.submitted == []


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
    result = asyncio.run(
        service.submit(order, rationale="second entry", intent_id="pending-risk", now=market_open)
    )
    assert result["submitted"] is False
    assert broker.submitted == []


def test_concurrent_submissions_are_serialized(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.orders_today = 19
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    async def submit_twice():
        return await asyncio.gather(
            service.submit(order, rationale="first", intent_id="concurrent-1", now=market_open),
            service.submit(order, rationale="second", intent_id="concurrent-2", now=market_open),
        )

    results = asyncio.run(submit_twice())
    assert [result["submitted"] for result in results].count(True) == 1
    assert len(broker.submitted) == 1


def test_exchange_clock_closure_denies_weekday_order(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.market_open = False
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    result = asyncio.run(
        service.submit(order, rationale="holiday", intent_id="holiday", now=market_open)
    )
    assert result["submitted"] is False
    assert any(breach["rule"] == "session" for breach in result["breaches"])


def test_order_day_starts_at_new_york_midnight(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    asyncio.run(service.check(order, now=market_open))
    assert broker.last_since == datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)


def test_close_position_respects_explicit_risk_reduction_policy(
    mandate: Mandate, market_open: datetime
) -> None:
    mandate = mandate.model_copy(update={"allow_risk_reducing_market_close": False})
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("5"), Decimal("100"))
    service = GuardService(mandate, broker)
    denied = asyncio.run(
        service.close_position("AAPL", Decimal("1"), rationale="reduce risk", now=market_open)
    )
    assert denied["submitted"] is False
    assert any(breach["rule"] == "allow_risk_reducing_market_close" for breach in denied["breaches"])
    assert broker.closed == []


def test_close_position_submits_only_when_market_close_is_authorized(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("5"), Decimal("100"))
    service = GuardService(mandate, broker)
    result = asyncio.run(
        service.close_position("AAPL", Decimal("2"), rationale="reduce risk", now=market_open)
    )
    assert result["submitted"] is True
    assert broker.closed == [("AAPL", Decimal("2"))]


def test_session_state_contains_live_risk_snapshot(mandate: Mandate, market_open: datetime) -> None:
    broker = FakeBroker()
    broker.positions["AAPL"] = Position(Decimal("5"), Decimal("100"))
    broker.pending_orders = (PendingOrder("MSFT", Side.BUY, Decimal("1"), Decimal("200")),)
    service = GuardService(mandate, broker)
    state = asyncio.run(service.session_state(now=market_open))
    assert state["account"]["equity"] == "10000"
    assert state["account"]["gross_exposure_pct"] == "5.00"
    assert state["market"]["is_open"] is True
    assert state["positions"]["AAPL"]["market_value"] == "500"
    assert state["pending_orders"][0]["symbol"] == "MSFT"


def test_mandate_state_reports_headroom_and_live_wake_triggers(
    mandate: Mandate, market_open: datetime
) -> None:
    mandate = mandate.model_copy(
        update={
            "wake_me_if": [
                "daily_loss_pct > 1.2",
                "single_symbol_move_pct > 5",
                "any_breach_requiring_override > 0",
            ]
        }
    )
    broker = FakeBroker()
    broker.equity = Decimal("9800")
    broker.positions["AAPL"] = Position(
        Decimal("5"), Decimal("100"), change_today_pct=Decimal("6")
    )
    broker.pending_orders = (PendingOrder("MSFT", Side.BUY, Decimal("2"), Decimal("200")),)
    service = GuardService(mandate, broker)
    service.journal.append("submit_order", "denied", "limit breach")

    state = asyncio.run(service.mandate_state(now=market_open))

    assert state["usage"]["max_position_pct"] == str(Decimal("500") / Decimal("9800") * 100)
    assert Decimal(state["headroom"]["max_position_pct"]) < Decimal("10")
    assert {trigger["metric"] for trigger in state["wake_triggers"]} == {
        "daily_loss_pct",
        "single_symbol_move_pct",
        "any_breach_requiring_override",
    }


def test_predecided_branch_is_enforced_by_guard_before_hard_limit(
    mandate: Mandate, market_open: datetime
) -> None:
    directive = {
        "when": "daily_loss_pct >= 1",
        "then": "park_new_orders",
        "reason": "pause before hard daily stop",
    }
    mandate = mandate.model_copy(
        update={"predecided": [Predecision.model_validate(directive)]}
    )
    broker = FakeBroker()
    broker.equity = Decimal("9900")
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    result = asyncio.run(service.check(order, now=market_open))

    assert result["allowed"] is False
    assert any(breach["rule"] == "predecided" for breach in result["breaches"])
    state = asyncio.run(service.mandate_state(now=market_open))
    assert state["active_predecisions"] == [directive]


def test_retry_with_same_intent_id_is_deduplicated(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    first = asyncio.run(
        service.submit(order, rationale="retry-safe", intent_id="stable-intent", now=market_open)
    )
    second = asyncio.run(
        service.submit(order, rationale="retry-safe", intent_id="stable-intent", now=market_open)
    )
    assert first["submitted"] is True
    assert second["deduplicated"] is True
    assert len(broker.submitted) == 1


def test_denied_intent_cannot_execute_later_when_state_changes(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    broker.market_open = False
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    first = asyncio.run(
        service.submit(order, rationale="market closed", intent_id="final-denial", now=market_open)
    )
    broker.market_open = True
    second = asyncio.run(
        service.submit(order, rationale="market reopened", intent_id="final-denial", now=market_open)
    )

    assert first["submitted"] is False
    assert second["submitted"] is False
    assert second["denied_final"] is True
    assert second["reason"] == "this intent_id was previously denied"
    assert broker.submitted == []


def test_reusing_intent_id_with_changed_terms_fails_closed(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    first_order = OrderIntent(
        "AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100")
    )
    changed_order = OrderIntent(
        "AAPL", Side.BUY, Decimal("2"), "limit", limit_price=Decimal("100")
    )

    first = asyncio.run(
        service.submit(first_order, rationale="original", intent_id="immutable", now=market_open)
    )
    second = asyncio.run(
        service.submit(changed_order, rationale="changed", intent_id="immutable", now=market_open)
    )

    assert first["submitted"] is True
    assert second["submitted"] is False
    assert second["intent_conflict"] is True
    assert len(broker.submitted) == 1


def test_prepared_intent_recovers_provenance_after_post_submit_journal_failure(
    mandate: Mandate, market_open: datetime
) -> None:
    class FailOnceAfterBrokerJournal(SessionJournal):
        def __init__(self) -> None:
            super().__init__()
            self.fail_terminal_write = True

        def append(self, action, outcome, rationale, details=None):
            if outcome == "submitted" and self.fail_terminal_write:
                self.fail_terminal_write = False
                raise OSError("simulated crash before terminal journal write")
            return super().append(action, outcome, rationale, details)

    broker = FakeBroker()
    journal = FailOnceAfterBrokerJournal()
    service = GuardService(mandate, broker, journal)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))

    try:
        asyncio.run(
            service.submit(order, rationale="crash test", intent_id="recoverable", now=market_open)
        )
    except OSError:
        pass
    else:
        raise AssertionError("terminal journal failure must propagate")

    assert len(broker.submitted) == 1
    assert [entry["outcome"] for entry in journal.snapshot()] == ["prepared"]

    recovered = GuardService(mandate, broker, journal)
    result = asyncio.run(
        recovered.submit(order, rationale="recover", intent_id="recoverable", now=market_open)
    )
    cancelled = asyncio.run(
        recovered.cancel_order("paper-order-1", rationale="cancel recovered order")
    )

    assert result["deduplicated"] is True
    assert "submitted_reconciled" in [entry["outcome"] for entry in journal.snapshot()]
    assert cancelled["cancelled"] is True


def test_cancel_only_allows_orders_recorded_as_submitted_by_guard(
    mandate: Mandate, market_open: datetime
) -> None:
    broker = FakeBroker()
    service = GuardService(mandate, broker)
    order = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    asyncio.run(
        service.submit(order, rationale="owned order", intent_id="cancel-owned", now=market_open)
    )

    result = asyncio.run(service.cancel_order("paper-order-1", rationale="signal invalidated"))

    assert result["cancelled"] is True
    assert broker.cancelled == ["paper-order-1"]


def test_cancel_parks_foreign_order_instead_of_touching_it(mandate: Mandate) -> None:
    broker = FakeBroker()
    broker.external_orders["manual-order"] = {
        "id": "manual-order",
        "client_order_id": "human-protective-stop",
    }
    service = GuardService(mandate, broker)

    result = asyncio.run(service.cancel_order("manual-order", rationale="agent changed its mind"))

    assert result["cancelled"] is False
    assert result["parked"] is True
    assert broker.cancelled == []
    assert service.journal.snapshot()[-1]["outcome"] == "parked"


def test_cancel_rejects_spoofed_mandate_prefix_without_journal_proof(mandate: Mandate) -> None:
    broker = FakeBroker()
    broker.external_orders["spoofed-order"] = {
        "id": "spoofed-order",
        "client_order_id": "mandate-spoofed",
    }
    service = GuardService(mandate, broker)

    result = asyncio.run(service.cancel_order("spoofed-order", rationale="looks internal"))

    assert result["cancelled"] is False
    assert broker.cancelled == []
