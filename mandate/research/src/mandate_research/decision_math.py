from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from mandate_research.live_comparison import compare_live_signals
from mandate_research.monitoring import collect_market_monitoring
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
    if len(normalized) > 20:
        raise ValueError("at most 20 symbols are supported")
    return normalized


def _compact_strategy(comparison: dict[str, Any]) -> dict[str, Any]:
    signals = comparison.get("signals", {})
    backtests = comparison.get("backtest", {})
    names = (
        "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
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
    market_is_open = monitoring.get("market_is_open") is True
    results: dict[str, Any] = {}
    candidates: list[str] = []
    sizing_enabled = all(
        value.strip() for value in (equity, position_headroom_pct, gross_headroom_pct)
    )

    for symbol in normalized:
        item = quality.get(symbol, {}) if isinstance(quality, dict) else {}
        comparison = comparisons.get(symbol, {})
        strategies = _compact_strategy(comparison)
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
        price_directions = {
            strategies[name].get("direction")
            for name in ("momentum", "mean_reversion", "breakout_volume")
        }
        price_news_aligned = (
            news_direction in {"buy", "sell"}
            and news_direction == ensemble_direction
            and news_direction in price_directions
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
        if not price_news_aligned:
            reasons.append("news_price_not_aligned")
        candidate = not reasons
        if candidate:
            candidates.append(symbol)
        sizing: dict[str, Any] = {"available": False, "reason": "mandate_inputs_required"}
        risk = comparison.get("risk", {}) if isinstance(comparison.get("risk"), dict) else {}
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
                    gross_headroom_pct=_decimal(gross_headroom_pct, "gross_headroom_pct"),
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
                "quality_pass": quality_pass,
            },
            "direction_counts": counts,
            "strategies": strategies,
            "risk": risk,
            "sizing": sizing,
            "news_price_aligned": price_news_aligned,
            "single_symbol_move_breach": move_breach,
            "research_candidate": candidate,
            "blocked_by": reasons,
        }

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
        "symbols": results,
        "research_candidates": candidates,
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
    comparisons = {symbol: compare(symbol=symbol, fee_bps=fee_bps) for symbol in normalized}
    return summarize_trajectory_math(
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
    )
