"""Onboard a vendor from an accepted Slack contract. Owner: D.

Flow: the vendor accepts the contract in Slack and fills the onboarding form (its "invite link": the request
itself came from the Helix person who negotiated, so vendors still never self-sign-up). We run every onboarding
check (CRS + code, backend/vendors/onboarding.py). Policy `onboarding.auto_approve_low_risk`: a LOW-risk vendor
(every check passed) is approved by policy with no human click; medium/high risk waits for a controller in the
app. On approval the vendor master gets the contract's payment terms and the verified contact, and a
confirmation email goes to that contact.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.ap.payments import PaymentStore
from backend.core.config import load_policy
from backend.notify import email as mail
from backend.slack.contract import KIND as CONTRACT_KIND, terms_text
from backend.store.base import Store
from backend.vendors import onboarding as onb
from backend.vendors.crs import make_crs
from contracts import OnboardingCase, OnboardingRequestIn, VendorContract

POLICY_APPROVER = "reconai-policy@helix.example"


def auto_approve_enabled() -> bool:
    return bool(load_policy().onboarding.get("auto_approve_low_risk", False))


def start(req: OnboardingRequestIn, contract: Optional[VendorContract], store: Store, pay: PaymentStore,
          now: datetime) -> OnboardingCase:
    case = onb.submit(req, store, make_crs(), now)
    case.source = "slack" if contract else "app"
    case.contract_id = contract.id if contract else None
    if contract:  # finish() reads the contract from the store for its terms
        contract.onboarding_id = case.id
        store.put_record(CONTRACT_KIND, contract.id, contract)
    if case.risk_tier == "low" and auto_approve_enabled():
        case = onb.decide(case, POLICY_APPROVER, "approver", "approved",
                          "Auto-approved by policy: low risk, every onboarding check passed", store, now)
        case.auto_approved = True
        finish(case, store, now)
    pay.save_onboarding(case)
    if contract:
        contract.status = "onboarded" if case.status == "approved" else "held"
        contract.onboarding_id = case.id
        store.put_record(CONTRACT_KIND, contract.id, contract)
    return case


def finish(case: OnboardingCase, store: Store, now: datetime) -> None:
    """After approval (policy or human): contract terms onto the vendor master, then the confirmation email."""
    if case.status != "approved" or not case.vendor_id:
        return
    vendor = store.get_vendor(case.vendor_id)
    contract = store.get_record(VendorContract, CONTRACT_KIND, case.contract_id) if case.contract_id else None
    if vendor and contract:
        vendor.terms = contract.terms
        store.save_vendor(vendor)
        contract.status = "onboarded"
        store.put_record(CONTRACT_KIND, contract.id, contract)
    to = case.request.contact_email or (vendor.contact_email if vendor else None)
    if not to or vendor is None:
        return
    lines = [f"Hello {case.request.contact_name or vendor.name},", "",
             f"{vendor.name} is now set up as a Helix Silicon supplier.", "",
             f"Supplier ID: {vendor.id}",
             f"Payment terms: {terms_text(vendor.terms) if vendor.terms else 'net 30'}"
             + (f" (agreement {contract.id})" if contract else ""),
             f"Bank account on file: ending {vendor.bank_last4}",
             f"Probation: first 90 days, until {vendor.probation_until}: full PO and receiving match on every invoice.",
             "", "How to get paid on time:",
             "- Put the Helix PO number and line on every invoice.",
             "- Send invoices from your registered address only.",
             "- Bank detail changes are accepted only after we verify them by phone at the number on file; "
             "please never send bank details by email.",
             "", "Welcome aboard,", "Helix Silicon Accounts Payable"]
    sent = mail.send(store, kind="onboarding_confirmation", to=to, vendor_id=vendor.id,
                     subject=f"Welcome to Helix Silicon: supplier {vendor.id} is active",
                     body="\n".join(lines), key=f"onboarded:{case.id}")
    case.confirmation_email_id = sent.id
