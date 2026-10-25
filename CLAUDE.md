# ReconAI

Working guide for everyone and every coding agent in this repo. It covers how the system works today, the rules code must never break, where things live, and how to verify a change.

- Feature details, endpoints and the score: [README.md](README.md).
- Pitch, demo beats and Q&A: [docs/DEMO.md](docs/DEMO.md).
- Inbound formats: [data/FORMATS.md](data/FORMATS.md).
- The original hackathon plan is in git history (`git show efa9b00:CLAUDE.md`).

**Cal Hacks 13.0.** Deadline Sunday Oct 25, 9:00 AM PST: a 3 min pitch plus 2 min Q&A, with a live or recorded demo. Hyphenate may test us live with their own scenario.

---

## 1. What it is

**ReconAI fills two seats at Helix Silicon, a fabless chip company: the AP specialist and the vendor-master clerk.** It matches every wafer and memory bill, explains every gap with citations, remembers every supplier, and never pays or changes bank details without a second person.

| Supplier | Bills | Currency | Planted trouble |
| --- | --- | --- | --- |
| Formosa Wafer Works (TW) | Wafers | TWD | Short delivery (billed 1,000, received 940); promised credit note never arrives |
| Kestrel Memory (KR) | HBM memory | USD | Bills an amended price before the amendment's effective date |
| Penang Pack & Test (MY) | Packaging | USD | Bank details change the day before a $3.3M payment (look-alike domain) |
| Aerolane Freight | Shipping | USD | Unapproved expedite fee for the 3rd time; resends paid INV-2291 as INV-2291-A |

**Internal people (simulated):**

| Person | Role | Can approve up to | Releases payments? |
| --- | --- | --- | --- |
| Ana Lee | AP lead | $100k | No |
| M. Chen | Controller | $1M | Yes |
| R. Okafor | CFO | Above $1M | Yes |
| H. Jogi | CTO | Same as the CFO | Yes |

The limits live in `config/policy.yaml`.

---

## 2. The workflow end to end

### 2a. A vendor gets in (vendor-master seat)

1. **Negotiate (Slack).** `/reconai negotiate <vendor>` in a shared channel. ReconAI privately coaches the Helix owner:
   - where the quote sits against our PO history and the market;
   - the counter, target and walk-away numbers.

   The numbers are Decimal math in `backend/slack/market.py`; Claude only phrases them.
2. **Contract.** `/reconai contract` produces a supply agreement PDF from a fixed template. The supplier clicks **Accept & start onboarding**. Vendors never self-sign-up; it always starts from a Helix request, either this Slack flow or the internal request form in Vendors → Onboarding.
3. **Onboarding checks** (`backend/vendors/`, which reuses the code checks in `backend/onboarding/checks.py`):
   - CRS identity and fraud checks on the owner (sandbox personas);
   - liens, judgments and bankruptcies;
   - sanctions, against a simulated list;
   - duplicate tax ID, bank or domain;
   - bank account vs employee records;
   - look-alike domain;
   - tax form.
4. **Approval.**
   - A low-risk vendor is auto-onboarded on probation (`onboarding.auto_approve_low_risk`).
   - A medium- or high-risk vendor needs a controller.
   - A sanctions hit or an employee-bank match can never be approved.
   - The requester can't approve.
5. **ERP.** Odoo 17 runs via `make erp` and `make erp-setup`; otherwise the built-in ERP is used, labelled "Simulated ERP". ReconAI creates the supplier, products and a confirmed PO from the contract.
6. **Billing cycle in Slack** (`backend/slack/cycle.py`):
   - Each person registers their AP role with `/reconai role`.
   - The vendor posts `/reconai shipped`. This is a claim, never a receipt.
   - A Helix person, never the vendor, records the goods receipt with `/reconai receive` or in the Purchasing page.
   - The vendor sends `/reconai invoice`, or shares a PDF, which goes to intake.
   - After the pipeline runs, approvers get a DM with **Approve** (AP lead) or **Approve & release via Coinbase** (controller, CFO or CTO).
   - Every button re-checks in code: the role, separation of duties, limits and the release rule.

### 2b. A bill gets paid (AP seat)

