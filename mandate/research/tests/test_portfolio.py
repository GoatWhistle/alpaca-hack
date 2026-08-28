from decimal import Decimal

from mandate_research.portfolio import correlation_cluster_scale, return_correlation


def test_correlation_cluster_scales_same_factor_exposures() -> None:
    target = [Decimal(value) for value in (".01", ".02", "-.01", ".03", ".02")]
    inverse = [-value for value in target]
    assert return_correlation(target, target) == Decimal("1")
    assert return_correlation(target, inverse) == Decimal("-1")
    scale, cluster_size = correlation_cluster_scale(target, [target, inverse])
    assert cluster_size == 2
    assert Decimal("0.70") < scale < Decimal("0.71")


def test_short_or_constant_series_fail_open_as_uncorrelated() -> None:
    assert return_correlation([Decimal("1")], [Decimal("1")]) == 0
    constant = [Decimal("1")] * 5
    assert return_correlation(constant, constant) == 0
