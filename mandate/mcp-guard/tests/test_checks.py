from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mandate_guard.checks import (
    OrderIntent,
    PendingOrder,
    Portfolio,
    Position,
    Side,
    check_daily_loss,
    check_expiry,
    check_gross_exposure,
    check_instrument,
    check_order,
    check_order_count,
    check_order_type,
    check_position_limit,
    check_session_window,
    check_short_position,
    check_universe,
    project_order,
)
from mandate_guard.mandate import Mandate


def test_universe_allows_member_and_rejects_outsider(mandate: Mandate, limit_buy: OrderIntent) -> None:
    assert check_universe(mandate, limit_buy) is None
    outside = OrderIntent("TSLA", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    assert check_universe(mandate, outside).rule == "universe"  # type: ignore[union-attr]


def test_instrument_allows_equity_and_rejects_crypto(mandate: Mandate, limit_buy: OrderIntent) -> None:
    assert check_instrument(mandate, limit_buy) is None
    crypto = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", "crypto", Decimal("100"))
    assert check_instrument(mandate, crypto).rule == "instrument"  # type: ignore[union-attr]


def test_order_type_allows_limit_and_requires_price(mandate: Mandate, limit_buy: OrderIntent) -> None:
    assert check_order_type(mandate, limit_buy) is None
    missing_price = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit")
    assert check_order_type(mandate, missing_price).rule == "limit_price"  # type: ignore[union-attr]


def test_order_type_rejects_market(mandate: Mandate) -> None:
    market = OrderIntent("AAPL", Side.BUY, Decimal("1"), "market")
    assert check_order_type(mandate, market).rule == "order_type"  # type: ignore[union-attr]


def test_position_limit_allows_exact_boundary(mandate: Mandate, portfolio: Portfolio) -> None:
    order = OrderIntent("AAPL", Side.BUY, Decimal("10"), "limit", limit_price=Decimal("100"))
    assert check_position_limit(mandate, project_order(portfolio, order, Decimal("100"))) is None


def test_position_limit_rejects_one_cent_over(mandate: Mandate, portfolio: Portfolio) -> None:
    order = OrderIntent("AAPL", Side.BUY, Decimal("10.0001"), "limit", limit_price=Decimal("100"))
    assert check_position_limit(mandate, project_order(portfolio, order, Decimal("100"))).rule == "max_position_pct"  # type: ignore[union-attr]


def test_gross_exposure_allows_boundary_and_rejects_excess(mandate: Mandate) -> None:
    portfolio = Portfolio(
        equity=Decimal("10000"),
        positions={"MSFT": Position(Decimal("50"), Decimal("100"))},
    )
    at_limit = OrderIntent("AAPL", Side.BUY, Decimal("10"), "limit", limit_price=Decimal("100"))
    over = OrderIntent("AAPL", Side.BUY, Decimal("10.0001"), "limit", limit_price=Decimal("100"))
    assert check_gross_exposure(mandate, project_order(portfolio, at_limit, Decimal("100"))) is None
    assert check_gross_exposure(mandate, project_order(portfolio, over, Decimal("100"))).rule == "max_gross_exposure_pct"  # type: ignore[union-attr]


def test_daily_loss_allows_below_limit_and_blocks_at_limit(mandate: Mandate) -> None:
    below = Portfolio(Decimal("10000"), {}, realized_pnl_today=Decimal("-199.99"))
    at_limit = Portfolio(Decimal("10000"), {}, realized_pnl_today=Decimal("-200"))
    assert check_daily_loss(mandate, below) is None
    assert check_daily_loss(mandate, at_limit).rule == "max_daily_loss_pct"  # type: ignore[union-attr]


def test_order_count_allows_last_slot_and_rejects_next(mandate: Mandate) -> None:
    assert check_order_count(mandate, Portfolio(Decimal("10000"), {}, orders_today=19)) is None
    assert check_order_count(mandate, Portfolio(Decimal("10000"), {}, orders_today=20)).rule == "max_orders_per_day"  # type: ignore[union-attr]


def test_session_allows_regular_hours_and_rejects_before_open(mandate: Mandate) -> None:
    during = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
    before = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    assert check_session_window(mandate, during, market_is_open=True) is None
    assert check_session_window(mandate, before, market_is_open=True).rule == "session"  # type: ignore[union-attr]


def test_session_rejects_weekend(mandate: Mandate) -> None:
    saturday = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    assert check_session_window(mandate, saturday, market_is_open=True).rule == "session"  # type: ignore[union-attr]


def test_session_fails_closed_without_exchange_clock(mandate: Mandate) -> None:
    during = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
    assert check_session_window(mandate, during).headroom == "unverified"  # type: ignore[union-attr]
    assert check_session_window(mandate, during, market_is_open=False).headroom == "closed"  # type: ignore[union-attr]


def test_expiry_allows_before_and_rejects_at_expiry(mandate: Mandate) -> None:
    before = datetime(2099, 8, 28, 19, 59, 59, tzinfo=timezone.utc)
    at_expiry = datetime(2099, 8, 28, 20, 0, tzinfo=timezone.utc)
    assert check_expiry(mandate, before) is None
    assert check_expiry(mandate, at_expiry).rule == "expires"  # type: ignore[union-attr]


def test_sell_reduces_long_position_before_opening_short(portfolio: Portfolio) -> None:
    portfolio = Portfolio(
        equity=Decimal("10000"),
        positions={"AAPL": Position(Decimal("8"), Decimal("100"))},
    )
    sell = OrderIntent("AAPL", Side.SELL, Decimal("3"), "limit", limit_price=Decimal("100"))
    projection = project_order(portfolio, sell, Decimal("100"))
    assert projection.projected_qty == Decimal("5")
    assert projection.position_pct == Decimal("5")


def test_short_position_requires_explicit_mandate_permission(mandate: Mandate) -> None:
    portfolio = Portfolio(equity=Decimal("10000"), positions={})
    sell = OrderIntent("AAPL", Side.SELL, Decimal("1"), "limit", limit_price=Decimal("100"))

    assert check_short_position(mandate, portfolio, sell).rule == "allow_short_positions"  # type: ignore[union-attr]
    opted_in = mandate.model_copy(update={"allow_short_positions": True})
    assert check_short_position(opted_in, portfolio, sell) is None


def test_pending_sells_cannot_collectively_cross_into_short(mandate: Mandate) -> None:
    portfolio = Portfolio(
        equity=Decimal("10000"),
        positions={"AAPL": Position(Decimal("5"), Decimal("100"))},
        pending_orders=(PendingOrder("AAPL", Side.SELL, Decimal("4"), Decimal("100")),),
    )
    safe_sell = OrderIntent("AAPL", Side.SELL, Decimal("1"), "limit", limit_price=Decimal("100"))
    short_sell = OrderIntent("AAPL", Side.SELL, Decimal("2"), "limit", limit_price=Decimal("100"))

    assert check_short_position(mandate, portfolio, safe_sell) is None
    assert check_short_position(mandate, portfolio, short_sell).rule == "allow_short_positions"  # type: ignore[union-attr]


def test_composite_check_reports_all_independent_breaches(
    mandate: Mandate, portfolio: Portfolio
) -> None:
    order = OrderIntent("TSLA", Side.BUY, Decimal("20"), "market")
    result = check_order(
        mandate,
        portfolio,
        order,
        Decimal("100"),
        now=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        market_is_open=False,
    )
    assert result.allowed is False
    assert {breach.rule for breach in result.breaches} >= {
        "universe",
        "order_type",
        "max_position_pct",
        "session",
    }


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1")])
def test_rejects_non_positive_reference_price(
    value: Decimal, portfolio: Portfolio, limit_buy: OrderIntent
) -> None:
    with pytest.raises(ValueError, match="reference_price"):
        project_order(portfolio, limit_buy, value)


def test_pending_orders_reserve_worst_case_position_and_gross(mandate: Mandate) -> None:
    portfolio = Portfolio(
        equity=Decimal("10000"),
        positions={},
        pending_orders=(PendingOrder("AAPL", Side.BUY, Decimal("5"), Decimal("100")),),
    )
    candidate = OrderIntent("AAPL", Side.BUY, Decimal("6"), "limit", limit_price=Decimal("100"))
    projection = project_order(portfolio, candidate, Decimal("100"))
    assert projection.position_pct == Decimal("11")
    assert check_position_limit(mandate, projection).rule == "max_position_pct"  # type: ignore[union-attr]


def test_opposing_pending_orders_do_not_cancel_risk() -> None:
    portfolio = Portfolio(
        equity=Decimal("10000"),
        positions={"AAPL": Position(Decimal("5"), Decimal("100"))},
        pending_orders=(
            PendingOrder("AAPL", Side.BUY, Decimal("5"), Decimal("100")),
            PendingOrder("AAPL", Side.SELL, Decimal("10"), Decimal("100")),
        ),
    )
    candidate = OrderIntent("AAPL", Side.BUY, Decimal("1"), "limit", limit_price=Decimal("100"))
    assert project_order(portfolio, candidate, Decimal("100")).position_pct == Decimal("11")
