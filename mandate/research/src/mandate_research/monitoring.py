from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from mandate_research.features import top_of_book_imbalance
from mandate_research.live_comparison import JsonFetcher, _fetch_json


SNAPSHOTS_ENDPOINT = "https://data.alpaca.markets/v2/stocks/snapshots"
MOVERS_ENDPOINT = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
ACTIVES_ENDPOINT = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
CORPORATE_ACTIONS_ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"
OPTION_CHAIN_ENDPOINT = "https://data.alpaca.markets/v1beta1/options/snapshots"
NASDAQ_IPO_CALENDAR_ENDPOINT = "https://api.nasdaq.com/api/ipo/calendar"
NEW_YORK = ZoneInfo("America/New_York")
MACRO_MOVE_THRESHOLD_PCT = Decimal("0.60")
IPO_LOOKBACK_DAYS = 45
MAX_IPO_CANDIDATES = 10
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
VOLUME_CURVE = (
    (0, Decimal("0.010")),
    (5, Decimal("0.040")),
    (15, Decimal("0.090")),
    (30, Decimal("0.150")),
    (60, Decimal("0.250")),
    (120, Decimal("0.420")),
    (180, Decimal("0.560")),
    (270, Decimal("0.740")),
    (330, Decimal("0.870")),
    (390, Decimal("1.000")),
)


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


def _expected_volume_fraction(now: datetime) -> tuple[Decimal | None, str]:
    """Approximate cumulative regular-session volume using a deterministic U-shaped curve."""
    local = now.astimezone(NEW_YORK)
    elapsed = (local.hour * 60 + local.minute) - (9 * 60 + 30)
    if elapsed < 0:
        return None, "pre_market"
    if elapsed >= 390:
        return Decimal("1"), "full_session"
    for (left_minute, left_fraction), (right_minute, right_fraction) in zip(
        VOLUME_CURVE, VOLUME_CURVE[1:]
    ):
        if left_minute <= elapsed <= right_minute:
            progress = Decimal(elapsed - left_minute) / Decimal(right_minute - left_minute)
            return left_fraction + (right_fraction - left_fraction) * progress, "time_adjusted"
    return Decimal("1"), "full_session"


def _macro_context(spy: dict[str, Any]) -> dict[str, Any]:
    moves = {
        name: value
        for name in ("session_change_pct", "gap_pct", "intraday_pct")
        if (value := _decimal(spy.get(name))) is not None
    }
    if not moves:
        return {
            "active": False,
            "direction": "neutral",
            "trigger": None,
            "move_pct": None,
            "threshold_pct": str(MACRO_MOVE_THRESHOLD_PCT),
        }
    trigger, move = max(moves.items(), key=lambda item: abs(item[1]))
    active = abs(move) >= MACRO_MOVE_THRESHOLD_PCT
    return {
        "active": active,
        "direction": "risk_on" if active and move > 0 else "risk_off" if active else "neutral",
        "trigger": trigger,
        "move_pct": str(move.quantize(Decimal("0.01"))),
        "threshold_pct": str(MACRO_MOVE_THRESHOLD_PCT),
    }


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
    bid_size, ask_size = _decimal(quote.get("bs")), _decimal(quote.get("as"))
    quote_imbalance = (
        top_of_book_imbalance(bid_size, ask_size)
        if bid_size is not None and ask_size is not None
        else None
    )
    mid = (bid + ask) / 2 if bid is not None and ask is not None and bid > 0 and ask >= bid else None
    spread_bps = (ask - bid) / mid * Decimal("10000") if mid else None
    current_volume, previous_volume = _decimal(daily.get("v")), _decimal(previous.get("v"))
    daily_volume_fraction = current_volume / previous_volume if current_volume is not None and previous_volume else None
    expected_volume_fraction, volume_basis = _expected_volume_fraction(now)
    relative_volume = (
        daily_volume_fraction / expected_volume_fraction
        if daily_volume_fraction is not None and expected_volume_fraction is not None
        and expected_volume_fraction > 0
        else daily_volume_fraction
    )
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
    freshest_seconds = min(ages) if ages else None
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
        "bid_size": str(bid_size) if bid_size is not None else None,
        "ask_size": str(ask_size) if ask_size is not None else None,
        "top_of_book_imbalance": (
            str(quote_imbalance.quantize(Decimal("0.0001")))
            if quote_imbalance is not None else None
        ),
        "spread_bps": str(spread_bps.quantize(Decimal("0.01"))) if spread_bps is not None else None,
        "relative_volume": str(relative_volume.quantize(Decimal("0.001"))) if relative_volume is not None else None,
        "daily_volume_fraction": (
            str(daily_volume_fraction.quantize(Decimal("0.001")))
            if daily_volume_fraction is not None else None
        ),
        "expected_volume_fraction": (
            str(expected_volume_fraction.quantize(Decimal("0.001")))
            if expected_volume_fraction is not None else None
        ),
        "relative_volume_basis": volume_basis,
        "gap_pct": str(gap_pct.quantize(Decimal("0.01"))) if gap_pct is not None else None,
        "intraday_pct": str(intraday_pct.quantize(Decimal("0.01"))) if intraday_pct is not None else None,
        "session_change_pct": (
            str(session_change_pct.quantize(Decimal("0.01")))
            if session_change_pct is not None
            else None
        ),
        "vwap": str(_decimal(daily.get("vw"))) if _decimal(daily.get("vw")) is not None else None,
        "stale_seconds": stale_seconds,
        "freshest_seconds": freshest_seconds,
        "quality_pass": not failures,
        "quality_failures": failures,
    }


