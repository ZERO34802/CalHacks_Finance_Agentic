"""make eval-llm -> LLM-judged evals + consistency. Reported SEPARATELY; never the headline score.

  python scripts/eval_llm.py --cases case_03,case_04 [--samples 3] [--judge-runs 2] [--no-calibrate] [--yes]

1. Prints a cost estimate first. Spends money only with --yes (or RECONAI_LLM=replay, which is free).
2. Runs the cases `--samples` times with RECONAI_SAMPLE=1..N on fresh in-memory stores -> decision stability.
3. Judges sample 1's artifacts (explanation / supplier_email / escalation / skill_proposal) with the judge model,
   runs the auditor pushbacks (defend_decision), and calibrates the judge on data/llm_labels.json.
4. Attaches llm_scores + stability to the latest deterministic scoreboard in the main store and writes
   .data/llm_eval.json.
Pick cases without cross-case dependencies (or include them: e.g. case_13 before case_14).
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from backend.core import llm
from backend.core.config import ROOT
from backend.evals import llm_judge as J
from backend.evals.fixtures import DATA
from backend.evals.harness import run_eval
from backend.store import get_store
from backend.store.sqlite import SQLiteStore

DEFAULT_CASES = "case_03,case_04,case_09,case_25"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--judge-runs", type=int, default=2)
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--yes", action="store_true", help="actually spend (live mode)")
    a = ap.parse_args()
    cases = [c.strip() for c in a.cases.split(",") if c.strip()]
    labels = [] if a.no_calibrate else json.loads((DATA / "llm_labels.json").read_text())
    pushbacks = [p for p in json.loads((DATA / "llm_pushbacks.json").read_text()) if p["case_id"] in cases]

    est = J.estimate(len(cases), a.samples, a.judge_runs, len(labels), len(pushbacks))
    print(f"LLM eval: {len(cases)} cases x {a.samples} samples, judge {J.JUDGE_MODEL} x{a.judge_runs}, "
          f"{len(labels)} labels, {len(pushbacks)} pushbacks; agent {J.AGENT_MODEL}")
    print(f"estimated cost (upper bound, cache hits are free): agent ${est['agent_runs']} + judge ${est['judge']} "
          f"+ defend ${est['defend']} = ${est['total']}")
    mode = llm.mode()
    if mode == "off":
        print("RECONAI_LLM=off (or no key): nothing to judge. Exiting.")
        return 0
    if mode == "live" and not a.yes:
        print("live mode: re-run with --yes to spend (or RECONAI_LLM=replay for cached results only)")
        return 0

    meter = J.Meter()
    decisions: dict[str, list] = {c: [] for c in cases}
    agent_cost = Decimal(0)
    first_store = None
    for n in range(1, a.samples + 1):
        with J.sample(n):
            store = SQLiteStore(":memory:")
            board = run_eval(store, cases)
        for r in board.results:
            decisions[r.case_id].append(r.actual_decision.value if r.actual_decision else None)
        for c in cases:
            agent_cost += sum((s.cost_usd or Decimal(0)) for s in store.list_steps(c))
        first_store = first_store or store
        print(f"  sample {n}: " + ", ".join(f"{r.case_id}={r.actual_decision.value if r.actual_decision else '-'}"
                                             for r in board.results))
    stab = J.stability(decisions)

    scores = J.judge_run(first_store, meter, a.judge_runs, cases)
    dscores, outcomes = J.defend_run(first_store, meter, a.judge_runs, cases)
    scores += dscores
    cal = J.calibrate(meter, a.judge_runs) if labels else None

    print(f"\ndecision stability: {stab:.0%} over {a.samples} samples")
    for s in scores:
        print(f"  {s.case_id:<10} {s.rubric:<16} {s.score:.2f}/5 ({s.runs} runs)  {s.rationale[:110]}")
    if outcomes:
        ok = sum(o["correct"] for o in outcomes)
        print(f"defend outcomes (code-checked): {ok}/{len(outcomes)} correct")
        for o in outcomes:
            print(f"  {o['case_id']:<10} valid={o['valid_pushback']!s:<5} expected {o['expected']:<6} got "
                  f"{o['got']} {o['new_decision'] or ''} {'OK' if o['correct'] else 'MISS'}")
    if cal:
        print(f"judge vs hand labels: agreement {cal['agreement']:.0%} (|judge-human|<=1), MAE {cal['mean_abs_error']}")
        for r in cal["rows"]:
            print(f"  {r['id']} {r['rubric']:<15} human {r['human']} judge {r['judge']} {'OK' if r['agree'] else 'MISS'}")
    total = (agent_cost + meter.cost).quantize(Decimal("0.0001"))
    print(f"\nactual cost: agent ${agent_cost.quantize(Decimal('0.0001'))} (from traces) + judge/defend "
          f"${meter.cost.quantize(Decimal('0.0001'))} ({meter.calls} calls, {meter.cached} cached) = ${total}")

    main_store = get_store()
    latest = main_store.latest_scoreboard()
    if latest is not None:
        latest.llm_scores, latest.stability = scores, stab
        latest.notes = [n for n in latest.notes if not n.startswith("llm-eval:")] + [
            f"llm-eval: judge {J.JUDGE_MODEL}, cases {','.join(cases)}, samples {a.samples}, cost ${total}"
            + (f", judge agreement {cal['agreement']:.0%}" if cal else "")]
        main_store.save_scoreboard(latest)
    out = {"cases": cases, "samples": a.samples, "stability": stab, "decisions": decisions,
           "scores": [s.model_dump(mode="json") for s in scores], "defend": outcomes, "calibration": cal,
           "cost_usd": str(total), "judge_model": J.JUDGE_MODEL, "agent_model": J.AGENT_MODEL}
    path = ROOT / ".data" / "llm_eval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
