from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mandate_guard.wake import parse_wake_condition


Percentage = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
Instrument = Literal["equity"]
OrderType = Literal["limit", "market"]
SessionPolicy = Literal["regular_hours_only"]


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_position_pct: Percentage
    max_gross_exposure_pct: Percentage
    max_daily_loss_pct: Percentage
    max_orders_per_day: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def position_cannot_exceed_gross(self) -> "Limits":
        if self.max_position_pct > self.max_gross_exposure_pct:
            raise ValueError("max_position_pct cannot exceed max_gross_exposure_pct")
        return self


class Predecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    when: Annotated[str, Field(min_length=1)]
    then: Literal["park_new_orders"]
    reason: Annotated[str, Field(min_length=1)]

    @field_validator("when")
    @classmethod
    def condition_must_use_guard_metric(cls, expression: str) -> str:
        condition = parse_wake_condition(expression)
        if condition.metric not in {"daily_loss_pct", "single_symbol_move_pct"}:
            raise ValueError("predecision metric must be observable before an order")
        return expression


class Mandate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1)]
    universe: Annotated[list[str], Field(min_length=1)]
    instruments: Annotated[list[Instrument], Field(min_length=1)]
    order_types: Annotated[list[OrderType], Field(min_length=1)]
    session: SessionPolicy
    limits: Limits
    wake_me_if: list[str] = Field(default_factory=list)
    predecided: list[Predecision] = Field(default_factory=list)
    allow_risk_reducing_market_close: bool = True
    expires: datetime

    @field_validator("universe")
    @classmethod
    def normalize_universe(cls, symbols: list[str]) -> list[str]:
        normalized = [symbol.strip().upper() for symbol in symbols]
        if any(not symbol for symbol in normalized):
            raise ValueError("universe symbols cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("universe symbols must be unique")
        return normalized

    @field_validator("instruments", "order_types")
    @classmethod
    def reject_duplicates(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("values must be unique")
        return values

    @field_validator("wake_me_if")
    @classmethod
    def validate_wake_conditions(cls, expressions: list[str]) -> list[str]:
        for expression in expressions:
            parse_wake_condition(expression)
        return expressions

    @field_validator("expires")
    @classmethod
    def expiry_must_be_aware_and_future(cls, expires: datetime) -> datetime:
        if expires.tzinfo is None or expires.utcoffset() is None:
            raise ValueError("expires must include a timezone")
        if expires <= datetime.now(timezone.utc):
            raise ValueError("mandate has already expired")
        return expires


def load_mandate(path: str | Path) -> Mandate:
    mandate_path = Path(path)
    raw = yaml.safe_load(mandate_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mandate must be a YAML mapping")
    return Mandate.model_validate(raw)
