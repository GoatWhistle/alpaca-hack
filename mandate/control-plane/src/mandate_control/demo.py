from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


SCENARIOS: tuple[dict[str, Any], ...] = (
    {"symbol": "NVDA", "qty": "12", "entry": "217.20", "current": "220.14", "headline": "AI accelerator shipments move ahead of the expected production ramp", "summary": "Price confirmation, relative volume and the benchmark regime align with the event signal."},
    {"symbol": "MSFT", "qty": "8", "entry": "513.30", "current": "518.74", "headline": "Cloud backlog expands as enterprise AI deployments accelerate", "summary": "The agent found a confirmed trend signal with enough mandate headroom for a bounded position."},
    {"symbol": "AAPL", "qty": "15", "entry": "319.60", "current": "323.11", "headline": "Supply-chain checks point to stronger device availability", "summary": "Fresh pricing and spread checks passed; the risk critic reduced the initial position size."},
    {"symbol": "GOOGL", "qty": "14", "entry": "346.40", "current": "351.22", "headline": "New enterprise model contracts support cloud demand outlook", "summary": "News novelty and price momentum agree while portfolio concentration remains inside limits."},
    {"symbol": "AMZN", "qty": "18", "entry": "266.20", "current": "270.15", "headline": "AWS capacity additions arrive ahead of the next demand window", "summary": "The signal passed liquidity, staleness, SPY-regime and deterministic ATR sizing checks."},
    {"symbol": "META", "qty": "6", "entry": "577.70", "current": "586.90", "headline": "Advertising demand remains firm alongside lower infrastructure costs", "summary": "The challenge agent found no mandate breach; execution still waits for the operator."},
)


