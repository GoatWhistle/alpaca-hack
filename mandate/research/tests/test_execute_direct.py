from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "execute_direct.py"
SPEC = importlib.util.spec_from_file_location("execute_direct", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
execute_direct = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(execute_direct)


def test_select_entry_uses_challenged_candidate_without_mandate_layer() -> None:
    evaluation = {
        "research_candidates": ["AAPL"],
        "symbols": {
            "AAPL": {
                "research_candidate": True,
                "signal_path": "price_confirmation",
                "strategies": {"regime_ensemble": {"direction": "buy", "strength": "0.8"}},
                "sizing": {"available": True, "qty": 10},
                "market": {"last": "100"},
            }
        },
    }
    order = execute_direct.select_entry(
        evaluation,
        {"action": "PROPOSE", "candidate": "AAPL", "hard_contradiction": False},
    )
    assert order == {
        "kind": "entry",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "limit_price": "100.12",
        "rationale": "direct price_confirmation entry; ensemble strength 0.8 after LLM challenge",
    }


def test_hard_contradiction_still_parks() -> None:
    assert execute_direct.select_entry(
        {"research_candidates": [], "symbols": {}},
        {"action": "PARK", "candidate": None, "hard_contradiction": True},
    ) is None


def test_closed_market_never_constructs_a_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        execute_direct,
        "PaperBroker",
        lambda: (_ for _ in ()).throw(AssertionError("broker must not be constructed")),
    )
    result = execute_direct.execute(
        {"market_is_open": False},
        {"action": "PROPOSE", "candidate": "AAPL", "hard_contradiction": False},
    )
    assert result["action"] == "PARK"
    assert result["submitted"] is False


def test_exit_selection_does_not_crash_and_requires_confident_reversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execute_direct, "run_exit_evaluation", lambda _positions: {
        "proposals": [{
            "symbol": "AAPL", "order_side": "sell", "qty": "2", "limit_price": "99.9",
            "rationale": "long stop", "reason": "long_stop", "urgency": "immediate", "age_minutes": 5,
        }],
    })
    positions = [{"symbol": "AAPL", "qty": "2", "avg_entry_price": "100", "asset_class": "us_equity"}]
    assert execute_direct.select_exits({"symbols": {}}, positions)[0]["exit_reason"] == "long_stop"

    monkeypatch.setattr(execute_direct, "run_exit_evaluation", lambda _positions: {"proposals": []})
    weak = {"symbols": {"AAPL": {
        "strategies": {"regime_ensemble": {"direction": "sell", "strength": "0.08"}},
        "market": {"last": "100"},
    }}}
    assert execute_direct.select_exits(weak, positions) == []


def test_spy_and_existing_option_underlying_are_not_selected() -> None:
    evaluation = {
        "research_candidates": ["SPY", "AAPL"],
        "symbols": {
            symbol: {
                "research_candidate": True,
                "signal_path": "price_confirmation",
                "strategies": {"regime_ensemble": {"direction": "buy", "strength": "0.8"}},
                "sizing": {"available": True, "qty": 10},
                "market": {"last": "100"},
            } for symbol in ("SPY", "AAPL")
        },
    }
    decision = {"action": "PROPOSE", "candidate": "SPY", "candidates": ["SPY", "AAPL"], "hard_contradiction": False}
    assert execute_direct.select_entries(evaluation, decision, existing_symbols={"AAPL"}) == []


