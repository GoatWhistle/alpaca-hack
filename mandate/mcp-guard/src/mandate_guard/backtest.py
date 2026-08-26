from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from mandate_guard.signals import Direction, PriceBar, TradeSignal


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
) -> BacktestMetrics:
    if warmup < 1:
        raise ValueError("warmup must be positive")
    if fee_bps < ZERO:
        raise ValueError("fee_bps cannot be negative")
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

    for index in range(warmup - 1, len(bars) - 1):
        signal = strategy(bars[: index + 1])
        target = _target(signal.direction)
        traded = abs(target - position)
        if traded:
            changes += 1
            turnover += traded
        cost = traded * fee_bps / Decimal("10000")
        next_return = bars[index + 1].close / bars[index].close - ONE
        equity *= ONE + target * next_return - cost
        position = target
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    observations = len(bars) - warmup
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
) -> dict[str, BacktestMetrics]:
    return {
        name: evaluate_strategy(bars, strategy, warmup=warmup, fee_bps=fee_bps)
        for name, (strategy, warmup) in strategies.items()
    }
