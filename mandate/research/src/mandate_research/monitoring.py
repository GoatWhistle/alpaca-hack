from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode

from mandate_research.live_comparison import JsonFetcher, _fetch_json


SNAPSHOTS_ENDPOINT = "https://data.alpaca.markets/v2/stocks/snapshots"
MOVERS_ENDPOINT = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
ACTIVES_ENDPOINT = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
CORPORATE_ACTIONS_ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"
OPTION_CHAIN_ENDPOINT = "https://data.alpaca.markets/v1beta1/options/snapshots"


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _percent(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * Decimal("100")


def _iso_age_seconds(value: Any, now: datetime) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))


def _quality(
    symbol: str,
    snapshot: dict[str, Any],
    *,
    now: datetime,
    max_spread_bps: Decimal,
    min_relative_volume: Decimal,
) -> dict[str, Any]:
    quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
    trade = snapshot.get("latestTrade") if isinstance(snapshot.get("latestTrade"), dict) else {}
    minute = snapshot.get("minuteBar") if isinstance(snapshot.get("minuteBar"), dict) else {}
    daily = snapshot.get("dailyBar") if isinstance(snapshot.get("dailyBar"), dict) else {}
    previous = snapshot.get("prevDailyBar") if isinstance(snapshot.get("prevDailyBar"), dict) else {}
    bid, ask = _decimal(quote.get("bp")), _decimal(quote.get("ap"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None and bid > 0 and ask >= bid else None
    spread_bps = (ask - bid) / mid * Decimal("10000") if mid else None
    current_volume, previous_volume = _decimal(daily.get("v")), _decimal(previous.get("v"))
    relative_volume = current_volume / previous_volume if current_volume is not None and previous_volume else None
    open_price, previous_close = _decimal(daily.get("o")), _decimal(previous.get("c"))
    last = _decimal(trade.get("p")) or _decimal(minute.get("c")) or _decimal(daily.get("c"))
    gap_pct = _percent(open_price - previous_close, previous_close) if open_price is not None and previous_close is not None else None
    intraday_pct = _percent(last - open_price, open_price) if last is not None and open_price is not None else None
    session_change_pct = (
        _percent(last - previous_close, previous_close)
        if last is not None and previous_close is not None
        else None
    )
    ages = [
        age for age in (
            _iso_age_seconds(quote.get("t"), now),
            _iso_age_seconds(trade.get("t"), now),
            _iso_age_seconds(minute.get("t"), now),
        ) if age is not None
    ]
    stale_seconds = max(ages) if ages else None
    failures: list[str] = []
    if spread_bps is None:
        failures.append("missing_spread")
    elif spread_bps > max_spread_bps:
        failures.append("spread")
    if relative_volume is None:
        failures.append("missing_relative_volume")
    elif relative_volume < min_relative_volume:
        failures.append("relative_volume")
    if stale_seconds is None:
        failures.append("missing_timestamp")
    elif stale_seconds > 180:
        failures.append("stale")
    return {
        "symbol": symbol,
        "last": str(last) if last is not None else None,
        "bid": str(bid) if bid is not None else None,
        "ask": str(ask) if ask is not None else None,
        "spread_bps": str(spread_bps.quantize(Decimal("0.01"))) if spread_bps is not None else None,
        "relative_volume": str(relative_volume.quantize(Decimal("0.001"))) if relative_volume is not None else None,
        "gap_pct": str(gap_pct.quantize(Decimal("0.01"))) if gap_pct is not None else None,
        "intraday_pct": str(intraday_pct.quantize(Decimal("0.01"))) if intraday_pct is not None else None,
        "session_change_pct": (
            str(session_change_pct.quantize(Decimal("0.01")))
            if session_change_pct is not None
            else None
        ),
        "vwap": str(_decimal(daily.get("vw"))) if _decimal(daily.get("vw")) is not None else None,
        "stale_seconds": stale_seconds,
        "quality_pass": not failures,
        "quality_failures": failures,
    }


def _safe_fetch(fetcher: JsonFetcher, url: str, headers: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return fetcher(url, headers), {"status": "ok"}
    except Exception as exc:  # Each optional Alpaca surface is isolated.
        return {}, {"status": "error", "error_type": type(exc).__name__}


def collect_market_monitoring(
    *,
    symbols: list[str],
    feed: str = "auto",
    discovery_enabled: bool = True,
    discovery_top: int = 10,
    monitor_corporate_actions: bool = True,
    options_confirmation: bool = False,
    max_spread_bps: str = "35",
    min_relative_volume: str = "0.25",
    now: datetime | None = None,
    fetcher: JsonFetcher = _fetch_json,
) -> dict[str, Any]:
    normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise ValueError("at least one symbol is required")
    if feed not in {"auto", "iex", "sip"}:
        raise ValueError("feed must be auto, iex, or sip")
    key, secret = os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise ValueError("Alpaca paper/data credentials are required")
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}
    trading_base = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
    clock, clock_status = _safe_fetch(fetcher, f"{trading_base}/v2/clock", headers)
    requested_symbols = list(dict.fromkeys([*normalized, "SPY"]))
    selected_feed = "iex" if feed == "auto" else feed
    snapshots_url = SNAPSHOTS_ENDPOINT + "?" + urlencode(
        {"symbols": ",".join(requested_symbols), "feed": selected_feed}
    )
    snapshots_payload, snapshot_status = _safe_fetch(fetcher, snapshots_url, headers)
    snapshots = snapshots_payload.get("snapshots", snapshots_payload)
    if not isinstance(snapshots, dict):
        snapshots = {}
        snapshot_status = {"status": "error", "error_type": "InvalidPayload"}
    spread_limit = _decimal(max_spread_bps)
    minimum_volume = _decimal(min_relative_volume)
    if spread_limit is None or not spread_limit.is_finite() or spread_limit <= 0:
        raise ValueError("max_spread_bps must be a positive finite decimal")
    if minimum_volume is None or not minimum_volume.is_finite() or minimum_volume < 0:
        raise ValueError("min_relative_volume must be a non-negative finite decimal")
    quality = {
        symbol: _quality(
            symbol,
            item if isinstance(item, dict) else {},
            now=checked_at,
            max_spread_bps=spread_limit,
            min_relative_volume=minimum_volume,
        )
        for symbol, item in snapshots.items()
        if symbol in requested_symbols
    }

    discovery: dict[str, Any] = {"enabled": discovery_enabled, "status": "disabled", "movers": {}, "most_active": []}
    if discovery_enabled:
        movers, movers_status = _safe_fetch(
            fetcher, MOVERS_ENDPOINT + "?" + urlencode({"top": discovery_top}), headers
        )
        active, active_status = _safe_fetch(
            fetcher,
            ACTIVES_ENDPOINT + "?" + urlencode({"top": discovery_top, "by": "volume"}),
            headers,
        )
        discovery = {
            "enabled": True,
            "status": "ok" if movers_status["status"] == active_status["status"] == "ok" else "degraded",
            "movers": movers,
            "most_active": active.get("most_actives", []),
            "sources": {"movers": movers_status, "most_active": active_status},
            "observation_only": True,
        }

    corporate_actions: list[dict[str, Any]] = []
    corporate_status: dict[str, Any] = {"status": "disabled"}
    if monitor_corporate_actions:
        corporate_url = CORPORATE_ACTIONS_ENDPOINT + "?" + urlencode(
            {
                "symbols": ",".join(normalized),
                "start": (checked_at.date() - timedelta(days=7)).isoformat(),
                "end": (checked_at.date() + timedelta(days=14)).isoformat(),
                "sort": "desc",
                "limit": 100,
                "data_quality": "all",
            }
        )
        payload, corporate_status = _safe_fetch(fetcher, corporate_url, headers)
        raw_actions = payload.get("corporate_actions", payload.get("corporateActions", []))
        if isinstance(raw_actions, list):
            corporate_actions = [item for item in raw_actions if isinstance(item, dict)]
        elif isinstance(raw_actions, dict):
            corporate_actions = [
                {"type": action_type, **item}
                for action_type, items in raw_actions.items()
                if isinstance(items, list)
                for item in items
                if isinstance(item, dict)
            ]

    option_confirmation: dict[str, Any] = {"enabled": options_confirmation, "status": "disabled"}
    if options_confirmation:
        option_confirmation = {"enabled": True, "status": "ok", "symbols": {}}
        for symbol in normalized:
            option_url = f"{OPTION_CHAIN_ENDPOINT}/{symbol}?" + urlencode(
                {"feed": "indicative", "limit": 100}
            )
            payload, status = _safe_fetch(fetcher, option_url, headers)
            snapshots_map = payload.get("snapshots", {})
            contracts = list(snapshots_map.values()) if isinstance(snapshots_map, dict) else []
            option_confirmation["symbols"][symbol] = {
                **status,
                "contract_count": len(contracts),
                "with_greeks": sum(
                    1 for item in contracts if isinstance(item, dict) and isinstance(item.get("greeks"), dict)
                ),
            }
        if any(item.get("status") != "ok" for item in option_confirmation["symbols"].values()):
            option_confirmation["status"] = "degraded"

    spy = quality.get("SPY", {})
    return {
        "checked_at": checked_at.isoformat(),
        "symbols": normalized,
        "feed": selected_feed,
        "feed_requested": feed,
        "sources": {"clock": clock_status, "snapshots": snapshot_status, "corporate_actions": corporate_status},
        "market_is_open": clock.get("is_open") is True,
        "quality": quality,
        "benchmark": {"symbol": "SPY", **spy},
        "discovery": discovery,
        "corporate_actions": corporate_actions,
        "options_confirmation": option_confirmation,
    }