```
 email / API / SFTP / S3 / ERP
   -> intake        type by content, size, macros, manifests, sender bound to vendor channel  -> else QUARANTINE
   -> reader        CSV/XLSX/API: versioned adapters | PDF/scan/email: Claude with NO tools; flags hidden instructions
   -> doc_dedup     file hash, normalized invoice no, line-item hash, fuzzy, paid history
   -> registry      one case per discrepancy (atomic fingerprint): attach / reopen delta / corrected / related pattern
   -> matcher       3-way match, contract price in force on the invoice date, FX, tolerance, materiality, probation
   -> router        code picks the skill; no skill -> escalate
   -> investigator  Factory Droid in a per-case read-only sandbox -> structured proposal (fallback: Claude, then template)
   -> vendor_guard  look-alike domains, bank changes, employee-bank matches, vendor history
   -> validators    citations exist, every number was computed by code, recommendation within policy
   -> approver      role-played AP lead / controller (separate identity), limits, reject -> re-plan, SLA -> backup
   -> poster        Beancount double entry; refuses SoD breach, over-limit, locked period, re-post; AP tie-out
   after case:      supplier email + follow-up, sub-cases, Memory Writer, skill-evolution observer
   clock (tick):    overdue follow-up reopens the case, SLA escalation, missing-file alerts
```

Then a person takes over in the AP workspace:

1. **Review** the bill in Bills → bill page. It shows the agents' checks, the 3-way match, documents, the agent trace and the Ask ReconAI chat. A second, independent set of code checks runs before any money moves (`backend/review/checks.py`).
2. **Approve** within your limit. CFO and CTO are equivalent for signing. The approval resumes the pipeline at the Poster, so posting stays in one place.
3. **Schedule** a payment run. A run pays at most what the Poster booked: the full total, or only the undisputed part of a hold, net of credits.
4. **Release.** Only a controller, CFO or CTO can release. AP leads approve but never release. A controller, CFO or CTO who approved a bill may release it directly, including "Approve & release via Coinbase".
   - **Bank rail:** simulated.
   - **Coinbase rail:** real USDC on Base Sepolia testnet, scaled down, always to the vendor master's wallet.
   - **Payment guard:** re-checked at scheduling and again at release. Bank mismatch, duplicate, hidden instructions, a pending callback, or a probation vendor without a goods receipt all block payment.

### 2c. The system improves (only through people)

- **Skill evolution.** Two similar controller rejections lead Droid to propose a diff on a *copy* of the skill. A replay against the eval gate follows, then controller approval, then a new version (case_43→45).
- **Memory.** After each case, the Memory Writer updates that supplier's file from trusted signals only.

---

## 3. Rules code must never break

These are enforced in code and checked by `make eval` invariants. Never weaken them, and never move them into a prompt.

**Money and math**
- All amounts are Decimal strings or integer cents, never floats. LLMs never compute totals; validators recompute every number a proposal cites.
- Debits = credits; AP subledger = GL control after every post; idempotent posting and emails.
- Materiality, approval limits, locked periods and tolerances come from `config/policy.yaml`.

**Separation of duties**
- The agent proposes, a different role approves, and code posts.
- The requester never approves.
- Only controller, CFO or CTO releases a payment.
- Vendor-master changes always need a second person.
- The agent can never initiate payment or edit bank details.
- The policy floor is computed in code: the agent can make an outcome stricter, never softer.

**Untrusted input**
- Document, email, chat and payload text never reaches a prompt that has tools.
- The Reader has zero tools.
- The Droid sandbox sees extracted JSON only.
- Supplier replies go through the Reader.
- A document can never choose its own skill.
- Payment and bank details come only from the vendor master, never from an invoice. Vendor confirmation goes through the contact on file, never a reply to the sender.

**Sandbox (per case)**
- Read-only mounts: case data, ERP snapshot, this vendor's memory, the selected skill.
- The scratchpad is writable and untrusted.
- The only exit is a proposal file that code validates.
- No network, no secrets, one sandbox per case.
- Known limitation: there is no container; Droid's own reads are limited by a deny list.

