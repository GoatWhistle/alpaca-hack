from __future__ import annotations

from decimal import Decimal

from mandate_research.decision_math import evaluate_trajectory, summarize_trajectory_math


def _comparison(symbol: str, news: str = "buy", momentum: str = "buy") -> dict:
    strategies = {
        "momentum": momentum,
        "mean_reversion": "flat",
        "breakout_volume": momentum,
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
    comparisons = {"AAPL": _comparison("AAPL"), "MSFT": _comparison("MSFT")}
    result = summarize_trajectory_math(
        symbols=["AAPL", "MSFT"], monitoring=monitoring, comparisons=comparisons,
    )
    assert result["research_candidates"] == ["AAPL"]
    assert result["decision"] == "PROPOSE_RESEARCH"
    assert result["execution_authority"] is False
    assert result["symbols"]["AAPL"]["direction_counts"] == {"buy": 4, "flat": 1}
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


def test_news_path_requires_two_price_votes_in_the_news_direction() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "quality": {"AAPL": {
            "last": "101", "spread_bps": "2", "relative_volume": "0.8",
            "session_change_pct": "1.2", "quality_pass": True,
        }},
    }
    comparison = _comparison("AAPL", news="buy", momentum="buy")
    comparison["signals"]["breakout_volume"]["direction"] = "flat"
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": comparison},
    )
    assert result["symbols"]["AAPL"]["news_price_aligned"] is False
    assert result["research_candidates"] == []

    comparison["signals"]["macd_trend"] = {
        "direction": "buy", "strength": "0.5", "rationale": "second price vote",
    }
    confirmed = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": comparison},
    )
    assert confirmed["symbols"]["AAPL"]["news_price_aligned"] is True


def test_macro_price_alignment_can_produce_candidate_without_company_news() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "macro_context": {
            "active": True, "direction": "risk_on",
            "trigger": "session_change_pct", "move_pct": "0.85",
        },
        "quality": {
            "AAPL": {
                "spread_bps": "2", "relative_volume": "0.8",
                "session_change_pct": "1.2", "quality_pass": True,
            }
        },
    }
    comparison = _comparison("AAPL", news="flat", momentum="buy")
    for name in ("mean_reversion", "breakout_volume"):
        comparison["signals"][name]["direction"] = "buy"
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": comparison}
    )
    assert result["research_candidates"] == ["AAPL"]
    assert result["symbols"]["AAPL"]["news_price_aligned"] is False
    assert result["symbols"]["AAPL"]["macro_price_aligned"] is True
    assert result["symbols"]["AAPL"]["signal_path"] == "macro_price"


def test_price_confirmation_can_trade_a_normal_day_without_news_or_macro_shock() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "macro_context": {"active": False, "direction": "neutral", "move_pct": "-0.30"},
        "quality": {"AAPL": {
            "last": "101", "spread_bps": "2", "relative_volume": "1.35",
            "session_change_pct": "1.10", "quality_pass": True,
        }},
    }
    comparison = _comparison("AAPL", news="flat", momentum="buy")
    for name in ("breakout_volume", "macd_trend", "volatility_adjusted_momentum"):
        comparison["signals"][name] = {
            "direction": "buy", "strength": "0.7", "rationale": "price confirmation",
        }
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": comparison}
    )
    item = result["symbols"]["AAPL"]
    assert result["research_candidates"] == ["AAPL"]
    assert item["price_confirmation_aligned"] is True
    assert item["price_confirmation_votes"] >= 3
    assert item["signal_path"] == "price_confirmation"


