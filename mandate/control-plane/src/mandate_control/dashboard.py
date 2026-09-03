from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import yaml
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from mandate_control.autonomy import AutonomyStore
from mandate_control.env import load_workspace_env


DEFAULT_TRUEFORGE_URL = "http://localhost:8790"
DEFAULT_RESEARCH_URL = "http://127.0.0.1:8020/mcp"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
APPROVABLE_TOOL_NAMES = frozenset({"append_trader_memory"})
TIMELINE_KINDS = frozenset({
    "trigger", "news", "reasoning", "tool_call", "tool_result",
    "critics", "plan", "execution", "risk_exit", "session",
})
TIMELINE_STATUSES = frozenset({"ok", "parked", "submitted", "degraded"})
NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_STARTING_EQUITY = Decimal("100000")
# The runner heartbeats every poll; a heartbeat older than this many polls
# (never less than two minutes) means the process is dead or wedged.
STALE_HEARTBEAT_POLLS = 3
STALE_HEARTBEAT_MIN_SECONDS = 120


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating `Z` and nanosecond fractions."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _starting_equity() -> Decimal:
    raw = os.environ.get("MANDATE_STARTING_EQUITY", "").strip()
    if not raw:
        return DEFAULT_STARTING_EQUITY
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return DEFAULT_STARTING_EQUITY
    return value if value.is_finite() and value > 0 else DEFAULT_STARTING_EQUITY


def _position_exit_policy(asset_class: str) -> dict[str, str]:
    if asset_class == "us_option":
        return {
            "stop": f"-{os.environ.get('MANDATE_OPTION_STOP_LOSS_PCT', '25')}% unrealized P&L",
            "target": f"+{os.environ.get('MANDATE_OPTION_PROFIT_TARGET_PCT', '40')}% unrealized P&L",
            "time_stop": f"{os.environ.get('MANDATE_OPTION_TIME_STOP_MINUTES', '180')}m in the dead band",
            "expiry": f"close at DTE <= {os.environ.get('MANDATE_OPTION_EXIT_DTE', '2')}",
            "flatten": "mandatory 15:50 ET session flatten",
            "review": "every scheduled pass and realtime risk wake",
        }
    return {
        "stop": f"{os.environ.get('MANDATE_EXIT_STOP_ATR', '0.90')}x ATR14 adverse move",
        "target": f"{os.environ.get('MANDATE_EXIT_TARGET_ATR', '1.50')}x ATR14 favorable move",
        "time_stop": (
            f"{os.environ.get('MANDATE_EXIT_TIME_STOP_MINUTES', '45')}m if still within "
            f"{os.environ.get('MANDATE_EXIT_DEAD_POSITION_ATR', '0.25')}x ATR14 of entry"
        ),
        "flatten": "mandatory 15:50 ET session flatten",
        "review": "every scheduled pass and realtime risk wake",
    }


def _pending_order(item: dict[str, Any]) -> dict[str, Any]:
    """Project a raw Alpaca order onto the fields the console renders."""
    legs = item.get("legs")
    return {
        "id": item.get("id"),
        "symbol": item.get("symbol") or "",
        "side": item.get("side"),
        "qty": item.get("qty"),
        "filled_qty": item.get("filled_qty"),
        "type": item.get("type") or item.get("order_type"),
        "order_class": item.get("order_class"),
        "limit_price": item.get("limit_price"),
        "status": item.get("status"),
        "submitted_at": item.get("submitted_at"),
        "legs": len(legs) if isinstance(legs, list) else 0,
        "asset_class": item.get("asset_class") or "us_equity",
    }


class BrokerReader(Protocol):
    async def read(self) -> tuple[dict[str, Any], dict[str, Any]]: ...


class ApprovalsReader(Protocol):
    async def read(self) -> dict[str, Any]: ...


