from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from mandate_guard.mandate import Mandate


ZERO = Decimal("0")
HUNDRED = Decimal("100")
NEW_YORK = ZoneInfo("America/New_York")


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Position:
    qty: Decimal
    market_price: Decimal

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.market_price


@dataclass(frozen=True)
class Portfolio:
    equity: Decimal
    positions: dict[str, Position]
    realized_pnl_today: Decimal = ZERO
    orders_today: int = 0

    def __post_init__(self) -> None:
        if self.equity <= ZERO:
            raise ValueError("portfolio equity must be positive")
        if self.orders_today < 0:
            raise ValueError("orders_today cannot be negative")


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Side
    qty: Decimal
    order_type: str
    instrument: str = "equity"
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if not self.symbol:
            raise ValueError("symbol cannot be blank")
        if self.qty <= ZERO:
            raise ValueError("qty must be positive")
        if self.limit_price is not None and self.limit_price <= ZERO:
            raise ValueError("limit_price must be positive")


@dataclass(frozen=True)
class Breach:
    rule: str
    limit: str
    projected: str
    headroom: str


@dataclass(frozen=True)
class Projection:
    price: Decimal
    current_qty: Decimal
    projected_qty: Decimal
    position_pct: Decimal
    gross_exposure_pct: Decimal


@dataclass(frozen=True)
class CheckResult:
    allowed: bool
    breaches: tuple[Breach, ...]
    projection: Projection


def _percent(value: Decimal, equity: Decimal) -> Decimal:
    return value / equity * HUNDRED


def project_order(portfolio: Portfolio, order: OrderIntent, reference_price: Decimal) -> Projection:
    if reference_price <= ZERO:
        raise ValueError("reference_price must be positive")

    current = portfolio.positions.get(order.symbol, Position(qty=ZERO, market_price=reference_price))
    signed_qty = order.qty if order.side is Side.BUY else -order.qty
    projected_qty = current.qty + signed_qty
    projected_value = abs(projected_qty * reference_price)

    other_gross = sum(
        abs(position.market_value)
        for symbol, position in portfolio.positions.items()
        if symbol != order.symbol
    )
    projected_gross = other_gross + projected_value

    return Projection(
        price=reference_price,
        current_qty=current.qty,
        projected_qty=projected_qty,
        position_pct=_percent(projected_value, portfolio.equity),
        gross_exposure_pct=_percent(projected_gross, portfolio.equity),
    )


def check_universe(mandate: Mandate, order: OrderIntent) -> Breach | None:
    if order.symbol in mandate.universe:
        return None
    return Breach("universe", ",".join(mandate.universe), order.symbol, "not-authorized")


def check_instrument(mandate: Mandate, order: OrderIntent) -> Breach | None:
    if order.instrument in mandate.instruments:
        return None
    return Breach("instrument", ",".join(mandate.instruments), order.instrument, "not-authorized")


def check_order_type(mandate: Mandate, order: OrderIntent) -> Breach | None:
    if order.order_type not in mandate.order_types:
        return Breach("order_type", ",".join(mandate.order_types), order.order_type, "not-authorized")
    if order.order_type in {"limit", "stop_limit"} and order.limit_price is None:
        return Breach("limit_price", "required", "missing", "not-authorized")
    return None


def check_position_limit(mandate: Mandate, projection: Projection) -> Breach | None:
    limit = mandate.limits.max_position_pct
    if projection.position_pct <= limit:
        return None
    return Breach(
        "max_position_pct",
        str(limit),
        str(projection.position_pct),
        str(limit - projection.position_pct),
    )


def check_gross_exposure(mandate: Mandate, projection: Projection) -> Breach | None:
    limit = mandate.limits.max_gross_exposure_pct
    if projection.gross_exposure_pct <= limit:
        return None
    return Breach(
        "max_gross_exposure_pct",
        str(limit),
        str(projection.gross_exposure_pct),
        str(limit - projection.gross_exposure_pct),
    )


def check_daily_loss(mandate: Mandate, portfolio: Portfolio) -> Breach | None:
    loss_pct = _percent(max(-portfolio.realized_pnl_today, ZERO), portfolio.equity)
    limit = mandate.limits.max_daily_loss_pct
    if loss_pct < limit:
        return None
    return Breach("max_daily_loss_pct", str(limit), str(loss_pct), str(limit - loss_pct))


def check_order_count(mandate: Mandate, portfolio: Portfolio) -> Breach | None:
    limit = mandate.limits.max_orders_per_day
    projected = portfolio.orders_today + 1
    if projected <= limit:
        return None
    return Breach("max_orders_per_day", str(limit), str(projected), str(limit - projected))


def check_session_window(mandate: Mandate, now: datetime) -> Breach | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    local = now.astimezone(NEW_YORK)
    minutes = local.hour * 60 + local.minute
    is_regular = local.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60
    if mandate.session == "regular_hours_only" and not is_regular:
        return Breach("session", "regular_hours_only", local.isoformat(), "closed")
    return None


def check_expiry(mandate: Mandate, now: datetime) -> Breach | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if now < mandate.expires:
        return None
    return Breach("expires", mandate.expires.isoformat(), now.isoformat(), "expired")


def check_order(
    mandate: Mandate,
    portfolio: Portfolio,
    order: OrderIntent,
    reference_price: Decimal,
    *,
    now: datetime | None = None,
) -> CheckResult:
    checked_at = now or datetime.now(timezone.utc)
    projection = project_order(portfolio, order, reference_price)
    candidates = (
        check_universe(mandate, order),
        check_instrument(mandate, order),
        check_order_type(mandate, order),
        check_position_limit(mandate, projection),
        check_gross_exposure(mandate, projection),
        check_daily_loss(mandate, portfolio),
        check_order_count(mandate, portfolio),
        check_session_window(mandate, checked_at),
        check_expiry(mandate, checked_at),
    )
    breaches = tuple(breach for breach in candidates if breach is not None)
    return CheckResult(allowed=not breaches, breaches=breaches, projection=projection)