def test_option_builder_prefers_defined_risk_debit_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    expiry = (datetime.now(timezone.utc).date() + timedelta(days=10)).strftime("%y%m%d")

    class Broker:
        def option_chain(self, underlying: str) -> dict:
            assert underlying == "AAPL"
            return {
                f"AAPL{expiry}C00100000": {"latestQuote": {"bp": "3.90", "ap": "4.00"}},
                f"AAPL{expiry}C00105000": {"latestQuote": {"bp": "1.90", "ap": "2.00"}},
            }

    monkeypatch.setenv("MANDATE_OPTIONS_ENABLED", "true")
    order = execute_direct.build_option_order(
        Broker(),
        {
            "symbol": "AAPL", "side": "buy", "last": "100", "qty": "50",
            "rationale": "strong price confirmation",
        },
        {"equity": "100000", "options_approved_level": 3},
        option_exposure=execute_direct.Decimal("0"),
    )
    assert order is not None
    assert order["kind"] == "option_spread_entry"
    assert order["payload"]["order_class"] == "mleg"
    assert [leg["side"] for leg in order["payload"]["legs"]] == ["buy", "sell"]
    assert order["payload"]["qty"] == "20"


def test_option_positions_receive_atomic_expiry_exit() -> None:
    expiry = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%y%m%d")
    positions = [
        {
            "symbol": f"AAPL{expiry}C00100000", "asset_class": "us_option", "qty": "2",
            "current_price": "3", "cost_basis": "800", "unrealized_pl": "-200",
        },
        {
            "symbol": f"AAPL{expiry}C00105000", "asset_class": "us_option", "qty": "-2",
            "current_price": "1", "cost_basis": "-300", "unrealized_pl": "100",
        },
    ]
    actions = execute_direct.select_option_exits(positions, limit=2)
    assert len(actions) == 1
    assert actions[0]["kind"] == "option_exit_mleg"
    assert actions[0]["payload"]["qty"] == "2"
    assert [leg["position_intent"] for leg in actions[0]["payload"]["legs"]] == [
        "sell_to_close", "buy_to_close",
    ]


def test_flat_option_position_receives_time_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    expiry = (now.date() + timedelta(days=10)).strftime("%y%m%d")
    monkeypatch.setenv("MANDATE_OPTION_TIME_STOP_MINUTES", "60")
    actions = execute_direct.select_option_exits(
        [{
            "symbol": f"AAPL{expiry}C00100000", "asset_class": "us_option", "qty": "1",
            "current_price": "2", "cost_basis": "200", "unrealized_pl": "5",
        }],
        now=now,
        first_seen={"AAPL": (now - timedelta(minutes=61)).isoformat()},
    )
    assert actions[0]["exit_reason"] == "option_time_stop_61m"


def test_exit_is_rechecked_and_clamped_to_live_position() -> None:
    class Broker:
        def positions(self) -> list[dict]:
            return [{"symbol": "AAPL", "qty": "3", "asset_class": "us_equity"}]

    action = execute_direct._refresh_exit_action(Broker(), {
        "kind": "exit", "symbol": "AAPL", "side": "sell", "qty": "10",
        "limit_price": "99", "rationale": "stop",
    })
    assert action["qty"] == "3"
    assert execute_direct._equity_payload(action)["position_intent"] == "sell_to_close"


def test_entry_risk_gate_enforces_daily_loss_and_order_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class Broker:
        def orders(self, **_kwargs: object) -> list[dict]:
            return [{} for _ in range(3)]

    monkeypatch.setenv("MANDATE_DAILY_ENTRY_STOP_PCT", "8")
    mandate = tmp_path / "mandate.yaml"
    mandate.write_text(
        "limits:\n  max_daily_loss_pct: 10\n  max_orders_per_day: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MANDATE_PATH", str(mandate))
    gate = execute_direct._entry_risk_gate(
        Broker(), {"equity": "91000", "last_equity": "100000"},
    )
    assert gate["allow_entries"] is False
    assert any(reason.startswith("daily_loss_") for reason in gate["reasons"])
    assert "order_budget_3_of_3" in gate["reasons"]


def test_only_tagged_open_orders_are_recovered() -> None:
    class Broker:
        cancelled: list[str] = []

        def orders(self, **_kwargs: object) -> list[dict]:
            return [
                {"id": "ours", "client_order_id": "mandate-direct-aapl-deadbeef"},
                {"id": "other", "client_order_id": "manual-order"},
            ]

        def cancel(self, order_id: str) -> None:
            self.cancelled.append(order_id)

    broker = Broker()
    recovered = execute_direct._cancel_tagged_open_orders(broker)
    assert broker.cancelled == ["ours"]
    assert recovered == ["mandate-direct-aapl-deadbeef"]