class AlpacaPaperReader:
    """Build the dashboard snapshot directly from the Alpaca paper Trading API."""

    def __init__(
        self,
        mandate_path: Path,
        journal_path: Path,
        *,
        timeout: float = 8.0,
        cache_seconds: float = 3.0,
    ) -> None:
        base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "paper-api.alpaca.markets"
            or parsed.port is not None
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("ALPACA_BASE_URL must be the official HTTPS Alpaca paper endpoint")
        self.base_url = "https://paper-api.alpaca.markets"
        self.mandate_path = mandate_path
        self.journal_path = journal_path
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, tuple[dict[str, Any], dict[str, Any]]] | None = None
        self._lock = asyncio.Lock()
        self._orders_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._orders_lock = asyncio.Lock()

    def _connection(self) -> tuple[dict[str, str], str | None]:
        key = os.environ.get("ALPACA_API_KEY", "")
        secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            raise ValueError("Alpaca paper credentials are required")
        headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        }
        proxy = None
        if os.environ.get("MANDATE_USE_ALPACA_PROXY", "false").lower() == "true":
            proxy = os.environ.get("ALPACA_PROXY_URL") or None
            if proxy is None:
                raise ValueError("ALPACA_PROXY_URL is required when the Alpaca proxy is enabled")
        return headers, proxy

    async def read_trade_orders(self) -> list[dict[str, Any]]:
        """Return complete broker order history, stripped of irrelevant fields."""
        cached = self._orders_cache
        if cached is not None and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        async with self._orders_lock:
            cached = self._orders_cache
            if cached is not None and time.monotonic() - cached[0] < self.cache_seconds:
                return cached[1]
            headers, proxy = self._connection()
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                proxy=proxy,
                trust_env=False,
            ) as client:
                raw_orders: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                until: str | None = None
                for _page in range(100):
                    params = {
                        "status": "all", "direction": "desc", "limit": 500, "nested": "true",
                    }
                    if until is not None:
                        params["until"] = until
                    response = await client.get("/v2/orders", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                        raise RuntimeError("Alpaca paper returned invalid order history")
                    for item in payload:
                        order_id = str(item.get("id") or "")
                        if order_id and order_id in seen_ids:
                            continue
                        if order_id:
                            seen_ids.add(order_id)
                        raw_orders.append(item)
                    if len(payload) < 500:
                        break
                    timestamps = [
                        str(item["submitted_at"])
                        for item in payload
                        if item.get("submitted_at")
                    ]
                    next_until = min(timestamps) if timestamps else None
                    if next_until is None or next_until == until:
                        raise RuntimeError("Alpaca paper order-history cursor did not advance")
                    until = next_until
                else:
                    raise RuntimeError("Alpaca paper order history exceeds the 50000-order safety bound")

            def project(item: dict[str, Any]) -> dict[str, Any]:
                legs = item.get("legs")
                return {
                    "id": item.get("id"),
                    "client_order_id": item.get("client_order_id"),
                    "replaces": item.get("replaces"),
                    "replaced_by": item.get("replaced_by"),
                    "symbol": item.get("symbol"),
                    "asset_class": item.get("asset_class"),
                    "side": item.get("side"),
                    "position_intent": item.get("position_intent"),
                    "ratio_qty": item.get("ratio_qty"),
                    "qty": item.get("qty"),
                    "filled_qty": item.get("filled_qty"),
                    "filled_avg_price": item.get("filled_avg_price"),
                    "order_class": item.get("order_class"),
                    "status": item.get("status"),
                    "submitted_at": item.get("submitted_at"),
                    "filled_at": item.get("filled_at"),
                    "legs": [project(leg) for leg in legs if isinstance(leg, dict)]
                    if isinstance(legs, list) else [],
                }

            result = [project(item) for item in raw_orders]
            self._orders_cache = (time.monotonic(), result)
            return result

    async def read(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Serve one broker read per cache window, shared across concurrent tabs."""
        cached = self._cache
        if cached is not None and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        async with self._lock:
            cached = self._cache
            if cached is not None and time.monotonic() - cached[0] < self.cache_seconds:
                return cached[1]
            result = await self._read_uncached()
            self._cache = (time.monotonic(), result)
            return result

    async def _read_uncached(self) -> tuple[dict[str, Any], dict[str, Any]]:
        headers, proxy = self._connection()
        # Order budgets are trading-day limits: count from New York midnight,
        # and ask Alpaca for that window only instead of the last 500 orders.
        now_utc = datetime.now(timezone.utc)
        trading_date = now_utc.astimezone(NEW_YORK).date()
        day_start = datetime.combine(trading_date, datetime.min.time(), tzinfo=NEW_YORK)
        after = day_start.astimezone(timezone.utc).isoformat()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            proxy=proxy,
            trust_env=False,
        ) as client:
            responses = await asyncio.gather(
                client.get("/v2/account"),
                client.get("/v2/positions"),
                client.get(
                    "/v2/orders",
                    params={"status": "all", "direction": "desc", "limit": 500, "after": after},
                ),
                client.get(
                    "/v2/orders",
                    params={"status": "open", "direction": "desc", "limit": 500, "nested": "true"},
                ),
                client.get("/v2/clock"),
            )
        for response in responses:
            response.raise_for_status()
        account = responses[0].json()
        positions_raw = responses[1].json()
        orders = responses[2].json()
        pending = responses[3].json()
        clock = responses[4].json()
        if not isinstance(account, dict) or not isinstance(positions_raw, list):
            raise RuntimeError("Alpaca paper returned an invalid account snapshot")
        equity = Decimal(str(account.get("equity", "0")))
        last_equity = Decimal(str(account.get("last_equity", equity)))
        starting_equity = _starting_equity()
        total_pnl = equity - starting_equity
        total_pnl_pct = total_pnl / starting_equity * Decimal("100")
        positions: dict[str, Any] = {}
        gross = Decimal("0")
        largest = Decimal("0")
        for item in positions_raw:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper()
            market_value = abs(Decimal(str(item.get("market_value", "0"))))
            gross += market_value
            largest = max(largest, market_value)
            qty = Decimal(str(item.get("qty", "0") or "0"))
            position = {
                "qty": str(item.get("qty", "0")),
                "side": str(item.get("side") or ("short" if qty < 0 else "long")),
                "asset_class": str(item.get("asset_class") or "us_equity"),
                "market_price": str(item.get("current_price", "0")),
                "market_value": str(item.get("market_value", "0")),
                "avg_entry_price": item.get("avg_entry_price"),
                "unrealized_pl": item.get("unrealized_pl"),
                "unrealized_plpc": item.get("unrealized_plpc"),
                "exit_policy": _position_exit_policy(str(item.get("asset_class") or "us_equity")),
            }
            if item.get("qty_available") is not None:
                position["qty_available"] = str(item.get("qty_available"))
            positions[symbol] = position
        gross_pct = gross / equity * Decimal("100") if equity else Decimal("0")
        largest_pct = largest / equity * Decimal("100") if equity else Decimal("0")
        daily_pnl = equity - last_equity
        local = _read_yaml(self.mandate_path)
        limits = local.get("limits", {}) if isinstance(local.get("limits"), dict) else {}
        now = now_utc.isoformat()
        orders_today = 0
        if isinstance(orders, list):
            for item in orders:
                if not isinstance(item, dict):
                    continue
                submitted = _parse_timestamp(item.get("submitted_at"))
                if submitted is not None and submitted.astimezone(NEW_YORK).date() == trading_date:
                    orders_today += 1
        pending_orders = [
            _pending_order(item) for item in pending if isinstance(item, dict)
        ] if isinstance(pending, list) else []
        mandate_state = {
            "mandate": local,
            "as_of": now,
            "market_is_open": bool(clock.get("is_open")) if isinstance(clock, dict) else False,
            "account": {"equity": str(equity)},
            "usage": {
                "max_position_pct": str(largest_pct),
                "gross_exposure_pct": str(gross_pct),
                "daily_loss_pct": str(max(Decimal("0"), -daily_pnl / last_equity * Decimal("100"))) if last_equity else "0",
                "orders_today": orders_today,
            },
            "headroom": {
                "buying_power": str(account.get("buying_power", "0")),
            },
            "wake_triggers": [],
            "active_predecisions": [],
        }
        session_state = {
            "as_of": now,
            "account": {
                "status": account.get("status"),
                "equity": str(equity),
                "last_equity": str(last_equity),
                "daily_pnl": str(daily_pnl),
                "starting_equity": str(starting_equity),
                "total_pnl": str(total_pnl),
                "total_pnl_pct": str(total_pnl_pct.quantize(Decimal("0.01"))),
                "gross_exposure_pct": str(gross_pct),
                "buying_power": str(account.get("buying_power", "0")),
                "options_approved_level": account.get("options_approved_level"),
            },
            "market": {
                "is_open": bool(clock.get("is_open")) if isinstance(clock, dict) else False,
                "clock_timestamp": clock.get("timestamp") if isinstance(clock, dict) else None,
            },
            "positions": positions,
            "orders_today": orders_today,
            "pending_orders": pending_orders,
            "journal": _read_journal(self.journal_path),
        }
        return mandate_state, session_state


def _pending_approvals(
    sessions: list[dict[str, Any]],
    events_by_session: dict[str, list[dict[str, Any]]],
    turns_by_session: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Derive awaiting-human approvals from TrueForge session events and turn inputs.

    A `tool.approval_required` tool call is pending until a later turn carries a
    `user.tool_approval` input for it (allow or deny) or a `tool.response` event shows
    the call already executed.
    """
    items: list[dict[str, Any]] = []
    for session in sessions:
        session_id = str(session.get("id", ""))
        if not session_id:
            continue
        events = events_by_session.get(session_id, [])
        model_messages: dict[str, dict[str, Any]] = {}
        executed: set[str] = set()
        approval_events: list[tuple[dict[str, Any], str]] = []
        for item in events:
            event = item.get("event") if isinstance(item, dict) else None
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "model.message":
                event_id = str(event.get("id", ""))
                if event_id:
                    model_messages[event_id] = event
            elif event_type == "tool.response":
                call_id = str(event.get("tool_call_id", ""))
                if call_id:
                    executed.add(call_id)
            elif event_type == "tool.approval_required":
                approval_events.append((event, str(item.get("turn_id", ""))))
        if not approval_events:
            continue
        answered: set[str] = set()
        for turn in turns_by_session.get(session_id, []):
            for input_item in turn.get("input") or []:
                if isinstance(input_item, dict) and input_item.get("type") == "user.tool_approval":
                    call_id = str(input_item.get("tool_call_id") or input_item.get("toolCallId") or "")
                    if call_id:
                        answered.add(call_id)
        for event, turn_id in approval_events:
            for ref in event.get("tool_calls") or []:
                if not isinstance(ref, dict):
                    continue
                call_id = str(ref.get("id", ""))
                if not call_id or call_id in answered or call_id in executed:
                    continue
                tool_name = ""
                arguments: Any = None
                source = model_messages.get(str(ref.get("source_event_id", "")))
                for call in (source or {}).get("tool_calls") or []:
                    if not isinstance(call, dict) or str(call.get("id", "")) != call_id:
                        continue
                    function = call.get("function") if isinstance(call.get("function"), dict) else {}
                    tool_name = str(function.get("name", ""))
                    arguments = _parse_tool_arguments(function.get("arguments"))
                    break
                if tool_name not in APPROVABLE_TOOL_NAMES:
                    continue
                items.append(
                    {
                        "session_id": session_id,
                        "session_title": session.get("title") or "",
                        "turn_id": turn_id,
                        "tool_call_id": call_id,
                        "thread_id": str(event.get("thread_id", "")),
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "created_at": event.get("created_at"),
                    }
                )
    return items


def _parse_tool_arguments(raw: Any) -> Any:
    if not isinstance(raw, str) or not raw.strip():
        return raw if isinstance(raw, (dict, type(None))) else None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return decoded if isinstance(decoded, dict) else raw


class TrueForgeApprovalsReader:
    """Reads pending tool approvals from the local TrueForge server (fail-soft)."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        agent_name: str = "",
        timeout: float = 3.0,
        session_limit: int = 8,
        event_limit: int = 100,
        turn_limit: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.agent_name = agent_name
        self.timeout = timeout
        self.session_limit = session_limit
        self.event_limit = event_limit
        self.turn_limit = turn_limit

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def read(self) -> dict[str, Any]:
        if not self.base_url:
            return {"count": 0, "items": []}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, headers=self._headers(), timeout=self.timeout
            ) as client:
                payload = await self._get(
                    client, "/api/v1/sessions", {"order": "desc", "limit": self.session_limit}
                )
                sessions = [item for item in payload.get("data", []) if isinstance(item, dict)]
                if self.agent_name:
                    sessions = [
                        session
                        for session in sessions
                        if isinstance(session.get("agent"), dict)
                        and session["agent"].get("name") == self.agent_name
                    ]
                sessions.sort(key=lambda session: str(session.get("updated_at", "")), reverse=True)
                events_by_session: dict[str, list[dict[str, Any]]] = {}
                for session in sessions:
                    session_id = str(session.get("id", ""))
                    if not session_id:
                        continue
                    events_payload = await self._get(
                        client,
                        f"/api/v1/sessions/{session_id}/events",
                        {"order": "asc", "limit": self.event_limit},
                    )
                    events_by_session[session_id] = [
                        item for item in events_payload.get("data", []) if isinstance(item, dict)
                    ]
                turns_by_session: dict[str, list[dict[str, Any]]] = {}
                for session_id, events in events_by_session.items():
                    has_approval = any(
                        isinstance(item.get("event"), dict)
                        and item["event"].get("type") == "tool.approval_required"
                        for item in events
                    )
                    if not has_approval:
                        continue
                    turns_payload = await self._get(
                        client,
                        f"/api/v1/sessions/{session_id}/turns",
                        {"order": "desc", "limit": self.turn_limit},
                    )
                    turns_by_session[session_id] = [
                        item for item in turns_payload.get("data", []) if isinstance(item, dict)
                    ]
            items = _pending_approvals(sessions, events_by_session, turns_by_session)
            return {"count": len(items), "items": items}
        except Exception as exc:  # Approvals are auxiliary; never break the snapshot.
            return {"count": 0, "items": [], "error": f"trueforge approvals unavailable: {type(exc).__name__}"}


def _approval_turn_body(
    *,
    thread_id: str,
    tool_call_id: str,
    approve: bool,
    reason: str = "",
) -> dict[str, Any]:
    approval: dict[str, Any] = {"status": "allow"} if approve else {"status": "deny"}
    if not approve and reason:
        approval["reason"] = reason
    return {
        "input": [
            {
                "type": "user.tool_approval",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id,
                "approval": approval,
            }
        ],
        "previous_turn_id": "auto",
    }


def _wire_payload(value: Any) -> Any:
    """Normalize typed MCP values before handing them to Starlette's JSON encoder."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _wire_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire_payload(item) for item in value]
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"cannot read mandate: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("mandate must be a YAML object")
    return payload


def _read_journal(
    path: Path, *, limit: int = 100, errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read the tail of an append-only JSONL file.

    The runner appends without a rename, so the final line may be half-written
    while the dashboard polls; that tail is skipped silently. Any other
    unreadable line is skipped and reported through `errors` instead of hiding
    the whole journal behind one bad record.
    """
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read journal: {type(exc).__name__}") from exc
    lines = content.splitlines()
    skipped = 0
    for line_number, line in enumerate(lines[-limit:], start=max(1, len(lines) - limit + 1)):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            if line_number == len(lines) and not content.endswith("\n"):
                break
            skipped += 1
            continue
        if isinstance(item, dict):
            entries.append(item)
    if skipped and errors is not None:
        errors.append(f"{path.name}: skipped {skipped} unreadable line(s)")
    return entries


def _read_outcomes(path: Path) -> dict[str, Any]:
    """Ship only the aggregate scorecard; the raw records are megabytes per poll."""
    payload = _read_json(path)
    return {key: payload[key] for key in ("updated_at", "scorecard") if key in payload}


def _runtime_staleness(
    runtime: dict[str, Any], trajectory: dict[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    """Annotate the persisted runner state with whether its heartbeat is fresh."""
    current = now or datetime.now(timezone.utc)
    status = str(runtime.get("status", "not_started"))
    heartbeat = _parse_timestamp(runtime.get("heartbeat_at"))
    poll_seconds = trajectory.get("news_poll_seconds")
    try:
        poll = int(poll_seconds) if poll_seconds is not None else 30
    except (TypeError, ValueError):
        poll = 30
    threshold = max(STALE_HEARTBEAT_MIN_SECONDS, STALE_HEARTBEAT_POLLS * max(1, poll))
    if heartbeat is None:
        return {
            **runtime,
            "stale": status != "not_started",
            "stale_seconds": None,
            "stale_threshold_seconds": threshold,
        }
    age = max(0, int((current - heartbeat).total_seconds()))
    return {
        **runtime,
        "stale": age > threshold,
        "stale_seconds": age,
        "stale_threshold_seconds": threshold,
    }


def _read_timeline(
    path: Path,
    *,
    after: int = 0,
    limit: int = 200,
    trading_date: str | None = None,
    latest: int | None = None,
) -> dict[str, Any]:
    """Read the append-only trader projection with a stable sequence cursor.

    `latest=N` returns the newest N matching items (still ascending) without
    paging through the whole journal; `after` is ignored in that mode.
    """
    if not path.exists():
        entries: list[dict[str, Any]] = []
    else:
        try:
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
        except OSError as exc:
            raise RuntimeError(f"cannot read trader timeline: {type(exc).__name__}") from exc
        entries = []
        previous_sequence = 0
        required = {
            "schema", "sequence", "at", "trading_date", "kind", "status",
            "session_id", "summary", "details",
        }
        for line_number, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                if line_number == len(lines) and not content.endswith("\n"):
                    break
                raise RuntimeError(f"invalid trader timeline at line {line_number}") from exc
            valid = (
                isinstance(entry, dict)
                and set(entry) == required
                and entry.get("schema") == "trader.timeline.v1"
                and isinstance(entry.get("sequence"), int)
                and not isinstance(entry.get("sequence"), bool)
                and entry["sequence"] > previous_sequence
                and entry.get("kind") in TIMELINE_KINDS
                and entry.get("status") in TIMELINE_STATUSES
                and isinstance(entry.get("summary"), str)
                and bool(entry["summary"].strip())
                and isinstance(entry.get("details"), dict)
                and (entry.get("session_id") is None or isinstance(entry.get("session_id"), str))
                and isinstance(entry.get("trading_date"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["trading_date"]) is not None
                and isinstance(entry.get("at"), str)
            )
            if not valid:
                raise RuntimeError(f"invalid trader timeline contract at line {line_number}")
            try:
                parsed_at = datetime.fromisoformat(entry["at"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise RuntimeError(f"invalid trader timeline timestamp at line {line_number}") from exc
            if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
                raise RuntimeError(f"invalid trader timeline timestamp at line {line_number}")
            previous_sequence = entry["sequence"]
            entries.append(entry)
    items: list[dict[str, Any]] = []
    for entry in entries:
        sequence = entry.get("sequence")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or (latest is None and sequence <= after)
        ):
            continue
        if trading_date is not None and entry.get("trading_date") != trading_date:
            continue
        items.append(entry)
        if latest is not None:
            if len(items) > latest:
                items.pop(0)
            continue
        if len(items) >= limit:
            break
    next_after = items[-1]["sequence"] if items else after
    return {
        "schema": "trader.timeline.page.v1",
        "items": items,
        "next_after": next_after,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {path.name}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object")
    return payload


async def _service_status(name: str, url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if host is None:
        return {"name": name, "url": url, "ok": False}
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.8)
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return {"name": name, "url": url, "ok": False}
    return {"name": name, "url": url, "ok": True}


async def build_snapshot(
    *,
    broker: BrokerReader,
    mandate_path: Path,
    journal_path: Path,
    service_urls: dict[str, str],
    approvals_reader: ApprovalsReader | None = None,
    trajectory_path: Path | None = None,
    runtime_path: Path | None = None,
    alerts_path: Path | None = None,
    market_path: Path | None = None,
    outcomes_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    local_mandate: dict[str, Any] = {}
    local_journal: list[dict[str, Any]] = []
    try:
        local_mandate = _read_yaml(mandate_path)
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        local_journal = _read_journal(journal_path, errors=errors)
    except RuntimeError as exc:
        errors.append(str(exc))
    autonomy: dict[str, Any] = {
        "trajectory": {},
        "runtime": {"status": "not_started"},
        "alerts": [],
        "market": {},
        "outcomes": {},
    }
    for key, path, reader in (
        ("trajectory", trajectory_path, _read_json),
        ("runtime", runtime_path, _read_json),
        ("alerts", alerts_path, lambda value: _read_journal(value, limit=50, errors=errors)),
        ("market", market_path, _read_json),
        ("outcomes", outcomes_path, _read_outcomes),
    ):
        if path is None:
            continue
        try:
            payload = reader(path)
            if payload:
                autonomy[key] = payload
        except RuntimeError as exc:
            errors.append(str(exc))
    if runtime_path is not None:
        autonomy["runtime"] = _runtime_staleness(autonomy["runtime"], autonomy["trajectory"])

    statuses_task = asyncio.gather(
        *(_service_status(name, url) for name, url in service_urls.items())
    )
    approvals_task = (
        approvals_reader.read() if approvals_reader is not None else None
    )
    source = "live"
    try:
        # An upstream broker or proxy can stall. Bound the whole account read so
        # one bad network path
        # cannot leave the operator UI waiting indefinitely.
        mandate_state, session_state = await asyncio.wait_for(broker.read(), timeout=8.0)
    except Exception as exc:  # The UI must remain useful while a local service restarts.
        source = "degraded"
        errors.append(f"paper broker unavailable: {type(exc).__name__}")
        mandate_state = {
            "mandate": local_mandate,
            "as_of": None,
            "market_is_open": False,
            "usage": {},
            "headroom": {},
            "wake_triggers": [],
            "active_predecisions": [],
        }
        session_state = {
            "as_of": None,
            "account": {},
            "market": {"is_open": False},
            "positions": {},
            "orders_today": 0,
            "pending_orders": [],
            "journal": local_journal,
        }

    services = await statuses_task
    approvals = (
        await approvals_task
        if approvals_task is not None
        else {"count": 0, "items": []}
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "paper_only": True,
        "agent_url": service_urls["trueforge"],
        "mandate": mandate_state,
        "session": session_state,
        "services": services,
        "autonomy": autonomy,
        "approvals": approvals,
        "errors": errors,
    }


def _default_paths() -> tuple[Path, ...]:
    mandate_root = Path(__file__).resolve().parents[3]
    dist = Path(os.environ.get("MANDATE_DASHBOARD_DIST", mandate_root / "app" / "dist"))
    mandate_path = Path(os.environ.get("MANDATE_PATH", mandate_root / "mandates" / "example.yaml"))
    journal_path = Path(os.environ.get("MANDATE_JOURNAL_PATH", mandate_root / "logs" / "session.jsonl"))
    trajectory_path = Path(
        os.environ.get("MANDATE_TRAJECTORY_PATH", mandate_root / "logs" / "trajectory.json")
    )
    runtime_path = Path(
        os.environ.get(
            "MANDATE_AUTONOMY_RUNTIME_PATH", mandate_root / "logs" / "autonomy-runtime.json"
        )
    )
    alerts_path = Path(
        os.environ.get("MANDATE_ALERTS_PATH", mandate_root / "logs" / "news-alerts.jsonl")
    )
    market_path = Path(
        os.environ.get("MANDATE_MARKET_MONITORING_PATH", mandate_root / "logs" / "market-monitoring.json")
    )
    outcomes_path = Path(
        os.environ.get("MANDATE_FORWARD_OUTCOMES_PATH", mandate_root / "logs" / "forward-outcomes.json")
    )
    timeline_path = Path(
        os.environ.get("MANDATE_TRADER_TIMELINE_PATH", mandate_root / "logs" / "trader-timeline.jsonl")
    )
    return (
        dist, mandate_path, journal_path, trajectory_path, runtime_path,
        alerts_path, market_path, outcomes_path, timeline_path,
    )


def create_dashboard(
    *,
    broker: BrokerReader | None = None,
    approvals_reader: ApprovalsReader | None = None,
    dist_path: Path | None = None,
    mandate_path: Path | None = None,
    journal_path: Path | None = None,
    trajectory_path: Path | None = None,
    runtime_path: Path | None = None,
    alerts_path: Path | None = None,
    market_path: Path | None = None,
    outcomes_path: Path | None = None,
    timeline_path: Path | None = None,
    service_urls: dict[str, str] | None = None,
) -> Starlette:
    (
        default_dist,
        default_mandate,
        default_journal,
        default_trajectory,
        default_runtime,
        default_alerts,
        default_market,
        default_outcomes,
        default_timeline,
    ) = _default_paths()
    urls = service_urls or {
        "trueforge": os.environ.get("TRUEFORGE_BASE_URL", DEFAULT_TRUEFORGE_URL),
        "research": os.environ.get("MANDATE_RESEARCH_URL", DEFAULT_RESEARCH_URL),
    }
    web_root = dist_path or default_dist
    active_mandate = mandate_path or default_mandate
    active_journal = journal_path or default_journal
    active_trajectory = trajectory_path or default_trajectory
    active_runtime = runtime_path or default_runtime
    active_alerts = alerts_path or default_alerts
    active_market = market_path or default_market
    active_outcomes = outcomes_path or default_outcomes
    active_timeline = timeline_path or default_timeline
    reader = broker or AlpacaPaperReader(active_mandate, active_journal)
    active_approvals = approvals_reader or TrueForgeApprovalsReader(
        urls["trueforge"],
        api_key=os.environ.get("TRUEFORGE_API_KEY", ""),
        agent_name=os.environ.get("MANDATE_OPERATOR_AGENT_NAME", "mandate-operator-agent"),
    )
    async def snapshot(request: Request) -> Response:
        payload = await build_snapshot(
            broker=reader,
            mandate_path=active_mandate,
            journal_path=active_journal,
            service_urls=urls,
            approvals_reader=active_approvals,
            trajectory_path=active_trajectory,
            runtime_path=active_runtime,
            alerts_path=active_alerts,
            market_path=active_market,
            outcomes_path=active_outcomes,
        )
        return JSONResponse(
            _wire_payload(payload),
            headers={"Cache-Control": "no-store"},
        )

    async def trader_timeline(request: Request) -> Response:
        try:
            after = int(request.query_params.get("after", "0"))
            limit = int(request.query_params.get("limit", "200"))
            latest_raw = request.query_params.get("latest")
            latest = int(latest_raw) if latest_raw is not None else None
        except ValueError:
            return JSONResponse({"error": "after, limit and latest must be integers"}, status_code=400)
        if after < 0 or not 1 <= limit <= 500:
            return JSONResponse({"error": "after must be nonnegative and limit must be 1..500"}, status_code=400)
        if latest is not None and not 1 <= latest <= 500:
            return JSONResponse({"error": "latest must be 1..500"}, status_code=400)
        trading_date = request.query_params.get("trading_date")
        if trading_date is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", trading_date) is None:
            return JSONResponse({"error": "trading_date must be YYYY-MM-DD"}, status_code=400)
        try:
            page = _read_timeline(
                active_timeline,
                after=after,
                limit=limit,
                trading_date=trading_date,
                latest=latest,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(_wire_payload(page), headers={"Cache-Control": "no-store"})

    async def trade_orders(request: Request) -> Response:
        read_orders = getattr(reader, "read_trade_orders", None)
        if not callable(read_orders):
            return JSONResponse(
                {"schema": "trade.orders.v1", "items": []},
                headers={"Cache-Control": "no-store"},
            )
        try:
            items = await asyncio.wait_for(read_orders(), timeout=10.0)
        except Exception as exc:
            return JSONResponse(
                {"error": f"paper broker order history unavailable: {type(exc).__name__}"},
                status_code=502,
            )
        return JSONResponse(
            _wire_payload({"schema": "trade.orders.v1", "items": items}),
            headers={"Cache-Control": "no-store"},
        )

    async def trader_stream(request: Request) -> Response:
        raw_after = request.query_params.get("after") or request.headers.get("last-event-id", "0")
        try:
            after = int(raw_after)
        except ValueError:
            return JSONResponse({"error": "after must be an integer"}, status_code=400)
        if after < 0:
            return JSONResponse({"error": "after must be nonnegative"}, status_code=400)
        trading_date = request.query_params.get("trading_date")
        if trading_date is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", trading_date) is None:
            return JSONResponse({"error": "trading_date must be YYYY-MM-DD"}, status_code=400)

        async def events() -> AsyncIterator[str]:
            cursor = after
            keepalive_at = time.monotonic()
            yield "retry: 1500\n\n"
            while not await request.is_disconnected():
                try:
                    page = _read_timeline(
                        active_timeline, after=cursor, limit=500, trading_date=trading_date,
                    )
                except RuntimeError as exc:
                    payload = json.dumps({"error": str(exc)}, separators=(",", ":"))
                    yield f"event: stream_error\ndata: {payload}\n\n"
                    await asyncio.sleep(1)
                    continue
                items = page["items"]
                for item in items:
                    cursor = item["sequence"]
                    payload = json.dumps(_wire_payload(item), separators=(",", ":"))
                    yield f"id: {cursor}\nevent: trader_event\ndata: {payload}\n\n"
                now = time.monotonic()
                if not items and now - keepalive_at >= 15:
                    yield ": keepalive\n\n"
                    keepalive_at = now
                await asyncio.sleep(0.5)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def update_trajectory(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse({"error": "application/json required"}, status_code=415)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict) or payload.pop("confirmed", False) is not True:
            return JSONResponse({"error": "explicit confirmation required"}, status_code=409)
        allowed_fields = {
            "enabled", "symbols", "news_poll_seconds", "analysis_interval_minutes", "risk_posture",
            "thesis", "monitoring_mode", "market_data_feed", "discovery_enabled", "discovery_top",
            "regular_hours_only", "max_spread_bps", "min_relative_volume",
            "monitor_corporate_actions", "options_confirmation",
        }
        if set(payload) - allowed_fields:
            return JSONResponse({"error": "unsupported trajectory field"}, status_code=400)
        mandate = _read_yaml(active_mandate)
        universe = mandate.get("universe", [])
        try:
            updated = AutonomyStore(active_trajectory, active_alerts).update(
                mandate_symbols=universe if isinstance(universe, list) else [],
                updated_by="dashboard:operator-confirmed",
                **payload,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_wire_payload(updated.model_dump()), headers={"Cache-Control": "no-store"})

    async def respond_approval(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse({"error": "application/json required"}, status_code=415)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict) or payload.pop("confirmed", False) is not True:
            return JSONResponse({"error": "explicit confirmation required"}, status_code=409)
        session_id = str(payload.get("session_id", ""))
        tool_call_id = str(payload.get("tool_call_id", ""))
        thread_id = str(payload.get("thread_id", ""))
        approve = payload.get("approve")
        reason = str(payload.get("reason", "")).strip()
        if not SESSION_ID_PATTERN.match(session_id):
            return JSONResponse({"error": "valid session_id required"}, status_code=400)
        if not tool_call_id or len(tool_call_id) > 256 or not thread_id or len(thread_id) > 256:
            return JSONResponse({"error": "tool_call_id and thread_id required"}, status_code=400)
        if not isinstance(approve, bool):
            return JSONResponse({"error": "approve must be a boolean"}, status_code=400)
        current = await active_approvals.read()
        matching = next((
            item for item in current.get("items", [])
            if isinstance(item, dict)
            and item.get("session_id") == session_id
            and item.get("tool_call_id") == tool_call_id
            and item.get("thread_id") == thread_id
        ), None)
        if matching is None or matching.get("tool_name") not in APPROVABLE_TOOL_NAMES:
            return JSONResponse(
                {"error": "only a currently pending trader-memory change can be approved"},
                status_code=409,
            )
        body = _approval_turn_body(
            thread_id=thread_id, tool_call_id=tool_call_id, approve=approve, reason=reason
        )
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        api_key = os.environ.get("TRUEFORGE_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        base_url = urls["trueforge"].rstrip("/")
        try:
            async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=8.0) as client:
                response = await client.post(f"/api/v1/sessions/{session_id}/turns", json=body)
        except httpx.HTTPError as exc:
            return JSONResponse(
                {"error": f"trueforge request failed: {type(exc).__name__}"}, status_code=502
            )
        if response.status_code >= 400:
            detail = ""
            try:
                message = response.json().get("error", {}).get("message", "")
                detail = f": {str(message)[:180]}" if message else ""
            except ValueError:
                detail = ""
            return JSONResponse(
                {"error": f"trueforge rejected the approval ({response.status_code}){detail}"},
                status_code=502,
            )
        return JSONResponse({"submitted": True}, headers={"Cache-Control": "no-store"})

    async def index(request: Request) -> Response:
        requested = request.path_params.get("path", "")
        candidate = (web_root / requested).resolve()
        root = web_root.resolve()
        if requested and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        index_file = root / "index.html"
        if index_file.is_file():
            return FileResponse(index_file, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {"error": "dashboard assets are not built", "hint": "cd mandate/app && npm run build"},
            status_code=503,
        )

    routes = [
        Route("/api/snapshot", snapshot),
        Route("/api/trade-history/orders", trade_orders),
        Route("/api/trader/timeline", trader_timeline),
        Route("/api/trader/stream", trader_stream),
        Route("/api/trajectory", update_trajectory, methods=["POST"]),
        Route("/api/approvals/respond", respond_approval, methods=["POST"]),
        Route("/{path:path}", index),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8790", "http://127.0.0.1:8790"],
        # The operator console is also run through Vite's dev/preview servers
        # during local development. Keep CORS loopback-only, but do not couple
        # the API to one frontend port.
        allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?",
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )
    return app


def main() -> None:
    import uvicorn

    load_workspace_env()
    host = os.environ.get("MANDATE_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("MANDATE_DASHBOARD_PORT", "8030"))
    uvicorn.run(create_dashboard(), host=host, port=port)


if __name__ == "__main__":
    main()
