from __future__ import annotations

import argparse
import fcntl
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from math import gcd
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx

from mandate_research.exits import clear_position_tracking, run_exit_evaluation


PAPER_HOST = "paper-api.alpaca.markets"
DATA_HOST = "data.alpaca.markets"
TERMINAL_ORDER_STATUSES = {"filled", "canceled", "expired", "rejected", "replaced", "done_for_day"}
OPTION_SYMBOL = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")
ZERO = Decimal("0")
ONE = Decimal("1")
NEW_YORK = ZoneInfo("America/New_York")
CLIENT_ORDER_PREFIX = "mandate-direct-"
MANDATE_ROOT = Path(__file__).resolve().parents[3]
EXIT_ACTION_KINDS = {"exit", "option_exit", "option_exit_mleg"}
OPTION_ACTION_KINDS = {"option_entry", "option_spread_entry", "option_exit", "option_exit_mleg"}
TRADE_PLAN_SCHEMA = "trade.plan.v2"
CRITIC_NAMES = frozenset({"risk", "market", "execution"})
MAX_PLAN_STEPS = 3


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _mandate_limits() -> dict[str, Decimal]:
    """Read the small scalar limits block without adding a YAML dependency."""
    raw_path = Path(os.environ.get("MANDATE_PATH", "mandates/example.yaml"))
    candidates = [raw_path] if raw_path.is_absolute() else [Path.cwd() / raw_path, MANDATE_ROOT / raw_path]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return {}
    limits: dict[str, Decimal] = {}
    in_limits = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_limits = stripped == "limits:"
            continue
        if not in_limits or indent < 2 or ":" not in stripped:
            continue
        key, raw = stripped.split(":", 1)
        try:
            limits[key.strip()] = _decimal(raw.split("#", 1)[0].strip(), f"mandate {key.strip()}")
        except ValueError:
            continue
    return limits


def _configured_limit(
    limits: dict[str, Decimal], key: str, env_name: str, default: str,
) -> Decimal:
    if key in limits:
        return limits[key]
    raw = os.environ.get(env_name)
    return _decimal(raw if raw not in {None, ""} else default, key)


def _execution_state_path() -> Path:
    raw = Path(os.environ.get("MANDATE_EXECUTION_STATE_PATH", "logs/execution-state.json"))
    return raw if raw.is_absolute() else MANDATE_ROOT / raw


def _execution_lock_path() -> Path:
    raw = Path(os.environ.get("MANDATE_EXECUTION_LOCK_PATH", "logs/execution.lock"))
    return raw if raw.is_absolute() else MANDATE_ROOT / raw


def _read_execution_state() -> dict[str, Any]:
    try:
        payload = json.loads(_execution_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbols": {}}
    return payload if isinstance(payload, dict) else {"symbols": {}}


def _write_execution_state(state: dict[str, Any]) -> None:
    path = _execution_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(NEW_YORK)


def _after_flatten_window(now: datetime | None = None) -> bool:
    value = (now or _now_et()).astimezone(NEW_YORK)
    return (value.hour, value.minute) >= (15, 50)


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
        response: httpx.Response | None = None
        attempts = 2 if method == "GET" else 1
        last_error: httpx.RequestError | None = None
        for attempt in range(attempts):
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
                if method != "GET" or response.status_code not in {408, 429, 500, 502, 503, 504}:
                    break
            except httpx.RequestError as exc:
                last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25)
        if response is None:
            raise RuntimeError("Alpaca paper request failed: network unavailable") from last_error
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

    def orders(self, *, status: str = "all", after: str | None = None) -> list[dict[str, Any]]:
        params = {"status": status, "limit": "500", "direction": "desc", "nested": "true"}
        if after:
            params["after"] = after
        payload = self.request("GET", "/v2/orders", params=params)
        if not isinstance(payload, list):
            raise RuntimeError("Alpaca orders response must be a list")
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


