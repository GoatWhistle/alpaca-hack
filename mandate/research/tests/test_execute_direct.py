from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mandate_research import execution


def _plan_evaluation(*symbols: str) -> dict:
    return {
        "checked_at": "2026-09-02T14:00:00Z",
        "cycle_id": "cycle-20260902-1400",
        "research_candidates": list(symbols),
        "trade_candidates": [
            {"candidate_id": f"candidate-{index + 1}", "symbol": symbol, "side": "untrusted"}
            for index, symbol in enumerate(symbols)
        ],
        "symbols": {
            symbol: {
                "research_candidate": True,
                "signal_path": "price_confirmation",
                "strategies": {"regime_ensemble": {"direction": "buy", "strength": "0.8"}},
                "sizing": {"available": True, "qty": str(10 + index)},
                "market": {"last": str(100 + index)},
            }
            for index, symbol in enumerate(symbols)
        },
    }


def _plan(*candidate_ids: str, action: str = "EXECUTE_PLAN") -> dict:
    return {
        "schema": "trade.plan.v2",
        "cycle_id": "cycle-20260902-1400",
        "action": action,
        "reason": "ranked canonical candidates",
        "hypotheses": [
            {
                "candidate_id": candidate_id,
                "thesis": f"bounded thesis for {candidate_id}",
                "confidence": "medium",
                "supports": [f"evaluation.trade_candidates.{candidate_id}"],
                "contradicts": [],
                "invalidation": "quality or confirmation gate fails",
            }
            for candidate_id in candidate_ids
        ],
        "steps": [
            {
                "candidate_id": candidate_id,
                "reason": f"evidence supports {candidate_id}",
                "evidence_refs": [f"evaluation.trade_candidates.{candidate_id}"],
            }
            for candidate_id in candidate_ids
        ],
        "critic_coverage": ["risk", "market", "execution"],
        "critic_resolutions": [
            {"critic": critic, "resolution": "ACCEPTED", "reason": "bounded evidence"}
            for critic in ("risk", "market", "execution")
        ],
        "memory_events": [],
    }


def test_trade_plan_maps_only_ids_to_canonical_evaluation_in_plan_order() -> None:
    evaluation = _plan_evaluation("AAPL", "MSFT")
    entries = execution.select_entries(evaluation, _plan("candidate-2", "candidate-1"))
    assert [entry["symbol"] for entry in entries] == ["MSFT", "AAPL"]
    assert [entry["side"] for entry in entries] == ["buy", "buy"]
    assert [entry["qty"] for entry in entries] == ["11", "10"]
    assert [entry["limit_price"] for entry in entries] == ["101.13", "100.12"]
    assert [entry["plan_candidate_id"] for entry in entries] == ["candidate-2", "candidate-1"]


@pytest.mark.parametrize(
    ("decision", "message"),
    [
        (_plan("candidate-1", "candidate-1"), "candidate_ids must be unique"),
        ({**_plan("candidate-1"), "steps": [{"candidate_id": "candidate-1", "reason": "", "evidence_refs": ["x"]}]}, "reason"),
        (_plan("not-canonical"), "unknown candidate_id"),
        (_plan("candidate-1", "candidate-2", "candidate-3", "candidate-4"), "requires 1-3 steps"),
        ({**_plan(action="PARK"), "reason": "no edge", "steps": [_plan("candidate-1")["steps"][0]]}, "cannot contain steps"),
    ],
)
def test_trade_plan_rejects_invalid_steps(decision: dict, message: str) -> None:
    evaluation = _plan_evaluation("AAPL", "MSFT", "NVDA", "AMD")
    with pytest.raises(ValueError, match=message):
        execution.select_entries(evaluation, decision)


def test_trade_plan_rejects_model_supplied_order_fields() -> None:
    plan = _plan("candidate-1")
    plan["steps"][0]["qty"] = "999999"
    with pytest.raises(ValueError, match="step fields"):
        execution.select_entries(_plan_evaluation("AAPL"), plan)


def test_trade_plan_requires_a_hypothesis_for_every_selected_candidate() -> None:
    plan = _plan("candidate-1", "candidate-2")
    plan["hypotheses"] = plan["hypotheses"][:1]
    with pytest.raises(ValueError, match="lacks a hypothesis"):
        execution.select_entries(_plan_evaluation("AAPL", "MSFT"), plan)


