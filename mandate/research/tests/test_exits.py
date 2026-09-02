from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mandate_research.exits import collect_exit_inputs, evaluate_position_exits, run_exit_evaluation


NOW = datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc)


def _position(symbol: str, qty: str, entry: str) -> dict:
    return {"symbol": symbol, "qty": qty, "avg_entry_price": entry}


def test_short_stop_proposes_immediate_close() -> None:
    result = evaluate_position_exits(
        positions=[_position("NVDA", "-10", "100")],
        last_prices={"NVDA": "105"},
        atr14={"NVDA": "2.5"},
        first_seen={"NVDA": (NOW - timedelta(minutes=30)).isoformat()},
        now=NOW,
    )
    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["reason"] == "short_stop"
    assert proposal["urgency"] == "immediate"
    assert proposal["side"] == "short"
    assert proposal["qty"] == "10"
    assert proposal["order_side"] == "buy"
    assert proposal["limit_price"] == "105.11"
    assert result["execution_authority"] is False


def test_short_profit_target_and_time_stop() -> None:
    target = evaluate_position_exits(
        positions=[_position("NVDA", "-10", "100")],
        last_prices={"NVDA": "96"},
        atr14={"NVDA": "2.5"},
        first_seen={"NVDA": (NOW - timedelta(minutes=10)).isoformat()},
        now=NOW,
    )
    assert target["proposals"][0]["reason"] == "short_profit_target"
    assert target["proposals"][0]["urgency"] == "normal"

    stale = evaluate_position_exits(
        positions=[_position("NVDA", "-10", "100")],
        last_prices={"NVDA": "100.3"},
        atr14={"NVDA": "2.5"},
        first_seen={"NVDA": (NOW - timedelta(minutes=300)).isoformat()},
        now=NOW,
    )
    assert stale["proposals"][0]["reason"] == "short_time_stop"

    young_and_flat = evaluate_position_exits(
        positions=[_position("NVDA", "-10", "100")],
        last_prices={"NVDA": "100.3"},
        atr14={"NVDA": "2.5"},
        first_seen={"NVDA": (NOW - timedelta(minutes=30)).isoformat()},
        now=NOW,
    )
    assert young_and_flat["proposals"] == []


def test_long_side_is_symmetric() -> None:
    result = evaluate_position_exits(
        positions=[_position("AAPL", "20", "100")],
        last_prices={"AAPL": "94.9"},
        atr14={"AAPL": "2.5"},
        first_seen={"AAPL": (NOW - timedelta(minutes=5)).isoformat()},
        now=NOW,
    )
    assert result["proposals"][0]["reason"] == "long_stop"
    assert result["proposals"][0]["urgency"] == "immediate"
    assert result["proposals"][0]["order_side"] == "sell"
    assert result["proposals"][0]["limit_price"] == "94.80"

    target = evaluate_position_exits(
        positions=[_position("AAPL", "20", "100")],
        last_prices={"AAPL": "104"},
        atr14={"AAPL": "2.5"},
        first_seen={"AAPL": (NOW - timedelta(minutes=5)).isoformat()},
        now=NOW,
    )
    assert target["proposals"][0]["reason"] == "long_profit_target"


def test_intraday_positions_flatten_at_1550_new_york() -> None:
    result = evaluate_position_exits(
        positions=[_position("MSFT", "19", "510.9")],
        last_prices={"MSFT": "510.1"},
        atr14={"MSFT": "3.4"},
        first_seen={"MSFT": (NOW - timedelta(minutes=10)).isoformat()},
        now=datetime(2026, 8, 28, 19, 51, tzinfo=timezone.utc),
    )
    assert result["proposals"][0]["reason"] == "session_flatten_1550"
    assert result["proposals"][0]["urgency"] == "immediate"
    assert result["proposals"][0]["order_side"] == "sell"


def test_missing_market_data_is_unevaluated_and_tracked() -> None:
    result = evaluate_position_exits(
        positions=[_position("MSFT", "-5", "400")],
        last_prices={},
        atr14={},
        first_seen={},
        now=NOW,
    )
    assert result["proposals"] == []
    assert result["unevaluated"] == [{"symbol": "MSFT", "reason": "missing_price_or_atr"}]
    assert result["first_seen"]["MSFT"] == NOW.isoformat()


