from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from mandate_research.news import NewsEvent, deduplicate


ZERO = Decimal("0")
ONE = Decimal("1")


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


@dataclass(frozen=True)
class PriceBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must include a timezone")
        if min(self.open, self.high, self.low, self.close) <= ZERO:
            raise ValueError("OHLC prices must be positive")
        if self.volume < ZERO:
            raise ValueError("volume cannot be negative")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low are inconsistent with open/close")


@dataclass(frozen=True)
class TradeSignal:
    direction: Direction
    strength: Decimal
    rationale: str
    as_of: datetime

    def __post_init__(self) -> None:
        if not ZERO <= self.strength <= ONE:
            raise ValueError("signal strength must be between 0 and 1")


def _flat(bars: Sequence[PriceBar], rationale: str) -> TradeSignal:
    if not bars:
        raise ValueError("at least one bar is required")
    return TradeSignal(Direction.FLAT, ZERO, rationale, bars[-1].timestamp)


def momentum_signal(
    bars: Sequence[PriceBar], *, lookback: int = 5, threshold_pct: Decimal = Decimal("0.5")
) -> TradeSignal:
    if lookback < 1:
        raise ValueError("lookback must be positive")
    if threshold_pct < ZERO:
        raise ValueError("threshold_pct cannot be negative")
    if len(bars) <= lookback:
        return _flat(bars, f"need {lookback + 1} bars")
    change_pct = (bars[-1].close / bars[-1 - lookback].close - ONE) * Decimal("100")
    if abs(change_pct) <= threshold_pct:
        return _flat(bars, f"momentum {change_pct:.4f}% inside threshold")
    direction = Direction.BUY if change_pct > ZERO else Direction.SELL
    strength = min(abs(change_pct) / max(threshold_pct * Decimal("4"), Decimal("0.0001")), ONE)
    return TradeSignal(direction, strength, f"{lookback}-bar momentum {change_pct:.4f}%", bars[-1].timestamp)


def mean_reversion_signal(
    bars: Sequence[PriceBar], *, lookback: int = 20, z_threshold: Decimal = Decimal("2")
) -> TradeSignal:
    if lookback < 2:
        raise ValueError("lookback must be at least 2")
    if z_threshold <= ZERO:
        raise ValueError("z_threshold must be positive")
    if len(bars) < lookback:
        return _flat(bars, f"need {lookback} bars")
    closes = [bar.close for bar in bars[-lookback:]]
    mean = sum(closes, ZERO) / Decimal(lookback)
    variance = sum(((value - mean) ** 2 for value in closes), ZERO) / Decimal(lookback)
    stddev = variance.sqrt()
    if stddev == ZERO:
        return _flat(bars, "zero rolling volatility")
    z_score = (closes[-1] - mean) / stddev
    if abs(z_score) < z_threshold:
        return _flat(bars, f"z-score {z_score:.4f} inside threshold")
    direction = Direction.SELL if z_score > ZERO else Direction.BUY
    strength = min(abs(z_score) / (z_threshold * Decimal("2")), ONE)
    return TradeSignal(direction, strength, f"mean-reversion z-score {z_score:.4f}", bars[-1].timestamp)


def breakout_volume_signal(
    bars: Sequence[PriceBar], *, lookback: int = 20, min_volume_ratio: Decimal = Decimal("1.5")
) -> TradeSignal:
    if lookback < 2:
        raise ValueError("lookback must be at least 2")
    if min_volume_ratio <= ZERO:
        raise ValueError("min_volume_ratio must be positive")
    if len(bars) <= lookback:
        return _flat(bars, f"need {lookback + 1} bars")
    history = bars[-1 - lookback : -1]
    latest = bars[-1]
    average_volume = sum((bar.volume for bar in history), ZERO) / Decimal(lookback)
    if average_volume == ZERO:
        return _flat(bars, "zero historical volume")
    volume_ratio = latest.volume / average_volume
    if volume_ratio < min_volume_ratio:
        return _flat(bars, f"volume ratio {volume_ratio:.3f} below confirmation")
    if latest.close > max(bar.high for bar in history):
        return TradeSignal(
            Direction.BUY,
            min(volume_ratio / (min_volume_ratio * Decimal("2")), ONE),
            f"upside breakout with {volume_ratio:.3f}x volume",
            latest.timestamp,
        )
    if latest.close < min(bar.low for bar in history):
        return TradeSignal(
            Direction.SELL,
            min(volume_ratio / (min_volume_ratio * Decimal("2")), ONE),
            f"downside breakout with {volume_ratio:.3f}x volume",
            latest.timestamp,
        )
    return _flat(bars, f"no price breakout; volume ratio {volume_ratio:.3f}")


def score_news(event: NewsEvent, *, symbol: str) -> Decimal:
    if event.symbols and symbol.upper() not in event.symbols:
        return ZERO
    try:
        score = Decimal(event.metadata.get("llm_score", "0"))
        confidence = Decimal(event.metadata.get("llm_confidence", "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    if not score.is_finite() or not confidence.is_finite():
        return ZERO
    if not -ONE <= score <= ONE or not ZERO <= confidence <= ONE:
        return ZERO
    return score * confidence


def news_price_confirmation_signal(
    bars: Sequence[PriceBar],
    events: Sequence[NewsEvent],
    *,
    symbol: str,
    lookback: int = 3,
    news_threshold: Decimal = Decimal("0.25"),
    max_news_age: timedelta = timedelta(hours=24),
) -> TradeSignal:
    if not bars:
        raise ValueError("at least one bar is required")
    if not ZERO <= news_threshold <= ONE:
        raise ValueError("news_threshold must be between 0 and 1")
    if max_news_age <= timedelta(0):
        raise ValueError("max_news_age must be positive")
    cutoff = bars[-1].timestamp
    earliest = cutoff - max_news_age
    eligible_events = deduplicate(
        event for event in events if earliest <= event.published_at <= cutoff
    )
    if not eligible_events:
        return _flat(bars, "no recent news")
    scores = [score_news(event, symbol=symbol) for event in eligible_events]
    news_score = sum(scores, ZERO) / Decimal(len(scores))
    price = momentum_signal(bars, lookback=lookback, threshold_pct=Decimal("0"))
    news_direction = Direction.BUY if news_score > ZERO else Direction.SELL if news_score < ZERO else Direction.FLAT
    if abs(news_score) < news_threshold:
        return _flat(bars, f"news score {news_score:.3f} below threshold")
    if news_direction is Direction.FLAT or price.direction is not news_direction:
        return _flat(bars, f"news {news_score:.3f} lacks price confirmation")
    return TradeSignal(
        news_direction,
        min((abs(news_score) + price.strength) / Decimal("2"), ONE),
        f"news score {news_score:.3f} confirmed by {price.rationale}",
        bars[-1].timestamp,
    )