def _required_text(value: Any, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    return text


def _canonical_trade_candidates(
    evaluation: dict[str, Any],
) -> tuple[dict[str, str], str]:
    """Map opaque candidate IDs to canonical symbols without accepting order fields."""
    symbols = _object(evaluation.get("symbols"), "evaluation symbols")
    raw_research = evaluation.get("research_candidates")
    if not isinstance(raw_research, list):
        raise ValueError("evaluation research_candidates must be a list")
    research = {
        str(value).strip().upper() for value in raw_research if str(value).strip()
    }
    raw_catalog = evaluation.get("trade_candidates")
    if not isinstance(raw_catalog, list):
        raise ValueError("evaluation trade_candidates must be a list")
    catalog: dict[str, str] = {}
    catalog_symbols: set[str] = set()
    for index, raw in enumerate(raw_catalog):
        record = _object(raw, f"trade_candidates[{index}]")
        candidate_id = _required_text(
            record.get("candidate_id"), f"trade_candidates[{index}].candidate_id", maximum=120,
        )
        symbol = _required_text(
            record.get("symbol"), f"trade_candidates[{index}].symbol", maximum=16,
        ).upper()
        if candidate_id in catalog:
            raise ValueError(f"duplicate canonical candidate_id: {candidate_id}")
        if symbol in catalog_symbols:
            raise ValueError(f"duplicate canonical trade candidate symbol: {symbol}")
        if symbol == "SPY" or symbol not in research or not isinstance(symbols.get(symbol), dict):
            raise ValueError(f"trade candidate {candidate_id} is not a canonical research candidate")
        catalog[candidate_id] = symbol
        catalog_symbols.add(symbol)
    return catalog, "trade_candidates"


def _trade_plan(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a model plan and resolve only its candidate IDs to canonical symbols."""
    if decision.get("schema") == TRADE_PLAN_SCHEMA:
        required_root = {
            "schema", "cycle_id", "reason", "action", "hypotheses", "steps", "critic_coverage",
            "critic_resolutions", "memory_events",
        }
        if set(decision) != required_root:
            raise ValueError("trade plan root fields do not match trade.plan.v2")
        action = decision.get("action")
        if action not in {"PARK", "EXECUTE_PLAN"}:
            raise ValueError("trade plan action must be PARK or EXECUTE_PLAN")
        cycle_id = _required_text(decision.get("cycle_id"), "trade plan cycle_id", maximum=160)
        canonical_cycle_id = _required_text(
            evaluation.get("cycle_id") or evaluation.get("checked_at"),
            "evaluation cycle_id",
            maximum=160,
        )
        if cycle_id != canonical_cycle_id:
            raise ValueError("trade plan cycle_id does not match the canonical evaluation cycle")
        reason = _required_text(decision.get("reason"), "trade plan reason")
        hypotheses = decision.get("hypotheses")
        if not isinstance(hypotheses, list) or len(hypotheses) > 5:
            raise ValueError("trade plan hypotheses must contain at most five items")
        if action == "EXECUTE_PLAN" and not hypotheses:
            raise ValueError("EXECUTE_PLAN requires at least one trade hypothesis")
        hypothesis_candidates: set[str] = set()
        for index, raw_hypothesis in enumerate(hypotheses):
            hypothesis = _object(raw_hypothesis, f"trade hypothesis {index}")
            if set(hypothesis) != {
                "candidate_id", "thesis", "confidence", "supports", "contradicts", "invalidation",
            }:
                raise ValueError("trade hypothesis fields do not match trade.plan.v2")
            candidate_id = _required_text(
                hypothesis.get("candidate_id"), f"trade hypothesis {index} candidate_id", maximum=120,
            )
            if candidate_id in hypothesis_candidates:
                raise ValueError("trade hypothesis candidate_ids must be unique")
            hypothesis_candidates.add(candidate_id)
            _required_text(hypothesis.get("thesis"), f"trade hypothesis {index} thesis", maximum=240)
            _required_text(
                hypothesis.get("invalidation"), f"trade hypothesis {index} invalidation", maximum=240,
            )
            if hypothesis.get("confidence") not in {"low", "medium", "high"}:
                raise ValueError("trade hypothesis confidence must be low, medium, or high")
            supports = hypothesis.get("supports")
            contradicts = hypothesis.get("contradicts")
            if not isinstance(supports, list) or not 1 <= len(supports) <= 12:
                raise ValueError("trade hypothesis supports must contain 1-12 evidence refs")
            if not isinstance(contradicts, list) or len(contradicts) > 8:
                raise ValueError("trade hypothesis contradicts must contain at most 8 evidence refs")
            for evidence_ref in [*supports, *contradicts]:
                _required_text(evidence_ref, f"trade hypothesis {index} evidence ref", maximum=300)
        raw_steps = decision.get("steps")
        if not isinstance(raw_steps, list):
            raise ValueError("trade plan steps must be a list")
        if action == "PARK" and raw_steps:
            raise ValueError("PARK trade plan cannot contain steps")
        if action == "EXECUTE_PLAN" and not 1 <= len(raw_steps) <= MAX_PLAN_STEPS:
            raise ValueError(f"EXECUTE_PLAN requires 1-{MAX_PLAN_STEPS} steps")
        coverage = decision.get("critic_coverage")
        if not isinstance(coverage, list) or len(coverage) != 3 or set(coverage) != CRITIC_NAMES:
            raise ValueError("trade plan must cover risk, market, and execution critics exactly once")
        resolutions = decision.get("critic_resolutions")
        if not isinstance(resolutions, list) or len(resolutions) != 3:
            raise ValueError("trade plan must resolve all three critics")
        resolved: set[str] = set()
        for index, raw_resolution in enumerate(resolutions):
            resolution = _object(raw_resolution, f"critic resolution {index}")
            if set(resolution) != {"critic", "resolution", "reason"}:
                raise ValueError("critic resolution fields do not match trade.plan.v2")
            critic = str(resolution.get("critic"))
            if critic not in CRITIC_NAMES or critic in resolved:
                raise ValueError("critic resolutions must be unique")
            if resolution.get("resolution") not in {"ACCEPTED", "OVERRIDDEN"}:
                raise ValueError("critic resolution must be ACCEPTED or OVERRIDDEN")
            _required_text(resolution.get("reason"), f"critic resolution {index} reason")
            resolved.add(critic)
        memory_events = decision.get("memory_events")
        if not isinstance(memory_events, list) or len(memory_events) > 5:
            raise ValueError("memory_events must contain at most five hypotheses")
        for index, raw_memory in enumerate(memory_events):
            memory = _object(raw_memory, f"memory event {index}")
            if set(memory) != {"hypothesis", "evidence_refs", "ttl_hours"}:
                raise ValueError("memory event fields do not match trade.plan.v2")
            _required_text(memory.get("hypothesis"), f"memory event {index} hypothesis")
            if not isinstance(memory.get("evidence_refs"), list) or not memory["evidence_refs"]:
                raise ValueError("memory event evidence_refs must be non-empty")
            for evidence_ref in memory["evidence_refs"]:
                _required_text(evidence_ref, f"memory event {index} evidence_ref", maximum=300)
            ttl_hours = memory.get("ttl_hours")
            if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int) or not 1 <= ttl_hours <= 168:
                raise ValueError("memory event ttl_hours must be between 1 and 168")
        catalog: dict[str, str] | None = None
        catalog_source = "trade_candidates"
        if hypothesis_candidates:
            catalog, catalog_source = _canonical_trade_candidates(evaluation)
            if any(candidate_id not in catalog for candidate_id in hypothesis_candidates):
                raise ValueError("trade hypothesis references an unknown candidate_id")
        if action == "PARK":
            return {
                "schema": TRADE_PLAN_SCHEMA,
                "source": "trade_candidates",
                "cycle_id": cycle_id,
                "action": action,
                "reason": reason,
                "steps": [],
            }
        if catalog is None:
            catalog, catalog_source = _canonical_trade_candidates(evaluation)
        steps: list[dict[str, Any]] = []
        candidate_ids: set[str] = set()
        symbols: set[str] = set()
        for index, raw in enumerate(raw_steps):
            step = _object(raw, f"trade plan step {index}")
            if set(step) != {"candidate_id", "reason", "evidence_refs"}:
                raise ValueError("trade plan step fields do not match trade.plan.v2")
            candidate_id = _required_text(
                step.get("candidate_id"), f"trade plan step {index} candidate_id", maximum=120,
            )
            step_reason = _required_text(step.get("reason"), f"trade plan step {index} reason")
            raw_evidence_refs = step.get("evidence_refs")
            if not isinstance(raw_evidence_refs, list) or not 1 <= len(raw_evidence_refs) <= 12:
                raise ValueError(f"trade plan step {index} evidence_refs must contain 1-12 items")
            evidence_refs = [
                _required_text(value, f"trade plan step {index} evidence_ref", maximum=300)
                for value in raw_evidence_refs
            ]
            if candidate_id in candidate_ids:
                raise ValueError(f"duplicate trade plan candidate_id: {candidate_id}")
            symbol = catalog.get(candidate_id)
            if symbol is None:
                raise ValueError(f"unknown trade plan candidate_id: {candidate_id}")
            if symbol in symbols:
                raise ValueError(f"trade plan resolves multiple IDs to {symbol}")
            if candidate_id not in hypothesis_candidates:
                raise ValueError(f"trade plan candidate_id lacks a hypothesis: {candidate_id}")
            candidate_ids.add(candidate_id)
            symbols.add(symbol)
            steps.append({
                "candidate_id": candidate_id,
                "symbol": symbol,
                "reason": step_reason,
                "evidence_refs": evidence_refs,
            })
        return {
            "schema": TRADE_PLAN_SCHEMA,
            "source": catalog_source,
            "cycle_id": cycle_id,
            "action": action,
            "reason": reason,
            "steps": steps,
        }

    raise ValueError(f"decision schema must be {TRADE_PLAN_SCHEMA}")


def select_entries(
    evaluation: dict[str, Any],
    decision: dict[str, Any],
    *,
    existing_symbols: set[str] | None = None,
    limit: int = MAX_PLAN_STEPS,
) -> list[dict[str, Any]]:
    plan = _trade_plan(evaluation, decision)
    if plan["action"] != "EXECUTE_PLAN":
        return []
    symbols = _object(evaluation.get("symbols"), "evaluation symbols")
    existing = existing_symbols or set()
    entries: list[dict[str, Any]] = []
    for step in plan["steps"]:
        symbol = str(step["symbol"])
        if symbol == "SPY" or symbol in existing:
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
        rationale = (
            f"direct {item.get('signal_path')} entry; ensemble strength "
            f"{ensemble.get('strength')} after plan challenge; {step['reason']}"
        )
        metadata = {
            "plan_schema": str(plan["schema"]),
            "plan_cycle_id": str(plan["cycle_id"]),
            "plan_candidate_id": str(step["candidate_id"]),
            "plan_reason": str(step["reason"]),
            "plan_evidence_refs": list(step["evidence_refs"]),
        }
        entries.append({
            "kind": "entry",
            "symbol": symbol,
            "side": side,
            "qty": str(qty),
            "limit_price": str(_limit_price(last, side)),
            "last": str(last),
            **metadata,
            "rationale": rationale,
        })
        if len(entries) >= limit:
            break
    return entries


def select_exits(
    evaluation: dict[str, Any],
    positions: list[dict[str, Any]],
    *,
    limit: int = 2,
    health: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    equity_positions = [
        item for item in positions
        if item.get("symbol") and str(item.get("asset_class", "us_equity")) == "us_equity"
    ]
    equities = [
        item for item in equity_positions if item.get("avg_entry_price") is not None
    ]
    proposals: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = [
        {"symbol": str(item.get("symbol", "")).upper(), "reason": "missing_avg_entry_price"}
        for item in equity_positions if item.get("avg_entry_price") is None
    ]
    if equities:
        try:
            exit_evaluation = run_exit_evaluation([
                {"symbol": item["symbol"], "qty": item["qty"], "avg_entry_price": item["avg_entry_price"]}
                for item in equities
            ])
            proposals.extend(
                value for value in exit_evaluation.get("proposals", []) if isinstance(value, dict)
            )
            issues.extend(
                value for value in exit_evaluation.get("unevaluated", []) if isinstance(value, dict)
            )
        except (RuntimeError, ValueError) as exc:
            issues.append({"symbol": "*", "reason": f"{type(exc).__name__}:{str(exc)[:120]}"})

    if health is not None:
        health.update({"healthy": not issues, "issues": issues})

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
        try:
            strength = _decimal(ensemble.get("strength") or 0, f"{symbol} ensemble strength")
            reversal_floor = _decimal(
                os.environ.get("MANDATE_REVERSAL_MIN_STRENGTH", "0.20"), "reversal strength floor"
            )
            qty = _decimal(position.get("qty"), f"{symbol} position qty")
        except ValueError:
            continue
        opposite = (qty > 0 and direction == "sell") or (qty < 0 and direction == "buy")
        market = item.get("market") if isinstance(item.get("market"), dict) else {}
        if not opposite or strength < reversal_floor or market.get("last") is None:
            continue
        try:
            last = _decimal(market["last"], f"{symbol} last")
        except ValueError:
            continue
        side = "sell" if qty > 0 else "buy"
        proposals.append({
            "symbol": symbol,
            "order_side": side,
            "qty": str(abs(qty)),
            "limit_price": str(_limit_price(last, side)),
            "rationale": (
                f"ensemble reversal: position {'long' if qty > 0 else 'short'} while signal is "
                f"{direction} at strength {strength}"
            ),
            "reason": "ensemble_reversal",
            "urgency": "immediate",
            "age_minutes": 0,
        })

    # Never submit an exit whose side would increase the current position.
    # This protects against stale evaluator state and Alpaca wash-trade rejects.
    position_sides: dict[str, Decimal] = {}
    for item in equities:
        try:
            position_sides[str(item.get("symbol", "")).upper()] = _decimal(
                item.get("qty", 0), "position qty",
            )
        except ValueError:
            continue
    safe_proposals = [
        value for value in proposals
        if (
            (position_sides.get(str(value.get("symbol", "")).upper(), ZERO) < 0 and value.get("order_side") == "buy")
            or (position_sides.get(str(value.get("symbol", "")).upper(), ZERO) > 0 and value.get("order_side") == "sell")
        )
    ]
    ranked = sorted(
        safe_proposals,
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


def _option_parts(symbol: str) -> tuple[date, str, Decimal] | None:
    match = OPTION_SYMBOL.fullmatch(symbol)
    if match is None:
        return None
    expiration = datetime.strptime(match.group(2), "%y%m%d").date()
    return expiration, match.group(3), Decimal(match.group(4)) / Decimal("1000")


def _option_underlying(symbol: str) -> str | None:
    match = OPTION_SYMBOL.fullmatch(symbol)
    return match.group(1) if match is not None else None


def select_option_exits(
    positions: list[dict[str, Any]], *, now: datetime | None = None, limit: int = 2,
    first_seen: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build risk exits for option positions, preserving up to four related legs atomically."""
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    flatten = _after_flatten_window(checked_at)
    stop_pct = _decimal(os.environ.get("MANDATE_OPTION_STOP_LOSS_PCT", "25"), "option stop loss")
    target_pct = _decimal(os.environ.get("MANDATE_OPTION_PROFIT_TARGET_PCT", "40"), "option profit target")
    exit_dte = int(os.environ.get("MANDATE_OPTION_EXIT_DTE", "2"))
    time_stop_minutes = int(os.environ.get("MANDATE_OPTION_TIME_STOP_MINUTES", "180"))
    dead_band_pct = _decimal(os.environ.get("MANDATE_OPTION_DEAD_BAND_PCT", "10"), "option dead band")
    tracked = first_seen or {}
    grouped: dict[tuple[str, date, str], list[dict[str, Any]]] = {}
    for position in positions:
        if str(position.get("asset_class", "")) != "us_option":
            continue
        symbol = str(position.get("symbol", "")).upper()
        parts = _option_parts(symbol)
        underlying = _option_underlying(symbol)
        if parts is None or underlying is None:
            continue
        try:
            qty = _decimal(position.get("qty"), f"{symbol} option qty")
            current = _decimal(position.get("current_price"), f"{symbol} current price")
            if qty == ZERO or current <= ZERO or qty != qty.to_integral_value():
                continue
        except ValueError:
            continue
        grouped.setdefault((underlying, parts[0], parts[1]), []).append({**position, "_qty": qty, "_current": current})

    actions: list[dict[str, Any]] = []
    for (underlying, expiration, kind), legs in sorted(grouped.items()):
        cost = sum((abs(_decimal(item.get("cost_basis") or 0, "option cost basis")) for item in legs), ZERO)
        pnl = sum((_decimal(item.get("unrealized_pl") or 0, "option unrealized P/L") for item in legs), ZERO)
        pnl_pct = pnl / cost * Decimal("100") if cost > ZERO else ZERO
        dte = (expiration - checked_at.date()).days
        raw_seen = tracked.get(underlying)
        try:
            seen = datetime.fromisoformat(str(raw_seen).replace("Z", "+00:00")) if raw_seen else checked_at
            age_minutes = max(0, int((checked_at - seen.astimezone(timezone.utc)).total_seconds() // 60))
        except ValueError:
            age_minutes = 0
        if flatten:
            reason = "session_flatten_1550"
        elif dte <= exit_dte:
            reason = f"option_expiry_guard_{dte}dte"
        elif pnl_pct <= -stop_pct:
            reason = f"option_stop_{pnl_pct.quantize(Decimal('0.01'))}pct"
        elif pnl_pct >= target_pct:
            reason = f"option_target_{pnl_pct.quantize(Decimal('0.01'))}pct"
        elif age_minutes >= time_stop_minutes and abs(pnl_pct) <= dead_band_pct:
            reason = f"option_time_stop_{age_minutes}m"
        else:
            continue
        # Alpaca mleg supports at most four legs. A larger group is split into
        # deterministic chunks; normal strategy construction produces 1-4 legs.
        for chunk_start in range(0, len(legs), 4):
            chunk = legs[chunk_start:chunk_start + 4]
            quantities = [int(abs(item["_qty"])) for item in chunk]
            common_qty = quantities[0]
            for value in quantities[1:]:
                common_qty = gcd(common_qty, value)
            ratios = [value // common_qty for value in quantities]
            net_credit = sum(
                item["_current"] * Decimal(ratio) * (ONE if item["_qty"] > ZERO else -ONE)
                for item, ratio in zip(chunk, ratios)
            )
            if len(chunk) == 1:
                item = chunk[0]
                side = "sell" if item["_qty"] > ZERO else "buy"
                price = (
                    item["_current"] * (Decimal("0.98") if side == "sell" else Decimal("1.02"))
                ).quantize(Decimal("0.01"), rounding=ROUND_FLOOR if side == "sell" else ROUND_CEILING)
                actions.append({
                    "kind": "option_exit", "symbol": str(item["symbol"]), "underlying": underlying,
                    "side": side, "qty": str(common_qty), "limit_price": str(max(Decimal("0.01"), price)),
                    "rationale": reason,
                    "limit_chase": "down" if side == "sell" else "up",
                    "payload": {
                        "symbol": str(item["symbol"]), "qty": str(common_qty), "side": side,
                        "type": "limit", "limit_price": str(max(Decimal("0.01"), price)),
                        "time_in_force": "day",
                        "position_intent": "sell_to_close" if side == "sell" else "buy_to_close",
                    },
                })
                continue
            chase_up = net_credit < ZERO
            raw_price = abs(net_credit) * (Decimal("1.02") if chase_up else Decimal("0.98"))
            price = max(Decimal("0.01"), raw_price).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING if chase_up else ROUND_FLOOR
            )
            payload_legs = [{
                "symbol": str(item["symbol"]), "ratio_qty": str(ratio),
                "side": "sell" if item["_qty"] > ZERO else "buy",
                "position_intent": "sell_to_close" if item["_qty"] > ZERO else "buy_to_close",
            } for item, ratio in zip(chunk, ratios)]
            actions.append({
                "kind": "option_exit_mleg", "symbol": underlying, "side": "buy" if chase_up else "sell",
                "qty": str(common_qty), "limit_price": str(price), "rationale": reason,
                "limit_chase": "up" if chase_up else "down",
                "payload": {
                    "qty": str(common_qty), "order_class": "mleg", "type": "limit",
                    "limit_price": str(price), "time_in_force": "day", "legs": payload_legs,
                },
            })
    return actions if flatten else actions[:limit]


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
    # A purely relative cap rejects every cheap near-the-money contract with a
    # $0.10 spread and leaves only deep in-the-money contracts, which then get
    # selected as "closest to ATM". A small absolute allowance keeps ATM eligible.
    max_spread_pct = Decimal(os.environ.get("MANDATE_OPTION_MAX_SPREAD_PCT", "8"))
    max_spread_abs = Decimal(os.environ.get("MANDATE_OPTION_MAX_SPREAD_ABS", "0.15"))
    if spread_pct > max_spread_pct and (ask - bid) > max_spread_abs:
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


def _plan_metadata(action: dict[str, Any]) -> dict[str, Any]:
    return {
        key: action[key] for key in (
            "plan_schema", "plan_cycle_id", "plan_candidate_id", "plan_reason",
            "plan_evidence_refs",
        ) if key in action
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
    # The long leg must sit near the money. Deep in-the-money contracts behave
    # like stock with none of the defined-risk convexity this path is for.
    moneyness_cap = last * Decimal(os.environ.get("MANDATE_OPTION_MAX_MONEYNESS_PCT", "10")) / Decimal("100")
    same_expiry: list[dict[str, Any]] = []
    near_money: list[dict[str, Any]] = []
    for expiration in sorted({value["expiration"] for value in contracts}):
        same_expiry = [value for value in contracts if value["expiration"] == expiration]
        near_money = [value for value in same_expiry if abs(value["strike"] - last) <= moneyness_cap]
        if near_money:
            break
    if not near_money:
        return None
    long_leg = min(near_money, key=lambda value: abs(value["strike"] - last))
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
    spread_prices: tuple[Decimal, Decimal] | None = None
    if short_leg is not None and approved_level >= 3:
        marketable_debit = long_leg["ask"] - short_leg["bid"]
        midpoint_debit = long_leg["mid"] - short_leg["mid"]
        width = abs(long_leg["strike"] - short_leg["strike"])
        if (
            midpoint_debit > Decimal("0.02")
            and marketable_debit > Decimal("0.02")
            and marketable_debit < width * Decimal("0.90")
        ):
            limit_price = min(width * Decimal("0.90"), midpoint_debit * Decimal("1.02")).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            max_limit_price = min(width * Decimal("0.90"), marketable_debit * Decimal("1.02")).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            spread_prices = limit_price, max_limit_price
    if short_leg is not None and spread_prices is not None:
        limit_price, max_limit_price = spread_prices
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
            "max_limit_price": str(max_limit_price),
            "limit_chase": "up",
            "rationale": f"defined-risk {'bull call' if desired_kind == 'C' else 'bear put'} spread for {entry['rationale']}",
            **_plan_metadata(entry),
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

    limit_price = (long_leg["mid"] * Decimal("1.01")).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
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
        "max_limit_price": str((long_leg["ask"] * Decimal("1.01")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)),
        "limit_chase": "up",
        "rationale": f"defined-loss long {'call' if desired_kind == 'C' else 'put'} for {entry['rationale']}",
        **_plan_metadata(entry),
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
    if action.get("plan_candidate_id") and action.get("plan_cycle_id"):
        raw = "|".join((
            str(action.get("plan_schema") or TRADE_PLAN_SCHEMA),
            str(action["plan_cycle_id"]), str(action["plan_candidate_id"]),
        ))
    else:
        raw = "|".join((
            str(action["kind"]), str(action["symbol"]), str(action["side"]),
            str(action["qty"]), str(checked_at), str(index),
        ))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    # Alpaca caps client_order_id at 48 characters. The canonical underlying
    # keeps a plan ID stable if its precomputed candidate becomes an option.
    label = _action_underlying(action).lower()[:11]
    return f"{CLIENT_ORDER_PREFIX}{label}-{digest}"


def _refresh_exit_action(broker: PaperBroker, action: dict[str, Any]) -> dict[str, Any]:
    """Re-read broker state and clamp every close so stale data cannot flip a position."""
    if "exit" not in str(action.get("kind", "")):
        return action
    live = {str(item.get("symbol", "")).upper(): item for item in broker.positions()}
    payload = dict(action.get("payload") or {})
    if payload.get("order_class") == "mleg" and isinstance(payload.get("legs"), list):
        allowed_parent: int | None = None
        for leg in payload["legs"]:
            if not isinstance(leg, dict):
                raise ValueError("option exit contains an invalid leg")
            symbol = str(leg.get("symbol", "")).upper()
            position = live.get(symbol)
            if position is None:
                raise ValueError(f"{symbol} option position no longer exists")
            qty = _decimal(position.get("qty"), f"{symbol} live qty")
            side = str(leg.get("side"))
            if not ((qty > ZERO and side == "sell") or (qty < ZERO and side == "buy")):
                raise ValueError(f"{symbol} exit side would increase or flip the live position")
            ratio = int(_decimal(leg.get("ratio_qty"), f"{symbol} ratio"))
            allowed = int(abs(qty)) // ratio
            allowed_parent = allowed if allowed_parent is None else min(allowed_parent, allowed)
        parent_qty = min(int(_decimal(payload.get("qty"), "mleg exit qty")), allowed_parent or 0)
        if parent_qty < 1:
            raise ValueError("option exit has no remaining live quantity")
        refreshed = dict(action)
        refreshed["qty"] = str(parent_qty)
        refreshed["payload"] = {**payload, "qty": str(parent_qty)}
        return refreshed

    target_symbol = str(payload.get("symbol") or action.get("symbol", "")).upper()
    position = live.get(target_symbol)
    if position is None:
        raise ValueError(f"{target_symbol} position no longer exists")
    live_qty = _decimal(position.get("qty"), f"{target_symbol} live qty")
    side = str(action.get("side"))
    if not ((live_qty > ZERO and side == "sell") or (live_qty < ZERO and side == "buy")):
        raise ValueError(f"{target_symbol} exit side would increase or flip the live position")
    quantity = min(int(abs(live_qty)), int(_decimal(action.get("qty"), "exit qty")))
    if quantity < 1:
        raise ValueError(f"{target_symbol} exit has no remaining live quantity")
    refreshed = dict(action)
    refreshed["qty"] = str(quantity)
    if payload:
        refreshed["payload"] = {**payload, "qty": str(quantity)}
    return refreshed


def _cancel_tagged_open_orders(broker: PaperBroker) -> list[str]:
    cancelled: list[str] = []
    for order in broker.orders(status="open"):
        client_id = str(order.get("client_order_id") or "")
        order_id = str(order.get("id") or "")
        if not client_id.startswith(CLIENT_ORDER_PREFIX) or not order_id:
            continue
        try:
            broker.cancel(order_id)
            cancelled.append(client_id)
        except RuntimeError:
            continue
    return cancelled


def _entry_risk_gate(
    broker: PaperBroker,
    account: dict[str, Any],
    limits: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    configured_limits = limits if limits is not None else _mandate_limits()
    max_daily_loss = _configured_limit(configured_limits, "max_daily_loss_pct", "MANDATE_MAX_DAILY_LOSS_PCT", "10")
    entry_stop = _decimal(os.environ.get("MANDATE_DAILY_ENTRY_STOP_PCT", "8"), "daily entry stop")
    max_orders = int(_configured_limit(configured_limits, "max_orders_per_day", "MANDATE_MAX_ORDERS_PER_DAY", "200"))
    equity = _decimal(account.get("equity") or 0, "account equity")
    last_equity = _decimal(account.get("last_equity") or equity, "account last equity")
    daily_loss_pct = max(ZERO, (last_equity - equity) / last_equity * Decimal("100")) if last_equity > ZERO else ZERO
    day_start = _now_et().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    try:
        orders_today = len(broker.orders(status="all", after=day_start))
        order_count_available = True
    except RuntimeError:
        orders_today = 0
        order_count_available = False
    reasons: list[str] = []
    if daily_loss_pct >= min(entry_stop, max_daily_loss):
        reasons.append(f"daily_loss_{daily_loss_pct.quantize(Decimal('0.01'))}pct")
    if orders_today >= max_orders:
        reasons.append(f"order_budget_{orders_today}_of_{max_orders}")
    if not order_count_available:
        reasons.append("order_count_unavailable")
    return {
        "allow_entries": not reasons,
        "reasons": reasons,
        "daily_loss_pct": str(daily_loss_pct.quantize(Decimal("0.01"))),
        "entry_stop_pct": str(min(entry_stop, max_daily_loss)),
        "orders_today": orders_today,
        "max_orders_per_day": max_orders,
    }


def _equity_payload(action: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "symbol": action["symbol"],
        "side": action["side"],
        "qty": action["qty"],
        "type": "limit",
        "limit_price": action["limit_price"],
        "time_in_force": "day",
        "extended_hours": False,
    }
    if action.get("kind") == "exit":
        payload["position_intent"] = "sell_to_close" if action["side"] == "sell" else "buy_to_close"
    return payload


def _cap_entry_to_headroom(
    action: dict[str, Any], available_cash: Decimal,
) -> tuple[dict[str, Any] | None, Decimal]:
    """Allocate portfolio headroom across the cycle's ranked entries."""
    limit_price = _decimal(action["limit_price"], "entry limit price")
    option = action.get("kind") in OPTION_ACTION_KINDS
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


def _cap_ipo_action(action: dict[str, Any], equity: Decimal, ipo_symbols: set[str]) -> dict[str, Any]:
    """Keep newly listed names small while still allowing aggressive selection."""
    if str(action.get("symbol", "")).upper() not in ipo_symbols:
        return action
    max_notional = equity * Decimal(os.environ.get("MANDATE_IPO_MAX_POSITION_PCT", "2")) / Decimal("100")
    price = _decimal(action.get("limit_price", 0), "IPO limit price")
    multiplier = Decimal("100") if action.get("kind") in OPTION_ACTION_KINDS else Decimal("1")
    max_qty = int((max_notional / (price * multiplier)).to_integral_value(rounding=ROUND_FLOOR))
    if max_qty < 1:
        return {}
    bounded = dict(action)
    bounded["qty"] = str(min(int(_decimal(action["qty"], "IPO quantity")), max_qty))
    if isinstance(action.get("payload"), dict):
        bounded["payload"] = {**action["payload"], "qty": bounded["qty"]}
    bounded["rationale"] = f"IPO capped at {os.environ.get('MANDATE_IPO_MAX_POSITION_PCT', '2')}% equity; {action.get('rationale', '')}"
    return bounded


def execute_with_lifecycle(
    broker: PaperBroker,
    action: dict[str, Any],
    *,
    checked_at: Any,
    index: int,
) -> dict[str, Any]:
    action = _refresh_exit_action(broker, action)
    client_order_id = _client_order_id(action, checked_at, index)
    payload = dict(action.get("payload") or _equity_payload(action))
    payload["qty"] = action["qty"]
    payload["limit_price"] = action["limit_price"]
    payload["client_order_id"] = client_order_id
    existing = broker.order_by_client_id(client_order_id)
    deduplicated = existing is not None
    current = existing or broker.submit(payload)
    attempts = max(1, min(5, int(os.environ.get("MANDATE_FILL_ATTEMPTS", "3"))))
    wait_seconds = max(0.0, min(10.0, float(os.environ.get("MANDATE_FILL_WAIT_SECONDS", "3"))))
    if action.get("kind") in EXIT_ACTION_KINDS:
        attempts = min(attempts, 2)
        wait_seconds = min(wait_seconds, 1.0)
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
        chase = str(action.get("limit_chase") or ("up" if action["side"] == "buy" else "down"))
        if chase == "up":
            if action["kind"] in OPTION_ACTION_KINDS and action.get("max_limit_price") is not None:
                maximum = _decimal(action["max_limit_price"], "max limit")
                next_limit = old_limit + (maximum - old_limit) * Decimal("0.5")
            else:
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
        "underlying": _action_underlying(action),
        "side": action["side"],
        "plan_schema": action.get("plan_schema"),
        "plan_cycle_id": action.get("plan_cycle_id"),
        "plan_candidate_id": action.get("plan_candidate_id"),
        "plan_evidence_refs": action.get("plan_evidence_refs"),
        "reason": action["rationale"],
        "exit_policy": _entry_exit_policy(action),
        "order": payload,
        "result": current,
    }


def _entry_exit_policy(action: dict[str, Any]) -> dict[str, str] | None:
    kind = str(action.get("kind") or "")
    if kind in EXIT_ACTION_KINDS:
        return None
    if kind in {"option_entry", "option_spread_entry"}:
        return {
            "stop": f"-{os.environ.get('MANDATE_OPTION_STOP_LOSS_PCT', '25')}% unrealized P&L",
            "target": f"+{os.environ.get('MANDATE_OPTION_PROFIT_TARGET_PCT', '40')}% unrealized P&L",
            "time_stop": f"{os.environ.get('MANDATE_OPTION_TIME_STOP_MINUTES', '180')}m in the dead band",
            "expiry": f"close at DTE <= {os.environ.get('MANDATE_OPTION_EXIT_DTE', '2')}",
            "flatten": "mandatory 15:50 ET session flatten",
        }
    return {
        "stop": f"{os.environ.get('MANDATE_EXIT_STOP_ATR', '0.90')}x ATR14 adverse move",
        "target": f"{os.environ.get('MANDATE_EXIT_TARGET_ATR', '1.50')}x ATR14 favorable move",
        "time_stop": (
            f"{os.environ.get('MANDATE_EXIT_TIME_STOP_MINUTES', '45')}m if still within "
            f"{os.environ.get('MANDATE_EXIT_DEAD_POSITION_ATR', '0.25')}x ATR14 of entry"
        ),
        "flatten": "mandatory 15:50 ET session flatten",
    }


def _append_journal(record: dict[str, Any]) -> None:
    path = Path(os.environ.get("MANDATE_JOURNAL_PATH", "./logs/session.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _journal(execution: dict[str, Any]) -> None:
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
            "side": execution.get("side"),
            "status": execution.get("status"),
            "filled_qty": execution.get("filled_qty"),
            "replacements": execution.get("replacements"),
            "plan_schema": execution.get("plan_schema"),
            "plan_cycle_id": execution.get("plan_cycle_id"),
            "plan_candidate_id": execution.get("plan_candidate_id"),
            "plan_evidence_refs": execution.get("plan_evidence_refs"),
            "exit_policy": execution.get("exit_policy"),
            "order": execution.get("order"),
            "broker_order_id": _object(execution.get("result", {}), "broker result").get("id"),
        },
    }
    _append_journal(record)


def _journal_diagnostic(kind: str, details: dict[str, Any]) -> None:
    _append_journal({
        "at": datetime.now(timezone.utc).isoformat(),
        "action": kind,
        "outcome": "observed",
        "rationale": kind.replace("_", " "),
        "details": details,
    })


def _action_underlying(action: dict[str, Any]) -> str:
    explicit = str(action.get("underlying") or "").upper()
    if explicit:
        return explicit
    symbol = str(action.get("symbol") or "").upper()
    return _option_underlying(symbol) or symbol


def _cooldown_active(state: dict[str, Any], symbol: str, *, now: datetime) -> bool:
    symbols = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    item = symbols.get(symbol) if isinstance(symbols.get(symbol), dict) else {}
    raw = item.get("last_exit_at")
    if not isinstance(raw, str):
        return False
    try:
        exited = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if (
        os.environ.get("MANDATE_ALLOW_SAME_DAY_REENTRY", "true").lower() != "true"
        and exited.astimezone(NEW_YORK).date() == now.astimezone(NEW_YORK).date()
    ):
        return True
    minutes = max(0, int(os.environ.get("MANDATE_REENTRY_COOLDOWN_MINUTES", "10")))
    return now - exited.astimezone(timezone.utc) < timedelta(minutes=minutes)


def _record_fills(state: dict[str, Any], executions: list[dict[str, Any]]) -> None:
    symbols = state.setdefault("symbols", {})
    if not isinstance(symbols, dict):
        symbols = {}
        state["symbols"] = symbols
    at = datetime.now(timezone.utc).isoformat()
    for execution in executions:
        if execution.get("filled") is not True:
            continue
        symbol = _action_underlying({
            "symbol": execution.get("candidate"),
            "underlying": execution.get("underlying"),
        })
        if not symbol:
            continue
        item = symbols.setdefault(symbol, {})
        if not isinstance(item, dict):
            item = {}
            symbols[symbol] = item
        kind = str(execution.get("kind") or "")
        if kind in EXIT_ACTION_KINDS:
            item["last_exit_at"] = at
            item.pop("first_seen_at", None)
        else:
            item["last_entry_at"] = at
            item.setdefault("first_seen_at", at)
    state["updated_at"] = at


def _run_actions(
    broker: PaperBroker,
    actions: list[dict[str, Any]],
    *,
    checked_at: Any,
    start_index: int = 0,
) -> tuple[list[dict[str, Any]], list[str]]:
    executions: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, action in enumerate(actions, start=start_index):
        try:
            execution = execute_with_lifecycle(
                broker, action, checked_at=checked_at, index=index,
            )
            executions.append(execution)
            _journal(execution)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{action['symbol']} {action['kind']}: {str(exc)[:180]}")
    return executions, errors


def _execution_is_complete(action: dict[str, Any], execution: dict[str, Any]) -> bool:
    if str(execution.get("status") or "").lower() != "filled":
        return False
    try:
        requested = _decimal(action.get("qty"), "planned quantity")
        filled = _decimal(execution.get("filled_qty") or 0, "filled quantity")
    except ValueError:
        return False
    return requested > ZERO and filled >= requested


def _live_underlyings(broker: PaperBroker) -> set[str]:
    result: set[str] = set()
    for position in broker.positions():
        symbol = str(position.get("symbol") or "").upper()
        if symbol:
            result.add(_option_underlying(symbol) or symbol)
    return result


def _option_risk_reserve(position: dict[str, Any]) -> Decimal:
    """Conservatively reserve at least marked value and original option cost."""
    values: list[Decimal] = []
    for key, label in (("market_value", "option market value"), ("cost_basis", "option cost basis")):
        raw = position.get(key)
        if raw in {None, ""}:
            continue
        values.append(abs(_decimal(raw, label)))
    if not values:
        raise ValueError(f"cannot determine option risk for {position.get('symbol', 'unknown')}")
    return max(values)


def _run_plan_actions(
    broker: PaperBroker,
    actions: list[dict[str, Any]],
    *,
    checked_at: Any,
    start_index: int,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Execute an ordered plan and stop after the first non-complete step."""
    executions: list[dict[str, Any]] = []
    errors: list[str] = []
    halt: dict[str, Any] = {"halted": False, "reason": None, "skipped": 0}
    for offset, action in enumerate(actions):
        candidate_id = str(action.get("plan_candidate_id") or action.get("symbol") or "")
        underlying = _action_underlying(action)
        try:
            if underlying in _live_underlyings(broker):
                raise ValueError(f"live position conflict for {underlying}")
            execution = execute_with_lifecycle(
                broker, action, checked_at=checked_at, index=start_index + offset,
            )
            executions.append(execution)
            _journal(execution)
            if _execution_is_complete(action, execution):
                continue
            filled = _decimal(execution.get("filled_qty") or 0, "filled quantity")
            status = str(execution.get("status") or "unknown").lower()
            category = "partial" if filled > ZERO else (
                "reject" if status == "rejected" else "timeout_or_unfilled"
            )
            halt = {
                "halted": True,
                "reason": f"{category}:{candidate_id}:{status}",
                "skipped": len(actions) - offset - 1,
            }
            break
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{candidate_id} plan step: {str(exc)[:180]}")
            halt = {
                "halted": True,
                "reason": f"conflict_or_error:{candidate_id}",
                "skipped": len(actions) - offset - 1,
            }
            break
    return executions, errors, halt


def _whole_plan_risk_error(
    risk_gate: dict[str, Any],
    actions: list[dict[str, Any]],
    expected_steps: int,
) -> str | None:
    if len(actions) != expected_steps:
        return f"plan resolved {len(actions)} of {expected_steps} canonical steps"
    orders_today = int(risk_gate.get("orders_today") or 0)
    max_orders = int(risk_gate.get("max_orders_per_day") or 0)
    if max_orders <= 0 or orders_today + len(actions) > max_orders:
        return f"whole plan exceeds order budget: {orders_today}+{len(actions)}>{max_orders}"
    return None


def _execute_locked(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if evaluation.get("market_is_open") is not True:
        return {
            "action": "PARK", "submitted": False, "filled": False,
            "reason": "regular market session is closed; no paper order sent",
            "executions": [], "errors": [],
        }
    broker = PaperBroker()
    recovered_orders = _cancel_tagged_open_orders(broker)
    account = broker.account()
    positions = broker.positions()
    checked_at = datetime.now(timezone.utc)
    state = _read_execution_state()
    state_symbols = state.setdefault("symbols", {})
    if not isinstance(state_symbols, dict):
        state_symbols = {}
        state["symbols"] = state_symbols
    live_option_underlyings: set[str] = set()
    for position in positions:
        if str(position.get("asset_class", "")) != "us_option":
            continue
        underlying = _option_underlying(str(position.get("symbol", "")).upper())
        if not underlying:
            continue
        live_option_underlyings.add(underlying)
        item = state_symbols.setdefault(underlying, {})
        if isinstance(item, dict):
            item.setdefault("first_seen_at", checked_at.isoformat())
    for symbol, item in state_symbols.items():
        if isinstance(item, dict) and symbol not in live_option_underlyings:
            item.pop("first_seen_at", None)
    after_flatten = _after_flatten_window(checked_at)
    exit_limit = max(2, len(positions)) if after_flatten else 2
    equity_exit_health: dict[str, Any] = {"healthy": True, "issues": []}
    equity_exits = select_exits(
        evaluation, positions, limit=exit_limit, health=equity_exit_health,
    )
    option_first_seen = {
        symbol: str(item.get("first_seen_at"))
        for symbol, item in state_symbols.items()
        if isinstance(item, dict) and item.get("first_seen_at")
    }
    option_exits = select_option_exits(
        positions, now=checked_at, limit=exit_limit, first_seen=option_first_seen,
    )
    exit_actions = equity_exits + option_exits
    executions, errors = _run_actions(
        broker, exit_actions, checked_at=evaluation.get("checked_at"),
    )
    hard_exit_incomplete = equity_exit_health.get("healthy") is not True or bool(errors) or len(executions) != len(exit_actions) or any(
        not _execution_is_complete(action, result)
        for action, result in zip(exit_actions, executions)
    )

    # A submitted exit may remain partially filled. Refresh actual positions
    # before admitting reversals or computing the remaining option risk budget.
    if exit_actions:
        positions = broker.positions()
        account = broker.account()
    equity = _decimal(account.get("equity", 0), "account equity")
    existing_underlyings: set[str] = set()
    for item in positions:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        existing_underlyings.add(_option_underlying(symbol) or symbol)
    # A symbol that received a fill on an exit this cycle is never re-entered in
    # the same cycle, and a fully closed symbol forgets its first-seen timestamp
    # so the next entry starts a fresh time-stop clock.
    exited_underlyings = {
        _action_underlying({"symbol": item.get("candidate"), "underlying": item.get("underlying")})
        for item in executions
        if item.get("filled") is True and str(item.get("kind") or "") in EXIT_ACTION_KINDS
    }
    exited_underlyings.discard("")
    closed_underlyings = exited_underlyings - existing_underlyings
    if closed_underlyings:
        clear_position_tracking(closed_underlyings)
    existing_underlyings |= exited_underlyings
    limits = _mandate_limits()
    risk_gate = _entry_risk_gate(broker, account, limits)
    plan: dict[str, Any] | None = None
    plan_error: str | None = None
    try:
        plan = _trade_plan(evaluation, decision)
    except ValueError as exc:
        plan_error = f"invalid trade plan: {str(exc)[:180]}"
    entry_blocked = after_flatten or risk_gate["allow_entries"] is not True or hard_exit_incomplete
    entries: list[dict[str, Any]] = []
    if plan is not None and plan["action"] == "EXECUTE_PLAN" and not entry_blocked:
        entries = select_entries(
            evaluation, decision, existing_symbols=existing_underlyings, limit=MAX_PLAN_STEPS,
        )
        entries = [
            entry for entry in entries
            if not _cooldown_active(state, str(entry["symbol"]), now=checked_at)
        ]
    option_exposure = sum(
        _option_risk_reserve(item)
        for item in positions if str(item.get("asset_class", "")) == "us_option"
    )
    buying_power = max(Decimal("0"), _decimal(account.get("buying_power") or account.get("cash") or 0, "buying power"))
    gross_limit_pct = _configured_limit(
        limits, "max_gross_exposure_pct", "MANDATE_MAX_GROSS_EXPOSURE_PCT", "100"
    )
    position_limit_pct = _configured_limit(
        limits, "max_position_pct", "MANDATE_MAX_POSITION_PCT", "40"
    )
    if gross_limit_pct <= 0 or gross_limit_pct > Decimal("400"):
        raise ValueError("MANDATE_MAX_GROSS_EXPOSURE_PCT must be greater than 0 and at most 400")
    if position_limit_pct <= 0 or position_limit_pct > Decimal("100"):
        raise ValueError("MANDATE_MAX_POSITION_PCT must be greater than 0 and at most 100")
    existing_gross = sum(
        abs(_decimal(item.get("market_value") or 0, "position market value")) for item in positions
    )
    portfolio_headroom = min(
        buying_power,
        max(Decimal("0"), equity * gross_limit_pct / Decimal("100") - existing_gross),
    )
    option_slots = max(0, min(2, int(os.environ.get("MANDATE_OPTIONS_PER_CYCLE", "1"))))
    entry_actions: list[dict[str, Any]] = []
    option_status: dict[str, Any] = {
        "enabled": os.environ.get("MANDATE_OPTIONS_ENABLED", "true").lower() == "true",
        "approved_level": int(account.get("options_approved_level") or account.get("options_trading_level") or 0),
        "attempted": 0,
        "constructed": 0,
        "fallbacks": [],
    }
    execution_context = evaluation.get("execution_context")
    execution_context = execution_context if isinstance(execution_context, dict) else {}
    ipo_symbols = {
        str(value).strip().upper() for value in execution_context.get("ipo_symbols", [])
        if str(value).strip()
    }
    build_error: str | None = None
    strict_plan = plan is not None and plan.get("schema") == TRADE_PLAN_SCHEMA
    for entry in entries:
        action: dict[str, Any] | None = None
        if len(entry_actions) < option_slots:
            option_status["attempted"] += 1
            try:
                action = build_option_order(broker, entry, account, option_exposure=option_exposure)
            except (RuntimeError, ValueError) as exc:
                option_status["fallbacks"].append({
                    "symbol": entry["symbol"], "reason": f"{type(exc).__name__}:{str(exc)[:120]}"
                })
                action = None
            if action is None and not any(
                item.get("symbol") == entry["symbol"] for item in option_status["fallbacks"]
            ):
                option_status["fallbacks"].append({
                    "symbol": entry["symbol"],
                    "reason": "disabled_permission_liquidity_or_option_risk_gate",
                })
            elif action is not None:
                option_status["constructed"] += 1
        if action is None:
            asset = broker.asset(str(entry["symbol"]))
            if asset.get("tradable") is not True:
                if strict_plan:
                    build_error = f"{entry['plan_candidate_id']} canonical asset is not tradable"
                    break
                continue
            if entry["side"] == "sell" and (
                asset.get("shortable") is not True or asset.get("easy_to_borrow") is not True
            ):
                if strict_plan:
                    build_error = f"{entry['plan_candidate_id']} canonical short is unavailable"
                    break
                continue
            action = entry
        action = _cap_ipo_action(action, equity, ipo_symbols)
        if not action:
            if strict_plan:
                build_error = f"{entry['plan_candidate_id']} failed the IPO position cap"
                break
            continue
        action_headroom = min(portfolio_headroom, equity * position_limit_pct / Decimal("100"))
        bounded, allocated = _cap_entry_to_headroom(action, action_headroom)
        if bounded is None:
            if strict_plan:
                build_error = f"{entry['plan_candidate_id']} has insufficient portfolio headroom"
                break
            continue
        action = bounded
        portfolio_headroom -= allocated
        if action.get("kind") in OPTION_ACTION_KINDS:
            option_exposure += (
                _decimal(action["qty"], "option quantity")
                * _decimal(action["limit_price"], "option limit price")
                * Decimal("100")
            )
        entry_actions.append(action)

    expected_steps = len(plan["steps"]) if plan is not None and plan["action"] == "EXECUTE_PLAN" else 0
    if strict_plan and expected_steps:
        build_error = build_error or _whole_plan_risk_error(risk_gate, entry_actions, expected_steps)
        if build_error:
            entry_actions = []
            plan_error = f"whole plan rejected: {build_error}"

    fallback_signature = json.dumps(option_status["fallbacks"], sort_keys=True)
    if option_status["fallbacks"] and state.get("last_option_fallback") != fallback_signature:
        _journal_diagnostic("option_fallback", option_status)
        state["last_option_fallback"] = fallback_signature
    risk_signature = json.dumps(risk_gate["reasons"], sort_keys=True)
    if risk_gate["allow_entries"] is not True and state.get("last_risk_gate") != risk_signature:
        _journal_diagnostic("entry_risk_gate", risk_gate)
        state["last_risk_gate"] = risk_signature
    elif risk_gate["allow_entries"] is True:
        state.pop("last_risk_gate", None)

    entry_executions, entry_errors, plan_execution = _run_plan_actions(
        broker,
        entry_actions,
        checked_at=evaluation.get("checked_at"),
        start_index=len(exit_actions),
    )
    executions.extend(entry_executions)
    errors.extend(entry_errors)
    _record_fills(state, executions)
    _write_execution_state(state)
    actions = exit_actions + entry_actions
    accepted = [
        item for item in executions
        if item.get("accepted") is True
        and (item.get("filled") is True or item.get("status") not in {"canceled", "rejected", "expired"})
    ]
    filled = [item for item in executions if item.get("filled") is True]
    plan_status = {
        "schema": plan.get("schema") if plan is not None else None,
        "source": plan.get("source") if plan is not None else None,
        "cycle_id": plan.get("cycle_id") if plan is not None else None,
        "action": plan.get("action") if plan is not None else None,
        "reason": plan.get("reason") if plan is not None else None,
        "planned_steps": expected_steps,
        "validated_steps": len(entry_actions),
        "error": plan_error,
        **plan_execution,
    }
    if not actions:
        gate_reason = "; ".join(risk_gate["reasons"])
        return {
            "action": "PARK", "submitted": False, "filled": False,
            "reason": (
                "intraday flatten window: new entries parked" if after_flatten
                else "automatic hard exit did not complete; new entries parked" if hard_exit_incomplete
                else f"entry risk gate: {gate_reason}" if gate_reason
                else plan_error if plan_error
                else str(plan.get("reason")) if plan is not None and plan.get("action") == "PARK"
                else "no exit or challenged entry"
            ),
            "executions": executions, "errors": errors, "risk_gate": risk_gate,
            "option_status": option_status, "recovered_orders": recovered_orders,
            "trade_plan": plan_status,
            "exit_health": equity_exit_health,
        }
    if not accepted:
        return {
            "action": "PARK", "submitted": False, "filled": False,
            "reason": "; ".join(errors[:3]) or "portfolio actions remained unfilled and were cancelled",
            "executions": executions, "errors": errors, "risk_gate": risk_gate,
            "option_status": option_status, "recovered_orders": recovered_orders,
            "trade_plan": plan_status,
            "exit_health": equity_exit_health,
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
        "risk_gate": risk_gate,
        "option_status": option_status,
        "recovered_orders": recovered_orders,
        "trade_plan": plan_status,
        "exit_health": equity_exit_health,
    }


def execute(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Serialize the complete broker reconciliation and submission transaction."""
    path = _execution_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            return _execute_locked(evaluation, decision)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute one aggressive paper portfolio cycle directly through Alpaca")
    parser.add_argument("--evaluation-path", required=True)
    parser.add_argument("--decision-path", required=True)
    args = parser.parse_args()
    evaluation = _object(json.loads(Path(args.evaluation_path).read_text(encoding="utf-8")), "evaluation")
    decision = _object(json.loads(Path(args.decision_path).read_text(encoding="utf-8")), "decision")
    print(json.dumps(execute(evaluation, decision), ensure_ascii=False, default=str))
