"""[5] Router. Owner: B. Picks a skill by event type, in code. No skill = escalate.

Event types come from the Matcher's discrepancies plus Vendor Guard's pre-screen (bank change /
look-alike domain). Vendor Guard runs after the Router in the fixed pipeline order, so the Router
calls the same pure `screen()` and merges its signals first; Vendor Guard re-checks later and
re-routes if anything new appears. The mapping is config/policy.yaml `skills`; documents never choose.

Before routing, code applies controller-approved rules that tighten materiality (never loosen):
  - skill policy `strict_price` (from skill evolution): a below-materiality price_over for the matching
    vendor / SKU prefix becomes material;
  - vendor memory controller rules (provenance 'controller: ...'): "Hold any expedite fee without signed
    approval" makes a below-materiality unapproved expedite line material. RECONAI_MEMORY=off disables this.
"""
import re

import yaml

from backend.agents import policy_rules as rules
from backend.agents.sandbox import vendor_memory
from backend.agents.skills import load_skill
from backend.core.stage import Ctx
from backend.pipeline.vendor_guard import merge, screen
from contracts import Case, Citation, Decision, DiscrepancyType as T, StepStatus

EXPEDITE_RULE = re.compile(r"hold any expedite fee", re.I)


def strict_price_rules(ctx: Ctx) -> list[dict]:
    name = ctx.policy.skills.get("three_way_match")
    try:
        pol = yaml.safe_load(load_skill(name).policy_yaml) or {}
    except KeyError:
        return []
    return [r for r in pol.get("strict_price") or [] if isinstance(r, dict)]


def apply_rules(case: Case, ctx: Ctx) -> list[dict]:
    """Reclassify below-materiality items as material under controller-approved rules. Returns what changed."""
    changed = []
    small = [d for d in case.discrepancies if d.type == T.below_materiality]
    if not small:
        return changed
    vid = case.invoice.vendor_id if case.invoice else case.vendor_id
    for r in strict_price_rules(ctx):
        for d in small:
            if d.original_type == T.price_over and r.get("vendor_id") in (None, vid) and \
                    (d.sku or "").startswith(r.get("sku_prefix", "")):
                d.type, d.material = T.price_over, True
                d.citations.append(Citation(doc_id=f"skill:{ctx.policy.skills['three_way_match']}",
                                            locator="policy.yaml strict_price", quote=r.get("source")))
                changed.append({"sku": d.sku, "to": "price_over", "rule": f"strict_price {r.get('sku_prefix')}"})
    vendor = ctx.store.get_vendor(vid)
    subject, lines, _ = vendor_memory(ctx, vendor)
    rule_lines = [i for i, ln in enumerate(lines) if "[controller" in ln and EXPEDITE_RULE.search(ln)]
    if rule_lines:
        for d in small:
            if d.type == T.below_materiality and d.original_type == T.unapproved_freight and "EXP" in (d.sku or "").upper():
                d.type, d.material = T.unapproved_freight, True
                d.citations.append(Citation(doc_id=f"memory:{subject}", locator=f"line {rule_lines[0] + 1}",
                                            quote="Hold any expedite fee without signed approval"))
                changed.append({"sku": d.sku, "to": "unapproved_freight", "rule": f"memory:{subject}"})
    if changed:
        from backend.pipeline.lib.split import split
        sp = split(case)
        case.disputed_amount = sp["disputed"] if sp["separable"] else None
        case.notes.append("router: controller rule made " + ", ".join(f"{c['sku']} {c['to']}" for c in changed)
                          + " material")
    return changed


class Router:
    name = "router"

    def run(self, case: Case, ctx: Ctx) -> Case:
        sc = screen(case, ctx)
        added = merge(case, sc.discrepancies)
        reclassified = apply_rules(case, ctx)
        case.skill, reason = rules.route(case, ctx.policy)
        policy_rec, why = rules.policy_recommendation(case)
        detail = {"reason": reason, "event_types": sorted({d.type.value for d in rules.material(case)}),
                  "vendor_risk_added": added, "policy_recommendation": policy_rec.value, "policy_reasons": why}
        if reclassified:
            detail["reclassified"] = reclassified
        if case.skill is None:
            ctx.trace.annotate(status=StepStatus.escalated if policy_rec == Decision.escalate else StepStatus.skipped,
                               detail=detail)
            return case
        skill = load_skill(case.skill)
        ctx.trace.annotate(skill=skill.name, skill_version=skill.version, detail=detail)
        return case
