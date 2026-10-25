"""Negotiation numbers, computed in code. Owner: D.

Three sources, each labelled in the Slack message:
  1. Helix history: unit prices on our own POs and contracts (data/world, the system of record)
  2. Market reference: backend/slack/market_reference.json (SIMULATED for the demo)
  3. Live market notes (optional): Claude with the web-search server tool, given ONLY our canonical category query,
     never the chat text (untrusted text never reaches a prompt with tools). Off with RECONAI_MARKET_WEB=off.
The LLM never computes: targets, savings and percent gaps are Decimal math here.
"""
from __future__ import annotations

import json
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Optional

from pydantic import BaseModel

from backend.core.config import ROOT, Policy
from backend.core import llm
from backend.slack.models import Category, NegotiationState, dec

HERE = Path(__file__).resolve().parent
CENT = Decimal("0.01")
PREFIX = {"WFR": Category.wafers, "HBM": Category.hbm_memory, "PKG": Category.packaging_test,
          "SUB": Category.substrates, "FRT-AIR": Category.freight_air, "FRT-OCN": Category.freight_ocean}


@lru_cache
def reference() -> dict:
    return json.loads((HERE / "market_reference.json").read_text())


def category_of_sku(sku: str) -> Category:
    for p in sorted(PREFIX, key=len, reverse=True):
        if sku.upper().startswith(p):
            return PREFIX[p]
    return Category.other


def _usd(amount: Decimal, currency: str, policy: Policy) -> Optional[Decimal]:
    rate = policy.fx_rates.get(currency.upper())
    return (amount * rate).quantize(CENT, ROUND_HALF_UP) if rate is not None else None


@lru_cache
def _history_raw() -> tuple[list, list]:
    world = ROOT / "data" / "world"
    return json.loads((world / "pos.json").read_text()), json.loads((world / "contract_terms.json").read_text())


def history(category: Category, policy: Policy) -> list[dict]:
    """Unit prices Helix has paid / contracted in this category (USD)."""
    pos, terms = _history_raw()
    out = []
    for p in pos:
        for ln in p["lines"]:
            if category_of_sku(ln["sku"]) == category:
                usd = _usd(Decimal(ln["unit_price"]), p["currency"], policy)
                out.append({"source": p["po_number"], "vendor_id": p["vendor_id"], "sku": ln["sku"], "usd": usd})
    for t in terms:
        if category_of_sku(t["sku"]) == category:
            out.append({"source": t["doc_id"], "vendor_id": t["vendor_id"], "sku": t["sku"],
                        "usd": _usd(Decimal(t["unit_price"]), t["currency"], policy)})
    return [h for h in out if h["usd"] is not None]


class LineAnalysis(BaseModel):
    description: str
    quantity: Optional[str] = None
    quoted_usd: Optional[str] = None
    internal_best_usd: Optional[str] = None
    internal_median_usd: Optional[str] = None
    internal_sources: list[str] = []
    market_p25: Optional[str] = None
    market_median: Optional[str] = None
    market_p75: Optional[str] = None
    position: Optional[str] = None
    gap_vs_target_pct: Optional[str] = None
    anchor_usd: Optional[str] = None
    target_usd: Optional[str] = None
    walk_away_usd: Optional[str] = None
    savings_at_target_usd: Optional[str] = None
    savings_at_anchor_usd: Optional[str] = None


class Analysis(BaseModel):
    category: str
    category_label: str
    unit: str
    currency: str
    lines: list[LineAnalysis] = []
    contract_value_usd: Optional[str] = None
    terms_on_table: str = ""
    term_asks: list[str] = []
    market_terms: str = ""
    market_lead_time: str = ""
    sources: list[str] = []


def _s(d: Optional[Decimal]) -> Optional[str]:
    return str(d.quantize(CENT, ROUND_HALF_UP)) if d is not None else None


def terms_label(net: Optional[int], pct: Optional[Decimal], days: Optional[int]) -> str:
    if pct and days:
        return f"{(pct * 100).normalize():f}/{days} net {net or 30}"
    return f"net {net}" if net else "not discussed yet"


