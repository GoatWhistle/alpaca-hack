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
