from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from mandate_research.exits import run_exit_evaluation


PAPER_HOST = "paper-api.alpaca.markets"
DATA_HOST = "data.alpaca.markets"
TERMINAL_ORDER_STATUSES = {"filled", "canceled", "expired", "rejected", "replaced", "done_for_day"}
OPTION_SYMBOL = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _paper_base_url() -> str:
    raw = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname != PAPER_HOST or parsed.port is not None:
        raise ValueError("ALPACA_BASE_URL must be the official HTTPS Alpaca paper endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ALPACA_BASE_URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("ALPACA_BASE_URL cannot contain a path")
    return f"https://{PAPER_HOST}"


class PaperBroker:
    def __init__(self) -> None:
        key = os.environ.get("ALPACA_API_KEY", "")
        secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            raise ValueError("Alpaca paper credentials are required")
        self.base_url = _paper_base_url()
        self.data_url = f"https://{DATA_HOST}"
        self.headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        data_api: bool = False,
    ) -> Any:
        url = (self.data_url if data_api else self.base_url) + path
        if params:
            url += "?" + urlencode(params)
        headers = dict(self.headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = httpx.request(
                method, url, headers=headers, json=payload, timeout=15,
                follow_redirects=False,
                proxy=(
                    os.environ.get("ALPACA_PROXY_URL") or None
                    if os.environ.get("MANDATE_USE_ALPACA_PROXY", "false").lower() == "true"
                    else None
                ),
                trust_env=False,
            )
        except httpx.RequestError as exc:
            raise RuntimeError("Alpaca paper request failed: network unavailable") from exc
        if allow_not_found and response.status_code == 404:
            return None
        if not response.is_success:
            try:
                detail = response.json().get("message", "")
            except (json.JSONDecodeError, AttributeError):
                detail = ""
            suffix = f": {str(detail)[:200]}" if detail else ""
            raise RuntimeError(f"Alpaca paper request failed ({response.status_code}){suffix}")
        return response.json() if response.content else None

    def account(self) -> dict[str, Any]:
        return _object(self.request("GET", "/v2/account"), "Alpaca account")

    def positions(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/v2/positions")
        if not isinstance(payload, list):
            raise RuntimeError("Alpaca positions response must be a list")
        return [item for item in payload if isinstance(item, dict)]

    def asset(self, symbol: str) -> dict[str, Any]:
        return _object(self.request("GET", f"/v2/assets/{quote(symbol)}"), "Alpaca asset")

    def option_chain(self, underlying: str) -> dict[str, Any]:
        snapshots: dict[str, Any] = {}
        page_token = ""
        for _ in range(4):
            params = {"feed": "indicative", "limit": "1000"}
            if page_token:
                params["page_token"] = page_token
            payload = _object(
                self.request(
                    "GET", f"/v1beta1/options/snapshots/{quote(underlying)}",
                    params=params, data_api=True,
                ),
                "option chain",
            )
            page = payload.get("snapshots", {})
            if isinstance(page, dict):
                snapshots.update(page)
            page_token = str(payload.get("next_page_token") or "")
            if not page_token:
                break
        return snapshots

    def order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        payload = self.request(
            "GET", "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id}, allow_not_found=True,
        )
        return _object(payload, "existing order") if payload is not None else None

    def order(self, order_id: str) -> dict[str, Any]:
        return _object(self.request("GET", f"/v2/orders/{quote(order_id)}"), "order status")

    def submit(self, order: dict[str, Any]) -> dict[str, Any]:
        return _object(self.request("POST", "/v2/orders", payload=order), "submitted order")

    def replace(self, order_id: str, limit_price: Decimal) -> dict[str, Any]:
        return _object(
            self.request(
                "PATCH", f"/v2/orders/{quote(order_id)}",
                payload={"limit_price": str(limit_price)},
            ),
            "replaced order",
        )

    def cancel(self, order_id: str) -> None:
        self.request("DELETE", f"/v2/orders/{quote(order_id)}")


def _limit_price(last: Decimal, side: str, *, cross_bps: Decimal = Decimal("12")) -> Decimal:
    if last <= 0:
        raise ValueError("last price must be positive")
    multiplier = cross_bps / Decimal("10000")
    return (
        (last * (Decimal("1") + multiplier)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        if side == "buy"
        else (last * (Decimal("1") - multiplier)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    )


def _ordered_candidates(evaluation: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    research = evaluation.get("research_candidates")
    if not isinstance(research, list):
        return []
    requested = decision.get("candidates")
    selected = [str(value).strip().upper() for value in requested] if isinstance(requested, list) else []
    primary = str(decision.get("candidate") or "").strip().upper()
    ordered = ([primary] if primary else []) + selected + [str(value).strip().upper() for value in research]
    return [value for value in dict.fromkeys(ordered) if value in research]


def select_entries(
    evaluation: dict[str, Any],
    decision: dict[str, Any],
    *,
    existing_symbols: set[str] | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    if decision.get("action") != "PROPOSE" or decision.get("hard_contradiction") is not False:
        return []
    symbols = _object(evaluation.get("symbols"), "evaluation symbols")
    existing = existing_symbols or set()
    entries: list[dict[str, Any]] = []
    for symbol in _ordered_candidates(evaluation, decision):
        if symbol in existing:
            continue
        item = _object(symbols.get(symbol), f"{symbol} evaluation")
        ensemble = _object(
            _object(item.get("strategies"), f"{symbol} strategies").get("regime_ensemble"),
            f"{symbol} ensemble",
        )
        side = str(ensemble.get("direction"))
        sizing = _object(item.get("sizing"), f"{symbol} sizing")
        market = _object(item.get("market"), f"{symbol} market")
        qty = _decimal(sizing.get("qty", 0), f"{symbol} qty")
        last = _decimal(market.get("last"), f"{symbol} last")
        if side not in {"buy", "sell"} or qty <= 0:
            continue
        if item.get("research_candidate") is not True or sizing.get("available") is not True:
            continue
        entries.append({
            "kind": "entry",
            "symbol": symbol,
            "side": side,
            "qty": str(qty),
            "limit_price": str(_limit_price(last, side)),
            "last": str(last),
            "strength": str(ensemble.get("strength") or "0"),
            "signal_path": str(item.get("signal_path") or "price_confirmation"),
            "rationale": (
                f"direct {item.get('signal_path')} entry; ensemble strength "
                f"{ensemble.get('strength')} after LLM challenge"
            ),
        })
        if len(entries) >= limit:
            break
    return entries


def select_entry(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any] | None:
    """Compatibility wrapper retained for focused unit tests."""
    entries = select_entries(evaluation, decision, limit=1)
    if not entries:
        return None
    return {
        key: value for key, value in entries[0].items()
        if key not in {"last", "strength", "signal_path"}
    }


def select_exits(evaluation: dict[str, Any], positions: list[dict[str, Any]], *, limit: int = 2) -> list[dict[str, Any]]:
    equities = [
        item for item in positions
        if item.get("symbol") and item.get("avg_entry_price") is not None
        and str(item.get("asset_class", "us_equity")) == "us_equity"
    ]
    proposals: list[dict[str, Any]] = []
    if equities:
        try:
            exit_evaluation = run_exit_evaluation([
                {"symbol": item["symbol"], "qty": item["qty"], "avg_entry_price": item["avg_entry_price"]}
                for item in equities
            ])
            proposals.extend(
                value for value in exit_evaluation.get("proposals", []) if isinstance(value, dict)
            )
        except (RuntimeError, ValueError):
            pass

    evaluated = evaluation.get("symbols")
    evaluated = evaluated if isinstance(evaluated, dict) else {}
    existing_proposals = {str(item.get("symbol", "")).upper() for item in proposals}
    for position in equities:
        symbol = str(position.get("symbol", "")).upper()
        if symbol in existing_proposals or not isinstance(evaluated.get(symbol), dict):
            continue
        item = evaluated[symbol]
        strategies = item.get("strategies") if isinstance(item.get("strategies"), dict) else {}
        ensemble = strategies.get("regime_ensemble") if isinstance(strategies.get("regime_ensemble"), dict) else {}
        direction = ensemble.get("direction")
        qty = _decimal(position.get("qty"), f"{symbol} position qty")
        opposite = (qty > 0 and direction == "sell") or (qty < 0 and direction == "buy")
        market = item.get("market") if isinstance(item.get("market"), dict) else {}
        if not opposite or market.get("last") is None:
            continue
        last = _decimal(market["last"], f"{symbol} last")
        side = "sell" if qty > 0 else "buy"
        proposals.append({
            "symbol": symbol,
            "order_side": side,
            "qty": str(abs(qty)),
            "limit_price": str(_limit_price(last, side)),
            "rationale": f"ensemble reversal: position {'long' if qty > 0 else 'short'} while signal is {direction}",
            "reason": "ensemble_reversal",
            "urgency": "immediate",
            "age_minutes": 0,
        })

    ranked = sorted(
        proposals,
        key=lambda value: (0 if value.get("urgency") == "immediate" else 1, -int(value.get("age_minutes", 0))),
    )
    return [{
        "kind": "exit",
        "symbol": str(value["symbol"]),
        "side": str(value["order_side"]),
        "qty": str(value["qty"]),
        "limit_price": str(value["limit_price"]),
        "rationale": str(value["rationale"]),
    } for value in ranked[:limit]]


def select_exit(positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    exits = select_exits({"symbols": {}}, positions, limit=1)
    return exits[0] if exits else None


def _option_parts(symbol: str) -> tuple[date, str, Decimal] | None:
    match = OPTION_SYMBOL.fullmatch(symbol)
    if match is None:
        return None
    expiration = datetime.strptime(match.group(2), "%y%m%d").date()
    return expiration, match.group(3), Decimal(match.group(4)) / Decimal("1000")


def _option_quote(symbol: str, snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    raw = snapshot.get("latestQuote")
    if not isinstance(raw, dict):
        return None
    bid = _decimal(raw.get("bp", 0), f"{symbol} bid")
    ask = _decimal(raw.get("ap", 0), f"{symbol} ask")
    if bid <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    spread_pct = (ask - bid) / mid * Decimal("100")
    if spread_pct > Decimal(os.environ.get("MANDATE_OPTION_MAX_SPREAD_PCT", "15")):
        return None
    parts = _option_parts(symbol)
    if parts is None:
        return None
    expiration, kind, strike = parts
    return {
        "symbol": symbol,
        "expiration": expiration,
        "kind": kind,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": spread_pct,
    }


def build_option_order(
    broker: PaperBroker,
    entry: dict[str, Any],
    account: dict[str, Any],
    *,
    option_exposure: Decimal,
) -> dict[str, Any] | None:
    if os.environ.get("MANDATE_OPTIONS_ENABLED", "true").lower() != "true":
        return None
    underlying = str(entry["symbol"])
    last = _decimal(entry["last"], "underlying last")
    desired_kind = "C" if entry["side"] == "buy" else "P"
    today = datetime.now(timezone.utc).date()
    min_dte = int(os.environ.get("MANDATE_OPTION_MIN_DTE", "7"))
    max_dte = int(os.environ.get("MANDATE_OPTION_MAX_DTE", "21"))
    chain = broker.option_chain(underlying)
    contracts = []
    for symbol, snapshot in chain.items():
        option = _option_quote(str(symbol), snapshot)
        if option is None or option["kind"] != desired_kind:
            continue
        dte = (option["expiration"] - today).days
        if min_dte <= dte <= max_dte:
            contracts.append(option)
    if not contracts:
        return None
    expirations = sorted({value["expiration"] for value in contracts})
    expiration = expirations[0]
    same_expiry = [value for value in contracts if value["expiration"] == expiration]
    long_leg = min(same_expiry, key=lambda value: abs(value["strike"] - last))
    if desired_kind == "C":
        farther = [value for value in same_expiry if value["strike"] > long_leg["strike"]]
        target = last * Decimal("1.04")
    else:
        farther = [value for value in same_expiry if value["strike"] < long_leg["strike"]]
        target = last * Decimal("0.96")
    short_leg = min(farther, key=lambda value: abs(value["strike"] - target)) if farther else None
    equity = _decimal(account.get("equity", 0), "account equity")
    if equity <= 0:
        raise ValueError("account equity must be positive")
    per_trade_budget = equity * Decimal(os.environ.get("MANDATE_OPTION_RISK_PCT", "6")) / Decimal("100")
    total_budget = equity * Decimal(os.environ.get("MANDATE_OPTION_TOTAL_RISK_PCT", "25")) / Decimal("100")
    available_budget = max(Decimal("0"), min(per_trade_budget, total_budget - option_exposure))
    if available_budget <= 0:
        return None

    approved_level = int(account.get("options_approved_level") or account.get("options_trading_level") or 0)
    if approved_level < 2:
        return None
    use_spread = short_leg is not None and approved_level >= 3
    if use_spread:
        debit = long_leg["ask"] - short_leg["bid"]
        width = abs(long_leg["strike"] - short_leg["strike"])
        if debit <= Decimal("0.02") or debit >= width * Decimal("0.90"):
            use_spread = False
    if use_spread and short_leg is not None:
        debit = (long_leg["ask"] - short_leg["bid"]).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        width = abs(long_leg["strike"] - short_leg["strike"])
        limit_price = min(width * Decimal("0.95"), debit * Decimal("1.03")).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        max_loss = limit_price * Decimal("100")
        contracts_qty = min(20, int((available_budget / max_loss).to_integral_value(rounding=ROUND_FLOOR)))
        if contracts_qty < 1:
            return None
        return {
            "kind": "option_spread_entry",
            "symbol": underlying,
            "side": entry["side"],
            "qty": str(contracts_qty),
            "limit_price": str(limit_price),
            "max_limit_price": str((width * Decimal("0.95")).quantize(Decimal("0.01"))),
            "rationale": f"defined-risk {'bull call' if desired_kind == 'C' else 'bear put'} spread for {entry['rationale']}",
            "payload": {
                "qty": str(contracts_qty),
                "order_class": "mleg",
                "type": "limit",
                "limit_price": str(limit_price),
                "time_in_force": "day",
                "legs": [
                    {"symbol": long_leg["symbol"], "ratio_qty": "1", "side": "buy", "position_intent": "buy_to_open"},
                    {"symbol": short_leg["symbol"], "ratio_qty": "1", "side": "sell", "position_intent": "sell_to_open"},
                ],
            },
        }

    limit_price = (long_leg["ask"] * Decimal("1.02")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    max_loss = limit_price * Decimal("100")
    contracts_qty = min(20, int((available_budget / max_loss).to_integral_value(rounding=ROUND_FLOOR)))
    if contracts_qty < 1:
        return None
    return {
        "kind": "option_entry",
        "symbol": underlying,
        "side": entry["side"],
        "qty": str(contracts_qty),
        "limit_price": str(limit_price),
        "max_limit_price": str((limit_price * Decimal("1.12")).quantize(Decimal("0.01"))),
        "rationale": f"defined-loss long {'call' if desired_kind == 'C' else 'put'} for {entry['rationale']}",
        "payload": {
            "symbol": long_leg["symbol"],
            "qty": str(contracts_qty),
            "side": "buy",
            "type": "limit",
            "limit_price": str(limit_price),
            "time_in_force": "day",
            "position_intent": "buy_to_open",
        },
    }


def _client_order_id(action: dict[str, Any], checked_at: Any, index: int) -> str:
    raw = "|".join((
        str(action["kind"]), str(action["symbol"]), str(action["side"]),
        str(action["qty"]), str(checked_at), str(index),
    ))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"mandate-direct-{str(action['symbol']).lower()}-{digest}"


def _equity_payload(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": action["symbol"],
        "side": action["side"],
        "qty": action["qty"],
        "type": "limit",
        "limit_price": action["limit_price"],
        "time_in_force": "day",
        "extended_hours": False,
    }


def _cap_entry_to_headroom(
    action: dict[str, Any], available_cash: Decimal,
) -> tuple[dict[str, Any] | None, Decimal]:
    """Allocate portfolio headroom across the cycle's ranked entries."""
    limit_price = _decimal(action["limit_price"], "entry limit price")
    option = str(action.get("kind", "")).startswith("option")
    multiplier = Decimal("100") if option else (
        Decimal("1.5") if action.get("side") == "sell" else Decimal("1")
    )
    unit_headroom = limit_price * multiplier
    if unit_headroom <= 0:
        return None, Decimal("0")
    proposed_qty = int(_decimal(action["qty"], "entry quantity"))
    allowed_qty = int((available_cash / unit_headroom).to_integral_value(rounding=ROUND_FLOOR))
    quantity = min(proposed_qty, allowed_qty)
    if quantity < 1:
        return None, Decimal("0")
    bounded = dict(action)
    bounded["qty"] = str(quantity)
    if isinstance(action.get("payload"), dict):
        bounded["payload"] = {**action["payload"], "qty": str(quantity)}
    return bounded, unit_headroom * Decimal(quantity)


def execute_with_lifecycle(
    broker: PaperBroker,
    action: dict[str, Any],
    *,
    checked_at: Any,
    index: int,
) -> dict[str, Any]:
    client_order_id = _client_order_id(action, checked_at, index)
    payload = dict(action.get("payload") or _equity_payload(action))
    payload["client_order_id"] = client_order_id
    existing = broker.order_by_client_id(client_order_id)
    deduplicated = existing is not None
    current = existing or broker.submit(payload)
    attempts = max(1, min(5, int(os.environ.get("MANDATE_FILL_ATTEMPTS", "3"))))
    wait_seconds = max(0.0, min(10.0, float(os.environ.get("MANDATE_FILL_WAIT_SECONDS", "3"))))
    replacements = 0
    for attempt in range(attempts):
        status = str(current.get("status", "")).lower()
        if status in TERMINAL_ORDER_STATUSES:
            break
        if wait_seconds:
            time.sleep(wait_seconds)
        current = broker.order(str(current["id"]))
        status = str(current.get("status", "")).lower()
        if status in TERMINAL_ORDER_STATUSES or attempt == attempts - 1:
            break
        old_limit = _decimal(current.get("limit_price") or payload["limit_price"], "working limit")
        if str(action["kind"]).startswith("option") or action["side"] == "buy":
            next_limit = old_limit * Decimal("1.003")
            rounding = ROUND_CEILING
        else:
            next_limit = old_limit * Decimal("0.997")
            rounding = ROUND_FLOOR
        if action.get("max_limit_price") is not None:
            next_limit = min(next_limit, _decimal(action["max_limit_price"], "max limit"))
        next_limit = next_limit.quantize(Decimal("0.01"), rounding=rounding)
        try:
            current = broker.replace(str(current["id"]), next_limit)
            replacements += 1
        except RuntimeError:
            break
    status = str(current.get("status", "")).lower()
    if status not in TERMINAL_ORDER_STATUSES:
        try:
            broker.cancel(str(current["id"]))
            current = broker.order(str(current["id"]))
        except RuntimeError:
            pass
        status = str(current.get("status", status)).lower()
    filled_qty = _decimal(current.get("filled_qty") or 0, "filled qty")
    return {
        "accepted": True,
        "filled": status == "filled" or filled_qty > 0,
        "status": status,
        "filled_qty": str(filled_qty),
        "deduplicated": deduplicated,
        "replacements": replacements,
        "kind": action["kind"],
        "candidate": action["symbol"],
        "reason": action["rationale"],
        "order": payload,
        "result": current,
    }


def _journal(execution: dict[str, Any]) -> None:
    path = Path(os.environ.get("MANDATE_JOURNAL_PATH", "./logs/session.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    outcome = "filled" if execution.get("filled") else (
        "submitted" if execution.get("status") not in {"canceled", "rejected", "expired"} else "unfilled_cancelled"
    )
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": "submit_order",
        "outcome": outcome,
        "rationale": execution.get("reason", "direct paper execution"),
        "details": {
            "execution": "direct_alpaca",
            "candidate": execution.get("candidate"),
            "kind": execution.get("kind"),
            "status": execution.get("status"),
            "filled_qty": execution.get("filled_qty"),
            "replacements": execution.get("replacements"),
            "order": execution.get("order"),
            "broker_order_id": _object(execution.get("result", {}), "broker result").get("id"),
        },
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def execute(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if evaluation.get("market_is_open") is not True:
        return {
            "action": "PARK", "submitted": False, "filled": False,
            "reason": "regular market session is closed; no paper order sent",
            "executions": [], "errors": [],
        }
    broker = PaperBroker()
    account = broker.account()
    positions = broker.positions()
    exit_actions = select_exits(evaluation, positions, limit=2)
    executions: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, action in enumerate(exit_actions):
        try:
            execution = execute_with_lifecycle(
                broker, action, checked_at=evaluation.get("checked_at"), index=index,
            )
            executions.append(execution)
            _journal(execution)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{action['symbol']} {action['kind']}: {str(exc)[:180]}")

    # A submitted exit may remain partially filled. Refresh actual positions
    # before admitting reversals or computing the remaining option risk budget.
    if exit_actions:
        positions = broker.positions()
        account = broker.account()
    existing_equities = {
        str(item.get("symbol", "")).upper()
        for item in positions
        if str(item.get("asset_class", "us_equity")) == "us_equity"
    }
    entries = select_entries(evaluation, decision, existing_symbols=existing_equities, limit=2)
    option_exposure = sum(
        abs(_decimal(item.get("market_value") or 0, "option market value"))
        for item in positions if str(item.get("asset_class", "")) == "us_option"
    )
    equity = _decimal(account.get("equity", 0), "account equity")
    buying_power = max(Decimal("0"), _decimal(account.get("buying_power") or account.get("cash") or 0, "buying power"))
    gross_limit_pct = _decimal(os.environ.get("MANDATE_MAX_GROSS_EXPOSURE_PCT", "200"), "gross exposure limit")
    if gross_limit_pct <= 0 or gross_limit_pct > Decimal("400"):
        raise ValueError("MANDATE_MAX_GROSS_EXPOSURE_PCT must be greater than 0 and at most 400")
    existing_gross = sum(
        abs(_decimal(item.get("market_value") or 0, "position market value")) for item in positions
    )
    portfolio_headroom = min(
        buying_power,
        max(Decimal("0"), equity * gross_limit_pct / Decimal("100") - existing_gross),
    )
    option_slots = max(0, min(2, int(os.environ.get("MANDATE_OPTIONS_PER_CYCLE", "1"))))
    entry_actions: list[dict[str, Any]] = []
    for entry in entries:
        action: dict[str, Any] | None = None
        if len(entry_actions) < option_slots:
            try:
                action = build_option_order(broker, entry, account, option_exposure=option_exposure)
            except (RuntimeError, ValueError):
                action = None
        if action is None:
            asset = broker.asset(str(entry["symbol"]))
            if asset.get("tradable") is not True:
                continue
            if entry["side"] == "sell" and (
                asset.get("shortable") is not True or asset.get("easy_to_borrow") is not True
            ):
                continue
            action = entry
        bounded, allocated = _cap_entry_to_headroom(action, portfolio_headroom)
        if bounded is None:
            continue
        action = bounded
        portfolio_headroom -= allocated
        if str(action.get("kind", "")).startswith("option"):
            option_exposure += (
                _decimal(action["qty"], "option quantity")
                * _decimal(action["limit_price"], "option limit price")
                * Decimal("100")
            )
        entry_actions.append(action)

    for offset, action in enumerate(entry_actions, start=len(exit_actions)):
        try:
            execution = execute_with_lifecycle(
                broker, action, checked_at=evaluation.get("checked_at"), index=offset,
            )
            executions.append(execution)
            _journal(execution)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{action['symbol']} {action['kind']}: {str(exc)[:180]}")
    actions = exit_actions + entry_actions
    accepted = [
        item for item in executions
        if item.get("accepted") is True
        and (item.get("filled") is True or item.get("status") not in {"canceled", "rejected", "expired"})
    ]
    filled = [item for item in executions if item.get("filled") is True]
    if not actions:
        return {"action": "PARK", "submitted": False, "filled": False, "reason": "no exit or challenged entry"}
    if not accepted:
        return {
            "action": "PARK", "submitted": False, "filled": False,
            "reason": "; ".join(errors[:3]) or "portfolio actions remained unfilled and were cancelled",
            "executions": executions, "errors": errors,
        }
    candidates = [str(item["candidate"]) for item in accepted]
    return {
        "action": "SUBMITTED",
        "submitted": True,
        "filled": bool(filled),
        "submitted_count": len(accepted),
        "filled_count": len(filled),
        "reason": f"Alpaca accepted {len(accepted)} portfolio action(s); {len(filled)} received a fill",
        "kind": "portfolio_rotation",
        "candidate": candidates[0] if candidates else None,
        "candidates": candidates,
        "executions": executions,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute one aggressive paper portfolio cycle directly through Alpaca")
    parser.add_argument("--evaluation-path", required=True)
    parser.add_argument("--decision-path", required=True)
    args = parser.parse_args()
    evaluation = _object(json.loads(Path(args.evaluation_path).read_text(encoding="utf-8")), "evaluation")
    decision = _object(json.loads(Path(args.decision_path).read_text(encoding="utf-8")), "decision")
    print(json.dumps(execute(evaluation, decision), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
