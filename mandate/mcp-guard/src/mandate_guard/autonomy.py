from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Trajectory(BaseModel):
    """Operator-owned preferences for the read-only autonomous research loop.

    These preferences can narrow attention and change research cadence, but they
    never grant execution authority or replace the human-authored mandate.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    enabled: bool = True
    execution_mode: Literal["approval", "auto_paper"] = "approval"
    symbols: list[str] = Field(default_factory=lambda: [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AMD", "AVGO", "ORCL",
        "IBM", "PLTR", "CRM", "ANET", "TSM", "ASML", "ARM", "BABA", "BIDU", "SPY",
    ])
    news_poll_seconds: int = Field(default=60, ge=30, le=3600)
    analysis_interval_minutes: int = Field(default=15, ge=5, le=1440)
    monitoring_mode: Literal["realtime", "polling"] = "realtime"
    market_data_feed: Literal["auto", "iex", "sip"] = "auto"
    discovery_enabled: bool = True
    discovery_top: int = Field(default=10, ge=1, le=50)
    regular_hours_only: bool = True
    max_spread_bps: int = Field(default=35, ge=1, le=1000)
    min_relative_volume: Decimal = Field(default=Decimal("0.25"), ge=0, le=100)
    monitor_corporate_actions: bool = True
    options_confirmation: bool = False
    risk_posture: Literal["defensive", "balanced", "opportunistic"] = "balanced"
    thesis: str = Field(
        default="Prefer explainable, price-confirmed signals and park when evidence conflicts.",
        max_length=2000,
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str = Field(default="bootstrap", min_length=1, max_length=120)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if not normalized or any(not value for value in normalized):
            raise ValueError("trajectory requires at least one nonblank symbol")
        if len(set(normalized)) != len(normalized):
            raise ValueError("trajectory symbols must be unique")
        return normalized

    @field_validator("thesis")
    @classmethod
    def normalize_thesis(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("trajectory thesis cannot be blank")
        return normalized


class AutonomyStore:
    def __init__(self, path: str | Path, alerts_path: str | Path) -> None:
        self.path = Path(path)
        self.alerts_path = Path(alerts_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> Trajectory:
        if not self.path.exists():
            trajectory = Trajectory()
            self._write(trajectory)
            return trajectory
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("autonomy trajectory is unreadable") from exc
        trajectory = Trajectory.model_validate(payload)
        if set(payload) != set(trajectory.model_dump(mode="json")):
            self._write(trajectory)
        return trajectory

    def update(
        self,
        *,
        mandate_symbols: list[str],
        updated_by: str,
        enabled: bool | None = None,
        execution_mode: str | None = None,
        symbols: list[str] | None = None,
        news_poll_seconds: int | None = None,
        analysis_interval_minutes: int | None = None,
        risk_posture: str | None = None,
        thesis: str | None = None,
        monitoring_mode: str | None = None,
        market_data_feed: str | None = None,
        discovery_enabled: bool | None = None,
        discovery_top: int | None = None,
        regular_hours_only: bool | None = None,
        max_spread_bps: int | None = None,
        min_relative_volume: Decimal | None = None,
        monitor_corporate_actions: bool | None = None,
        options_confirmation: bool | None = None,
    ) -> Trajectory:
        current = self.read()
        changes: dict[str, Any] = {
            "version": current.version + 1,
            "updated_at": datetime.now(timezone.utc),
            "updated_by": updated_by,
        }
        for key, value in {
            "enabled": enabled,
            "execution_mode": execution_mode,
            "symbols": symbols,
            "news_poll_seconds": news_poll_seconds,
            "analysis_interval_minutes": analysis_interval_minutes,
            "risk_posture": risk_posture,
            "thesis": thesis,
            "monitoring_mode": monitoring_mode,
            "market_data_feed": market_data_feed,
            "discovery_enabled": discovery_enabled,
            "discovery_top": discovery_top,
            "regular_hours_only": regular_hours_only,
            "max_spread_bps": max_spread_bps,
            "min_relative_volume": min_relative_volume,
            "monitor_corporate_actions": monitor_corporate_actions,
            "options_confirmation": options_confirmation,
        }.items():
            if value is not None:
                changes[key] = value
        updated = current.model_copy(update=changes)
        # model_copy does not revalidate updates in Pydantic v2.
        updated = Trajectory.model_validate(updated.model_dump())
        allowed = {symbol.strip().upper() for symbol in mandate_symbols}
        outside = sorted(set(updated.symbols) - allowed)
        if outside:
            raise ValueError(f"trajectory cannot expand mandate universe: {', '.join(outside)}")
        self._write(updated)
        return updated

    def recent_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 100))
        if not self.alerts_path.exists():
            return []
        lines = self.alerts_path.read_text(encoding="utf-8").splitlines()
        alerts: list[dict[str, Any]] = []
        for line in lines[-bounded:]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                alerts.append(payload)
        return alerts

    def _write(self, trajectory: Trajectory) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = trajectory.model_dump(mode="json")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