def test_tracking_prunes_closed_symbols() -> None:
    result = evaluate_position_exits(
        positions=[_position("AAPL", "10", "100")],
        last_prices={"AAPL": "100"},
        atr14={"AAPL": "1"},
        first_seen={"AAPL": NOW.isoformat(), "MSFT": NOW.isoformat()},
        now=NOW,
    )
    assert set(result["first_seen"]) == {"AAPL"}


def test_malformed_position_isolated_from_valid_stop() -> None:
    result = evaluate_position_exits(
        positions=[
            _position("AAPL", "10", "100"),
            {"symbol": "BROKEN", "qty": "1", "avg_entry_price": "not-a-price"},
        ],
        last_prices={"AAPL": "95"},
        atr14={"AAPL": "2"},
        first_seen={},
        now=NOW,
    )
    assert result["proposals"][0]["reason"] == "long_stop"
    assert result["unevaluated"][0]["symbol"] == "BROKEN"


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_position_exits(
            positions=[],
            last_prices={},
            atr14={},
            first_seen={},
            now=datetime(2026, 8, 28, 16, 0),
        )


def test_run_exit_evaluation_persists_first_seen(tmp_path: Path) -> None:
    tracking = tmp_path / "position-tracking.json"

    def stub_inputs(symbols: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        return {"NVDA": "105"}, {"NVDA": "2.5"}

    first = run_exit_evaluation(
        [_position("NVDA", "-10", "100")],
        now=NOW,
        inputs=stub_inputs,
        tracking_path=tracking,
    )
    assert first["proposals"][0]["reason"] == "short_stop"
    stored = json.loads(tracking.read_text(encoding="utf-8"))
    assert stored["first_seen"]["NVDA"] == NOW.isoformat()

    later = run_exit_evaluation(
        [_position("NVDA", "-10", "100")],
        now=NOW + timedelta(minutes=90),
        inputs=stub_inputs,
        tracking_path=tracking,
    )
    assert later["proposals"] == [] or later["proposals"][0]["age_minutes"] == 90
    assert json.loads(tracking.read_text(encoding="utf-8"))["first_seen"]["NVDA"] == NOW.isoformat()


def test_run_exit_evaluation_uses_the_same_env_policy_shown_by_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("MANDATE_EXIT_STOP_ATR", "0.50")
    monkeypatch.setenv("MANDATE_EXIT_TARGET_ATR", "2.00")
    monkeypatch.setenv("MANDATE_EXIT_TIME_STOP_MINUTES", "90")
    monkeypatch.setenv("MANDATE_EXIT_DEAD_POSITION_ATR", "0.10")
    result = run_exit_evaluation(
        [_position("AAPL", "10", "100")],
        now=NOW,
        inputs=lambda _symbols: ({"AAPL": "99.4"}, {"AAPL": "1"}),
        tracking_path=tmp_path / "tracking.json",
    )
    assert result["proposals"][0]["reason"] == "long_stop"
    assert "0.50xATR" in result["proposals"][0]["rationale"]


def test_exit_atr_fetch_has_an_explicit_history_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    urls: list[str] = []

    def fetcher(url: str, _headers: dict[str, str]) -> dict:
        urls.append(url)
        if "snapshots" in url:
            return {"snapshots": {"AAPL": {"latestTrade": {"p": 100}}}}
        bars = [{
            "t": (NOW - timedelta(hours=20 - index)).isoformat(),
            "o": "100", "h": "102", "l": "99", "c": "101", "v": "1000",
        } for index in range(20)]
        return {"bars": bars}

    prices, atr = collect_exit_inputs(["AAPL"], fetcher=fetcher)
    assert prices == {"AAPL": "100"}
    assert Decimal(atr["AAPL"]) > 0
    bars_url = next(url for url in urls if "/bars" in url)
    assert "start=" in bars_url and "end=" in bars_url and "limit=1000" in bars_url
