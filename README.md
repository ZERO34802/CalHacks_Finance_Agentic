# ReconAI

AP specialist + vendor-master clerk for Helix Silicon. Full plan: [CLAUDE.md](CLAUDE.md).

P0 for A (intake, pipeline, controls), B (agents, sandbox, approvals) and C (data, state, evals) is built. D's UI is still the minimal shell.

**Keys.** Put `ANTHROPIC_API_KEY` and `FACTORY_API_KEY` in `.env` at the repo root (template: `config/.env.example`). Without them, every LLM/Droid step takes its offline fallback, and PDF, image and email invoices escalate as "evidence missing".

## Quick start

```bash
make setup                 # .venv (Python 3.12) + ui/node_modules
make run CASE=case_02      # one fixture: intake + 10 stages, prints the trace
make eval                  # all fixtures -> scoreboard; exits 1 if any invariant fails
make test                  # skeleton guarantees

make api                   # real backend on :8000, WS /events, docs at /docs
make mock                  # Prism mock of the same OpenAPI spec on :4010 (no WS)
make ui                    # UI on :5173; set VITE_API_URL in ui/.env (default: mock)
make types                 # after a contract change: JSON Schema + OpenAPI + TS types
make data                  # regenerate data/world + 33 cases + answer key (deterministic)

make stdb-start            # SpacetimeDB on :3000 (separate terminal), then:
make stdb-publish          # publish the module; RECONAI_STORE=spacetime make eval
```

Current baseline (no keys, LLM off): **12/33 passed, catch 96%, false alarm 70%, invariants 100%**, identical on SQLite and SpacetimeDB. Every PDF and image case misses because the Reader cannot run offline. Every structured case (API, CSV, XLSX) and every quarantine case passes, except case_16 (its duplicate check needs case_01 to be extracted first).

## Layout and owners

| Path | Owner | What |
| --- | --- | --- |
| `contracts/models.py` | everyone | Pydantic models, the single source of truth. **Announce changes, then `make types`.** |
| `backend/core/` | shared | `Stage` protocol, `Ctx`, `run_case` + `PIPELINE`, policy loader |
| `backend/intake/` | A | connectors, ingest validation + quarantine, CSV/XLSX/API adapters |
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

## Where Droid runs (Factory)

| Job | Trigger | Can touch |
| --- | --- | --- |
| Investigator (`backend/agents/investigator.py`, `droid.py`) | material exception after the Matcher | read-only `ro/` mount with extracted JSON (never raw document text), ERP snapshot, this vendor's memory, the skill; writes only `scratch/` and `proposal.json` |

- Droid runs at the lowest autonomy, with tools limited to `backend/skills/<skill>/tools.yaml`.
- A permission handler allows Create/Edit only on `proposal.json` and `scratch/`.
- A per-run sandbox settings file denies reads of `.env`, `backend/`, `data/`, the DB and the caches. There is no network beyond Factory itself.
- The proposal is validated by code (`Validators`), and the agent can never recommend below the policy floor computed in code.
- Fallback chain: Droid → Claude (structured output, no tools) → a fixed template (labelled `deterministic fallback`).
- `RECONAI_DROID=live|replay|off`.
- Not enforced: there is no container, and Droid's own file reads are limited only by the settings deny list.
- Skill evolution and adapter generation (the other two Droid jobs) are P1/P2.

## Fixtures

| Case | Vendor | Planted | Expected |
| --- | --- | --- | --- |
| case_01 | Kestrel | clean | approve |
| case_02 | Formosa | billed 1000 wafers, received 940 | hold, qty_short |
| case_03 | Kestrel | amended price billed before effective date | hold, price_over |
| case_04 | Penang | bank change from look-alike domain | escalate, bank_change + lookalike_domain |
| case_05 | Aerolane | paid INV-2291 resent as INV-2291-A | reject, duplicate_invoice |

These are the 5 seed cases. `data/generate.py` builds 33 cases in total: PDFs in 3 layouts, scans, CSV, XLSX, API JSON and `.eml`; email, SFTP and API channels; attacks; dedup of each type; and controls. Each case's reasoning is in `data/answer_key.json` (`note`). The formats contract is [data/FORMATS.md](data/FORMATS.md). Vendor-onboarding data is in `data/onboarding/` and is not part of the eval yet.

## Rules

- Merge small and often, each person in their own folders.
- `make eval` must stay at 100% invariants before you merge.
- Integration checkpoints at midnight and 2 AM: merge everything, run `make eval`, fix what broke.
- No secrets in the repo. Copy `config/.env.example` to `.env`.
