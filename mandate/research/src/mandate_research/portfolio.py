from __future__ import annotations

from decimal import Decimal
from typing import Sequence


ZERO = Decimal("0")
ONE = Decimal("1")


def return_correlation(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    """Return bounded Pearson correlation over the aligned trailing observations."""
    count = min(len(left), len(right))
    if count < 5:
        return ZERO
    xs = list(left[-count:])
    ys = list(right[-count:])
    x_mean = sum(xs, ZERO) / Decimal(count)
    y_mean = sum(ys, ZERO) / Decimal(count)
    covariance = sum(((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)), ZERO)
    x_variance = sum(((x - x_mean) ** 2 for x in xs), ZERO)
    y_variance = sum(((y - y_mean) ** 2 for y in ys), ZERO)
    if x_variance == ZERO or y_variance == ZERO:
        return ZERO
    return max(-ONE, min(ONE, covariance / (x_variance * y_variance).sqrt()))


def correlation_cluster_scale(
    target_returns: Sequence[Decimal], peer_returns: Sequence[Sequence[Decimal]],
    *, threshold: Decimal = Decimal("0.70"),
) -> tuple[Decimal, int]:
    """Scale a position by 1/sqrt(cluster size) for highly correlated same-side peers."""
    if not ZERO <= threshold <= ONE:
        raise ValueError("correlation threshold must be between 0 and 1")
    correlated_peers = sum(
        return_correlation(target_returns, peer) >= threshold
        for peer in peer_returns
    )
    cluster_size = 1 + correlated_peers
    return ONE / Decimal(cluster_size).sqrt(), cluster_size
