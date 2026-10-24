# ReconAI

AP specialist + vendor-master clerk for Helix Silicon. Full plan: [CLAUDE.md](CLAUDE.md).

This is the **walking skeleton**: every stage is a stub that returns valid output, so the pipeline runs end to end today. Replace your own stubs; don't touch anyone else's.

## Quick start

```bash
make setup                 # .venv (Python 3.12) + ui/node_modules
make run CASE=case_02      # one fixture through all 10 stages, prints the trace
make eval                  # all fixtures -> scoreboard; exits 1 if any invariant fails
make test                  # skeleton guarantees

make api                   # real backend (stub stages) on :8000, WS /events, docs at /docs
make mock                  # Prism mock of the same OpenAPI spec on :4010 (no WS)
make ui                    # UI on :5173; set VITE_API_URL in ui/.env (default: mock)
make types                 # after a contract change: JSON Schema + OpenAPI + TS types
```

Current baseline with stubs: **1/5 passed, catch 50%, false alarms 0%, invariants 100%.** Every point gained from here comes from a real stage.

## Layout and owners

| Path | Owner | What |
| --- | --- | --- |
| `contracts/models.py` | everyone | Pydantic models, the single source of truth. **Announce changes, then `make types`.** |
| `backend/core/` | shared | `Stage` protocol, `Ctx`, `run_case` + `PIPELINE`, policy loader |
| `backend/intake/` | A | connectors, ingest validation, adapters (not in skeleton yet) |
| `backend/pipeline/` | A | reader, doc_dedup, registry, matcher, vendor_guard, validators, poster |
| `backend/agents/` | B | router, investigator, approver |
| `backend/skills/` | B | `ap-3way-match/`, `vendor-bank-change/` |
| `backend/store/` | C | `Store` protocol + `SQLiteStore` (SpacetimeDB goes behind the same protocol) |
| `backend/trace/` | C | `Tracer`: `with ctx.trace.step(...)`, `ctx.trace.annotate(...)`, events |
| `backend/memory/` | C | memory file parser (writer later) |
| `backend/evals/` | C | fixture loader, harness, invariants, scoreboard |
| `backend/api/` | shared | thin FastAPI layer; `openapi.json` is generated |
| `data/` | C | 5 hand-made cases, `answer_key.json`, `vendors.json`, `paid_history.json`, memory files |
| `ui/` | D | Vite + React; `src/types/contracts.ts` is generated |
| `config/policy.yaml` | shared | materiality, limits, locked periods, FX (simulated), accounts, skill routing |
| `ledger/` | A | Beancount |

## Writing a stage

```python
class Matcher:
    name = "matcher"
    def run(self, case: Case, ctx: Ctx) -> Case:
        ...                                    # all math in code, Decimal only
        ctx.trace.annotate(inputs=[...], detail={...})   # optional; status=StepStatus.blocked etc.
        return case
```

The runner wraps every stage in a trace step and saves the case after it. Timing, failures, and WS events are automatic. Raise to fail the step. Use `annotate(status=...)` for skipped, blocked, or escalated.

## Fixtures

| Case | Vendor | Planted | Expected |
| --- | --- | --- | --- |
| case_01 | Kestrel | clean | approve |
| case_02 | Formosa | billed 1000 wafers, received 940 | hold, qty_short |
| case_03 | Kestrel | amended price billed before effective date | hold, price_over |
| case_04 | Penang | bank change from look-alike domain | escalate, bank_change + lookalike_domain |
| case_05 | Aerolane | paid INV-2291 resent as INV-2291-A | reject, duplicate_invoice |

Fixtures arrive pre-parsed (`invoice`, `po`, `receipts` filled in). Raw document text is in `documents[].text` for the real Reader.

## Rules

- Merge small and often, each person in their own folders.
- `make eval` must stay at 100% invariants before you merge.
- Integration checkpoints at midnight and 2 AM: merge everything, run `make eval`, fix what broke.
- No secrets in the repo. Copy `config/.env.example` to `.env`.