def test_open_market_cycle_blocks_entries_after_daily_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class Broker:
        def account(self) -> dict:
            return {"equity": "91000", "last_equity": "100000", "buying_power": "200000"}

        def positions(self) -> list[dict]:
            return []

        def orders(self, **_kwargs: object) -> list[dict]:
            return []

        def cancel(self, _order_id: str) -> None:
            raise AssertionError("there are no working orders")

    mandate = tmp_path / "mandate.yaml"
    mandate.write_text(
        "limits:\n  max_position_pct: 40\n  max_gross_exposure_pct: 100\n"
        "  max_daily_loss_pct: 10\n  max_orders_per_day: 200\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execute_direct, "PaperBroker", Broker)
    monkeypatch.setenv("MANDATE_PATH", str(mandate))
    monkeypatch.setenv("MANDATE_EXECUTION_STATE_PATH", str(tmp_path / "execution-state.json"))
    monkeypatch.setenv("MANDATE_JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    result = execute_direct.execute(
        {"market_is_open": True, "checked_at": "2026-09-02T14:00:00Z", "symbols": {}},
        {"action": "PROPOSE", "candidate": "AAPL", "hard_contradiction": False},
    )
    assert result["action"] == "PARK"
    assert result["risk_gate"]["allow_entries"] is False
    assert "daily_loss_9.00pct" in result["risk_gate"]["reasons"]


def test_order_lifecycle_reprices_then_reports_real_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broker:
        replacements = 0
        status_reads = 0

        def order_by_client_id(self, _client_order_id: str) -> None:
            return None

        def submit(self, payload: dict) -> dict:
            return {"id": "order-1", "status": "accepted", "limit_price": payload["limit_price"], "filled_qty": "0"}

        def order(self, _order_id: str) -> dict:
            self.status_reads += 1
            if self.status_reads >= 2:
                return {"id": "order-1", "status": "filled", "limit_price": "100.42", "filled_qty": "10"}
            return {"id": "order-1", "status": "accepted", "limit_price": "100.12", "filled_qty": "0"}

        def replace(self, _order_id: str, limit_price: object) -> dict:
            self.replacements += 1
            return {"id": "order-1", "status": "accepted", "limit_price": str(limit_price), "filled_qty": "0"}

        def cancel(self, _order_id: str) -> None:
            raise AssertionError("filled order must not be cancelled")

    monkeypatch.setenv("MANDATE_FILL_WAIT_SECONDS", "0")
    broker = Broker()
    result = execute_direct.execute_with_lifecycle(
        broker,
        {
            "kind": "entry", "symbol": "AAPL", "side": "buy", "qty": "10",
            "limit_price": "100.12", "rationale": "test entry",
        },
        checked_at="2026-09-01T14:00:00Z",
        index=0,
    )
    assert result["filled"] is True
    assert result["filled_qty"] == "10"
    assert result["deduplicated"] is False
    assert result["replacements"] == 1


def test_portfolio_headroom_is_allocated_across_ranked_entries() -> None:
    action = {
        "kind": "entry", "symbol": "AAPL", "side": "buy", "qty": "100",
        "limit_price": "100", "rationale": "test entry",
    }
    bounded, allocated = execute_direct._cap_entry_to_headroom(
        action, execute_direct.Decimal("3500"),
    )
    assert bounded is not None
    assert bounded["qty"] == "35"
    assert allocated == execute_direct.Decimal("3500")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.attacker.invalid",
        "https://paper-api.alpaca.markets/v2/account",
    ],
)
def test_executor_rejects_non_paper_endpoints(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", url)
    with pytest.raises(ValueError, match="ALPACA_BASE_URL"):
        execute_direct._paper_base_url()
