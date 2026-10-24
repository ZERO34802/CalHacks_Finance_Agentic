# ReconAI

**ReconAI fills two seats at Helix Silicon, a fabless chip company: the AP specialist and the vendor-master clerk.** It matches every wafer and memory bill, explains every gap with citations, remembers every supplier, and never pays or changes bank details without a second approver.

> Demo script and Q&A answers: [docs/DEMO.md](docs/DEMO.md). Full plan: [CLAUDE.md](CLAUDE.md).

## Results

Final live run on 48 hand-built cases (real Claude + Factory Droid calls, cached responses reused):

| Passed | Catch rate | False alarms | Control invariants | Onboarding |
| --- | --- | --- | --- | --- |
| **46/48** | **100%** | **0%** | **100%** (9 checks) | 6/6 |

- Every format and channel passes except two clean PDFs by email, which were approved correctly but tagged with a skill after a reviewer re-plan.
- Dollars caught before payment: USD 857k. Hours saved: 23 (an estimate).
- Cost of the run: $2.07.

- The score is **deterministic**: decisions, discrepancy types, routing, duplicate links, extraction (invoice no / total / currency), variance to the cent, paid amount, and control invariants.
- **Misses are shown, not hidden:** `make eval` prints every failed check.
- **LLM-judged quality is reported separately** (`make eval-llm`): explanation, supplier email, escalation, and defending a decision against a skeptical auditor. The judge is Claude Sonnet 5.5, a different model from the Opus 5.5 agent, and it is calibrated against hand labels.

## How a bill flows

```
 email / API / SFTP / S3 / ERP
   -> intake       file type by content, size, macros, manifests, sender bound to vendor channel  -> else QUARANTINE
   -> reader       CSV/XLSX/API: fixed adapters | PDF/scan/email: Claude with NO tools; code recomputes every amount;
                   hidden instructions flagged
   -> doc_dedup    file hash, normalized invoice no, line-item hash, fuzzy, paid history
   -> registry     fingerprint per discrepancy (atomic); attach / reopen delta / corrected / related pattern / supplier reply
   -> matcher      3-way match + contract price in force on the invoice date, FX, tolerance, materiality, probation
   -> router       code picks the skill (documents never choose); no skill -> escalate
   -> investigator Factory Droid in a per-case sandbox -> structured proposal (fallback: Claude, then template)
   -> vendor_guard look-alike domains, bank changes, employee-bank matches, vendor history
   -> validators   every citation exists, every number is one code computed, recommendation within policy
   -> approver     AP lead / controller role-play (separate identity), limits by amount, reject -> re-plan,
                   pay-the-undisputed-part, SLA timer -> backup approver
   -> poster       Beancount double entry; refuses SoD breach, over-limit, locked period, re-post; AP tie-out
   after case:     supplier email + follow-up, sub-cases, queue priority, Memory Writer, skill-evolution observer
   clock ticks:    overdue follow-up -> case reopens, SLA escalation, missing-file alerts
```

Then a person reviews the bill in the AP workspace and approves within their limit. A **different person** releases the payment run (settlement is simulated).

## Controls that make it hireable

- **All math in code** (Decimal). The LLM never computes totals; validators recompute every number it cites.
- **The Reader has no tools**, so a poisoned PDF can't trigger anything (case_31). Untrusted text never reaches a prompt that has tools: the Droid sandbox gets extracted JSON only.
- **Agent proposes, a different role approves, code posts.** The requester can never approve. The agent can never pay or edit bank details.
- **A policy floor computed in code:** the agent can make an outcome stricter, never softer.
- **Every decision cites** a document and line, rule, skill version, memory version and approver.
- **Failed fetches are never guessed.** They show as "evidence missing" and the case escalates.
- **Controls enforced by code:**
  - materiality thresholds;
  - approval limits ($100k AP lead / $1M controller / CFO above);
  - locked periods;
  - AP subledger = GL tie-out after every post;
  - idempotent posting;
  - pay only the undisputed part;
  - kill switch (global or per vendor);
  - human handoff and release.

