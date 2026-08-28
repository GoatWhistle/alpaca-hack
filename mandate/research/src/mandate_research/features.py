from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from mandate_research.signals import PriceBar


ZERO = Decimal("0")
ONE = Decimal("1")


def relative_strength_index(bars: Sequence[PriceBar], *, period: int = 14) -> Decimal:
    if period < 2 or len(bars) <= period:
        raise ValueError("RSI requires period + 1 bars and period >= 2")
    changes = [current.close - previous.close for previous, current in zip(bars[-period - 1:-1], bars[-period:])]
    average_gain = sum((max(change, ZERO) for change in changes), ZERO) / Decimal(period)
    average_loss = sum((max(-change, ZERO) for change in changes), ZERO) / Decimal(period)
    if average_loss == ZERO:
        return Decimal("100") if average_gain > ZERO else Decimal("50")
    relative_strength = average_gain / average_loss
    return Decimal("100") - Decimal("100") / (ONE + relative_strength)


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal]:
    if period < 2 or len(values) < period:
        raise ValueError("EMA requires at least period values and period >= 2")
    alpha = Decimal("2") / Decimal(period + 1)
    current = sum(values[:period], ZERO) / Decimal(period)
    result = [current]
    for value in values[period:]:
        current = value * alpha + current * (ONE - alpha)
        result.append(current)
    return result


def macd_histogram(
    bars: Sequence[PriceBar], *, fast: int = 12, slow: int = 26, signal: int = 9,
) -> Decimal:
    if not 2 <= fast < slow or signal < 2:
        raise ValueError("MACD requires 2 <= fast < slow and signal >= 2")
    closes = [bar.close for bar in bars]
    if len(closes) < slow + signal - 1:
        raise ValueError("MACD requires slow + signal - 1 bars")
    fast_series = _ema_series(closes, fast)
    slow_series = _ema_series(closes, slow)
    aligned_fast = fast_series[slow - fast:]
    macd = [fast_value - slow_value for fast_value, slow_value in zip(aligned_fast, slow_series)]
    signal_series = _ema_series(macd, signal)
    return macd[-1] - signal_series[-1]


def realized_volatility(bars: Sequence[PriceBar], *, lookback: int = 20) -> Decimal:
    if lookback < 2 or len(bars) <= lookback:
        raise ValueError("volatility requires lookback + 1 bars and lookback >= 2")
    returns = [
        current.close / previous.close - ONE
        for previous, current in zip(bars[-lookback - 1:-1], bars[-lookback:])
    ]
    mean = sum(returns, ZERO) / Decimal(lookback)
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(lookback)
    return variance.sqrt()


def relative_strength_vs_benchmark(
    bars: Sequence[PriceBar], benchmark: Sequence[PriceBar], *, lookback: int = 20,
) -> Decimal:
    if lookback < 1 or len(bars) <= lookback or len(benchmark) <= lookback:
        raise ValueError("relative strength requires lookback + 1 bars for both series")
    asset_return = bars[-1].close / bars[-1 - lookback].close - ONE
    benchmark_return = benchmark[-1].close / benchmark[-1 - lookback].close - ONE
    return (asset_return - benchmark_return) * Decimal("100")


def top_of_book_imbalance(bid_size: Decimal, ask_size: Decimal) -> Decimal:
    if bid_size < ZERO or ask_size < ZERO:
        raise ValueError("quote sizes cannot be negative")
    total = bid_size + ask_size
    return ZERO if total == ZERO else (bid_size - ask_size) / total
