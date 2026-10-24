"""Decimal-only money helpers. Never float."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from backend.core.config import Policy

CENT = Decimal("0.01")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def parse_decimal(value: object, field: str = "amount") -> Decimal:
    """Strict decimal parse. Accepts '1,240.00', ' 40 ', Decimal, int. Rejects anything else."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field}: missing or invalid value {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):  # never trust binary floats for money
        raise ValueError(f"{field}: float not allowed ({value!r}); send a decimal string")
    s = str(value).strip().replace(",", "").replace(" ", "").replace(" ", "")
    if not _NUM.match(s):
        raise ValueError(f"{field}: not a decimal number: {value!r}")
    try:
        return Decimal(s)
    except InvalidOperation as e:  # pragma: no cover - regex guards this
        raise ValueError(f"{field}: {value!r}") from e


def q2(d: Decimal) -> Decimal:
    return d.quantize(CENT)


def to_usd(amount: Decimal, currency: str, policy: Policy) -> Optional[Decimal]:
    rate = policy.fx_rates.get(currency)
    return None if rate is None else q2(amount * rate)


def convert(amount: Decimal, src: str, dst: str, policy: Policy) -> Optional[Decimal]:
    """FX only via the policy table (SIMULATED)."""
    rs, rd = policy.fx_rates.get(src), policy.fx_rates.get(dst)
    if rs is None or rd is None or rd == 0:
        return None
    return q2(amount * rs / rd)
