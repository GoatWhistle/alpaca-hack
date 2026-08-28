from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
from typing import Any, Callable

from mandate_research.live_comparison import compare_live_signals
from mandate_research.monitoring import collect_market_monitoring
from mandate_research.portfolio import correlation_cluster_scale
from mandate_research.sizing import calculate_position_size


Comparison = Callable[..., dict[str, Any]]
Monitoring = Callable[..., dict[str, Any]]


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be decimal-compatible") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _normalized_symbols(symbols: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise ValueError("at least one symbol is required")
    if len(normalized) > 30:
        raise ValueError("at most 30 symbols are supported")
    return normalized


def _research_funnel(
    symbols: list[str], monitoring: dict[str, Any], *, priority_symbols: list[str], limit: int,
) -> list[str]:
    if not 2 <= limit <= 12:
        raise ValueError("research_limit must be between 2 and 12")
    quality = monitoring.get("quality", {})
    priority = {symbol: len(priority_symbols) - index for index, symbol in enumerate(priority_symbols)}

    def rank(symbol: str) -> tuple[int, int, Decimal, Decimal, str]:
        item = quality.get(symbol, {}) if isinstance(quality, dict) else {}
        relative_volume = _decimal(item.get("relative_volume") or "0", f"{symbol} relative volume")
        session_move = abs(_decimal(item.get("session_change_pct") or "0", f"{symbol} session move"))
        return (
            priority.get(symbol, 0),
            1 if item.get("quality_pass") is True else 0,
            relative_volume,
            session_move,
            symbol,
        )

    candidates = sorted((symbol for symbol in symbols if symbol != "SPY"), key=rank, reverse=True)
    selected = candidates[: max(0, limit - 1)]
    if "SPY" in symbols or selected:
        selected.append("SPY")
    return list(dict.fromkeys(selected))


def _compact_strategy(comparison: dict[str, Any]) -> dict[str, Any]:
    signals = comparison.get("signals", {})
    backtests = comparison.get("backtest", {})
    names = (
        "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
        "rsi_reversion", "macd_trend", "volatility_adjusted_momentum",
        "regime_ensemble",
    )
    compact: dict[str, Any] = {}
    for name in names:
        signal = signals.get(name, {}) if isinstance(signals, dict) else {}
        backtest = backtests.get(name, {}) if isinstance(backtests, dict) else {}
        compact[name] = {
            "direction": signal.get("direction"),
            "strength": signal.get("strength"),
            "rationale": signal.get("rationale"),
            "backtest": {
                "total_return_pct": backtest.get("total_return_pct"),
                "max_drawdown_pct": backtest.get("max_drawdown_pct"),
                "turnover": backtest.get("turnover"),
                "position_changes": backtest.get("position_changes"),
                "observations": backtest.get("observations"),
            },
        }
    return compact


