from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from mandate_research.backtest import Strategy, compare_strategies, evaluate_strategy
from mandate_research.news import NewsEvent, deduplicate
from mandate_research.regime import classify_market_regime, weighted_ensemble
from mandate_research.signals import (
    PriceBar,
    breakout_volume_signal,
    mean_reversion_signal,
    momentum_signal,
    news_price_confirmation_signal,
)
from mandate_research.sizing import average_true_range


DEFAULT_PARAMETERS: dict[str, dict[str, Any]] = {
    "momentum": {"lookback": 5, "threshold_pct": Decimal("0.5")},
    "mean_reversion": {"lookback": 20, "z_threshold": Decimal("2")},
    "breakout_volume": {"lookback": 20, "min_volume_ratio": Decimal("1.5")},
    "news_price_confirmation": {"lookback": 3, "news_threshold": Decimal("0.25")},
}
PARAMETER_GRID: dict[str, list[dict[str, Any]]] = {
    "momentum": [
        {"lookback": lookback, "threshold_pct": threshold}
        for lookback in (3, 5, 10)
        for threshold in (Decimal("0.25"), Decimal("0.5"), Decimal("1"))
    ],
    "mean_reversion": [
        {"lookback": lookback, "z_threshold": threshold}
        for lookback in (10, 20)
        for threshold in (Decimal("1.5"), Decimal("2"), Decimal("2.5"))
    ],
    "breakout_volume": [
        {"lookback": lookback, "min_volume_ratio": ratio}
        for lookback in (10, 20)
        for ratio in (Decimal("1.25"), Decimal("1.5"), Decimal("2"))
    ],
    "news_price_confirmation": [
        {"lookback": lookback, "news_threshold": threshold}
        for lookback in (2, 3, 5)
        for threshold in (Decimal("0.15"), Decimal("0.25"), Decimal("0.4"))
    ],
}


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def _bar(item: dict[str, Any]) -> PriceBar:
    return PriceBar(
        timestamp=_datetime(item["timestamp"]),
        open=_decimal(item["open"]),
        high=_decimal(item["high"]),
        low=_decimal(item["low"]),
        close=_decimal(item["close"]),
        volume=_decimal(item["volume"]),
    )


def _news(item: dict[str, Any]) -> NewsEvent:
    symbols = tuple(
        normalized
        for symbol in item.get("symbols", [])
        if (normalized := str(symbol).strip().upper())
    )
    return NewsEvent(
        source=str(item["source"]),
        external_id=str(item["external_id"]),
        published_at=_datetime(item["published_at"]),
        headline=str(item["headline"]),
        summary=str(item.get("summary", "")),
        symbols=symbols,
        url=str(item["url"]) if item.get("url") else None,
        metadata={
            key: str(item[key])
            for key in ("llm_score", "llm_confidence", "llm_reason", "llm_event_type", "llm_horizon")
            if item.get(key) is not None
        },
    )


def _component_strategies(
    *, symbol: str, events: list[NewsEvent], max_news_age: timedelta,
    parameters: dict[str, dict[str, Any]],
) -> dict[str, tuple[Strategy, int]]:
    momentum = parameters["momentum"]
    reversion = parameters["mean_reversion"]
    breakout = parameters["breakout_volume"]
    news = parameters["news_price_confirmation"]
    return {
        "momentum": (
            lambda window: momentum_signal(window, **momentum),
            int(momentum["lookback"]) + 1,
        ),
        "mean_reversion": (
            lambda window: mean_reversion_signal(window, **reversion),
            int(reversion["lookback"]),
        ),
        "breakout_volume": (
            lambda window: breakout_volume_signal(window, **breakout),
            int(breakout["lookback"]) + 1,
        ),
        "news_price_confirmation": (
            lambda window: news_price_confirmation_signal(
                window, events, symbol=symbol, max_news_age=max_news_age, **news,
            ),
            int(news["lookback"]) + 1,
        ),
    }


def _with_ensemble(
    components: dict[str, tuple[Strategy, int]],
) -> dict[str, tuple[Strategy, int]]:
    strategies = dict(components)

    def regime_ensemble(window: Sequence[PriceBar]):
        component_signals = {
            name: strategy(window) for name, (strategy, _warmup) in components.items()
        }
        regime = classify_market_regime(window)
        return weighted_ensemble(component_signals, regime["strategy_weights"])

    strategies["regime_ensemble"] = (regime_ensemble, 21)
    return strategies