def analyze(state: NegotiationState, policy: Policy) -> Analysis:
    ref = reference().get(state.category.value) or reference()["other"]
    hist = history(state.category, policy)
    p25, med, p75 = dec(ref.get("p25")), dec(ref.get("median")), dec(ref.get("p75"))
    a = Analysis(category=state.category.value, category_label=ref["label"], unit=ref["unit"], currency=state.currency,
                 market_terms=ref.get("terms", ""), market_lead_time=ref.get("lead_time", ""),
                 sources=["Helix PO + contract history (system of record)", "Market reference (SIMULATED demo table)"])
    value = Decimal(0)
    for ln in state.lines:
        la = LineAnalysis(description=ln.description[:80], quantity=ln.quantity)
        qty = dec(ln.quantity)
        price = dec(ln.agreed_unit_price) or dec(ln.vendor_unit_price)
        quoted = _usd(price, state.currency, policy) if price is not None else None
        same = [h for h in hist if ln.sku and h["sku"].upper() == ln.sku.upper()] or hist
        if same:
            vals = [h["usd"] for h in same]
            la.internal_best_usd, la.internal_median_usd = _s(min(vals)), _s(Decimal(str(median(vals))))
            la.internal_sources = sorted({h["source"] for h in same})[:4]
        la.market_p25, la.market_median, la.market_p75 = _s(p25), _s(med), _s(p75)
        best = min(vals) if same else None
        # anchor: the lower of our best price and the market's 25th percentile; target: the lower of the market
        # median and our best; walk away above the 75th percentile
        anchor = min(x for x in (best, p25) if x is not None) if (best is not None or p25 is not None) else None
        target = min(x for x in (med, best) if x is not None) if (med is not None or best is not None) else None
        la.anchor_usd, la.target_usd, la.walk_away_usd = _s(anchor), _s(target), _s(p75)
        if quoted is not None:
            la.quoted_usd = _s(quoted)
            if p25 is not None and med is not None and p75 is not None:
                la.position = ("below the market 25th percentile" if quoted < p25 else
                               "between the 25th percentile and the median" if quoted <= med else
                               "between the median and the 75th percentile" if quoted <= p75 else
                               "above the market 75th percentile")
            if target is not None and target > 0:
                la.gap_vs_target_pct = str(((quoted - target) / target * 100).quantize(Decimal("0.1"), ROUND_HALF_UP))
            if qty is not None:
                value += quoted * qty
                if target is not None and quoted > target:
                    la.savings_at_target_usd = _s((quoted - target) * qty)
                if anchor is not None and quoted > anchor:
                    la.savings_at_anchor_usd = _s((quoted - anchor) * qty)
        a.lines.append(la)
    a.contract_value_usd = _s(value) if value else None
    pct = dec(state.discount_pct)
    a.terms_on_table = terms_label(state.net_days, pct, state.discount_days)
    if not pct:
        two = (value * Decimal("0.02")).quantize(CENT, ROUND_HALF_UP) if value else None
        a.term_asks.append("Ask for an early-payment discount, e.g. 2/15 net 30"
                           + (f" (worth {two} USD on this deal at 2%)" if two else "")
                           + "; ReconAI captures it automatically when the bill is approved in time.")
    if (state.net_days or 30) < 45:
        a.term_asks.append("If they won't discount, ask for net 45 instead of net 30 (keeps cash longer).")
    if value and value >= Decimal("250000"):
        a.term_asks.append("Volume tier: ask for an extra 1-3% above an annual volume threshold, and a 2-quarter price hold.")
    if state.category in (Category.freight_air, Category.freight_ocean):
        a.term_asks.append("Expedite / fuel surcharges only with written pre-approval on the PO (a recurring AP problem).")
    a.term_asks.append("Credit notes for short deliveries or price errors within 7 days of our notice.")
    a.term_asks.append("Bank details change only after a verified callback to the number on file.")
    return a


# --- optional live market notes ------------------------------------------------------------------

def web_enabled() -> bool:
    return os.environ.get("RECONAI_MARKET_WEB", "on").lower() != "off" and llm.mode() == "live"


def market_notes(category: Category, store=None) -> list[str]:
    """Up to 3 short, sourced notes from a web search on OUR canonical query (cached per category per day)."""
    query = (reference().get(category.value) or {}).get("query")
    if not query or not web_enabled():
        return []
    key = f"{category.value}:{date.today().isoformat()}"
    if store is not None:
        hit = store.get_record(_Notes, "market_notes", key)
        if hit:
            return hit.notes
        if key not in _FETCHING:  # first time today: fetch in the background, coach now with code numbers only
            _FETCHING.add(key)
            import threading
            threading.Thread(target=_fetch_notes, args=(category, store, key, query), daemon=True).start()
        return []
    return _fetch_notes(category, None, key, query)


_FETCHING: set[str] = set()


def _fetch_notes(category: Category, store, key: str, query: str) -> list[str]:
    try:
        client = llm._get_client()
        messages = [{"role": "user", "content": (
            f"Research: {query}. Reply with at most 3 bullet points, each one sentence with a number or trend that "
            "would help a buyer negotiate, ending with the source domain in parentheses. Nothing else.")}]
        resp = None
        for _ in range(3):  # server tools may pause a long turn; continue it
            resp = client.messages.create(model=llm.MODEL, max_tokens=1200, messages=messages,
                                          tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}])
            if resp.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        notes = [ln.strip("-•* ").strip() for ln in text.splitlines() if ln.strip().startswith(("-", "•", "*"))][:3]
    except Exception:  # network / tool unavailable: the code numbers still stand
        return []
    if store is not None:
        store.put_record("market_notes", key, _Notes(notes=notes))
    return notes


class _Notes(BaseModel):
    notes: list[str] = []