## Where Claude and Factory Droid run

| Job | Model / runtime | Can touch |
| --- | --- | --- |
| Reader | Claude Opus 5.5, **no tools**, structured output | the document only |
| Investigator | **Factory Droid**, lowest autonomy, tools `Read/Grep/Glob/LS` | read-only sandbox (extracted JSON, ERP snapshot, this vendor's memory, the skill); exits through a code-validated structured proposal |
| Skill evolution | **Factory Droid**, edits a *copy* of the skill | the copy's `SKILL.md`/`policy.yaml` only. Code checks the real skills dir is unchanged, replays the eval gate, and applies only after controller sign-off (loosening needs a second signer) |
| Approver / controller | Claude Opus 5.5, separate identity per role, no tools | the proposal and policy (not raw documents) |
| Supplier email, reply reading, reviewer chat | Claude Opus 5.5, single calls, no tools | the case record; reply text is untrusted and never written to memory |
| LLM judge | Claude Sonnet 5.5 (independent of the agent) | eval artifacts |

Fallbacks: Droid → Claude → a fixed template, labelled "deterministic fallback". With no API keys, `make eval` still runs offline.

**Not Droid, on purpose:** the Reader (must have zero tools), the approver and the judge (must stay independent of the agent they judge), and the deterministic stages.

**Sandbox enforcement:**
- **Enforced:** read-only mounts, no raw document text, the permission handler, code validation of the output, and per-run sandbox settings that deny reads of `.env`, the code, data, the DB and the caches.
- **Not enforced:** there is no container, and Droid's own file reads are limited only by that deny list.

## Skills, memory, dedup, evals

- **Skills** (`backend/skills/`): `ap-3way-match` and `vendor-bank-change`, each with a `SKILL.md`, `policy.yaml` and `tools.yaml` allowlist. Code routes to them.
  - Self-evolving: two similar controller rejections lead to a Droid diff, then a replay gate, then controller approval, then a new version (case_43→45). There is a ratchet: tightening is free, loosening needs two signers.
- **Memory** (`backend/memory/`): one file per supplier, person, open matter or pattern. Every line carries provenance and a valid-from date.
  - Written only from trusted signals: human decisions, outcomes, and system-of-record changes. Never from documents or emails (case_32).
  - Versioned, with history kept and last-4-only bank numbers.
  - It changes outcomes where history matters: case_42 holds a $45 fee with memory, and approves with `RECONAI_MEMORY=off`.
- **Dedup:** documents (file hash, normalized number, line hash, fuzzy, paid) and cases (fingerprint per discrepancy, corrections, patterns, sub-cases).
- **Evals** (`backend/evals/`): a deterministic harness with per-format and per-channel breakdown, tick fixtures for time-based controls, separately scored onboarding, the LLM judge, and consistency across repeated samples.

## Real vs simulated

| Real | Simulated (labelled in the UI) |
| --- | --- |
| Claude reading PDFs/scans, Droid investigations, role-play reviewers, ledger (Beancount), matching, dedup, controls, evals, SpacetimeDB store | FX rates, supplier emails (drafted, not sent), approvers' identities, vendor API senders, SFTP/S3/ERP (folders + mock payloads), malware scan hook, employee records, callbacks, CRS (unless credentials are set), payment settlement, sanctions list |

## Known limitations

- The 48 cases are hand-built. Judges' own scenarios escalate when no skill fits, which is by design.
- **Live reviewer wording can vary:** a re-plan count can flip between samples, but decisions are stable.
- Format evolution (adapting to a vendor's new API/CSV shape), the auditor evidence pack, Coinbase and Cartesia are not built (P2).
- **Two onboarding paths:** the UI flow (`backend/vendors/`, with CRS) reuses the scored flow's checks (`backend/onboarding/`). The approval rules are duplicated.
- The UI's payment-run clock is the wall clock, not a fixture's `as_of`.

## Run it

```bash
make setup                         # Python 3.12 venv + ui deps
cp config/.env.example .env        # ANTHROPIC_API_KEY, FACTORY_API_KEY (optional: CRS_*)
make eval                          # 48 cases -> scoreboard (exit 1 if any invariant fails)
make run CASE=case_04              # one case, full trace
make api & make ui                 # http://localhost:5173 (ui/.env: VITE_API_URL=http://localhost:8000)
make test                          # all teams' tests
make eval-llm ARGS="--cases case_03 --yes"   # LLM judge + consistency (costs money; RECONAI_LLM=replay is free)
make tick AS_OF=2026-10-28         # advance the business clock: SLA, follow-ups, missing files
make stdb-start / make stdb-publish  # SpacetimeDB; then RECONAI_STORE=spacetime
```

Env flags:

| Flag | Values | What it does |
| --- | --- | --- |
| `RECONAI_LLM` | `live` \| `replay` \| `off` | Claude calls |
| `RECONAI_DROID` | `live` \| `replay` \| `off` | Droid runs |
| `RECONAI_MEMORY` | `off` | memory ablation |
| `RECONAI_SAMPLE` | `n` | fresh samples for the consistency eval |
| `RECONAI_SKILLS_DIR` | path | skills override |
| `RECONAI_SIM_SKILL_APPROVAL` | `off` | approve skill changes by hand in the demo |
| `RECONAI_DEMO_PACE` | seconds | delay per step, so the live pipeline is visible |
| `RECONAI_STORE` | `sqlite` \| `spacetime` | which store to use |

## The AP workspace (UI)

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

**Bills on real pipeline output** (`backend/ap/state.py`): a bill is a parent case. Sub-cases are grouped under it; supplier replies, credit notes and corrected invoices that add nothing to pay show in its Activity. A bill's **payable** amount is what the Poster booked (`paid_amount` once a journal entry exists: the full total, or only the undisputed part of a hold), net of credit notes. Payment runs pay at most that and never post to the ledger. `POST /approvals/{id}` checks SoD + limits, refuses bank-change / look-alike / hidden-instruction escalations until the callback follow-up is done, and then resumes the pipeline at the Poster (`run_case(start_at="poster")`), so posting stays in one place. On a hold the default scope is `undisputed`.

**Pre-payment checks** (`backend/review/checks.py`, code, Decimal): read the system of record from the store (PO, receipts, contract terms in force on the invoice date, paid history, vendor master, earlier bills). Bank account vs vendor master, look-alike sender domain, duplicate (paid or in process), PO missing, currency or total mismatch, quantity short, price above the agreed price, line not on PO, hidden instructions, probation, with the policy's materiality and tolerances. They are a second, independent line of defence before money moves; where they disagree with the agents' decision the bill shows it (`Bill.disagreements`). With replayed LLM output they agree on 40/42 bills; case_42 (memory) and case_45 (skill evolution) are stricter than code by design. **Payment guard:** bank mismatch, duplicate, hidden instructions, the out-of-band step, or a probation vendor without a GRN block payment at scheduling and again at release.

Endpoints: `GET /ap/discounts`, `GET|POST /ap/prepayments`, `GET /ap/prepayments/quote`, `POST /ap/prepayments/{id}/decide`, `GET /vendors/onboarding/samples`, `GET /vendors/onboarding/list`, `POST /vendors/onboarding`, `POST /vendors/onboarding/{id}/recheck|decide`, `GET /ap/bills`, `GET /ap/bills/{id}`, `GET /ap/report`, `GET /ap/settings`, `GET|POST /ap/payments`, `POST /ap/payments/{id}/release`, plus `POST /intake`, `GET /cases/{id}/review`, `POST /cases/{id}/chat`, `POST /approvals/{id}`. Payment runs, prepayments and onboarding cases are stored in the same SQLite file (`payment_batches`, `prepayments`, `onboarding` tables); settlement is **simulated**.

**Early-pay discounts** (`backend/ap/discounts.py`): terms live on the vendor master (`data/world/vendors.json` from `data/generate.py`, labelled demo terms), never read from the invoice. Code computes the discount on the payable amount (Decimal, half-up), the last day to earn it (invoice date + discount days) and the annualized return. A payment run dated inside the window takes the discount automatically; blocked or unapproved bills are listed but can't be scheduled.

**Advance payments** (`backend/ap/payments.py`): buy vendor credit at the contract's prepay discount (Kestrel 3%, Formosa 4%), capped per vendor. Prepayments skip the 3-way match, so only a controller or CFO who is not the requester can approve; vendors on probation can't be prepaid. Credit is applied oldest-first to that vendor's next payment runs (gross − discount − credit = net). Settlement is simulated.

**Vendor onboarding** (`backend/vendors/onboarding.py`, `backend/vendors/crs.py`): vendors never self-sign-up. Checks: CRS business identity (Experian search), business credit (Intelliscore+), liens/judgments/bankruptcies, sanctions (OFAC), plus the code checks of A's scored flow (`backend/onboarding/checks.run_checks`: duplicate tax ID / bank / domain, simulated sanctions list, bank vs world employees, look-alike domain, tax form, simulated domain age) and a same-name warning. Sample requests: `backend/vendors/samples.json` (CRS scenarios) plus C's `data/onboarding/onb_*.json`. A CRS timeout is retried once, then the check is "incomplete" and the vendor can't be approved until re-run. Requester can't approve; medium/high risk needs a controller; OFAC or employee-bank matches can't be approved at all. Approved vendors start on probation. CRS covers US businesses only; non-US vendors show "not covered" and need manual documents.

CRS: set `CRS_BASE_URL`, `CRS_USERNAME`, `CRS_PASSWORD` (and `CRS_AUTH_HEADER` / `CRS_AUTH_SCHEME` if the sandbox needs them) to call the live API. Without them a **simulated** sandbox of fictional test businesses is used and every result is labelled simulated. The CRS portal doesn't publish the base URL or auth header, and the response field mapping must be confirmed against a real sandbox response.

Chat: Claude (`claude-opus-5-5`, no tools) from the case record when `ANTHROPIC_API_KEY` is set; otherwise deterministic answers from the same record. Not built (out of scope): IRS 1099 filing, card payments/cashback, real ERP sync.

Other pages: `/prototype.html` (visual concept), `/legacy.html` (earlier dashboard).

## For contributors

| Path | Owner | What |
| --- | --- | --- |
| `contracts/models.py` | everyone | Pydantic models, the single source of truth. **Announce changes, then `make types`.** |
| `backend/core/` | lead | Stage protocol, Ctx, runner + gate, hooks, Claude helper (`llm.py`), policy loader |
| `backend/intake/`, `backend/pipeline/`, `backend/onboarding/checks.py`, `ledger/` | A | connectors, adapters, reader, dedup, registry, matcher, validators, poster, onboarding checks |
| `backend/agents/`, `backend/skills/`, `backend/pipeline/vendor_guard.py`, `backend/onboarding/flow.py` | B | router, sandbox, Droid investigator, approver, SLA, handoff, supplier loop, skill evolution |
| `data/`, `backend/store/`, `backend/trace/`, `backend/memory/`, `backend/evals/`, `spacetime/` | C | generator + answer key, stores, tracing, Memory Writer, harness, LLM judge, metrics |
| `ui/`, `backend/ap/`, `backend/review/`, `backend/dashboard/`, `backend/vendors/` | D | AP workspace, payment runs, discounts, prepayments, second-line checks, chat, onboarding UI |
| `backend/api/` | shared | `app.py` + `routes_a/b/c.py`; `openapi.json` is generated |
| `config/policy.yaml` | shared | materiality, limits, locked periods, FX (simulated), SLA, probation, queue, metrics |
| `data/FORMATS.md` | shared | inbound formats, decision table, P1 conventions |

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

Rules: merge small and often, stay in your own folders, keep `make eval` invariants at 100% before merging, and commit no secrets.
