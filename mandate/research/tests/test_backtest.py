from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mandate_research.backtest import compare_strategies, evaluate_strategy
from mandate_research.signals import Direction, PriceBar, TradeSignal, momentum_signal


def make_bars(closes: list[str]) -> list[PriceBar]:
    start = datetime(2026, 8, 26, 13, 30, tzinfo=timezone.utc)
    return [
        PriceBar(
            start + timedelta(minutes=index),
            Decimal(close),
            Decimal(close),
            Decimal(close),
            Decimal(close),
            Decimal("100"),
        )
        for index, close in enumerate(closes)
    ]


def always_buy(history: list[PriceBar] | tuple[PriceBar, ...]) -> TradeSignal:
    return TradeSignal(Direction.BUY, Decimal("1"), "baseline", history[-1].timestamp)


def test_backtest_uses_only_history_available_at_decision_time() -> None:
    bars = make_bars(["100", "101", "102", "103"])
    observed_lengths: list[int] = []

    def recording_strategy(history):
        observed_lengths.append(len(history))
        return always_buy(history)

    result = evaluate_strategy(bars, recording_strategy, warmup=2)
    assert observed_lengths == [2, 3]
    assert result.observations == 2
    assert result.total_return_pct > Decimal("0")


def test_fees_reduce_return_and_turnover_is_reported() -> None:
    bars = make_bars(["100", "101", "102", "103"])
    free = evaluate_strategy(bars, always_buy, warmup=1)
    paid = evaluate_strategy(bars, always_buy, warmup=1, fee_bps=Decimal("10"))
    assert paid.total_return_pct < free.total_return_pct
    assert paid.turnover == Decimal("1")
    assert paid.position_changes == 1


def test_compare_runs_explainable_strategies_on_same_bars() -> None:
    bars = make_bars(["100", "101", "102", "103", "104"])
    results = compare_strategies(
        bars,
        {
            "buy_hold": (always_buy, 1),
            "momentum": (lambda history: momentum_signal(history, lookback=2), 3),
        },
    )
    assert set(results) == {"buy_hold", "momentum"}
    assert all(result.max_drawdown_pct >= Decimal("0") for result in results.values())


def test_backtest_rejects_unsorted_bars() -> None:
    bars = make_bars(["100", "101", "102"])
    with pytest.raises(ValueError, match="chronological"):
        evaluate_strategy([bars[1], bars[0], bars[2]], always_buy, warmup=1)
