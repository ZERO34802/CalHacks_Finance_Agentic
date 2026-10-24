"""[5] Router. Owner: B. Picks a skill by event type, in code. No skill = escalate.

Event types come from the Matcher's discrepancies plus Vendor Guard's pre-screen (bank change /
look-alike domain). Vendor Guard runs after the Router in the fixed pipeline order, so the Router
calls the same pure `screen()` and merges its signals first; Vendor Guard re-checks later and
re-routes if anything new appears. The mapping is config/policy.yaml `skills`; documents never choose.
"""
from backend.agents import policy_rules as rules
from backend.agents.skills import load_skill
from backend.core.stage import Ctx
from backend.pipeline.vendor_guard import merge, screen
from contracts import Case, Decision, StepStatus


class Router:
    name = "router"

    def run(self, case: Case, ctx: Ctx) -> Case:
        sc = screen(case, ctx)
        added = merge(case, sc.discrepancies)
        case.skill, reason = rules.route(case, ctx.policy)
        policy_rec, why = rules.policy_recommendation(case)
        detail = {"reason": reason, "event_types": sorted({d.type.value for d in rules.material(case)}),
                  "vendor_risk_added": added, "policy_recommendation": policy_rec.value, "policy_reasons": why}
        if case.skill is None:
            ctx.trace.annotate(status=StepStatus.escalated if policy_rec == Decision.escalate else StepStatus.skipped,
                               detail=detail)
            return case
        skill = load_skill(case.skill)
        ctx.trace.annotate(skill=skill.name, skill_version=skill.version, detail=detail)
        return case