def _select_train_parameters(
    *, bars: list[PriceBar], symbol: str, events: list[NewsEvent], max_news_age: timedelta,
    fee_bps: Decimal, slippage_bps: Decimal,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for name, candidates in PARAMETER_GRID.items():
        best: tuple[Decimal, dict[str, Any]] | None = None
        for candidate in candidates:
            parameters = {**DEFAULT_PARAMETERS, name: candidate}
            strategy, warmup = _component_strategies(
                symbol=symbol, events=events, max_news_age=max_news_age, parameters=parameters,
            )[name]
            if len(bars) <= warmup:
                continue
            metrics = evaluate_strategy(
                bars, strategy, warmup=warmup, fee_bps=fee_bps,
                slippage_bps=slippage_bps, liquidate_at_end=True,
            )
            objective = metrics.total_return_pct - metrics.max_drawdown_pct
            if best is None or objective > best[0]:
                best = (objective, candidate)
        selected[name] = dict(best[1] if best else DEFAULT_PARAMETERS[name])
    return selected


def _wire_parameters(parameters: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        name: {key: str(value) if isinstance(value, Decimal) else value for key, value in values.items()}
        for name, values in parameters.items()
    }


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload["symbol"]).strip().upper()
    if not symbol:
        raise ValueError("symbol cannot be blank")
    bars = sorted((_bar(item) for item in payload["bars"]), key=lambda bar: bar.timestamp)
    if len(bars) < 22:
        raise ValueError("at least 22 chronological bars are required")
    cutoff = bars[-1].timestamp
    all_eligible_events = [
        event
        for event in (_news(item) for item in payload.get("news", []))
        if event.published_at <= cutoff
    ]
    news_max_age_hours = _decimal(payload.get("news_max_age_hours", "24"))
    if not Decimal("0") < news_max_age_hours <= Decimal("8760"):
        raise ValueError("news_max_age_hours must be between 0 and 8760")
    max_news_age = timedelta(
        microseconds=int(news_max_age_hours * Decimal("3600000000"))
    )
    current_events = deduplicate(
        event for event in all_eligible_events if event.published_at >= cutoff - max_news_age
    )

    strategies = _with_ensemble(_component_strategies(
        symbol=symbol, events=all_eligible_events, max_news_age=max_news_age,
        parameters=DEFAULT_PARAMETERS,
    ))
    fee_bps = _decimal(payload.get("fee_bps", "1"))
    slippage_bps = _decimal(payload.get("slippage_bps", "2"))
    metrics = compare_strategies(
        bars, strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
        liquidate_at_end=True,
    )
    split = max(22, int(len(bars) * 2 / 3))
    holdout: dict[str, Any] = {"status": "insufficient_history"}
    if split < len(bars):
        selected_parameters = _select_train_parameters(
            bars=bars[:split], symbol=symbol, events=all_eligible_events,
            max_news_age=max_news_age, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        selected_strategies = _with_ensemble(_component_strategies(
            symbol=symbol, events=all_eligible_events, max_news_age=max_news_age,
            parameters=selected_parameters,
        ))
        train_metrics = compare_strategies(
            bars[:split], selected_strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
            liquidate_at_end=True,
        )
        test_metrics = compare_strategies(
            bars, selected_strategies, fee_bps=fee_bps, slippage_bps=slippage_bps,
            evaluation_start=split, liquidate_at_end=True,
        )
        holdout = {
            "status": "ok",
            "train_bars": split,
            "test_bars": len(bars) - split,
            "parameters_frozen": True,
            "selection_objective": "train total_return_pct minus max_drawdown_pct",
            "selected_parameters": _wire_parameters(selected_parameters),
            "train": {
                name: {key: str(value) for key, value in asdict(result).items()}
                for name, result in train_metrics.items()
            },
            "test": {
                name: {key: str(value) for key, value in asdict(result).items()}
                for name, result in test_metrics.items()
            },
        }
    current = {name: strategy(bars) for name, (strategy, _warmup) in strategies.items()}
    regime = classify_market_regime(bars)
    atr14 = average_true_range(bars)
    return {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "news_events_used": len(current_events),
        "news_max_age_hours": str(news_max_age_hours),
        "fee_bps": str(fee_bps),
        "slippage_bps": str(slippage_bps),
        "cost_model": "fee plus explicit spread-crossing slippage on entries, changes, and final exit",
        "chronological_holdout": holdout,
        "risk": {
            "atr14": str(atr14),
            "atr_pct": str((atr14 / bars[-1].close * Decimal("100")).quantize(Decimal("0.0001"))),
            "market_regime": regime,
        },
        "signals": {
            name: {
                "direction": signal.direction.value,
                "strength": str(signal.strength),
                "rationale": signal.rationale,
            }
            for name, signal in current.items()
        },
        "backtest": {
            name: {key: str(value) for key, value in asdict(result).items()}
            for name, result in metrics.items()
        },
    }
