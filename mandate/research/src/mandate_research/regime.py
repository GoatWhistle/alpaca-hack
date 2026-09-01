from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from mandate_research.signals import Direction, PriceBar, TradeSignal


ZERO = Decimal("0")
ONE = Decimal("1")
STRATEGIES = (
    "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
    "rsi_reversion", "macd_trend", "volatility_adjusted_momentum",
)


def _linear_r_squared(values: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    count = Decimal(len(values))
    xs = [Decimal(index) for index in range(len(values))]
    x_mean = sum(xs, ZERO) / count
    y_mean = sum(values, ZERO) / count
    xx = sum(((value - x_mean) ** 2 for value in xs), ZERO)
    yy = sum(((value - y_mean) ** 2 for value in values), ZERO)
    if xx == ZERO or yy == ZERO:
        return ZERO, ZERO
    xy = sum(((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)), ZERO)
    slope = xy / xx
    return min((xy * xy) / (xx * yy), ONE), slope


def _realized_volatility(closes: Sequence[Decimal]) -> Decimal:
    returns = [current / previous - ONE for previous, current in zip(closes, closes[1:])]
    if not returns:
        return ZERO
    return (sum((value * value for value in returns), ZERO) / Decimal(len(returns))).sqrt() * Decimal("100")


def classify_market_regime(bars: Sequence[PriceBar], *, lookback: int = 20) -> dict[str, Any]:
    if lookback < 5 or len(bars) <= lookback:
        raise ValueError("regime classification requires lookback + 1 bars")
    closes = [bar.close for bar in bars]
    window = closes[-lookback:]
    r_squared, slope = _linear_r_squared(window)
    slope_pct = slope / (sum(window, ZERO) / Decimal(lookback)) * Decimal("100")
    current_volatility = _realized_volatility(window)
    sma20 = sum(window, ZERO) / Decimal(lookback)
    price_vs_sma_pct = (window[-1] / sma20 - ONE) * Decimal("100")
    risk_off = window[-1] < sma20
    historical = [
        _realized_volatility(closes[end - lookback : end])
        for end in range(lookback, len(closes) + 1)
    ]
    percentile = Decimal(sum(value <= current_volatility for value in historical)) / Decimal(len(historical)) * Decimal("100")
    trending = r_squared >= Decimal("0.60") and abs(slope_pct) >= Decimal("0.05")
    regime = "trend" if trending else "range"
    direction = "up" if trending and slope > ZERO else "down" if trending else "flat"
    volatility = "high" if percentile >= Decimal("75") else "low" if percentile <= Decimal("25") else "normal"
    # Aggressive short: in a down-trend the ensemble must lean on trend-following
    # strategies. Counter-trend signals (mean_reversion, rsi_reversion) vote BUY in a
    # falling market, so boosting them here damped exactly the shorts this regime is
    # meant to take. They stay at entry-timer weight only; the bounce gate in
    # decision_math keeps shorts from chasing fresh lows.
    if trending and direction == "down":
        weights = {
            "momentum": "0.22", "mean_reversion": "0.05", "breakout_volume": "0.15",
            "news_price_confirmation": "0.20", "rsi_reversion": "0.05",
            "macd_trend": "0.20", "volatility_adjusted_momentum": "0.13",
        }
    elif trending:
        weights = {
            "momentum": "0.25", "mean_reversion": "0.05", "breakout_volume": "0.15",
            "news_price_confirmation": "0.15", "rsi_reversion": "0.05",
            "macd_trend": "0.20", "volatility_adjusted_momentum": "0.15",
        }
    else:
        weights = {
            "momentum": "0.08", "mean_reversion": "0.25", "breakout_volume": "0.08",
            "news_price_confirmation": "0.15", "rsi_reversion": "0.25",
            "macd_trend": "0.07", "volatility_adjusted_momentum": "0.12",
        }
    return {
        "regime": regime,
        "direction": direction,
        "r_squared": str(r_squared.quantize(Decimal("0.0001"))),
        "slope_pct_per_bar": str(slope_pct.quantize(Decimal("0.0001"))),
        "volatility_pct": str(current_volatility.quantize(Decimal("0.0001"))),
        "volatility_percentile": str(percentile.quantize(Decimal("0.1"))),
        "volatility_bucket": volatility,
        "sma20": str(sma20.quantize(Decimal("0.0001"))),
        "price_vs_sma20_pct": str(price_vs_sma_pct.quantize(Decimal("0.0001"))),
        "risk_off": risk_off,
        "gross_scale": "0.5" if risk_off else "1",
        "strategy_weights": weights,
    }


def weighted_ensemble(
    signals: Mapping[str, TradeSignal],
    weights: Mapping[str, str],
    *,
    threshold: Decimal = Decimal("0.10"),
) -> TradeSignal:
    if not signals:
        raise ValueError("ensemble requires signals")
    if threshold < ZERO or threshold > ONE:
        raise ValueError("ensemble threshold must be between 0 and 1")
    as_of = max(signal.as_of for signal in signals.values())
    score = ZERO
    weight_sum = ZERO
    contributions: list[str] = []
    for name in STRATEGIES:
        signal = signals.get(name)
        weight = Decimal(str(weights.get(name, "0")))
        if signal is None or weight <= ZERO:
            continue
        signed = {Direction.BUY: ONE, Direction.SELL: -ONE, Direction.FLAT: ZERO}[signal.direction]
        contribution = signed * signal.strength * weight
        score += contribution
        weight_sum += weight
        contributions.append(f"{name}={contribution:.3f}")
    normalized = score / weight_sum if weight_sum else ZERO
    direction = Direction.FLAT
    if abs(normalized) >= threshold:
        direction = Direction.BUY if normalized > ZERO else Direction.SELL
    return TradeSignal(
        direction,
        min(abs(normalized), ONE),
        f"weighted score {normalized:.4f}; " + ", ".join(contributions),
        as_of,
    )
