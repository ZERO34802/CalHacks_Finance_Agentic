"""Outbound email: supplier discrepancy emails and vendor onboarding confirmations. Owner: D.

Every email is kept in the outbox (store records, kind `email`), whether or not it was delivered.
Delivery goes through Resend (POST https://api.resend.com/emails) when RESEND_API_KEY is set.

Safety rules (code, not prompts):
- Idempotent: one email per idempotency key (also sent to Resend as the Idempotency-Key header).
- The fixture vendors are fictional but their domains could be real, so mail for them is never sent there:
  with RECONAI_EMAIL_REDIRECT set, every email goes to that inbox instead (the intended recipient is printed at
  the top); without it, fixture mail stays in the outbox.
- Only the API layer calls `deliver_*`; pipeline runs, evals and tests only draft (backend/agents/supplier.py).

Env: RESEND_API_KEY, RESEND_FROM (default "ReconAI AP <onboarding@resend.dev>"; Resend's test sender can only
reach the Resend account's own address, so set RECONAI_EMAIL_REDIRECT to it until a domain is verified),
RECONAI_EMAIL_REDIRECT.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import httpx
from dotenv import load_dotenv

from backend.core.config import ROOT
from backend.store.base import Store
from contracts import Case, OutboundEmail

load_dotenv(ROOT / ".env")

KIND = "email"
RESEND_URL = "https://api.resend.com/emails"


def configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def redirect() -> Optional[str]:
    return os.environ.get("RECONAI_EMAIL_REDIRECT") or None


@lru_cache
def fictional_domains() -> frozenset[str]:
    """Domains of the fictional world (fixture vendors + Helix itself)."""
    vendors = json.loads((ROOT / "data" / "world" / "vendors.json").read_text())
    doms = {v["email_domain"].lower() for v in vendors} | {"helix.example"}
    doms |= {v.get("contact_email", "").split("@")[-1].lower() for v in vendors if v.get("contact_email")}
    return frozenset(doms)


def _fictional(addr: str) -> bool:
    dom = addr.rsplit("@", 1)[-1].lower()
    return dom in fictional_domains() or dom.endswith(".example")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get(store: Store, key: str) -> Optional[OutboundEmail]:
    return store.get_record(OutboundEmail, KIND, key)


def outbox(store: Store, case_id: Optional[str] = None, vendor_id: Optional[str] = None) -> list[OutboundEmail]:
    out = [e for e in store.list_records(OutboundEmail, KIND)
           if (case_id is None or e.case_id == case_id) and (vendor_id is None or e.vendor_id == vendor_id)]
    return sorted(out, key=lambda e: e.created_at, reverse=True)


def _resend_key(key: str, to: str, subject: str, text: str) -> str:
    """Resend refuses a reused key with a different body (409). Same content -> same key (a retry can't double
    send); changed content (e.g. a re-run case's new wording) -> a new key. Our outbox key stays per case."""
    return f"{key[:200]}:{hashlib.sha256(f'{to}|{subject}|{text}'.encode()).hexdigest()[:16]}"


def _resend(to: str, subject: str, text: str, key: str) -> str:
    sender = os.environ.get("RESEND_FROM") or "ReconAI AP <onboarding@resend.dev>"
    body = {"from": sender, "to": [to], "subject": subject, "text": text,
            "html": f"<pre style=\"font-family:system-ui,sans-serif;white-space:pre-wrap\">{html.escape(text)}</pre>"}
    r = httpx.post(RESEND_URL, json=body, timeout=20,
                   headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Idempotency-Key": _resend_key(key, to, subject, text)})
    if r.status_code >= 400:
        raise RuntimeError(f"Resend HTTP {r.status_code}: {r.text[:200]}")
    return r.json().get("id", "")


def send(store: Store, *, kind: str, to: str, subject: str, body: str, key: str,
         case_id: Optional[str] = None, vendor_id: Optional[str] = None) -> OutboundEmail:
    """Deliver once per key. Returns the outbox record (sent | outbox | failed)."""
    prior = get(store, key)
    if prior and prior.status == "sent":
        return prior
    dest = redirect()
    email = OutboundEmail(id=prior.id if prior else f"mail_{hashlib.sha256(key.encode()).hexdigest()[:10]}",
                          kind=kind, case_id=case_id, vendor_id=vendor_id, to=to, subject=subject, body=body,
                          status="outbox", provider="outbox", idempotency_key=key,
                          created_at=prior.created_at if prior else _now())
    if not configured():
        email.error = "RESEND_API_KEY not set: kept in the outbox"
    elif dest is None and _fictional(to):
        email.error = "fictional demo address: set RECONAI_EMAIL_REDIRECT to deliver to a test inbox"
    else:
        target = dest or to
        text = body if target == to else f"[ReconAI demo: intended for {to}]\n\n{body}"
        try:
            email.provider_id = _resend(target, subject, text, key)
            email.status, email.provider, email.delivered_to = "sent", "resend", target
        except Exception as e:  # network / Resend error: kept in the outbox, retried on the next delivery
            email.status, email.provider, email.error = "failed", "resend", str(e)[:300]
    store.put_record(KIND, key, email, idx=case_id or vendor_id or "")
    return email


def deliver_case(store: Store, case: Case) -> list[OutboundEmail]:
    """Send every supplier email the agents drafted on this case (once each)."""
    return [send(store, kind="supplier_discrepancy", to=o.to, subject=o.subject, body=o.body,
                 key=f"supplier:{o.idempotency_key}", case_id=case.id, vendor_id=case.vendor_id)
            for o in case.outbound]