def test_intraday_consensus_accepts_a_bounded_low_amplitude_move() -> None:
    monitoring = {
        "market_is_open": True,
        "benchmark": {"quality_pass": True},
        "macro_context": {"active": False, "direction": "neutral"},
        "quality": {"AAPL": {
            "last": "101", "spread_bps": "2", "relative_volume": "0.9",
            "session_change_pct": "0.45", "quality_pass": True,
        }},
    }
    comparison = _comparison("AAPL", news="flat", momentum="buy")
    for name in ("momentum", "macd_trend", "volatility_adjusted_momentum"):
        comparison["signals"][name] = {
            "direction": "buy", "strength": "0.18", "rationale": "bounded intraday move",
        }
    for name in ("mean_reversion", "breakout_volume", "rsi_reversion"):
        comparison["signals"][name] = {
            "direction": "flat", "strength": "0", "rationale": "no contradiction",
        }
    result = summarize_trajectory_math(
        symbols=["AAPL"], monitoring=monitoring, comparisons={"AAPL": comparison}
    )
    assert result["research_candidates"] == ["AAPL"]
    assert Decimal(result["symbols"]["AAPL"]["strategies"]["regime_ensemble"]["strength"]) >= Decimal("0.07")


def test_price_confirmation_rejects_thin_volume_and_active_spy_conflict() -> None:
    comparison = _comparison("AAPL", news="flat", momentum="buy")
    for name in ("breakout_volume", "macd_trend", "volatility_adjusted_momentum"):
        comparison["signals"][name] = {
            "direction": "buy", "strength": "0.7", "rationale": "price confirmation",
        }
    base_quality = {
        "last": "101", "spread_bps": "2", "relative_volume": "0.49",
        "session_change_pct": "1.10", "quality_pass": True,
    }
    thin = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring={
            "market_is_open": True, "benchmark": {"quality_pass": True},
            "macro_context": {"active": False, "direction": "neutral"},
            "quality": {"AAPL": base_quality},
        },
        comparisons={"AAPL": comparison},
    )
    conflict = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring={
            "market_is_open": True, "benchmark": {"quality_pass": True},
            "macro_context": {"active": True, "direction": "risk_off"},
            "quality": {"AAPL": {**base_quality, "relative_volume": "1.20"}},
        },
        comparisons={"AAPL": comparison},
    )
    assert thin["research_candidates"] == []
    assert conflict["research_candidates"] == []


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


def test_research_funnel_prioritizes_alerts_and_bounds_expensive_comparisons() -> None:
    compared: list[str] = []
    symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "SPY"]

    def monitor(**_: object) -> dict:
        return {
            "market_is_open": True,
            "benchmark": {"quality_pass": True},
            "quality": {
                symbol: {
                    "spread_bps": "1", "relative_volume": str(index + 1),
                    "session_change_pct": "1", "quality_pass": True,
                }
                for index, symbol in enumerate(symbols)
            },
        }

    def compare(**kwargs: object) -> dict:
        symbol = str(kwargs["symbol"])
        compared.append(symbol)
        return _comparison(symbol)

    result = evaluate_trajectory(
        symbols=symbols, priority_symbols_csv="AAPL", research_limit=3,
        monitor=monitor, compare=compare,
    )
    assert set(compared) == {"AAPL", "AMZN", "SPY"}
    assert result["research_funnel"]["selected_symbols"] == ["AAPL", "AMZN", "SPY"]
    assert result["symbols"]["MSFT"]["blocked_by"] == ["research_funnel"]


def test_compact_output_returns_only_fully_researched_symbols() -> None:
    symbols = ["AAPL", "MSFT", "NVDA", "SPY"]

    def monitor(**_: object) -> dict:
        return {
            "market_is_open": True, "benchmark": {"quality_pass": True},
            "quality": {
                symbol: {
                    "spread_bps": "1", "relative_volume": "1",
                    "session_change_pct": "1", "quality_pass": True,
                }
                for symbol in symbols
            },
        }

    result = evaluate_trajectory(
        symbols=symbols, research_limit=3, compact_output=True,
        monitor=monitor, compare=lambda **kwargs: _comparison(str(kwargs["symbol"])),
    )
    assert result["research_funnel"]["input_symbols"] == symbols
    assert set(result["symbols"]) == set(result["research_funnel"]["selected_symbols"])
    assert len(result["symbols"]) == 3


