from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from mandate_research.live_comparison import ALPACA_BARS_ENDPOINT, JsonFetcher, _fetch_json, _paginated_bars
from mandate_research.monitoring import SNAPSHOTS_ENDPOINT
from mandate_research.signals import PriceBar
from mandate_research.sizing import average_true_range


ZERO = Decimal("0")
NEW_YORK = ZoneInfo("America/New_York")


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be decimal-compatible") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


@dataclass(frozen=True)
class ExitProposal:
    symbol: str
    side: str  # "short" for qty < 0, "long" for qty > 0
    qty: str
    reason: str
    urgency: str  # "immediate" for stops, "normal" for targets and time stops
    entry_price: str
    last_price: str
    atr14: str
    age_minutes: int
    rationale: str
    order_side: str
    limit_price: str


def _parse_tracked_at(value: Any, *, now: datetime) -> datetime:
    if not isinstance(value, str):
        return now
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return now
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return now
    return parsed


def evaluate_position_exits(
    *,
    positions: list[dict[str, Any]],
    last_prices: dict[str, Any],
    atr14: dict[str, Any],
    first_seen: dict[str, Any],
    now: datetime,
    stop_atr: str = "0.90",
    target_atr: str = "1.50",
    time_stop_minutes: int = 45,
    dead_position_atr: str = "0.25",
) -> dict[str, Any]:
    """Deterministic stop/target/time proposals for open positions.

    Proposals only: this module never executes, sizes, or authorizes anything.
    Stops are urgent, profit targets and time stops are normal priority.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    stop_multiple = _decimal(stop_atr, "stop_atr")
    target_multiple = _decimal(target_atr, "target_atr")
    dead_multiple = _decimal(dead_position_atr, "dead_position_atr")
    if stop_multiple <= ZERO or target_multiple <= ZERO:
        raise ValueError("stop and target multiples must be positive")
    if time_stop_minutes <= 0 or dead_multiple < ZERO:
        raise ValueError("time stop must be positive and dead band cannot be negative")

    proposals: list[ExitProposal] = []
    unevaluated: list[dict[str, str]] = []
    tracking: dict[str, str] = {}
    seen_now = now.isoformat()
    market_time = now.astimezone(NEW_YORK)
    session_flatten = (market_time.hour, market_time.minute) >= (15, 50)

    validated: list[tuple[str, Decimal, Decimal]] = []
    for position in positions:
        if not isinstance(position, dict):
            unevaluated.append({"symbol": "", "reason": "invalid_position_object"})
            continue
        symbol = str(position.get("symbol", "")).strip().upper()
        try:
            if not symbol:
                raise ValueError("position symbol cannot be blank")
            qty = _decimal(position.get("qty"), f"{symbol} qty")
            if qty == ZERO:
                continue
            entry = _decimal(position.get("avg_entry_price"), f"{symbol} avg_entry_price")
            if entry <= ZERO:
                raise ValueError(f"{symbol} avg_entry_price must be positive")
        except ValueError as exc:
            unevaluated.append({"symbol": symbol, "reason": f"invalid_position:{str(exc)[:120]}"})
            continue
        validated.append((symbol, qty, entry))

    for symbol, qty, entry in validated:
        tracking[symbol] = str(first_seen.get(symbol) or seen_now)
        if symbol not in last_prices or symbol not in atr14:
            unevaluated.append({"symbol": symbol, "reason": "missing_price_or_atr"})
            continue
        try:
            last = _decimal(last_prices[symbol], f"{symbol} last")
            atr = _decimal(atr14[symbol], f"{symbol} atr14")
        except ValueError as exc:
            unevaluated.append({"symbol": symbol, "reason": f"invalid_market_data:{str(exc)[:120]}"})
            continue
        if last <= ZERO or atr <= ZERO:
            unevaluated.append({"symbol": symbol, "reason": "nonpositive_price_or_atr"})
            continue
        opened_at = _parse_tracked_at(tracking[symbol], now=now)
        age_minutes = max(0, int((now - opened_at).total_seconds() // 60))
        distance = last - entry
        side = "short" if qty < ZERO else "long"

        def propose(reason: str, urgency: str, condition: str) -> ExitProposal:
            order_side = "buy" if side == "short" else "sell"
            marketable_limit = (
                (last * Decimal("1.001")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
                if order_side == "buy"
                else (last * Decimal("0.999")).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
            )
            return ExitProposal(
                symbol=symbol,
                side=side,
                qty=str(abs(qty)),
                reason=reason,
                urgency=urgency,
                entry_price=str(entry),
                last_price=str(last),
                atr14=str(atr),
                age_minutes=age_minutes,
                rationale=f"{reason}: {condition}",
                order_side=order_side,
                limit_price=str(marketable_limit),
            )

        if side == "short":
            if distance >= stop_multiple * atr:
                proposals.append(
                    propose("short_stop", "immediate", f"last {last} >= entry {entry} + {stop_atr}xATR {atr}")
                )
            elif session_flatten:
                proposals.append(
                    propose("session_flatten_1550", "immediate", "intraday mandate flattens at 15:50 ET")
                )
            elif -distance >= target_multiple * atr:
                proposals.append(
                    propose("short_profit_target", "normal", f"last {last} <= entry {entry} - {target_atr}xATR {atr}")
                )
            elif age_minutes >= time_stop_minutes and abs(distance) <= dead_multiple * atr:
                proposals.append(
                    propose("short_time_stop", "normal", f"flat for {age_minutes}m within {dead_multiple}xATR")
                )
        else:
            if -distance >= stop_multiple * atr:
                proposals.append(
                    propose("long_stop", "immediate", f"last {last} <= entry {entry} - {stop_atr}xATR {atr}")
                )
            elif session_flatten:
                proposals.append(
                    propose("session_flatten_1550", "immediate", "intraday mandate flattens at 15:50 ET")
                )
            elif distance >= target_multiple * atr:
                proposals.append(
                    propose("long_profit_target", "normal", f"last {last} >= entry {entry} + {target_atr}xATR {atr}")
                )
            elif age_minutes >= time_stop_minutes and abs(distance) <= dead_multiple * atr:
                proposals.append(
                    propose("long_time_stop", "normal", f"flat for {age_minutes}m within {dead_multiple}xATR")
                )

    return {
        "checked_at": now.isoformat(),
        "proposals": [asdict(proposal) for proposal in proposals],
        "first_seen": tracking,
        "unevaluated": unevaluated,
        "execution_authority": False,
    }


def _bars_to_price_bars(items: list[dict[str, Any]]) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for item in items:
        timestamp = datetime.fromisoformat(str(item["t"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must include a timezone")
        bars.append(
            PriceBar(
                timestamp=timestamp,
                open=Decimal(str(item["o"])),
                high=Decimal(str(item["h"])),
                low=Decimal(str(item["l"])),
                close=Decimal(str(item["c"])),
                volume=Decimal(str(item["v"])),
            )
        )
    return bars


def collect_exit_inputs(
    symbols: list[str], *, fetcher: JsonFetcher = _fetch_json
) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch last prices (one snapshot call) and ATR14 (1Hour bars) per symbol."""
    normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        return {}, {}
    key, secret = os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise ValueError("Alpaca paper/data credentials are required")
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }
    snapshots_url = SNAPSHOTS_ENDPOINT + "?" + urlencode({"symbols": ",".join(normalized), "feed": "iex"})
    payload = fetcher(snapshots_url, headers)
    snapshots = payload.get("snapshots", payload)
    last_prices: dict[str, str] = {}
    if isinstance(snapshots, dict):
        for symbol, item in snapshots.items():
            if not isinstance(item, dict):
                continue
            trade = item.get("latestTrade") if isinstance(item.get("latestTrade"), dict) else {}
            minute = item.get("minuteBar") if isinstance(item.get("minuteBar"), dict) else {}
            price = trade.get("p") or minute.get("c")
            if price is not None:
                last_prices[str(symbol).upper()] = str(price)
    atr14: dict[str, str] = {}
    checked_at = datetime.now(timezone.utc)
    start = checked_at - timedelta(days=45)

    def fetch_atr(symbol: str) -> tuple[str, str] | None:
        if symbol not in last_prices:
            return None
        bars_url = ALPACA_BARS_ENDPOINT.format(symbol=symbol) + "?" + urlencode(
            {
                "timeframe": "1Hour",
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": checked_at.isoformat().replace("+00:00", "Z"),
                "limit": 1000,
                "adjustment": "all",
                "feed": "iex",
                "sort": "asc",
            }
        )
        bars = _bars_to_price_bars(_paginated_bars(bars_url, headers, fetcher))
        return symbol, str(average_true_range(bars))

    workers = min(8, max(1, len(normalized)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(fetch_atr, normalized):
            if result is not None:
                atr14[result[0]] = result[1]
    return last_prices, atr14


def _default_tracking_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return Path(os.environ.get("MANDATE_POSITION_TRACKING_PATH", root / "logs" / "position-tracking.json"))


def _read_tracking(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_tracking(path: Path, tracking: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(tracking, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


ExitInputs = Callable[[list[str]], tuple[dict[str, str], dict[str, str]]]


def run_exit_evaluation(
    positions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    inputs: ExitInputs = collect_exit_inputs,
    tracking_path: Path | None = None,
) -> dict[str, Any]:
    """Compose input fetching, durable first-seen tracking, and exit evaluation."""
    checked_at = now or datetime.now(timezone.utc)
    symbols = [str(position.get("symbol", "")) for position in positions if isinstance(position, dict)]
    last_prices, atr14 = inputs([symbol for symbol in symbols if symbol.strip()])
    active_path = tracking_path or _default_tracking_path()
    stored = _read_tracking(active_path)
    result = evaluate_position_exits(
        positions=positions,
        last_prices=last_prices,
        atr14=atr14,
        first_seen=stored.get("first_seen", {}) if isinstance(stored.get("first_seen"), dict) else {},
        now=checked_at,
    )
    _write_tracking(active_path, {"first_seen": result["first_seen"]})
    return result
