from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

import httpx

from mandate_guard.checks import OrderIntent, PendingOrder, Position, Side
from mandate_guard.config import validate_paper_base_url


DATA_BASE_URL = "https://data.alpaca.markets"


class AlpacaError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountSnapshot:
    equity: Decimal
    last_equity: Decimal
    status: str


@dataclass(frozen=True)
class PortfolioSnapshot:
    account: AccountSnapshot
    positions: dict[str, Position]
    orders_today: int
    pending_orders: tuple[PendingOrder, ...] = ()


@dataclass(frozen=True)
class MarketClock:
    timestamp: datetime
    is_open: bool


class AlpacaPaperClient:
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = validate_paper_base_url(base_url)
        if not api_key or not secret_key:
            raise ValueError("Alpaca paper credentials are required")
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AlpacaError(f"Alpaca paper request failed: {type(exc).__name__}") from exc
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AlpacaError("Alpaca returned invalid JSON") from exc

    async def get_account(self) -> AccountSnapshot:
        data = await self._request("GET", f"{self.base_url}/v2/account")
        return AccountSnapshot(
            equity=Decimal(str(data["equity"])),
            last_equity=Decimal(str(data["last_equity"])),
            status=str(data["status"]),
        )

    async def get_positions(self) -> dict[str, Position]:
        data = await self._request("GET", f"{self.base_url}/v2/positions")
        return {
            str(item["symbol"]).upper(): Position(
                qty=Decimal(str(item["qty"])),
                market_price=Decimal(str(item["current_price"])),
                change_today_pct=Decimal(str(item.get("change_today", "0"))) * Decimal("100"),
            )
            for item in data
        }

    async def _all_orders(self, *, status: str, after: datetime | None = None) -> list[Mapping[str, Any]]:
        params: dict[str, Any] = {"status": status, "direction": "desc", "limit": 500}
        if after is not None:
            params["after"] = after.isoformat()
        orders: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        while True:
            page = await self._request("GET", f"{self.base_url}/v2/orders", params=params)
            if not isinstance(page, list):
                raise AlpacaError("Alpaca orders response must be a list")
            if after is not None and "before_order_id" in params:
                page = [item for item in page if _order_timestamp(item) > after]
            orders.extend(page)
            if len(page) < 500:
                return orders
            cursor = str(page[-1].get("id", ""))
            if not cursor or cursor in seen_cursors:
                raise AlpacaError("Alpaca order pagination did not advance")
            seen_cursors.add(cursor)
            params = {
                "status": status,
                "direction": "desc",
                "limit": 500,
                "before_order_id": cursor,
            }

    async def count_orders_since(self, since: datetime) -> int:
        return len(await self._all_orders(status="all", after=since))

    async def get_open_orders(self) -> tuple[PendingOrder, ...]:
        orders = await self._all_orders(status="open")
        pending: list[PendingOrder] = []
        for item in orders:
            remaining = Decimal(str(item["qty"])) - Decimal(str(item.get("filled_qty", "0")))
            if remaining <= 0:
                continue
            raw_price = item.get("limit_price") or item.get("stop_price") or item.get("hwm")
            if raw_price is None:
                raise AlpacaError("open order has no bounded reference price; refusing risk projection")
            pending.append(
                PendingOrder(
                    symbol=str(item["symbol"]),
                    side=Side(str(item["side"])),
                    remaining_qty=remaining,
                    reference_price=Decimal(str(raw_price)),
                )
            )
        return tuple(pending)

    async def get_market_clock(self) -> MarketClock:
        data = await self._request("GET", f"{self.base_url}/v2/clock")
        timestamp = datetime.fromisoformat(str(data["timestamp"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise AlpacaError("Alpaca market clock timestamp is timezone-naive")
        return MarketClock(timestamp=timestamp, is_open=bool(data["is_open"]))

    async def get_latest_trade_price(self, symbol: str) -> Decimal:
        data = await self._request(
            "GET",
            f"{DATA_BASE_URL}/v2/stocks/{symbol}/trades/latest",
            params={"feed": "iex"},
        )
        return Decimal(str(data["trade"]["p"]))

    async def submit_order(self, order: OrderIntent, *, client_order_id: str) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": str(order.qty),
            "type": order.order_type,
            "time_in_force": "day",
            "extended_hours": False,
            "client_order_id": client_order_id,
        }
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)
        return await self._request("POST", f"{self.base_url}/v2/orders", json=payload)

    async def find_order_by_client_id(self, client_order_id: str) -> Mapping[str, Any] | None:
        try:
            return await self._request(
                "GET",
                f"{self.base_url}/v2/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
            )
        except AlpacaError as exc:
            cause = exc.__cause__
            if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404:
                return None
            raise

    async def get_order_by_id(self, order_id: str) -> Mapping[str, Any]:
        return await self._request("GET", f"{self.base_url}/v2/orders/{order_id}")

    async def cancel_order(self, order_id: str) -> None:
        await self._request("DELETE", f"{self.base_url}/v2/orders/{order_id}")

    async def close_position(self, symbol: str, qty: Decimal) -> Mapping[str, Any]:
        return await self._request(
            "DELETE",
            f"{self.base_url}/v2/positions/{symbol.upper()}",
            params={"qty": str(qty)},
        )


def _order_timestamp(item: Mapping[str, Any]) -> datetime:
    value = datetime.fromisoformat(str(item["submitted_at"]).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlpacaError("Alpaca order timestamp is timezone-naive")
    return value