def _now() -> str:
    return _utcnow().isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dynamic_position(item: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Mark a rehearsal position along a monotonic one-minute price path."""
    entry = Decimal(str(item.get("avg_entry_price", "0")))
    target = Decimal(str(item.get("target_price", item.get("market_price", entry))))
    qty = Decimal(str(item.get("qty", "0")))
    try:
        opened_at = datetime.fromisoformat(str(item["opened_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        opened_at = now
    elapsed = max(Decimal("0"), Decimal(str((now - opened_at).total_seconds())))
    linear = min(Decimal("1"), elapsed / Decimal("60"))
    # Ease out without downward ticks: fast enough to read on video, gradual
    # enough that equity, market value and P&L visibly change over many polls.
    progress = Decimal("1") - (Decimal("1") - linear) ** 2
    current = (entry + (target - entry) * progress).quantize(Decimal("0.01"))
    market_value = (qty * current).quantize(Decimal("0.01"))
    pnl = (qty * (current - entry)).quantize(Decimal("0.01"))
    return {
        "qty": str(item.get("qty", "0")),
        "market_price": str(current),
        "market_value": str(market_value),
        "avg_entry_price": str(entry),
        "unrealized_pl": str(max(Decimal("0"), pnl)),
    }


class DemoStore:
    """Persistent, deterministic rehearsal state. It never calls a broker."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"enabled": False, "kind": "simulated"}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"enabled": False, "kind": "simulated"}
        return payload if isinstance(payload, dict) else {"enabled": False, "kind": "simulated"}

    def set_enabled(self, enabled: bool, *, execution_mode: str) -> dict[str, Any]:
        if enabled and execution_mode != "approval":
            raise ValueError("simulation is available only in manual approval mode")
        if not enabled:
            state = self.read()
            state["enabled"] = False
            self._write(state)
            return state
        state = {
            "enabled": True,
            "kind": "simulated",
            "started_at": _now(),
            "step": 0,
            "positions": {},
            "journal": [],
            "orders_today": 0,
        }
        self._write(state)
        return state

    def respond(self, tool_call_id: str, approve: bool) -> dict[str, Any]:
        state = self.read()
        if not state.get("enabled"):
            raise ValueError("simulation is not active")
        step = int(state.get("step", 0))
        expected = f"sim-call-{step + 1}"
        if step >= len(SCENARIOS) or tool_call_id != expected:
            raise ValueError("simulation decision is no longer pending")
        scenario = SCENARIOS[step]
        outcome = "denied"
        rationale = "Operator refused the proposed order; no paper position was opened."
        if approve:
            entry = Decimal(scenario["entry"])
            state.setdefault("positions", {})[scenario["symbol"]] = {
                "qty": scenario["qty"],
                "avg_entry_price": str(entry),
                "target_price": scenario["current"],
                "opened_at": _now(),
            }
            state["orders_today"] = int(state.get("orders_today", 0)) + 1
            outcome = "submitted"
            rationale = "Operator approved; Alpaca accepted the direct paper order."
        state.setdefault("journal", []).append(
            {
                "at": _now(),
                "action": "place_stock_order",
                "outcome": outcome,
                "rationale": rationale,
                "details": {
                    "intent_id": f"sim-intent-{step + 1}",
                    "order_id": f"sim-order-{step + 1}" if approve else None,
                    "order": {
                        "symbol": scenario["symbol"],
                        "side": "buy",
                        "qty": scenario["qty"],
                        "limit_price": scenario["entry"],
                    },
                },
            }
        )
        state["step"] = step + 1
        self._write(state)
        return state

    def overlay(self, payload: dict[str, Any], *, force_sanitized: bool = False) -> dict[str, Any]:
        state = self.read()
        payload["demo"] = {
            "enabled": bool(state.get("enabled")),
            "kind": "simulated",
            "complete": int(state.get("step", 0)) >= len(SCENARIOS),
        }
        if not state.get("enabled") and force_sanitized:
            payload["agent_url"] = ""
            payload["services"] = [
                {"name": item.get("name", "service"), "url": "", "ok": bool(item.get("ok"))}
                for item in payload.get("services", [])
                if isinstance(item, dict)
            ]
            payload["session"] = {
                "as_of": payload.get("generated_at"),
                "account": {
                    "status": "ACTIVE",
                    "equity": "100000.00",
                    "daily_pnl": "0.00",
                    "gross_exposure_pct": "0.00",
                },
                "market": {"is_open": False},
                "positions": {},
                "orders_today": 0,
                "pending_orders": [],
                "journal": [],
            }
            payload["approvals"] = {"count": 0, "items": []}
            return payload
        if not state.get("enabled"):
            return payload
        if force_sanitized:
            payload["agent_url"] = ""
            payload["services"] = [
                {"name": item.get("name", "service"), "url": "", "ok": bool(item.get("ok"))}
                for item in payload.get("services", [])
                if isinstance(item, dict)
            ]
        stored_positions = state.get("positions", {}) if isinstance(state.get("positions"), dict) else {}
        now = _utcnow()
        positions = {
            symbol: _dynamic_position(item, now)
            for symbol, item in stored_positions.items()
            if isinstance(item, dict)
        }
        total_pnl = sum(
            (Decimal(str(item.get("unrealized_pl", "0"))) for item in positions.values()),
            Decimal("0"),
        )
        market_value = sum(
            (Decimal(str(item.get("market_value", "0"))) for item in positions.values()),
            Decimal("0"),
        )
        equity = Decimal("100000") + total_pnl
        session = payload["session"]
        session["account"] = {
            "status": "ACTIVE",
            "equity": str(equity.quantize(Decimal("0.01"))),
            "daily_pnl": str(total_pnl.quantize(Decimal("0.01"))),
            "gross_exposure_pct": str((market_value / equity * 100).quantize(Decimal("0.01"))),
        }
        session["positions"] = positions
        session["orders_today"] = int(state.get("orders_today", 0))
        session["pending_orders"] = []
        session["journal"] = state.get("journal", [])
        step = int(state.get("step", 0))
        pending: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        visible_count = min(step + 1, len(SCENARIOS))
        for index, scenario in enumerate(SCENARIOS[:visible_count]):
            alerts.append({
                "kind": "news",
                "source": "market-wire",
                "external_id": f"sim-news-{index + 1}",
                "published_at": state.get("started_at", _now()),
                "headline": scenario["headline"],
                "summary": scenario["summary"],
                "symbols": [scenario["symbol"]],
            })
        if step < len(SCENARIOS):
            scenario = SCENARIOS[step]
            pending.append({
                "session_id": "demo-safety",
                "session_title": "Safety approval rehearsal",
                "thread_id": "sim-thread",
                "tool_call_id": f"sim-call-{step + 1}",
                "tool_name": "place_stock_order",
                "created_at": state.get("started_at", _now()),
                "sequence": {"current": step + 1, "total": len(SCENARIOS)},
                "arguments": {
                    "intent_id": f"sim-intent-{step + 1}",
                    "symbol": scenario["symbol"],
                    "side": "buy",
                    "qty": scenario["qty"],
                    "order_type": "limit",
                    "limit_price": scenario["entry"],
                    "atr14": "6.42",
                    "signal_strength": "0.86",
                    "risk_budget_pct": "0.80",
                    "safety_checks": [
                        "Fresh price + spread",
                        "ATR-sized position",
                        "Mandate headroom",
                        "Risk critic passed",
                        "Human approval required",
                    ],
                    "rationale": scenario["summary"],
                },
            })
        payload["approvals"] = {"count": len(pending), "items": pending}
        payload["autonomy"]["alerts"] = alerts
        payload["autonomy"]["runtime"] = {
            "status": "awaiting_approval" if pending else "rehearsal_complete",
            "last_action": "PROPOSE" if pending else "COMPLETE",
            "delivered_alerts": len(alerts),
            "quality_pass": visible_count,
            "quality_total": visible_count,
        }
        return payload

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(self.path)
