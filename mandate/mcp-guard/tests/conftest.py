from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mandate_guard.checks import OrderIntent, Portfolio, Side
from mandate_guard.mandate import Mandate


@pytest.fixture
def mandate() -> Mandate:
    return Mandate.model_validate(
        {
            "name": "test-mandate",
            "universe": ["AAPL", "MSFT"],
            "instruments": ["equity"],
            "order_types": ["limit"],
            "session": "regular_hours_only",
            "limits": {
                "max_position_pct": "10",
                "max_gross_exposure_pct": "60",
                "max_daily_loss_pct": "2",
                "max_orders_per_day": 20,
            },
            "wake_me_if": ["daily_loss_pct > 1.2"],
            "allow_risk_reducing_market_close": True,
            "expires": "2099-08-28T20:00:00Z",
        }
    )


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio(equity=Decimal("10000"), positions={})


@pytest.fixture
def limit_buy() -> OrderIntent:
    return OrderIntent(
        symbol="AAPL",
        side=Side.BUY,
        qty=Decimal("10"),
        order_type="limit",
        limit_price=Decimal("100"),
    )


@pytest.fixture
def market_open() -> datetime:
    return datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
