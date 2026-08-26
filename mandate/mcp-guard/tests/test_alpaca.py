from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from mandate_guard.alpaca import AlpacaError, AlpacaPaperClient


def _client(handler) -> AlpacaPaperClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"APCA-API-KEY-ID": "paper-test", "APCA-API-SECRET-KEY": "paper-secret"},
    )
    return AlpacaPaperClient(
        api_key="paper-test",
        secret_key="paper-secret",
        base_url="https://paper-api.alpaca.markets",
        http_client=http,
    )


def test_order_count_paginates_beyond_alpaca_page_limit() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "before_order_id" not in request.url.params:
            page = [
                {
                    "id": f"order-{index}",
                    "submitted_at": "2026-08-26T14:00:00Z",
                }
                for index in range(500)
            ]
            return httpx.Response(200, json=page)
        return httpx.Response(
            200,
            json=[
                {"id": "order-500", "submitted_at": "2026-08-26T13:00:00Z"},
                {"id": "older", "submitted_at": "2026-08-26T03:59:59Z"},
            ],
        )

    client = _client(handler)
    count = asyncio.run(
        client.count_orders_since(datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc))
    )
    assert count == 501
    assert len(calls) == 2
    assert calls[0].url.params["after"].startswith("2026-08-26T04:00:00")
    assert calls[1].url.params["before_order_id"] == "order-499"
    asyncio.run(client._http.aclose())


def test_open_market_order_without_bounded_price_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "open-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": "5",
                    "filled_qty": "1",
                    "limit_price": None,
                    "submitted_at": "2026-08-26T14:00:00Z",
                }
            ],
        )

    client = _client(handler)
    with pytest.raises(AlpacaError, match="no bounded limit price"):
        asyncio.run(client.get_open_orders())
    asyncio.run(client._http.aclose())
