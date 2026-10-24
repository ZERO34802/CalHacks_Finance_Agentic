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
| `backend/store/factory.py` | D | `make_store()`: `RECONAI_STORE=sqlite` (default) or `spacetime` |
| `backend/trace/` | C | `Tracer`: `with ctx.trace.step(...)`, `ctx.trace.annotate(...)`, events |
| `backend/memory/` | C | memory file parser (writer later) |
| `backend/evals/` | C | fixture loader, harness, invariants, scoreboard |
| `backend/api/` | shared | thin FastAPI layer; `openapi.json` is generated |
| `data/` | C | 5 hand-made cases, `answer_key.json`, `vendors.json`, `paid_history.json`, memory files |
| `backend/dashboard/` | D | read models: approval queue priority, business metrics, failures panel |
| `ui/` | D | Vite + React dashboard; `src/types/contracts.ts` is generated |
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

## AP workspace (D)

`make api` + `make ui` (with `ui/.env` → `VITE_API_URL=http://localhost:8000`), then open http://localhost:5173.

**Flow:** invoice arrives (`POST /intake`, 202) → agents run in the background → notification → the bill lands in the right queue → a person reviews (summary, checks, 3-way match, GL coding, chat, documents, trace, activity) → approves within their limit → the bill is batched into a payment run → **a different person** releases it (simulated).

Layout modelled on bill-pay tools (⌘K search, Bill Pay > Bills as the core, three-pane bill review).

| Screen | For the finance team |
| --- | --- |
| Home | Needs your sign-off, ready to pay, payment-blocked, due in 7 days, touchless rate, cash out by week, **early-pay discounts** (ready-to-pay bills still inside their discount window, best annualized return first; one click schedules a run on the last discount day) |
| Bills | Tabs **Overview · For approval · For payment · History**, status chips, inline warning rows (duplicate, fraud signals, overbilling), Review per row, footer total. For approval: bulk approve/hold/reject. For payment: **Review payments** drawer (schedule approved bills, release scheduled runs grouped by date; you can't release a run you prepared) |
| Bill (3 panes) | Left: bill list by stage, search, Prev/Next (K/J). Centre: **Ready to approve / Review recommended / Higher risk of fraud** card with failed checks and checks passed (with references), payment status stepper + estimated date, vendor with last paid, bill details, line items with suggested GL, payment method (ACH / domestic wire / check for US, international wire otherwise), pay-to = vendor master, memo, **approval chain** (agents → role by amount, requester removed for separation of duties → release payment). Tabs: Activity, Agent trace, **Ask ReconAI** chat. Sticky actions: Hold · Reject · **Approve & schedule** (disabled if your limit doesn't cover it). Right: invoice as extracted (printed bank account flagged if it differs), all documents, the email |
| Vendors | **Vendor master**: terms (e.g. 2/15 net 30), open balance, tax form (W-9 / W-8BEN-E), risk, bank-change alerts, memory with provenance, **advance payments**. **Onboarding**: internal request form (8 sample requests), CRS + code checks, approve/reject with separation of duties |
| Insights | **Spending** (vendor, GL) · **AP aging** (bills by bucket + outstanding bills) + cash out by week · **Efficiency** (touchless, caught before payment, discounts captured / available / missed, agent accuracy vs answer key) |
| Policy | Approval matrix, SLA, materiality, tolerances, locked periods, GL accounts, FX (simulated), integrations |

**Pre-payment checks** (`backend/review/checks.py`, code, Decimal): bank account vs vendor master, look-alike sender domain, duplicate vs paid history, quantity short, price above PO (flags an amendment on file), line not on PO, hidden instructions, probation. On the fixtures they catch all five planted issues and nothing on the clean invoice. They overlap A's Matcher / DocDedup / Vendor Guard on purpose: a second, independent line of defence before money moves. **Payment guard:** bank mismatch, duplicate or hidden instructions block payment even after approval.

Endpoints: `GET /ap/discounts`, `GET|POST /ap/prepayments`, `GET /ap/prepayments/quote`, `POST /ap/prepayments/{id}/decide`, `GET /vendors/onboarding/samples`, `GET /vendors/onboarding/list`, `POST /vendors/onboarding`, `POST /vendors/onboarding/{id}/recheck|decide`, `GET /ap/bills`, `GET /ap/bills/{id}`, `GET /ap/report`, `GET /ap/settings`, `GET|POST /ap/payments`, `POST /ap/payments/{id}/release`, plus `POST /intake`, `GET /cases/{id}/review`, `POST /cases/{id}/chat`, `POST /approvals/{id}`. Payment runs, prepayments and onboarding cases are stored in the same SQLite file (`payment_batches`, `prepayments`, `onboarding` tables); settlement is **simulated**.

**Early-pay discounts** (`backend/ap/discounts.py`): terms live on the vendor master (`data/vendors.json`, labelled demo terms), never read from the invoice. Code computes the discount (Decimal, half-up), the last day to earn it (invoice date + discount days) and the annualized return. A payment run dated inside the window takes the discount automatically; blocked or unapproved bills are listed but can't be scheduled.

**Advance payments** (`backend/ap/payments.py`): buy vendor credit at the contract's prepay discount (Kestrel 3%, Formosa 4%), capped per vendor. Prepayments skip the 3-way match, so only a controller or CFO who is not the requester can approve; vendors on probation can't be prepaid. Credit is applied oldest-first to that vendor's next payment runs (gross − discount − credit = net). Settlement is simulated.

**Vendor onboarding** (`backend/vendors/onboarding.py`, `backend/vendors/crs.py`): vendors never self-sign-up. Checks: CRS business identity (Experian search), business credit (Intelliscore+), liens/judgments/bankruptcies, sanctions (OFAC), plus code checks for duplicate vendor (tax ID, bank, name), bank account vs employee records (`data/onboarding/employees.json`), look-alike email domain and tax form. A CRS timeout is retried once, then the check is "incomplete" and the vendor can't be approved until re-run. Requester can't approve; medium/high risk needs a controller; OFAC or employee-bank matches can't be approved at all. Approved vendors start on probation. CRS covers US businesses only; non-US vendors show "not covered" and need manual documents.

CRS: set `CRS_BASE_URL`, `CRS_USERNAME`, `CRS_PASSWORD` (and `CRS_AUTH_HEADER` / `CRS_AUTH_SCHEME` if the sandbox needs them) to call the live API. Without them a **simulated** sandbox of fictional test businesses is used and every result is labelled simulated. The CRS portal doesn't publish the base URL or auth header, and the response field mapping must be confirmed against a real sandbox response.

Chat: Claude (`claude-opus-5-5`, no tools) from the case record when `ANTHROPIC_API_KEY` is set; otherwise deterministic answers from the same record. Not built (out of scope): IRS 1099 filing, card payments/cashback, real ERP sync.

Other pages: `/prototype.html` (visual concept), `/legacy.html` (earlier dashboard).

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
