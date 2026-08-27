from __future__ import annotations

from decimal import Decimal

from mandate_research.decision_math import evaluate_trajectory, summarize_trajectory_math


def _comparison(symbol: str, news: str = "buy", momentum: str = "buy") -> dict:
    strategies = {
        "momentum": momentum,
        "mean_reversion": "flat",
        "breakout_volume": "flat",
        "news_price_confirmation": news,
        "regime_ensemble": news if news == momentum else "flat",
    }
    return {
        "symbol": symbol,
        "as_of": "2026-08-27T17:00:00+00:00",
        "signals": {
            name: {"direction": direction, "strength": "0.5", "rationale": name}
            for name, direction in strategies.items()
        },
        "backtest": {
            name: {
                "total_return_pct": "1.2",
                "max_drawdown_pct": "0.4",
                "turnover": "3",
                "position_changes": "2",
                "observations": "30",
            }
            for name in strategies
        },
        "risk": {"atr14": "2", "market_regime": {"regime": "trend"}},
    }


def test_summary_replaces_repeated_liquidity_and_alignment_math() -> None:
    monitoring = {
        "checked_at": "2026-08-27T17:01:00+00:00",
        "market_is_open": True,
        "feed": "iex",
        "benchmark": {"symbol": "SPY", "quality_pass": True},
        "quality": {
            "AAPL": {
                "last": "101",
                "spread_bps": "2.5",
                "relative_volume": "0.8",
                "session_change_pct": "1.25",
                "stale_seconds": 4,
                "quality_pass": True,
            },
            "MSFT": {
                "last": "500",
                "spread_bps": "40",
                "relative_volume": "1.2",
                "session_change_pct": "2",
                "stale_seconds": 4,
                "quality_pass": False,
            },
        },
    }
    result = summarize_trajectory_math(
        symbols=["AAPL", "MSFT"],
        monitoring=monitoring,
        comparisons={"AAPL": _comparison("AAPL"), "MSFT": _comparison("MSFT")},
    )
    assert result["research_candidates"] == ["AAPL"]
    assert result["decision"] == "PROPOSE_RESEARCH"
    assert result["execution_authority"] is False
    assert result["symbols"]["AAPL"]["direction_counts"] == {"buy": 3, "flat": 2}
    assert result["symbols"]["MSFT"]["blocked_by"] == ["quality_gate"]


def test_summary_fails_closed_for_large_or_missing_session_move() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "quality": {
            "AAPL": {"spread_bps": "1", "relative_volume": "1", "session_change_pct": "5", "quality_pass": True},
            "MSFT": {"spread_bps": "1", "relative_volume": "1", "session_change_pct": None, "quality_pass": True},
        },
    }
    result = summarize_trajectory_math(
        symbols=["AAPL", "MSFT"],
        monitoring=monitoring,
        comparisons={"AAPL": _comparison("AAPL"), "MSFT": _comparison("MSFT")},
    )
    assert result["decision"] == "PARK"
    assert "single_symbol_move_gate" in result["symbols"]["AAPL"]["blocked_by"]
    assert "missing_session_move" in result["symbols"]["MSFT"]["blocked_by"]


def test_live_wrapper_fetches_monitoring_once_and_each_symbol_once() -> None:
    calls: list[tuple[str, object]] = []

    def monitor(**kwargs: object) -> dict:
        calls.append(("monitor", kwargs["symbols"]))
        return {
            "market_is_open": True,
            "benchmark": {"quality_pass": True},
            "quality": {
                symbol: {"spread_bps": "1", "relative_volume": "1", "session_change_pct": "1", "quality_pass": True}
                for symbol in kwargs["symbols"]
            },
        }

    def compare(**kwargs: object) -> dict:
        calls.append(("compare", kwargs["symbol"]))
        return _comparison(str(kwargs["symbol"]))

    result = evaluate_trajectory(symbols=["aapl", "MSFT"], compare=compare, monitor=monitor)
    assert result["research_candidates"] == ["AAPL", "MSFT"]
    assert calls[0] == ("monitor", ["AAPL", "MSFT"])
    assert sorted(calls[1:]) == [
        ("compare", "AAPL"), ("compare", "MSFT"), ("compare", "SPY"),
    ]
    assert result["spy_regime"]["regime"] == "trend"


def test_summary_returns_ready_quantity_capped_by_mandate_headroom() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "quality": {
            "AAPL": {
                "last": "100", "spread_bps": "1", "relative_volume": "1",
                "session_change_pct": "1", "quality_pass": True,
            },
        },
    }
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": _comparison("AAPL")},
        equity="100000", risk_budget_pct="1", atr_multiplier="2",
        position_headroom_pct="10", gross_headroom_pct="4",
    )
    assert result["symbols"]["AAPL"]["sizing"]["available"] is True
    assert result["symbols"]["AAPL"]["sizing"]["qty"] == 40
    assert result["symbols"]["AAPL"]["sizing"]["binding_constraint"] == "mandate_headroom"


def test_summary_applies_spy_risk_off_and_adaptive_weights() -> None:
    monitoring = {
        "market_is_open": True, "benchmark": {"quality_pass": True},
        "quality": {"AAPL": {
            "last": "100", "spread_bps": "1", "relative_volume": "1",
            "session_change_pct": "1", "quality_pass": True,
        }},
    }
    aapl = _comparison("AAPL")
    spy = _comparison("SPY")
    spy["risk"]["market_regime"] = {
        "risk_off": True,
        "gross_scale": "0.5",
        "strategy_weights": {
            "momentum": "0.45", "mean_reversion": "0.10",
            "breakout_volume": "0.25", "news_price_confirmation": "0.20",
        },
    }
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": aapl, "SPY": spy},
        equity="100000", risk_budget_pct="1", atr_multiplier="2",
        position_headroom_pct="10", gross_headroom_pct="4",
        adaptive_weights_json='{"news_price_confirmation":"1.5","momentum":"0.5"}',
    )
    item = result["symbols"]["AAPL"]
    assert result["spy_regime"]["risk_off"] is True
    assert item["sizing"]["headroom_notional"] == "2000.00"
    assert Decimal(item["effective_strategy_weights"]["news_price_confirmation"]) > Decimal("0.20")