def test_trade_plan_fails_closed_when_a_critic_is_unavailable() -> None:
    plan = _plan("candidate-1")
    plan["critic_resolutions"][1] = {
        "critic": "market",
        "resolution": "UNAVAILABLE",
        "reason": "timeout: advisory deadline exceeded",
    }
    with pytest.raises(ValueError, match="forbidden while a critic is unavailable"):
        execution.select_entries(_plan_evaluation("AAPL"), plan)

    parked = _plan(action="PARK")
    parked["critic_resolutions"][1] = plan["critic_resolutions"][1]
    assert execution.select_entries(_plan_evaluation("AAPL"), parked) == []


def test_trade_plan_park_requires_reason_and_selects_nothing() -> None:
    evaluation = _plan_evaluation("AAPL")
    assert execution.select_entries(evaluation, _plan(action="PARK")) == []
    assert execution.select_entries(
        {"cycle_id": "cycle-20260902-1400"},
        _plan(action="PARK"),
    ) == []
    with pytest.raises(ValueError, match="reason"):
        execution.select_entries(evaluation, {**_plan(action="PARK"), "reason": ""})


def test_trade_plan_cycle_id_must_match_canonical_evaluation() -> None:
    evaluation = _plan_evaluation("AAPL")
    with pytest.raises(ValueError, match="cycle_id does not match"):
        execution.select_entries(
            evaluation,
            {**_plan("candidate-1"), "cycle_id": "model-invented-retry-id"},
        )


def test_closed_market_never_constructs_a_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        execution,
        "PaperBroker",
        lambda: (_ for _ in ()).throw(AssertionError("broker must not be constructed")),
    )
    result = execution.execute(
        {"market_is_open": False},
        _plan(action="PARK"),
    )
    assert result["action"] == "PARK"
    assert result["submitted"] is False


def test_exit_selection_does_not_crash_and_requires_confident_reversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "run_exit_evaluation", lambda _positions: {
        "proposals": [{
            "symbol": "AAPL", "order_side": "sell", "qty": "2", "limit_price": "99.9",
            "rationale": "long stop", "reason": "long_stop", "urgency": "immediate", "age_minutes": 5,
        }],
    })
    positions = [{"symbol": "AAPL", "qty": "2", "avg_entry_price": "100", "asset_class": "us_equity"}]
    assert execution.select_exits({"symbols": {}}, positions)[0]["rationale"] == "long stop"

    monkeypatch.setattr(execution, "run_exit_evaluation", lambda _positions: {"proposals": []})
    weak = {"symbols": {"AAPL": {
        "strategies": {"regime_ensemble": {"direction": "sell", "strength": "0.08"}},
        "market": {"last": "100"},
    }}}
    assert execution.select_exits(weak, positions) == []


def test_malformed_position_does_not_block_other_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "run_exit_evaluation", lambda _positions: {
        "proposals": [{
            "symbol": "MSFT", "order_side": "sell", "qty": "1", "limit_price": "99.9",
            "rationale": "valid stop", "urgency": "immediate", "age_minutes": 5,
        }],
    })
    positions = [
        {"symbol": "BROKEN", "qty": "bad", "avg_entry_price": "100", "asset_class": "us_equity"},
        {"symbol": "MSFT", "qty": "1", "avg_entry_price": "100", "asset_class": "us_equity"},
    ]
    assert execution.select_exits({"symbols": {}}, positions)[0]["symbol"] == "MSFT"


def test_unevaluated_position_marks_exit_pass_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "run_exit_evaluation", lambda _positions: {
        "proposals": [],
        "unevaluated": [{"symbol": "AAPL", "reason": "missing_price_or_atr"}],
    })
    health: dict = {}
    assert execution.select_exits(
        {"symbols": {}},
        [{"symbol": "AAPL", "qty": "1", "avg_entry_price": "100", "asset_class": "us_equity"}],
        health=health,
    ) == []
    assert health == {
        "healthy": False,
        "issues": [{"symbol": "AAPL", "reason": "missing_price_or_atr"}],
    }


def test_option_risk_reserve_uses_conservative_cost_basis() -> None:
    assert execution._option_risk_reserve({
        "symbol": "AAPL260918C00100000",
        "market_value": "1000",
        "cost_basis": "10000",
    }) == execution.Decimal("10000")
    with pytest.raises(ValueError, match="cannot determine option risk"):
        execution._option_risk_reserve({"symbol": "AAPL260918C00100000"})


