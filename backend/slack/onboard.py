"""Onboard a vendor from an accepted Slack contract. Owner: D.

Flow: the vendor accepts the contract in Slack and fills the onboarding form (its "invite link": the request
itself came from the Helix person who negotiated, so vendors still never self-sign-up). We run every onboarding
check (CRS + code, backend/vendors/onboarding.py). Policy `onboarding.auto_approve_low_risk`: a LOW-risk vendor
(every check passed) is approved by policy with no human click; medium/high risk waits for a controller in the
app. On approval the vendor master gets the contract's payment terms and the verified contact, the Slack channel
(bound to the Slack user who submitted the form: the only one whose invoices we take for this vendor), a confirmed
PO in the Helix ERP from the contract (backend/erp), and a confirmation email goes to that contact.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.ap.payments import PaymentStore
from backend.core.config import load_policy
from backend.notify import email as mail
from backend.slack.contract import KIND as CONTRACT_KIND, terms_text
from backend.slack.models import (AMENDMENT_KIND, APPLICANT_KIND, DEAL_KIND, SESSION_KIND, VENDOR_USER_KIND,
                                  Amendment, Deal, Session, VendorUser)
from backend.store.base import Store
from backend.vendors import onboarding as onb
from backend.vendors.crs import make_crs
from contracts import PO, Channel, ContractTerm, OnboardingCase, OnboardingRequestIn, VendorContract

log = logging.getLogger("reconai.slack")
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


def po_for_contract(store: Store, contract_id: str) -> Optional[PO]:
    from backend import erp
    return next((p for p in store.list_records(PO, erp.INDEX) if p.contract_id == contract_id), None)


def _activate(contract: VendorContract, vendor, store: Store) -> Optional[PO]:
    """Slack channel bound to the applicant, then the PO from the contract (ERP trouble never undoes onboarding)."""
    applicant = store.get_record(VendorUser, APPLICANT_KIND, contract.id)
    if applicant and Channel.slack not in vendor.channels:
        vendor.channels.append(Channel.slack)
        store.save_vendor(vendor)
    if applicant:
        applicant.vendor_id = vendor.id
        store.put_record(APPLICANT_KIND, contract.id, applicant)
        store.put_record(VENDOR_USER_KIND, applicant.slack_user, applicant)
    return _open_deal(contract, vendor, applicant.slack_user if applicant else None, store)


def _open_deal(contract: VendorContract, vendor, vendor_user: Optional[str], store: Store) -> Optional[PO]:
    """The PO from the contract in the ERP + the deal record (channel, vendor contact, requester)."""
    from backend import erp
    try:
        po = erp.po_from_contract(contract, vendor, store)
    except Exception as e:
        log.warning("PO from contract %s failed: %s", contract.id, e)
        return None
    sess = store.get_record(Session, SESSION_KIND, contract.channel) if contract.channel else None
    store.put_record(DEAL_KIND, po.po_number, Deal(
        po_number=po.po_number, contract_id=contract.id, vendor_id=vendor.id, channel=contract.channel,
        vendor_user=vendor_user, requester_user=sess.owner if sess else None, requester_email=po.requester))
    return po


# --- an existing supplier: a new deal or an amendment, no second onboarding --------------------------------------
def recheck(vendor) -> Optional[str]:
    """What onboarding checks again before an existing supplier's new agreement: still on the vendor master with
    a bank account on file, and not on the (SIMULATED) sanctions list. None = fine."""
    from backend.onboarding import checks
    if vendor is None:
        return "The supplier is no longer on the vendor master."
    if not vendor.bank_last4:
        return f"{vendor.name} has no bank account on file; it needs a verified callback first."
    tax = checks._norm(vendor.tax_id)
    hits = [s for s in checks._json("sanctions_simulated.json", [])
            if (tax and checks._norm(s.get("tax_id")) == tax) or checks._name(s.get("name", "")) == checks._name(vendor.name)]
    if hits:
        return f"{vendor.name} is on {hits[0].get('list', 'the SIMULATED sanctions list')}: escalate to a controller."
    return None


def accept_returning(contract: VendorContract, vu: VendorUser, store: Store) -> tuple[Optional[PO], Optional[str]]:
    """The supplier's registered Slack contact accepts a new agreement: no onboarding form, no second vendor record.
    The vendor master keeps its identity and bank details; it takes the agreed payment terms. Returns (PO, problem)."""
    vendor = store.get_vendor(vu.vendor_id)
    problem = recheck(vendor)
    if problem:
        contract.status = "held"
        store.put_record(CONTRACT_KIND, contract.id, contract)
        return None, problem
    vendor.terms = contract.terms
    store.save_vendor(vendor)
    contract.status, contract.accepted_by = "accepted", f"{vu.name or vu.slack_user} (Slack {vu.slack_user})"
    store.put_record(CONTRACT_KIND, contract.id, contract)
    store.put_record(APPLICANT_KIND, contract.id, vu)
    po = _open_deal(contract, vendor, vu.slack_user, store)
    if po and vendor.contact_email:
        mail.send(store, kind="onboarding_confirmation", to=vendor.contact_email, vendor_id=vendor.id,
                  subject=f"Helix Silicon: agreement {contract.id} accepted, {po.po_number} opened",
                  body="\n".join([f"Hello {vendor.name},", "",
                                  f"Agreement {contract.id} is accepted and purchase order {po.po_number} is open.",
                                  f"Quote {po.po_number} and the item codes ({', '.join(ln.sku for ln in po.lines)}) "
                                  "on every invoice.", f"Payment terms: {terms_text(contract.terms)}.",
                                  "Your bank account on file is unchanged.", "", "Helix Silicon Accounts Payable"]),
                  key=f"contract_accepted:{contract.id}")
    return po, None


def prices_in_force(store: Store, vendor_id: str, po: PO, on, exclude_doc: Optional[str] = None) -> dict[str, Decimal]:
    """Unit price per PO line on date `on`: the latest contract term effective by then, else the PO price."""
    out = {ln.sku: ln.unit_price for ln in po.lines}
    for t in sorted((t for t in store.list_contract_terms(vendor_id) if t.effective_from <= on
                     and t.currency == po.currency and t.doc_id != exclude_doc), key=lambda t: t.effective_from):
        if t.sku in out:
            out[t.sku] = t.unit_price
    return out


def accept_amendment(a: Amendment, c: VendorContract, vu: VendorUser, store: Store) -> Optional[str]:
    """The supplier accepts an amendment: its unit prices become contract terms effective from its date (the
    Matcher checks invoices dated earlier at the earlier price) and the vendor master takes its payment terms.
    Quantities, the PO and bank details are unchanged. Returns a problem, or None."""
    vendor = store.get_vendor(a.vendor_id)
    problem = recheck(vendor)
    if problem:
        return problem
    for i in c.items:
        store.save_contract_term(ContractTerm(doc_id=f"erp-{c.id}", vendor_id=vendor.id, sku=i["sku"],
                                              unit_price=Decimal(i["unit_price"]), currency=c.currency,
                                              effective_from=a.effective_from))
    vendor.terms = c.terms
    store.save_vendor(vendor)
    who = f"{vu.name or vu.slack_user} (Slack {vu.slack_user})"
    a.status, a.accepted_by = "accepted", who
    store.put_record(AMENDMENT_KIND, a.id, a)
    c.status, c.accepted_by = "accepted", who
    store.put_record(CONTRACT_KIND, c.id, c)
    return None


def finish(case: OnboardingCase, store: Store, now: datetime) -> Optional[PO]:
    """After approval (policy or human): contract terms onto the vendor master, Slack channel + PO from the
    contract, then the confirmation email. Returns the PO (None without a contract)."""
    if case.status != "approved" or not case.vendor_id:
        return None
    vendor = store.get_vendor(case.vendor_id)
    contract = store.get_record(VendorContract, CONTRACT_KIND, case.contract_id) if case.contract_id else None
    po = None
    if vendor and contract:
        vendor.terms = contract.terms
        store.save_vendor(vendor)
        contract.status = "onboarded"
        store.put_record(CONTRACT_KIND, contract.id, contract)
        po = _activate(contract, vendor, store)
    to = case.request.contact_email or (vendor.contact_email if vendor else None)
    if not to or vendor is None:
        return po
    lines = [f"Hello {case.request.contact_name or vendor.name},", "",
             f"{vendor.name} is now set up as a Helix Silicon supplier.", "",
             f"Supplier ID: {vendor.id}",
             f"Payment terms: {terms_text(vendor.terms) if vendor.terms else 'net 30'}"
             + (f" (agreement {contract.id})" if contract else ""),
             f"Bank account on file: ending {vendor.bank_last4}",
             *([f"Purchase order: {po.po_number}: quote it and the item codes "
                f"({', '.join(ln.sku for ln in po.lines)}) on every invoice."] if po else []),
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
    return po
