"""Slack negotiation state (internal to the bot; the UI sees VendorContract / OnboardingCase from contracts)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    wafers = "wafers"
    hbm_memory = "hbm_memory"
    packaging_test = "packaging_test"
    substrates = "substrates"
    freight_air = "freight_air"
    freight_ocean = "freight_ocean"
    probe_cards = "probe_cards"
    other = "other"


class Line(BaseModel):
    description: str = Field(description="Item as discussed, max 80 chars")
    sku: Optional[str] = Field(None, description="Part number if one was written")
    quantity: Optional[str] = Field(None, description="Number as written, digits only, e.g. 2000")
    unit: Optional[str] = Field(None, description="e.g. wafer, stack, unit, shipment")
    vendor_unit_price: Optional[str] = Field(None, description="Latest unit price the VENDOR offered, digits only, e.g. 1450.00")
    our_counter_price: Optional[str] = Field(None, description="Latest unit price HELIX offered, digits only")
    agreed_unit_price: Optional[str] = Field(None, description="Unit price BOTH sides explicitly agreed, digits only")


class NegotiationState(BaseModel):
    """What has been said so far. Extracted from untrusted chat text: numbers as written, never computed."""
    vendor_name: Optional[str] = Field(None, description="Vendor company name if stated")
    category: Category = Category.other
    currency: str = Field("USD", description="ISO currency of the prices")
    lines: list[Line] = Field(default_factory=list, max_length=6)
    net_days: Optional[int] = Field(None, description="Payment terms in days (net N) currently on the table")
    discount_pct: Optional[str] = Field(None, description="Early-payment discount as a fraction, e.g. 0.02 for 2%")
    discount_days: Optional[int] = Field(None, description="Days to pay to earn the discount")
    lead_time: Optional[str] = None
    delivery: Optional[str] = Field(None, description="Delivery / Incoterms if discussed")
    warranty: Optional[str] = None
    other_terms: list[str] = Field(default_factory=list, max_length=8, description="Other terms proposed, short")
    agreed: bool = Field(False, description="True only if both sides explicitly agreed price AND payment terms")
    open_points: list[str] = Field(default_factory=list, max_length=6)


def dec(v: Optional[str]) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d >= 0 else None


class Message(BaseModel):
    user: str
    name: str = ""
    internal: bool
    text: str
    ts: str


class Session(BaseModel):
    channel: str
    owner: str = Field(description="Slack user id of the Helix person who started the negotiation")
    owner_email: str
    owner_name: str = ""
    vendor_name: str = ""
    started_at: datetime
    transcript: list[Message] = []
    state: Optional[NegotiationState] = None
    last_signature: str = ""
    suggestions: int = 0
    contract_id: Optional[str] = None
    active: bool = True
    qa: list[dict] = Field(default_factory=list, description="Private /recon questions and answers (owner only)")


class NegotiationLog(BaseModel):
    """The negotiation as it happened, archived when the contract is drafted (audit trail: why Helix agreed this)."""
    contract_id: str
    channel: str
    owner: str
    owner_name: str = ""
    vendor_name: str = ""
    started_at: datetime
    archived_at: datetime
    transcript: list[Message] = []
    state: Optional[NegotiationState] = None
    suggestions: int = 0


NEGOTIATION_LOG_KIND = "slack_negotiation_log"  # contract id -> NegotiationLog


# --- billing cycle in Slack (record kinds in the store) ---------------------------------------------
SESSION_KIND = "slack_session"      # channel -> Session
VENDOR_USER_KIND = "slack_vendor"   # Slack user id -> VendorUser (the vendor's registered contact)
APPLICANT_KIND = "slack_applicant"  # contract id -> VendorUser (who submitted onboarding; vendor_id once approved)
DEAL_KIND = "slack_deal"            # PO number -> Deal
SHIPMENT_KIND = "slack_shipment"    # shipment notice id -> Shipment


class VendorUser(BaseModel):
    """The Slack user who submitted a vendor's onboarding form: the only one whose invoices / shipment notices
    ReconAI takes for that vendor."""
    slack_user: str
    vendor_id: str = ""
    name: str = ""
    email: str = ""
    channel: str = ""
    contract_id: str = ""


class Deal(BaseModel):
    """A PO created from a Slack contract: where to talk about it and who to tell."""
    po_number: str
    contract_id: str
    vendor_id: str
    channel: str
    vendor_user: Optional[str] = None
    requester_user: Optional[str] = None
    requester_email: str = ""


class Shipment(BaseModel):
    """A vendor's shipment notice. Only a CLAIM: the goods receipt is created by a Helix person's count."""
    id: str
    po_number: str
    lines: dict[str, str] = Field(description="sku -> qty the vendor says it shipped (never a receipt)")
    vendor_user: str
    at: datetime
    receipt_id: Optional[str] = None
    received_by: Optional[str] = None
