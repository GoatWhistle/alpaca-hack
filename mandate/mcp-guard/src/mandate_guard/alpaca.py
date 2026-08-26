from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

import httpx

from mandate_guard.checks import OrderIntent, Position
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
            )
            for item in data
        }

    async def count_orders_since(self, since: datetime) -> int:
        data = await self._request(
            "GET",
            f"{self.base_url}/v2/orders",
            params={"status": "all", "after": since.isoformat(), "limit": 500},
        )
        return len(data)

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

    async def cancel_order(self, order_id: str) -> None:
        await self._request("DELETE", f"{self.base_url}/v2/orders/{order_id}")

    async def close_position(self, symbol: str, qty: Decimal) -> Mapping[str, Any]:
        return await self._request(
            "DELETE",
            f"{self.base_url}/v2/positions/{symbol.upper()}",
            params={"qty": str(qty)},
        )