def _adaptive_weights(value: str) -> dict[str, Decimal]:
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("adaptive_weights_json must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("adaptive_weights_json must be an object")
    allowed = {
        "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
        "rsi_reversion", "macd_trend", "volatility_adjusted_momentum",
    }
    result: dict[str, Decimal] = {}
    for name, raw in decoded.items():
        if name not in allowed:
            continue
        multiplier = _decimal(raw, f"adaptive weight {name}")
        if not Decimal("0.25") <= multiplier <= Decimal("2"):
            raise ValueError("adaptive weight multipliers must be between 0.25 and 2")
        result[name] = multiplier
    return result


def _weighted_payload_ensemble(
    strategies: dict[str, Any], base_weights: dict[str, Any], adaptive: dict[str, Decimal]
) -> tuple[dict[str, Any], dict[str, str]]:
    components = (
        "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
        "rsi_reversion", "macd_trend", "volatility_adjusted_momentum",
    )
    active = tuple(
        name for name in components
        if strategies[name].get("direction") in {"buy", "sell", "flat"}
        and strategies[name].get("strength") is not None
    )
    raw_weights = {
        name: _decimal(base_weights.get(name, "0.25"), f"base weight {name}") * adaptive.get(name, Decimal("1"))
        for name in active
    }
    total = sum(raw_weights.values(), Decimal("0"))
    weights = (
        {name: value / total for name, value in raw_weights.items()}
        if total
        else ({name: Decimal("1") / Decimal(len(active)) for name in active} if active else {})
    )
    score = Decimal("0")
    contributions: list[str] = []
    for name in active:
        signal = strategies[name]
        direction = {"buy": Decimal("1"), "sell": Decimal("-1")}.get(signal.get("direction"), Decimal("0"))
        strength = _decimal(signal.get("strength") or "0", f"{name} strength")
        contribution = direction * strength * weights[name]
        score += contribution
        contributions.append(f"{name}={contribution:.3f}")
    direction = "flat"
    if abs(score) >= Decimal("0.15"):
        direction = "buy" if score > 0 else "sell"
    return ({
        "direction": direction,
        "strength": str(min(abs(score), Decimal("1"))),
        "rationale": f"SPY-regime adaptive score {score:.4f}; " + ", ".join(contributions),
        "backtest": strategies.get("regime_ensemble", {}).get("backtest", {}),
    }, {name: str(value.quantize(Decimal("0.0001"))) for name, value in weights.items()})


def summarize_trajectory_math(
    *,
    symbols: list[str],
    monitoring: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
    max_spread_bps: str = "35",
    min_relative_volume: str = "0.25",
    single_symbol_move_pct: str = "5",
    regular_hours_only: bool = True,
    equity: str = "",
    risk_budget_pct: str = "0.25",
    atr_multiplier: str = "2",
    position_headroom_pct: str = "",
    gross_headroom_pct: str = "",
    adaptive_weights_json: str = "{}",
) -> dict[str, Any]:
    normalized = _normalized_symbols(symbols)
    spread_limit = _decimal(max_spread_bps, "max_spread_bps")
    volume_floor = _decimal(min_relative_volume, "min_relative_volume")
    move_limit = _decimal(single_symbol_move_pct, "single_symbol_move_pct")
    if spread_limit <= 0 or volume_floor < 0 or move_limit <= 0:
        raise ValueError("spread and move limits must be positive; volume floor cannot be negative")
    quality = monitoring.get("quality", {})
    benchmark = monitoring.get("benchmark", {})
    benchmark_pass = isinstance(benchmark, dict) and benchmark.get("quality_pass") is True
    macro_context = monitoring.get("macro_context", {})
    macro_active = isinstance(macro_context, dict) and macro_context.get("active") is True
    macro_direction = macro_context.get("direction") if isinstance(macro_context, dict) else None
    market_is_open = monitoring.get("market_is_open") is True
    results: dict[str, Any] = {}
    candidates: list[str] = []
    adaptive = _adaptive_weights(adaptive_weights_json)
    spy_risk = comparisons.get("SPY", {}).get("risk", {})
    spy_regime = spy_risk.get("market_regime", {}) if isinstance(spy_risk, dict) else {}
    base_weights = spy_regime.get("strategy_weights", {}) if isinstance(spy_regime, dict) else {}
    risk_off = isinstance(spy_regime, dict) and spy_regime.get("risk_off") is True
    sizing_enabled = all(
        value.strip() for value in (equity, position_headroom_pct, gross_headroom_pct)
    )
    spy_return = comparisons.get("SPY", {}).get("features", {}).get("return_20_pct")

    for symbol in normalized:
        item = quality.get(symbol, {}) if isinstance(quality, dict) else {}
        comparison = comparisons.get(symbol, {})
        if not comparison:
            results[symbol] = {
                "as_of": None,
                "market": {
                    "last": item.get("last"), "spread_bps": item.get("spread_bps"),
                    "relative_volume": item.get("relative_volume"),
                    "session_change_pct": item.get("session_change_pct"),
                    "stale_seconds": item.get("stale_seconds"),
                    "top_of_book_imbalance": item.get("top_of_book_imbalance"),
                    "quality_pass": item.get("quality_pass") is True,
                },
                "direction_counts": {}, "strategies": {}, "risk": {},
                "news_scoring": {"events": None, "llm_scored": None},
                "effective_strategy_weights": {},
                "sizing": {"available": False, "reason": "research_funnel"},
                "news_price_aligned": False, "macro_price_aligned": False,
                "signal_path": None, "single_symbol_move_breach": False,
                "research_candidate": False, "blocked_by": ["research_funnel"],
            }
            continue
        strategies = _compact_strategy(comparison)
        ensemble, effective_weights = _weighted_payload_ensemble(strategies, base_weights, adaptive)
        strategies["regime_ensemble"] = ensemble
        directions = [
            str(value.get("direction"))
            for value in strategies.values()
            if value.get("direction") in {"buy", "sell", "flat"}
        ]
        counts = dict(Counter(directions))
        spread = _decimal(item.get("spread_bps"), "spread_bps") if item.get("spread_bps") is not None else None
        relative_volume = (
            _decimal(item.get("relative_volume"), "relative_volume")
            if item.get("relative_volume") is not None
            else None
        )
        session_move = (
            _decimal(item.get("session_change_pct"), "session_change_pct")
            if item.get("session_change_pct") is not None
            else None
        )
        quality_pass = (
            item.get("quality_pass") is True
            and spread is not None
            and spread <= spread_limit
            and relative_volume is not None
            and relative_volume >= volume_floor
        )
        move_breach = session_move is None or abs(session_move) >= move_limit
        news_direction = strategies["news_price_confirmation"].get("direction")
        ensemble = strategies["regime_ensemble"]
        ensemble_direction = ensemble.get("direction")
        price_directions = [
            strategies[name].get("direction")
            for name in (
                "momentum", "mean_reversion", "breakout_volume",
                "rsi_reversion", "macd_trend", "volatility_adjusted_momentum",
            )
        ]
        price_news_aligned = (
            news_direction in {"buy", "sell"}
            and news_direction == ensemble_direction
            and news_direction in price_directions
        )
        macro_signal_direction = {
            "risk_on": "buy",
            "risk_off": "sell",
        }.get(macro_direction)
        macro_price_aligned = (
            macro_active
            and macro_signal_direction is not None
            and ensemble_direction == macro_signal_direction
            and sum(direction == macro_signal_direction for direction in price_directions) >= 2
        )
        reasons: list[str] = []
        if regular_hours_only and not market_is_open:
            reasons.append("outside_regular_hours")
        if not quality_pass:
            reasons.append("quality_gate")
        if not benchmark_pass:
            reasons.append("spy_quality_gate")
        if move_breach:
            reasons.append("single_symbol_move_gate" if session_move is not None else "missing_session_move")
        if not (price_news_aligned or macro_price_aligned):
            reasons.append("news_or_macro_price_not_aligned")
        candidate = not reasons
        if candidate:
            candidates.append(symbol)
        sizing: dict[str, Any] = {"available": False, "reason": "mandate_inputs_required"}
        risk = comparison.get("risk", {}) if isinstance(comparison.get("risk"), dict) else {}
        data = comparison.get("data", {}) if isinstance(comparison.get("data"), dict) else {}
        features = comparison.get("features", {}) if isinstance(comparison.get("features"), dict) else {}
        relative_strength_vs_spy = None
        if symbol != "SPY" and features.get("return_20_pct") is not None and spy_return is not None:
            relative_strength_vs_spy = str(
                (_decimal(features["return_20_pct"], "return_20_pct") - _decimal(spy_return, "SPY return_20_pct"))
                .quantize(Decimal("0.0001"))
            )
        if sizing_enabled and item.get("last") is not None and risk.get("atr14") is not None:
            sizing = {
                "available": True,
                **calculate_position_size(
                    equity=_decimal(equity, "equity"),
                    price=_decimal(item["last"], "last"),
                    atr14=_decimal(risk["atr14"], "atr14"),
                    signal_strength=_decimal(ensemble.get("strength", "0"), "ensemble strength"),
                    risk_budget_pct=_decimal(risk_budget_pct, "risk_budget_pct"),
                    atr_multiplier=_decimal(atr_multiplier, "atr_multiplier"),
                    position_headroom_pct=_decimal(position_headroom_pct, "position_headroom_pct"),
                    gross_headroom_pct=(
                        _decimal(gross_headroom_pct, "gross_headroom_pct")
                        * (Decimal("0.5") if risk_off else Decimal("1"))
                    ),
                ),
            }
        results[symbol] = {
            "as_of": comparison.get("as_of"),
            "market": {
                "last": item.get("last"),
                "spread_bps": item.get("spread_bps"),
                "relative_volume": item.get("relative_volume"),
                "session_change_pct": item.get("session_change_pct"),
                "stale_seconds": item.get("stale_seconds"),
                "top_of_book_imbalance": item.get("top_of_book_imbalance"),
                "relative_strength_vs_spy_pct": relative_strength_vs_spy,
                "quality_pass": quality_pass,
            },
            "direction_counts": counts,
            "strategies": strategies,
            "risk": risk,
            "news_scoring": {
                "events": data.get("news"),
                "llm_scored": data.get("news_llm_scored"),
            },
            "effective_strategy_weights": effective_weights,
            "sizing": sizing,
            "news_price_aligned": price_news_aligned,
            "macro_price_aligned": macro_price_aligned,
            "signal_path": (
                "news_price" if price_news_aligned else "macro_price" if macro_price_aligned else None
            ),
            "single_symbol_move_breach": move_breach,
            "research_candidate": candidate,
            "blocked_by": reasons,
        }

    for symbol in candidates:
        sizing = results[symbol]["sizing"]
        if sizing.get("available") is not True or sizing.get("qty", 0) <= 0:
            continue
        direction = results[symbol]["strategies"]["regime_ensemble"].get("direction")
        raw_returns = comparisons[symbol].get("features", {}).get("returns_20", [])
        target_returns = [_decimal(value, f"{symbol} return") for value in raw_returns]
        peers = []
        for peer in candidates:
            if peer == symbol or results[peer]["strategies"]["regime_ensemble"].get("direction") != direction:
                continue
            peer_values = comparisons[peer].get("features", {}).get("returns_20", [])
            peers.append([_decimal(value, f"{peer} return") for value in peer_values])
        scale, cluster_size = correlation_cluster_scale(target_returns, peers)
        initial_qty = int(sizing["qty"])
        final_qty = int((Decimal(initial_qty) * scale).to_integral_value(rounding=ROUND_FLOOR))
        sizing["pre_correlation_qty"] = initial_qty
        sizing["qty"] = final_qty
        sizing["correlation_scale"] = str(scale.quantize(Decimal("0.0001")))
        sizing["correlation_cluster_size"] = cluster_size
        if final_qty < initial_qty:
            sizing["binding_constraint"] = "correlation_cluster"

    return {
        "checked_at": monitoring.get("checked_at"),
        "market_is_open": market_is_open,
        "feed": monitoring.get("feed"),
        "thresholds": {
            "max_spread_bps": str(spread_limit),
            "min_relative_volume": str(volume_floor),
            "single_symbol_move_pct": str(move_limit),
            "regular_hours_only": regular_hours_only,
        },
        "benchmark": benchmark,
        "macro_context": macro_context,
        "symbols": results,
        "research_candidates": candidates,
        "spy_regime": spy_regime,
        "decision": "PROPOSE_RESEARCH" if candidates else "PARK",
        "execution_authority": False,
    }


def evaluate_trajectory(
    *,
    symbols: list[str],
    fee_bps: str = "1",
    max_spread_bps: str = "35",
    min_relative_volume: str = "0.25",
    single_symbol_move_pct: str = "5",
    regular_hours_only: bool = True,
    equity: str = "",
    risk_budget_pct: str = "0.25",
    atr_multiplier: str = "2",
    position_headroom_pct: str = "",
    gross_headroom_pct: str = "",
    adaptive_weights_json: str = "{}",
    priority_symbols_csv: str = "",
    research_limit: int = 8,
    compact_output: bool = False,
    compare: Comparison = compare_live_signals,
    monitor: Monitoring = collect_market_monitoring,
) -> dict[str, Any]:
    normalized = _normalized_symbols(symbols)
    monitoring = monitor(
        symbols=normalized,
        feed="auto",
        discovery_enabled=False,
        monitor_corporate_actions=False,
        max_spread_bps=max_spread_bps,
        min_relative_volume=min_relative_volume,
    )
    priorities = _normalized_symbols(priority_symbols_csv.split(",")) if priority_symbols_csv.strip() else []
    priorities = [symbol for symbol in priorities if symbol in normalized]
    comparison_symbols = _research_funnel(
        normalized, monitoring, priority_symbols=priorities, limit=research_limit,
    )
    with ThreadPoolExecutor(max_workers=min(4, len(comparison_symbols))) as pool:
        comparison_values = pool.map(
            lambda symbol: compare(symbol=symbol, fee_bps=fee_bps),
            comparison_symbols,
        )
        comparisons = dict(zip(comparison_symbols, comparison_values))
    result = summarize_trajectory_math(
        symbols=normalized,
        monitoring=monitoring,
        comparisons=comparisons,
        max_spread_bps=max_spread_bps,
        min_relative_volume=min_relative_volume,
        single_symbol_move_pct=single_symbol_move_pct,
        regular_hours_only=regular_hours_only,
        equity=equity,
        risk_budget_pct=risk_budget_pct,
        atr_multiplier=atr_multiplier,
        position_headroom_pct=position_headroom_pct,
        gross_headroom_pct=gross_headroom_pct,
        adaptive_weights_json=adaptive_weights_json,
    )
    result["research_funnel"] = {
        "input_symbols": normalized,
        "priority_symbols": priorities,
        "selected_symbols": comparison_symbols,
        "limit": research_limit,
    }
    if compact_output:
        result["symbols"] = {
            symbol: result["symbols"][symbol]
            for symbol in comparison_symbols
        }
    return result
