from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from mandate_research.monitoring import collect_market_monitoring


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


def test_collect_monitoring_computes_quality_and_falls_back_to_iex(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "feed=sip" in url:
            raise RuntimeError("subscription unavailable")
        if "/snapshots" in url:
            return {
                    "AAPL": {
                        "latestQuote": {"bp": 99.9, "ap": 100.1, "bs": 300, "as": 100, "t": NOW.isoformat()},
                        "latestTrade": {"p": 101, "t": NOW.isoformat()},
                        "dailyBar": {"o": 100, "c": 101, "v": 500, "vw": 100.5},
                        "prevDailyBar": {"c": 98, "v": 1000},
                    },
                    "SPY": {
                        "latestQuote": {"bp": 499.9, "ap": 500.1, "t": NOW.isoformat()},
                        "latestTrade": {"p": 501, "t": NOW.isoformat()},
                        "dailyBar": {"o": 500, "c": 501, "v": 600, "vw": 500.5},
                        "prevDailyBar": {"c": 499, "v": 1000},
                    }
            }
        if "movers" in url:
            return {"gainers": [{"symbol": "AAPL"}], "losers": []}
        if "most-actives" in url:
            return {"most_actives": [{"symbol": "AAPL"}]}
        if "corporate-actions" in url:
            return {"corporate_actions": [{"id": "ca-1", "symbol": "AAPL", "type": "cash_dividend"}]}
        raise AssertionError(url)

    result = collect_market_monitoring(symbols=[" aapl "], now=NOW, fetcher=fetch)
    assert result["feed"] == "iex"
    assert result["quality"]["AAPL"]["spread_bps"] == "20.00"
    assert result["quality"]["AAPL"]["relative_volume"] == "1.493"
    assert result["quality"]["AAPL"]["daily_volume_fraction"] == "0.500"
    assert result["quality"]["AAPL"]["expected_volume_fraction"] == "0.335"
    assert result["quality"]["AAPL"]["relative_volume_basis"] == "time_adjusted"
    assert result["quality"]["AAPL"]["session_change_pct"] == "3.06"
    assert result["quality"]["AAPL"]["top_of_book_imbalance"] == "0.5000"
    assert result["quality"]["AAPL"]["quality_pass"] is True
    assert result["benchmark"]["symbol"] == "SPY"
    assert result["discovery"]["observation_only"] is True
    assert result["corporate_actions"][0]["id"] == "ca-1"


def test_opening_volume_is_compared_with_expected_volume_to_time(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    opening = datetime(2026, 8, 28, 13, 33, tzinfo=timezone.utc)

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "/snapshots" in url:
            return {
                "AAPL": {
                    "latestQuote": {"bp": 100, "ap": 100.1, "t": opening.isoformat()},
                    "latestTrade": {"p": 100.05, "t": opening.isoformat()},
                    "dailyBar": {"o": 100, "c": 100.05, "v": 14},
                    "prevDailyBar": {"c": 100, "v": 1000},
                },
                "SPY": {
                    "latestQuote": {"bp": 500, "ap": 500.1, "t": opening.isoformat()},
                    "latestTrade": {"p": 500.05, "t": opening.isoformat()},
                    "dailyBar": {"o": 500, "c": 500.05, "v": 14},
                    "prevDailyBar": {"c": 500, "v": 1000},
                },
            }
        return {}

    result = collect_market_monitoring(
        symbols=["AAPL"], discovery_enabled=False, monitor_corporate_actions=False,
        now=opening, fetcher=fetch,
    )
    quality = result["quality"]["AAPL"]
    assert quality["daily_volume_fraction"] == "0.014"
    assert quality["expected_volume_fraction"] == "0.028"
    assert quality["relative_volume"] == "0.500"
    assert quality["quality_pass"] is True


def test_spy_macro_move_is_exposed_as_deterministic_context(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "/snapshots" in url:
            return {
                "SPY": {
                    "latestQuote": {"bp": 504.9, "ap": 505.1, "t": NOW.isoformat()},
                    "latestTrade": {"p": 505, "t": NOW.isoformat()},
                    "dailyBar": {"o": 501, "c": 505, "v": 500},
                    "prevDailyBar": {"c": 500, "v": 1000},
                }
            }
        return {}

    result = collect_market_monitoring(
        symbols=["SPY"], discovery_enabled=False, monitor_corporate_actions=False,
        now=NOW, fetcher=fetch,
    )
    assert result["macro_context"] == {
        "active": True,
        "direction": "risk_on",
        "trigger": "session_change_pct",
        "move_pct": "1.00",
        "threshold_pct": "0.60",
    }


def test_optional_surfaces_degrade_without_losing_snapshots(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "/snapshots" in url and "feed=iex" in url:
            return {"snapshots": {}}
        raise RuntimeError("unavailable")

    result = collect_market_monitoring(
        symbols=["AAPL"], feed="iex", now=NOW, fetcher=fetch
    )
    assert result["sources"]["snapshots"]["status"] == "ok"
    assert result["discovery"]["status"] == "degraded"
    assert result["sources"]["corporate_actions"]["status"] == "error"


def test_optional_option_confirmation_is_summarized_without_exposing_contract_payloads(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "/options/snapshots/AAPL" in url:
            return {"snapshots": {"AAPL260828C00300000": {"greeks": {"delta": "0.5"}}}}
        if "/stocks/snapshots" in url:
            return {}
        return {}

    result = collect_market_monitoring(
        symbols=["AAPL"],
        feed="iex",
        discovery_enabled=False,
        monitor_corporate_actions=False,
        options_confirmation=True,
        now=NOW,
        fetcher=fetch,
    )
    assert result["options_confirmation"]["status"] == "ok"
    assert result["options_confirmation"]["symbols"]["AAPL"] == {
        "status": "ok",
        "contract_count": 1,
        "with_greeks": 1,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_spread_bps", "NaN"), ("max_spread_bps", "0"), ("min_relative_volume", "-0.1")],
)
def test_monitoring_rejects_invalid_decimal_thresholds(
    monkeypatch: Any, field: str, value: str
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    arguments = {
        "symbols": ["AAPL"],
        "discovery_enabled": False,
        "monitor_corporate_actions": False,
        "now": NOW,
        "fetcher": lambda *_: {},
        field: value,
    }
    with pytest.raises(ValueError):
        collect_market_monitoring(**arguments)