def _safe_fetch(fetcher: JsonFetcher, url: str, headers: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return fetcher(url, headers), {"status": "ok"}
    except Exception as exc:  # Each optional Alpaca surface is isolated.
        return {}, {"status": "error", "error_type": type(exc).__name__}


def _looks_like_spac(symbol: str, company: str) -> bool:
    """Reject obvious blank-check vehicles while retaining ordinary companies with 'Capital' names."""
    lowered = company.casefold()
    return (
        symbol.endswith(("U", "W"))
        or "acquisition corp" in lowered
        or "acquisition company" in lowered
        or "blank check" in lowered
    )


def _parse_priced_ipos(
    payloads: list[dict[str, Any]], *, now: datetime, lookback_days: int
) -> list[dict[str, Any]]:
    cutoff = now.date() - timedelta(days=lookback_days)
    candidates: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        priced = data.get("priced") if isinstance(data.get("priced"), dict) else {}
        rows = priced.get("rows") if isinstance(priced.get("rows"), list) else []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("proposedTickerSymbol") or "").strip().upper()
            company = str(raw.get("companyName") or "").strip()
            priced_date = str(raw.get("pricedDate") or "").strip()
            if not TICKER_PATTERN.fullmatch(symbol) or not company or _looks_like_spac(symbol, company):
                continue
            try:
                listing_date = datetime.strptime(priced_date, "%m/%d/%Y").date()
            except ValueError:
                continue
            if listing_date < cutoff or listing_date > now.date():
                continue
            candidates[symbol] = {
                "symbol": symbol,
                "company": company,
                "listing_date": listing_date.isoformat(),
                "days_since_listing": (now.date() - listing_date).days,
                "exchange": str(raw.get("proposedExchange") or "").strip() or None,
                "offer_price": str(raw.get("proposedSharePrice") or "").strip() or None,
                "shares_offered": str(raw.get("sharesOffered") or "").strip() or None,
            }
    return sorted(candidates.values(), key=lambda item: (item["listing_date"], item["symbol"]), reverse=True)