def test_summary_scales_correlated_same_side_candidates() -> None:
    monitoring = {
        "market_is_open": True, "benchmark": {"quality_pass": True},
        "quality": {
            symbol: {
                "last": "100", "spread_bps": "1", "relative_volume": "1",
                "session_change_pct": "1", "quality_pass": True,
            }
            for symbol in ("AAPL", "MSFT")
        },
    }
    returns = ["0.01", "0.02", "-0.01", "0.03", "0.02"]
    comparisons = {symbol: _comparison(symbol) for symbol in ("AAPL", "MSFT")}
    for comparison in comparisons.values():
        comparison["features"] = {"returns_20": returns}
    result = summarize_trajectory_math(
        symbols=["AAPL", "MSFT"], monitoring=monitoring, comparisons=comparisons,
        equity="100000", risk_budget_pct="1", atr_multiplier="2",
        position_headroom_pct="10", gross_headroom_pct="4",
    )
    for symbol in ("AAPL", "MSFT"):
        sizing = result["symbols"][symbol]["sizing"]
        assert sizing["pre_correlation_qty"] == 40
        assert sizing["qty"] == 28
        assert sizing["correlation_cluster_size"] == 2
        assert sizing["binding_constraint"] == "correlation_cluster"


def _short_comparison(symbol: str, *, low_20: str, direction: str = "down") -> dict:
    base = _comparison(symbol, news="sell", momentum="sell")
    base["signals"]["regime_ensemble"] = {"direction": "sell", "strength": "0.6", "rationale": "ensemble"}
    base["risk"] = {"atr14": "2", "market_regime": {"regime": "trend", "direction": direction}}
    base["features"] = {"low_20": low_20, "atr14": "2"}
    return base


def _sell_monitoring(last: str) -> dict:
    return {
        "checked_at": "2026-08-27T17:01:00+00:00",
        "market_is_open": True,
        "feed": "iex",
        "benchmark": {"symbol": "SPY", "quality_pass": True},
        "quality": {
            "AAPL": {
                "last": last,
                "spread_bps": "2.5",
                "relative_volume": "0.8",
                "session_change_pct": "-1.25",
                "stale_seconds": 4,
                "quality_pass": True,
            }
        },
    }


def test_short_entry_blocked_when_chasing_fresh_low() -> None:
    comparison = _short_comparison("AAPL", low_20="100.4")
    result = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring=_sell_monitoring(last="100.5"),
        comparisons={"AAPL": comparison},
    )
    assert "short_entry_chasing_low" in result["symbols"]["AAPL"]["blocked_by"]
    assert result["research_candidates"] == []


def test_short_entry_allowed_after_realized_bounce() -> None:
    comparison = _short_comparison("AAPL", low_20="99.0")
    result = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring=_sell_monitoring(last="100.5"),
        comparisons={"AAPL": comparison},
    )
    assert "short_entry_chasing_low" not in result["symbols"]["AAPL"]["blocked_by"]
    assert result["research_candidates"] == ["AAPL"]


def test_short_entry_fails_closed_without_reference_prices() -> None:
    comparison = _short_comparison("AAPL", low_20="99.0")
    comparison["features"] = {}
    result = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring=_sell_monitoring(last="100.5"),
        comparisons={"AAPL": comparison},
    )
    assert "short_entry_missing_references" in result["symbols"]["AAPL"]["blocked_by"]


def test_bounce_gate_inactive_outside_down_trend() -> None:
    comparison = _short_comparison("AAPL", low_20="100.4", direction="up")
    result = summarize_trajectory_math(
        symbols=["AAPL"],
        monitoring=_sell_monitoring(last="100.5"),
        comparisons={"AAPL": comparison},
    )
    assert "short_entry_chasing_low" not in result["symbols"]["AAPL"]["blocked_by"]
