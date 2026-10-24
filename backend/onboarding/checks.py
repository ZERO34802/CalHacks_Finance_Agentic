"""Vendor onboarding checks (CLAUDE.md 10d step 3). Owner: A. Deterministic; SIMULATED sources labeled.

run_checks(req, ctx) -> list[OnboardingCheck]. A failed check's `name` is the flag C's answer key uses
(data/onboarding/answer_key.json):
  duplicate_tax_id       same tax id as an existing vendor
  duplicate_bank         same bank last4 as an existing vendor
  duplicate_domain       same email domain as an existing vendor
  sanctions_hit          name or tax id on data/world/sanctions_simulated.json (SIMULATED list)
  bank_matches_employee  bank last4 equals an employee's (insider-fraud signal)
  lookalike_domain       domain imitates an existing vendor's domain (normalized edit distance)
  missing_tax_form       no tax form / invalid_tax_form: wrong form (W-9 for US, W-8BEN-E foreign)
  domain_age             SIMULATED: data/world/domain_ages_simulated.json (days); < 90 days fails; absent passes
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from backend.core.stage import Ctx
from backend.evals.fixtures import WORLD
from backend.intake.ingest import closest_vendor
from contracts import OnboardingCheck, OnboardingRequest

MIN_DOMAIN_AGE_DAYS = 90


def _json(name: str, default):
    p = WORLD / name
    return json.loads(p.read_text()) if p.exists() else default


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return " ".join(w for w in s.split() if w not in {"co", "ltd", "llc", "inc", "sdn", "bhd", "corp", "the"})


def run_checks(req: OnboardingRequest, ctx: Ctx) -> list[OnboardingCheck]:
    vendors = ctx.store.list_vendors()
    out: list[OnboardingCheck] = []

    def add(name: str, failed_detail: Optional[str], ok_detail: str, simulated: bool = False) -> None:
        out.append(OnboardingCheck(name=name, passed=failed_detail is None,
                                   detail=failed_detail or ok_detail, simulated=simulated))

    tax = _norm(req.tax_id)
    dup = [v for v in vendors if tax and _norm(v.tax_id) == tax]
    add("duplicate_tax_id", f"tax id {req.tax_id} already on {', '.join(v.id for v in dup)}" if dup else None,
        "tax id unique")
    dupb = [v for v in vendors if v.bank_last4 == req.bank_last4]
    add("duplicate_bank", f"bank ****{req.bank_last4} already on {', '.join(v.id for v in dupb)}" if dupb else None,
        "bank unique")
    dom = req.email_domain.lower().strip()
    dupd = [v for v in vendors if v.email_domain.lower() == dom]
    add("duplicate_domain", f"domain {dom} already on {', '.join(v.id for v in dupd)}" if dupd else None,
        "domain unique")

    sanc = _json("sanctions_simulated.json", [])
    names = {_name(req.legal_name)} | {_name(t) for t in req.trade_names if len(_name(t)) > 3}
    hits = [s for s in sanc if (tax and _norm(s.get("tax_id")) == tax) or _name(s.get("name", "")) in names]
    add("sanctions_hit", f"on {hits[0].get('list', 'SIMULATED list')}: {hits[0].get('name')}" if hits else None,
        "not on the SIMULATED sanctions list", simulated=True)

    emp = [e for e in ctx.store.list_employees() if e.bank_last4 == req.bank_last4]
    add("bank_matches_employee",
        f"bank ****{req.bank_last4} belongs to employee {emp[0].id} {emp[0].name}"
        + (" (also the requester)" if emp[0].email.lower() == req.requested_by.lower() else "") if emp else None,
        "bank matches no employee")

    look = None if dupd else closest_vendor(dom, vendors)
    add("lookalike_domain", f"{dom} imitates {look[0].email_domain} ({look[0].id}), distance {look[1]:.2f}"
        if look else None, "domain resembles no existing vendor")

    form = (req.tax_form or "").upper().replace(" ", "")
    want = "W-9" if req.country.upper() == "US" else "W-8BEN-E"
    if not form:
        add("missing_tax_form", f"no tax form (need {want})", "")
    elif form != want:
        add("invalid_tax_form", f"{req.tax_form} given, {want} required for country {req.country}", "")
    else:
        add("missing_tax_form", None, f"{want} present")

    ages = _json("domain_ages_simulated.json", {})
    age = ages.get(dom)
    add("domain_age", f"domain registered {age} days ago (< {MIN_DOMAIN_AGE_DAYS})"
        if age is not None and int(age) < MIN_DOMAIN_AGE_DAYS else None,
        f"domain age {age} days" if age is not None else "no registration data (SIMULATED source absent)",
        simulated=True)
    return out


def flags(checks: list[OnboardingCheck]) -> list[str]:
    return [c.name for c in checks if not c.passed]
