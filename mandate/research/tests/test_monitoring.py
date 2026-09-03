from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from mandate_research.monitoring import _ipo_calendar_months, collect_market_monitoring


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


def test_ipo_calendar_queries_every_month_in_the_lookback_window() -> None:
    checked_at = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
    assert _ipo_calendar_months(checked_at, 45) == ["2026-09", "2026-08", "2026-07"]
    year_boundary = datetime(2027, 1, 4, 12, tzinfo=timezone.utc)
    assert _ipo_calendar_months(year_boundary, 45) == ["2027-01", "2026-12", "2026-11"]


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


def test_liquid_tradable_mover_is_admitted_to_the_live_cycle(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def snapshot(symbol: str, price: float) -> dict[str, Any]:
        return {
            "latestQuote": {"bp": price - 0.05, "ap": price + 0.05, "t": NOW.isoformat()},
            "latestTrade": {"p": price, "t": NOW.isoformat()},
            "dailyBar": {"o": price - 1, "c": price, "v": 800},
            "prevDailyBar": {"c": price - 1, "v": 1000},
        }

    def fetch(url: str, _headers: dict[str, str]) -> dict[str, Any]:
        if "symbols=TSLA" in url:
            return {"snapshots": {"TSLA": snapshot("TSLA", 250)}}
        if "/stocks/snapshots" in url:
            return {"snapshots": {"AAPL": snapshot("AAPL", 100), "SPY": snapshot("SPY", 500)}}
        if "movers" in url:
            return {"gainers": [{"symbol": "TSLA"}], "losers": []}
        if "most-actives" in url:
            return {"most_actives": [{"symbol": "TSLA"}]}
        if "/v2/assets/TSLA" in url:
            return {
                "symbol": "TSLA", "status": "active", "tradable": True,
                "shortable": True, "easy_to_borrow": True, "fractionable": True,
            }
        return {}

    result = collect_market_monitoring(
        symbols=["AAPL"], ipo_discovery_enabled=False, monitor_corporate_actions=False,
        now=NOW, fetcher=fetch,
    )
    assert result["discovery"]["auto_admitted"] == ["TSLA"]
    assert result["discovery"]["observation_only"] is False
    assert result["quality"]["TSLA"]["quality_pass"] is True
    assert result["discovery"]["auto_admitted_access"]["TSLA"]["easy_to_borrow"] is True


def test_ipo_discovery_filters_spacs_and_ranks_tradable_price_confirmed_listings(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    def fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
        if "api.nasdaq.com/api/ipo/calendar" in url:
            assert "APCA-API-KEY-ID" not in headers
            return {"data": {"priced": {"rows": [
                {
                    "proposedTickerSymbol": "NEWC", "companyName": "New Company, Inc.",
                    "pricedDate": "08/26/2026", "proposedExchange": "NASDAQ",
                    "proposedSharePrice": "$12.00", "sharesOffered": "5,000,000",
                },
                {
                    "proposedTickerSymbol": "SPACU", "companyName": "Example Acquisition Corp",
                    "pricedDate": "08/26/2026", "proposedExchange": "NASDAQ",
                },
            ]}}}
        if "/v2/assets/NEWC" in url:
            return {
                "symbol": "NEWC", "status": "active", "tradable": True,
                "fractionable": False, "shortable": False, "easy_to_borrow": False,
            }
        if "/stocks/snapshots" in url and "NEWC" in url:
            return {"snapshots": {"NEWC": {
                "latestQuote": {"t": NOW.isoformat()},
                "latestTrade": {"p": 14, "t": NOW.isoformat()},
                "dailyBar": {"o": 13, "c": 14, "v": 900},
                "prevDailyBar": {"c": 12.5, "v": 1000},
            }}}
        if "/stocks/snapshots" in url:
            return {"snapshots": {}}
        if "movers" in url:
            return {"gainers": [], "losers": []}
        if "most-actives" in url:
            return {"most_actives": []}
        return {}

    result = collect_market_monitoring(
        symbols=["AAPL"], monitor_corporate_actions=False, now=NOW, fetcher=fetch
    )
    ipo = result["discovery"]["ipos"]
    assert ipo["status"] == "ok"
    assert [item["symbol"] for item in ipo["candidates"]] == ["NEWC"]
    candidate = ipo["candidates"][0]
    assert candidate["research_ready"] is True
    assert candidate["execution_ready"] is False
    assert candidate["research_warnings"] == ["missing_spread"]
    assert candidate["quality"]["session_change_pct"] == "12.00"
    assert candidate["alpaca"] == {
        "tradable": True, "fractionable": False, "shortable": False, "easy_to_borrow": False,
    }
    assert ipo["observation_only"] is True
    assert ipo["policy"] == "research_only_until_added_to_trajectory_and_mandate"


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
