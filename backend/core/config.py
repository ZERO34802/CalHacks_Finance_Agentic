"""Loads config/policy.yaml into a typed Policy. Amounts become Decimal."""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "policy.yaml"


class Materiality(BaseModel):
    abs: Decimal
    pct: Decimal


class Tolerances(BaseModel):
    qty_pct: Decimal
    price_pct: Decimal


class Accounts(BaseModel):
    ap_control: str
    expense_default: str
    freight: str


class Policy(BaseModel):
    materiality: Materiality
    tolerances: Tolerances
    approval_limits: dict[str, Decimal]
    locked_periods: list[str]
    fx_rates: dict[str, Decimal]
    accounts: Accounts
    skills: dict[str, str]
    sla: dict[str, Any] = {}
    probation: dict[str, Any] = {}
    queue: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    onboarding: dict[str, Any] = {}
    release: dict[str, Any] = {}


@lru_cache
def load_policy(path: Path = POLICY_PATH) -> Policy:
    return Policy.model_validate(yaml.safe_load(path.read_text()))
