from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from mandate_research.signals import Direction, PriceBar, TradeSignal


ONE = Decimal("1")
ZERO = Decimal("0")
Strategy = Callable[[Sequence[PriceBar]], TradeSignal]


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    turnover: Decimal
    position_changes: int
    observations: int


def _target(direction: Direction) -> Decimal:
    return {Direction.BUY: ONE, Direction.SELL: -ONE, Direction.FLAT: ZERO}[direction]


def evaluate_strategy(
    bars: Sequence[PriceBar],
    strategy: Strategy,
    *,
    warmup: int,
    fee_bps: Decimal = ZERO,
    slippage_bps: Decimal = ZERO,
    evaluation_start: int | None = None,
    liquidate_at_end: bool = False,
) -> BacktestMetrics:
    if warmup < 1:
        raise ValueError("warmup must be positive")
    if fee_bps < ZERO:
        raise ValueError("fee_bps cannot be negative")
    if slippage_bps < ZERO:
        raise ValueError("slippage_bps cannot be negative")
    if len(bars) <= warmup:
        raise ValueError("not enough bars for warmup and one out-of-sample observation")
    if any(left.timestamp >= right.timestamp for left, right in zip(bars, bars[1:])):
        raise ValueError("bars must be strictly chronological")

    equity = ONE
    peak = ONE
    max_drawdown = ZERO
    position = ZERO
    turnover = ZERO
    changes = 0

    first_index = warmup - 1
    if evaluation_start is not None:
        if not warmup <= evaluation_start < len(bars):
            raise ValueError("evaluation_start must leave at least one eligible observation")
        first_index = max(first_index, evaluation_start - 1)
    for index in range(first_index, len(bars) - 1):
        signal = strategy(bars[: index + 1])
        target = _target(signal.direction)
        traded = abs(target - position)
        if traded:
            changes += 1
            turnover += traded
        cost = traded * (fee_bps + slippage_bps) / Decimal("10000")
        next_return = bars[index + 1].close / bars[index].close - ONE
        equity *= ONE + target * next_return - cost
        position = target
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    if liquidate_at_end and position:
        closing_turnover = abs(position)
        equity *= ONE - closing_turnover * (fee_bps + slippage_bps) / Decimal("10000")
        turnover += closing_turnover
        changes += 1
        max_drawdown = max(max_drawdown, (peak - equity) / peak)

    observations = len(bars) - (evaluation_start or warmup)
    return BacktestMetrics(
        total_return_pct=(equity - ONE) * Decimal("100"),
        max_drawdown_pct=max_drawdown * Decimal("100"),
        turnover=turnover,
        position_changes=changes,
        observations=observations,
    )


def compare_strategies(
    bars: Sequence[PriceBar],
    strategies: Mapping[str, tuple[Strategy, int]],
    *,
    fee_bps: Decimal = ZERO,
    slippage_bps: Decimal = ZERO,
    evaluation_start: int | None = None,
    liquidate_at_end: bool = False,
) -> dict[str, BacktestMetrics]:
    return {
        name: evaluate_strategy(
            bars, strategy, warmup=warmup, fee_bps=fee_bps,
            slippage_bps=slippage_bps, evaluation_start=evaluation_start,
            liquidate_at_end=liquidate_at_end,
        )
        for name, (strategy, warmup) in strategies.items()
    }