**Learning**
- Skills, memory and rules learn only from human decisions and verified outcomes, never from incoming documents or emails.
- Tightening a rule is free. Loosening needs a controller plus a second signer, and some limits are locked.
- New skills start in shadow mode.
- The agent evolves **adapters**, never **connectors**: new SFTP servers, buckets, inboxes or endpoints are a human decision. A format change that adds payment fields is treated as a possible attack.

**Memory**
- Every line has a provenance tag and a valid-from date. History is kept.
- Lookup is by exact vendor ID only, never by similarity across vendors.
- Memory is context, not evidence: a decision still needs current documents.
- Audit replay uses memory as of the decision date.
- Never store full bank numbers (last 4 only) or instructions that loosen controls.

**Traceability**
- Every decision records its source document and line, rule, skill version, memory version and approver.
- Failed fetches are never guessed: they show "evidence missing" and the case escalates.
- No step may go missing from the trace.

---

## 4. Where things live

| Path | Owner | What |
| --- | --- | --- |
| `contracts/models.py` | everyone | Pydantic models, the single source of truth. **Announce changes, then `make types`** (regenerates JSON Schema, OpenAPI and `ui/src/types/contracts.ts`) |
| `backend/core/` | lead | Stage protocol, Ctx, runner + gate, hooks, Claude helper (`llm.py`), policy loader |
| `backend/intake/`, `backend/pipeline/`, `backend/onboarding/checks.py`, `ledger/` | A | connectors, adapters, reader, dedup, registry, matcher, validators, poster, onboarding checks |
| `backend/agents/`, `backend/skills/`, `backend/pipeline/vendor_guard.py`, `backend/onboarding/flow.py` | B | router, sandbox, Droid investigator, approver, SLA, handoff, supplier loop, skill evolution |
| `data/`, `backend/store/`, `backend/trace/`, `backend/memory/`, `backend/evals/`, `spacetime/` | C | generator + answer key (48 cases), stores (SQLite / SpacetimeDB), tracing, Memory Writer, eval harness, LLM judge |
| `ui/`, `backend/ap/`, `backend/review/`, `backend/dashboard/`, `backend/vendors/` | D | AP workspace, payment runs, Coinbase, discounts, prepayments, second-line checks, chat, onboarding UI |
| `backend/slack/` | D | Slack bot: negotiation coach, contract, onboarding, goods receipt, roles |
| `backend/erp/` | D | Odoo XML-RPC client, PO from contract, goods receipts (mirrored into the store) |
| `backend/api/` | shared | `app.py` + `routes_*.py`; `openapi.json` is generated |
| `config/policy.yaml` | shared | materiality, limits, release roles, locked periods, FX (simulated), SLA, probation |

**Where Claude and Droid run:**

| Job | Runtime | Tools |
| --- | --- | --- |
| Reader | Claude Opus 5.5 | **None** |
| Investigator | Factory Droid, lowest autonomy | `Read/Grep/Glob/LS` |
| Skill evolution | Factory Droid | Edits a skill copy only |
| Approver / controller | Claude, separate identity per role | None |
| Supplier email, reply reading, chat, Slack phrasing | Claude, single calls | None |
| LLM judge | Claude Sonnet 5.5, independent of the agent | None |

Fallbacks: Droid → Claude → template (labelled). With no keys, `make eval` runs offline.

---

## 5. UI conventions (`ui/src/review/`)

- **Structure**
  - The live app is `ui/src/review/`: entry `main.tsx`, shell `ReviewApp.tsx`, hash routes in `context.tsx`.
  - Everything else under `ui/src/` is the legacy dashboard (`/legacy.html`) and the prototype (`/prototype.html`).
  - Pages: Home, Insights (`Reports.tsx`), Bills, Bill (`BillPage.tsx`), Vendors, Purchasing, Policy (`Settings.tsx`).
  - There is no Memory page; `#/memory/...` redirects to the vendor. Vendor memory shows inside the vendor panel.
- **Colour**
  - One family from the logo teal `#0E6E76`. `main.tsx` remaps Mantine's named colours onto teal, aqua, slate and teal-tinted grey.
  - **Amber + warning triangle** means needs review.
  - **Red + danger octagon** means rejected, blocked, failed or fraud. Use `StageIcon` / `StageBadge` from `parts.tsx`.
  - Add no other hues.