def test_package_move_preserves_mandate_and_state_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MANDATE_PATH", raising=False)
    monkeypatch.delenv("MANDATE_EXECUTION_STATE_PATH", raising=False)
    assert execution._mandate_limits()["max_daily_loss_pct"] == execution.Decimal("10")
    assert execution._execution_state_path() == execution.MANDATE_ROOT / "logs/execution-state.json"


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
    order = execution.build_option_order(
        Broker(),
        {
            "symbol": "AAPL", "side": "buy", "last": "100", "qty": "50",
            "rationale": "strong price confirmation",
        },
        {"equity": "100000", "options_approved_level": 3},
        option_exposure=execution.Decimal("0"),
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
    actions = execution.select_option_exits(positions, limit=2)
    assert len(actions) == 1
    assert actions[0]["kind"] == "option_exit_mleg"
    assert actions[0]["payload"]["qty"] == "2"
    assert [leg["position_intent"] for leg in actions[0]["payload"]["legs"]] == [
        "sell_to_close", "buy_to_close",
    ]


def test_flat_option_position_receives_time_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep this before the mandatory 15:50 America/New_York flatten window so
    # the test isolates the option time-stop rule regardless of wall-clock time.
    now = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    expiry = (now.date() + timedelta(days=10)).strftime("%y%m%d")
    monkeypatch.setenv("MANDATE_OPTION_TIME_STOP_MINUTES", "60")
    actions = execution.select_option_exits(
        [{
            "symbol": f"AAPL{expiry}C00100000", "asset_class": "us_option", "qty": "1",
            "current_price": "2", "cost_basis": "200", "unrealized_pl": "5",
        }],
        now=now,
        first_seen={"AAPL": (now - timedelta(minutes=61)).isoformat()},
    )
    assert actions[0]["rationale"] == "option_time_stop_61m"


def test_same_day_reentry_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    state = {"symbols": {"AAPL": {"last_exit_at": (now - timedelta(hours=4)).isoformat()}}}
    monkeypatch.setenv("MANDATE_ALLOW_SAME_DAY_REENTRY", "false")
    monkeypatch.setenv("MANDATE_REENTRY_COOLDOWN_MINUTES", "10")
    assert execution._cooldown_active(state, "AAPL", now=now) is True

    next_day = now + timedelta(days=1)
    assert execution._cooldown_active(state, "AAPL", now=next_day) is False


def test_broker_retries_reads_but_not_order_submissions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("MANDATE_USE_ALPACA_PROXY", "false")
    calls: list[str] = []

    def flaky(method: str, *_args, **_kwargs):
        calls.append(method)
        if len(calls) == 1:
            raise execution.httpx.ConnectTimeout("transient")
        return execution.httpx.Response(200, json={"equity": "100000"})

    monkeypatch.setattr(execution.httpx, "request", flaky)
    broker = execution.PaperBroker()
    assert broker.account()["equity"] == "100000"
    assert calls == ["GET", "GET"]

    calls.clear()

    def unavailable(method: str, *_args, **_kwargs):
        calls.append(method)
        raise execution.httpx.ConnectTimeout("transient")

    monkeypatch.setattr(execution.httpx, "request", unavailable)
    with pytest.raises(RuntimeError, match="network unavailable"):
        broker.submit({"symbol": "AAPL"})
    assert calls == ["POST"]


def test_exit_is_rechecked_and_clamped_to_live_position() -> None:
    class Broker:
        def positions(self) -> list[dict]:
            return [{"symbol": "AAPL", "qty": "3", "asset_class": "us_equity"}]

    action = execution._refresh_exit_action(Broker(), {
        "kind": "exit", "symbol": "AAPL", "side": "sell", "qty": "10",
        "limit_price": "99", "rationale": "stop",
    })
    assert action["qty"] == "3"
    assert execution._equity_payload(action)["position_intent"] == "sell_to_close"


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
    gate = execution._entry_risk_gate(
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
    recovered = execution._cancel_tagged_open_orders(broker)
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
    monkeypatch.setattr(execution, "PaperBroker", Broker)
    monkeypatch.setenv("MANDATE_PATH", str(mandate))
    monkeypatch.setenv("MANDATE_EXECUTION_STATE_PATH", str(tmp_path / "execution-state.json"))
    monkeypatch.setenv("MANDATE_JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    result = execution.execute(
        {
            "market_is_open": True,
            "checked_at": "2026-09-02T14:00:00Z",
            "cycle_id": "cycle-20260902-1400",
            "symbols": {},
        },
        _plan(action="PARK"),
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
    result = execution.execute_with_lifecycle(
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
    assert result["exit_policy"] == {
        "stop": "0.90x ATR14 adverse move",
        "target": "1.50x ATR14 favorable move",
        "time_stop": "45m if still within 0.25x ATR14 of entry",
        "flatten": "mandatory 15:50 ET session flatten",
    }


def test_exit_policy_is_exact_for_options_and_absent_for_closing_orders() -> None:
    assert execution._entry_exit_policy({"kind": "option_entry"}) == {
        "stop": "-25% unrealized P&L",
        "target": "+40% unrealized P&L",
        "time_stop": "180m in the dead band",
        "expiry": "close at DTE <= 2",
        "flatten": "mandatory 15:50 ET session flatten",
    }
    assert execution._entry_exit_policy({"kind": "exit"}) is None


def test_plan_client_order_id_is_stable_across_index_and_canonical_repricing() -> None:
    action = {
        "kind": "entry", "symbol": "AAPL", "side": "buy", "qty": "10",
        "limit_price": "100", "plan_schema": "trade.plan.v2",
        "plan_cycle_id": "cycle-1", "plan_candidate_id": "candidate-1",
    }
    first = execution._client_order_id(action, "first-check", 0)
    second = execution._client_order_id(
        {
            **action, "kind": "option_entry", "symbol": "AAPL260911C00100000",
            "underlying": "AAPL", "qty": "2", "limit_price": "4.20",
        },
        "second-check", 99,
    )
    assert first == second
    assert len(first) <= 48


def test_ordered_plan_stops_after_partial_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broker:
        def positions(self) -> list[dict]:
            return []

    submitted: list[str] = []

    def lifecycle(_broker, action: dict, **_kwargs) -> dict:
        submitted.append(action["plan_candidate_id"])
        filled = "5" if action["plan_candidate_id"] == "candidate-2" else action["qty"]
        return {
            "accepted": True, "filled": True, "status": "filled", "filled_qty": filled,
            "kind": action["kind"], "candidate": action["symbol"],
            "underlying": action["symbol"], "reason": action["rationale"],
            "result": {}, "order": {},
        }

    monkeypatch.setattr(execution, "execute_with_lifecycle", lifecycle)
    monkeypatch.setattr(execution, "_journal", lambda _value: None)
    actions = [{
        "kind": "entry", "symbol": symbol, "side": "buy", "qty": "10",
        "limit_price": "100", "rationale": "test", "plan_candidate_id": candidate_id,
        "plan_cycle_id": "cycle-1", "plan_schema": "trade.plan.v2",
    } for symbol, candidate_id in (
        ("AAPL", "candidate-1"), ("MSFT", "candidate-2"), ("NVDA", "candidate-3"),
    )]
    results, errors, halt = execution._run_plan_actions(
        Broker(), actions, checked_at="checked", start_index=2,
    )
    assert submitted == ["candidate-1", "candidate-2"]
    assert len(results) == 2
    assert errors == []
    assert halt == {"halted": True, "reason": "partial:candidate-2:filled", "skipped": 1}


def test_ordered_plan_stops_before_submit_on_live_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broker:
        def positions(self) -> list[dict]:
            return [{"symbol": "AAPL", "qty": "1", "asset_class": "us_equity"}]

    monkeypatch.setattr(
        execution,
        "execute_with_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not submit")),
    )
    action = {
        "kind": "entry", "symbol": "AAPL", "side": "buy", "qty": "10",
        "limit_price": "100", "rationale": "test", "plan_candidate_id": "candidate-1",
        "plan_cycle_id": "cycle-1", "plan_schema": "trade.plan.v2",
    }
    results, errors, halt = execution._run_plan_actions(
        Broker(), [action], checked_at="checked", start_index=0,
    )
    assert results == []
    assert errors == ["candidate-1 plan step: live position conflict for AAPL"]
    assert halt["halted"] is True


def test_whole_plan_risk_validation_reserves_order_budget() -> None:
    actions = [{"symbol": symbol} for symbol in ("AAPL", "MSFT", "NVDA")]
    gate = {"orders_today": 198, "max_orders_per_day": 200}
    assert execution._whole_plan_risk_error(gate, actions, 3) == (
        "whole plan exceeds order budget: 198+3>200"
    )
    assert execution._whole_plan_risk_error(gate, actions[:2], 3) == (
        "plan resolved 2 of 3 canonical steps"
    )


def test_execute_prioritizes_hard_exits_before_ordered_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class Broker:
        position_reads = 0

        def account(self) -> dict:
            return {
                "equity": "100000", "last_equity": "100000", "buying_power": "100000",
                "options_approved_level": 0,
            }

        def positions(self) -> list[dict]:
            self.position_reads += 1
            if self.position_reads == 1:
                return [{
                    "symbol": "AAPL", "asset_class": "us_equity", "qty": "1",
                    "market_value": "100", "avg_entry_price": "100",
                }]
            return []

        def orders(self, **_kwargs: object) -> list[dict]:
            return []

        def asset(self, symbol: str) -> dict:
            assert symbol == "MSFT"
            return {"tradable": True, "shortable": True, "easy_to_borrow": True}

    sequence: list[str] = []
    hard_exit = {
        "kind": "exit", "symbol": "AAPL", "side": "sell", "qty": "1",
        "limit_price": "99", "rationale": "automatic hard stop",
    }

    def run_exits(_broker, actions: list[dict], **_kwargs) -> tuple[list[dict], list[str]]:
        assert actions == [hard_exit]
        sequence.append("hard_exit")
        return [{
            "accepted": True, "filled": True, "status": "filled", "filled_qty": "1",
            "kind": "exit", "candidate": "AAPL", "underlying": "AAPL",
            "reason": "automatic hard stop", "result": {}, "order": {},
        }], []

    def run_plan(_broker, actions: list[dict], **_kwargs):
        sequence.append("plan")
        assert [action["plan_candidate_id"] for action in actions] == ["candidate-1"]
        return [{
            "accepted": True, "filled": True, "status": "filled", "filled_qty": actions[0]["qty"],
            "kind": "entry", "candidate": "MSFT", "underlying": "MSFT",
            "reason": actions[0]["rationale"], "result": {}, "order": {},
        }], [], {"halted": False, "reason": None, "skipped": 0}

    mandate = tmp_path / "mandate.yaml"
    mandate.write_text(
        "limits:\n  max_position_pct: 40\n  max_gross_exposure_pct: 100\n"
        "  max_daily_loss_pct: 10\n  max_orders_per_day: 200\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution, "PaperBroker", Broker)
    monkeypatch.setattr(execution, "_cancel_tagged_open_orders", lambda _broker: [])
    monkeypatch.setattr(execution, "_after_flatten_window", lambda _now: False)
    monkeypatch.setattr(execution, "select_exits", lambda *_args, **_kwargs: [hard_exit])
    monkeypatch.setattr(execution, "select_option_exits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(execution, "_run_actions", run_exits)
    monkeypatch.setattr(execution, "_run_plan_actions", run_plan)
    monkeypatch.setenv("MANDATE_OPTIONS_ENABLED", "false")
    monkeypatch.setenv("MANDATE_PATH", str(mandate))
    monkeypatch.setenv("MANDATE_EXECUTION_STATE_PATH", str(tmp_path / "execution-state.json"))
    monkeypatch.setenv("MANDATE_JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    evaluation = _plan_evaluation("MSFT")
    evaluation["market_is_open"] = True
    result = execution.execute(evaluation, _plan("candidate-1"))
    assert sequence == ["hard_exit", "plan"]
    assert result["submitted_count"] == 2
    assert result["trade_plan"]["validated_steps"] == 1


def test_portfolio_headroom_is_allocated_across_ranked_entries() -> None:
    action = {
        "kind": "entry", "symbol": "AAPL", "side": "buy", "qty": "100",
        "limit_price": "100", "rationale": "test entry",
    }
    bounded, allocated = execution._cap_entry_to_headroom(
        action, execution.Decimal("3500"),
    )
    assert bounded is not None
    assert bounded["qty"] == "35"
    assert allocated == execution.Decimal("3500")


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
        execution._paper_base_url()