def _ipo_research(
    *,
    checked_at: datetime,
    lookback_days: int,
    trading_base: str,
    selected_feed: str,
    alpaca_headers: dict[str, str],
    max_spread_bps: Decimal,
    min_relative_volume: Decimal,
    fetcher: JsonFetcher,
) -> dict[str, Any]:
    months = sorted({
        checked_at.strftime("%Y-%m"),
        (checked_at - timedelta(days=lookback_days)).strftime("%Y-%m"),
    }, reverse=True)
    nasdaq_headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (compatible; MandateIPOResearch/1.0)",
    }
    calendar_payloads: list[dict[str, Any]] = []
    calendar_statuses: list[dict[str, Any]] = []
    for month in months:
        payload, status = _safe_fetch(
            fetcher,
            NASDAQ_IPO_CALENDAR_ENDPOINT + "?" + urlencode({"date": month}),
            nasdaq_headers,
        )
        calendar_payloads.append(payload)
        calendar_statuses.append(status)

    priced = _parse_priced_ipos(calendar_payloads, now=checked_at, lookback_days=lookback_days)
    tradable: list[dict[str, Any]] = []
    asset_errors = 0
    checked_candidates = priced[: MAX_IPO_CANDIDATES * 2]

    def fetch_asset(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        asset, status = _safe_fetch(
            fetcher, f"{trading_base}/v2/assets/{candidate['symbol']}", alpaca_headers
        )
        return candidate, asset, status

    with ThreadPoolExecutor(max_workers=min(10, max(1, len(checked_candidates)))) as executor:
        asset_results = list(executor.map(fetch_asset, checked_candidates))
    for candidate, asset, status in asset_results:
        if status["status"] != "ok":
            asset_errors += 1
            continue
        if asset.get("status") != "active" or asset.get("tradable") is not True:
            continue
        tradable.append({
            **candidate,
            "alpaca": {
                "tradable": True,
                "fractionable": asset.get("fractionable") is True,
                "shortable": asset.get("shortable") is True,
                "easy_to_borrow": asset.get("easy_to_borrow") is True,
            },
        })
        if len(tradable) >= MAX_IPO_CANDIDATES:
            break

    snapshot_status: dict[str, Any] = {"status": "disabled"}
    if tradable:
        symbols = [item["symbol"] for item in tradable]
        url = SNAPSHOTS_ENDPOINT + "?" + urlencode({"symbols": ",".join(symbols), "feed": selected_feed})
        payload, snapshot_status = _safe_fetch(fetcher, url, alpaca_headers)
        snapshots = payload.get("snapshots", payload)
        snapshots = snapshots if isinstance(snapshots, dict) else {}
        for candidate in tradable:
            quality = _quality(
                candidate["symbol"],
                snapshots.get(candidate["symbol"], {}) if isinstance(snapshots.get(candidate["symbol"]), dict) else {},
                now=checked_at,
                max_spread_bps=max_spread_bps,
                min_relative_volume=min_relative_volume,
            )
            change = _decimal(quality.get("session_change_pct"))
            relative_volume = _decimal(quality.get("relative_volume"))
            freshest_seconds = quality.get("freshest_seconds")
            candidate["quality"] = quality
            candidate["execution_ready"] = quality["quality_pass"]
            candidate["research_ready"] = bool(
                change is not None and change != 0
                and relative_volume is not None and relative_volume >= Decimal("1")
                and isinstance(freshest_seconds, int) and freshest_seconds <= 1800
            )
            candidate["research_direction"] = (
                "long" if change is not None and change > 0
                else "short" if change is not None and change < 0 else None
            )
            candidate["research_warnings"] = quality["quality_failures"]

    def rank(item: dict[str, Any]) -> tuple[int, Decimal, Decimal, int]:
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        change = _decimal(quality.get("session_change_pct"))
        return (
            int(item.get("research_ready") is True),
            abs(change) if change is not None else Decimal("-1"),
            _decimal(quality.get("relative_volume")) or Decimal("-1"),
            -int(item["days_since_listing"]),
        )

    tradable.sort(key=rank, reverse=True)
    calendar_ok = all(status["status"] == "ok" for status in calendar_statuses)
    fully_ok = calendar_ok and asset_errors == 0 and snapshot_status.get("status") in {"ok", "disabled"}
    return {
        "enabled": True,
        "status": "ok" if fully_ok else "degraded",
        "observation_only": True,
        "policy": "research_only_until_added_to_trajectory_and_mandate",
        "lookback_days": lookback_days,
        "candidates": tradable,
        "sources": {
            "nasdaq_calendar": {"status": "ok" if calendar_ok else "degraded", "months": months},
            "alpaca_assets": {
                "status": "ok" if asset_errors == 0 else "degraded",
                "checked": len(checked_candidates),
                "tradable": len(tradable),
            },
            "alpaca_snapshots": snapshot_status,
        },
    }


def collect_market_monitoring(
    *,
    symbols: list[str],
    feed: str = "auto",
    discovery_enabled: bool = True,
    discovery_top: int = 10,
    ipo_discovery_enabled: bool = True,
    ipo_lookback_days: int = IPO_LOOKBACK_DAYS,
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
    if not 1 <= ipo_lookback_days <= 180:
        raise ValueError("ipo_lookback_days must be between 1 and 180")
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
        discovery["ipos"] = (
            _ipo_research(
                checked_at=checked_at,
                lookback_days=ipo_lookback_days,
                trading_base=trading_base,
                selected_feed=selected_feed,
                alpaca_headers=headers,
                max_spread_bps=spread_limit,
                min_relative_volume=minimum_volume,
                fetcher=fetcher,
            )
            if ipo_discovery_enabled
            else {"enabled": False, "status": "disabled", "candidates": []}
        )
        if discovery["ipos"].get("status") == "degraded":
            discovery["status"] = "degraded"

        # Promote only liquid, fresh, broker-tradable movers into this session's
        # execution universe. The configured trajectory remains the stable seed.
        raw_discovered = [
            item
            for value in (
                movers.get("gainers", []) if isinstance(movers, dict) else [],
                movers.get("losers", []) if isinstance(movers, dict) else [],
                active.get("most_actives", []) if isinstance(active, dict) else [],
            )
            for item in (value if isinstance(value, list) else [])
        ]
        discovered_symbols = list(dict.fromkeys(
            str(item.get("symbol", "")).strip().upper()
            for item in raw_discovered
            if isinstance(item, dict) and str(item.get("symbol", "")).strip()
        ))
        discovered_symbols = [
            symbol for symbol in discovered_symbols
            if symbol not in normalized and symbol != "SPY"
        ][: min(discovery_top, 12)]
        discovered_quality: dict[str, Any] = {}
        if discovered_symbols:
            extra_url = SNAPSHOTS_ENDPOINT + "?" + urlencode(
                {"symbols": ",".join(discovered_symbols), "feed": selected_feed}
            )
            extra_payload, extra_status = _safe_fetch(fetcher, extra_url, headers)
            extra_snapshots = extra_payload.get("snapshots", extra_payload)
            if isinstance(extra_snapshots, dict):
                discovered_quality = {
                    symbol: _quality(
                        symbol,
                        extra_snapshots.get(symbol, {})
                        if isinstance(extra_snapshots.get(symbol), dict) else {},
                        now=checked_at,
                        max_spread_bps=spread_limit,
                        min_relative_volume=max(minimum_volume, Decimal("1.5")),
                    )
                    for symbol in discovered_symbols
                }
                quality.update(discovered_quality)
            discovery.setdefault("sources", {})["candidate_snapshots"] = extra_status
        admitted: list[str] = []
        access: dict[str, Any] = {}
        qualified_symbols = [
            symbol for symbol in discovered_symbols
            if discovered_quality.get(symbol, {}).get("quality_pass") is True
        ]

        def fetch_discovered_asset(symbol: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
            asset, asset_status = _safe_fetch(
                fetcher, f"{trading_base}/v2/assets/{symbol}", headers
            )
            return symbol, asset, asset_status

        with ThreadPoolExecutor(max_workers=min(10, max(1, len(qualified_symbols)))) as executor:
            discovered_assets = list(executor.map(fetch_discovered_asset, qualified_symbols))
        for symbol, asset, asset_status in discovered_assets:
            if (
                asset_status.get("status") != "ok"
                or asset.get("status") != "active"
                or asset.get("tradable") is not True
            ):
                continue
            admitted.append(symbol)
            access[symbol] = {
                "shortable": asset.get("shortable") is True,
                "easy_to_borrow": asset.get("easy_to_borrow") is True,
                "fractionable": asset.get("fractionable") is True,
            }
            if len(admitted) >= 6:
                break
        discovery["observation_only"] = not admitted
        discovery["auto_admitted"] = admitted
        discovery["auto_admitted_access"] = access

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

        def confirm_options(symbol: str) -> tuple[str, dict[str, Any]]:
            option_url = f"{OPTION_CHAIN_ENDPOINT}/{symbol}?" + urlencode(
                {"feed": "indicative", "limit": 100}
            )
            payload, status = _safe_fetch(fetcher, option_url, headers)
            snapshots_map = payload.get("snapshots", {})
            contracts = list(snapshots_map.values()) if isinstance(snapshots_map, dict) else []
            return symbol, {
                **status,
                "contract_count": len(contracts),
                "with_greeks": sum(
                    1 for item in contracts if isinstance(item, dict) and isinstance(item.get("greeks"), dict)
                ),
            }

        with ThreadPoolExecutor(max_workers=min(10, len(normalized))) as executor:
            option_results = list(executor.map(confirm_options, normalized))
        option_confirmation["symbols"] = dict(option_results)
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
        "macro_context": _macro_context(spy),
        "discovery": discovery,
        "corporate_actions": corporate_actions,
        "options_confirmation": option_confirmation,
    }