- **Card headers:** use `CardHead` (`HEAD_BG` = `brand.0`, `HEAD_BORDER` = `brand.2`) so headers never merge with the rows below.
- **Money**
  - `amount(value, currency)` renders symbols ($, NT$, RM, ₩…), never "USD".
  - `symbols()` converts currency codes inside backend text.
  - Sum only with `sumMoney` (BigInt cents). `Number()` is for chart display only.
- **Layout**
  - Pages fit the window (`calc(100vh - 124px)`); long lists scroll inside their card, never the whole page.
  - Below 860px tall, pages switch to a short-screen mode with fewer rows.
- **Agent trace:** `trace.tsx` (React Flow) groups the raw steps into pipeline phases. Click a phase for its sub-steps. A controller rejection shows as a dashed re-plan loop.
- **Copy:** minimal, plain-language facts that mean something to a finance lead. No decorative shapes, no boxed tags, no explanatory paragraphs.

---

## 6. Run and verify

```bash
make setup                          # Python 3.12 venv + ui deps
cp config/.env.example .env         # ANTHROPIC_API_KEY, FACTORY_API_KEY (optional: CRS_*, SLACK_*, CDP/Coinbase, ODOO_*)
make eval                           # 48 cases -> scoreboard; exits 1 if any invariant fails
make run CASE=case_04               # one case, full trace
make test                           # all tests
make api & make ui                  # http://localhost:5173 (ui/.env: VITE_API_URL=http://localhost:8000)
make tick AS_OF=2026-10-28          # advance the business clock
RECONAI_LLM=replay RECONAI_DROID=replay make eval   # free, from the response cache
```

Before merging:
- `make eval` shows no regressions and 100% invariants.
- The relevant `make run CASE=...` behaves as expected.
- For UI changes, `cd ui && npx tsc --noEmit -p tsconfig.json --noUnusedLocals && npx tsc -b` passes, and the page is checked in a browser at 1440×900 and 1280×800 with no page scroll.

The env flags (`RECONAI_LLM`, `RECONAI_DROID`, `RECONAI_MEMORY`, `RECONAI_STORE`, `RECONAI_ERP`, `RECONAI_CRS`…) are listed in the README.

**Simulated, and labelled so in the UI:**
- FX rates;
- approver identities;
- supplier mailboxes (redirected to a demo inbox);
- vendor API senders;
- SFTP/S3 (folders);
- the malware scan hook;
- employee records and callbacks;
- the sanctions list;
- bank settlement;
- the ERP when Odoo is off;
- CRS when no credentials are set (recorded sandbox replies).

**Not built:** format evolution (adapting adapters to a vendor's new API/CSV shape), the auditor evidence pack, Cartesia voice, and real ERP sync beyond POs and receipts.

---

## 7. Engineering guidelines

Based on the Karpathy-inspired Claude Code guidelines (forrestchang/andrej-karpathy-skills, MIT).

1. **Think before coding.** State assumptions. If a request has two readings, list them. If something simpler exists, say so. If confused, stop and ask.
2. **Simplicity first.** Write the minimum code that solves the problem: no speculative features, abstractions or error handling for impossible cases.
3. **Surgical changes.** Touch only what the task needs and match the surrounding style.
   - Remove only what your own change made unused.
   - Mention other dead code; don't delete it.
   - Don't delete someone else's stub.
4. **Goal-driven.** Turn tasks into checks ("write a failing test for the bad input, then make it pass"). For multi-step work, write the plan with a check per step, and loop until the checks pass.

**ReconAI-specific:**
- Stay in your own folders (section 4). Announce `contracts/` changes first.
- Every stage implements the Stage interface and logs through the trace helper:

  ```python
  class Matcher:
      name = "matcher"
      def run(self, case: Case, ctx: Ctx) -> Case:
          ...                                              # all math in code, Decimal only
          ctx.trace.annotate(inputs=[...], detail={...})   # optional; status=StepStatus.blocked etc.
          return case
  ```

  The runner wraps each stage in a trace step, saves the case and emits WS events. To fail a step, raise.
- No secrets in the repo: use `.env` and keep `config/.env.example` updated.
- Keep PRs small and merge them often.
- **Hackathon tradeoff:** full rigor on contracts, money logic, controls and security; use judgment on UI tweaks and obvious one-liners.
