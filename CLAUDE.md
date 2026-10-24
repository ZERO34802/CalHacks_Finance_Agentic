# ReconAI: Cal Hacks 13.0 Plan

**Deadline: Sunday Oct 25, 9:00 AM PST. Hard.** 3 min pitch + 2 min Q&A. Live or recorded demo required. Hyphenate may test us with their own scenario live.

---

## 1. The pitch in one line

> **ReconAI** fills the **AP specialist** and **vendor-master clerk** seats at Helix Silicon, a fabless chip company: matches every wafer and memory bill, explains every gap, remembers every supplier, and never pays or changes bank details without a second approver.

**The company (fictional):** Helix Silicon designs AI chips and buys everything else.

| Supplier | What they bill | Currency | Planted trouble |
| --- | --- | --- | --- |
| Formosa Wafer Works (TW) | Wafers | TWD | Short delivery (billed 1,000, received 940); credit note promised, never arrives |
| Kestrel Memory (KR) | HBM memory | USD | Bills amended price before the amendment's effective date |
| Penang Pack & Test (MY) | Packaging | USD | Bank details change the day before a multi-million payment (look-alike domain) |
| Aerolane Freight | Shipping | USD | Unapproved air-freight expedite fee, 3rd time this year; resends a paid invoice as INV-2291-A |

**Internal people (Claude role-play):** AP approver, controller, warehouse lead.

---

## 2. What Hyphenate is judging (and our answer)

| Their question / hard part | Our answer |
| --- | --- |
| Is it real enough? | Realistic messy data, planted errors with answer key, scoreboard with misses shown |
| Would you hire it? | Sandbox, read-only access, segregation of duties in code, full trace, escalates when unsure |
| Something new? | Fabless chip AP + self-evolving skills + memory with provenance + self-evolving API intake |
| The moment | Bank-change catch, controller rejection + re-plan, defends decision with citations |
| Sources that disagree | Says which document wins (PO vs invoice vs contract amendment) and why |
| Time | Per-supplier memory, follow-ups that auto-reopen, audit replay with "what it knew then" |
| Working with others | Controller can say no; agent re-plans |
| Limits | Requester can never approve; agent can never pay or edit bank details |
| Explainable and accountable | Every decision traces to doc line, rule, skill version, memory version, approver |

---

## 3. Final track list

| # | Track | Tier | Must-have for submission |
| --- | --- | --- | --- |
| 1 | **Hyphenate** (primary) | Core | Video opens with the moment. One line on seats. Proof: real vs simulated + answer-key score. Live demo, ready for their scenario. |
| 2 | **Microsoft** Built for the Real World + Customer Impact | Core | Customer, measurable usefulness, path to production, responsible design, end to end. |
| 3 | **Factory Droid SDK** | Core | Droid runs on 3 triggers we designed (Investigator, skill evolution, adapter generation in P2), each with its own tool allowlist, plans and diffs visible. README says where Droid runs. |
| 4 | **Anthropic** | Core | Named user group. Talk to one real AP/finance person. Say where Claude could go wrong. |
| 5 | **Armadin** Best Security Hack | Free | Sandbox + injection + bank-change defense front and center. |
| 6 | **Cal Hacks general** | Free | Image + GitHub repo on Devpost. |
| 7 | **MLH Commit Fellowship** | Free | Opt in on Devpost + supplemental form. |
| 8 | **SpacetimeDB** | Foundation | Real backend: cases, traces, approvals, memory, live dashboard. |
| 9 | **CRS** Identity/Fraud | Add-on | Only if booth confirms test businesses. Live on sandbox. Vendor onboarding (10d) puts business credit, OFAC, and public records at the core of a whole workflow, which is what CRS judges on. |
| 10 | **Coinbase** Payment Agents | Add-on | Only if booth confirms F-1 eligibility. Testnet, labeled simulated. |
| 11 | **Cartesia** | Add-on (last) | Voice core to supplier outreach. 2-min demo-first video, README with features + limitations. |

**Before anything else:** ask organizers if there's a cap on sponsor tracks per project.

---

## 4. Architecture

```
 Sources: API | email | SFTP | S3 | ERP
        |
 [0a] Connectors + ingest validation (auth, vendor-channel binding, file type
      by content, size, macros, checksum, manifests, missing-file alerts)
        |   fails? -> QUARANTINE with reason
        |
 [0b] Format router
        |-- API JSON / CSV / XLSX / ERP export -> versioned adapter -> canonical schema
        |        unknown shape? -> QUARANTINE -> intake evolution loop (10b)
        |-- PDF / image / email body -> [1] Reader
        |
 [1] Reader (Claude, NO tools) -> strict JSON schema, flags embedded instructions
        |
 [2] Document Dedup (code) -> file hash, normalized inv no, line-item hash, fuzzy, paid history
        |
 [3] Case Registry lookup (code) -> already triaged? skip / link / reopen delta / attach
        |
 [4] Matcher (code) -> 3-way match, FX, tolerance, variance split
        |
   clean? --yes--> [9] Approver queue
        | no
 [5] Router (code) -> picks a skill by event type; no skill = escalate
        |
 [6] Investigator (Factory Droid on Claude) inside SANDBOX
        - read-only: case docs, ledger snapshot, this vendor's memory, skill
        - writable: scratchpad only, no network, no secrets
        - only exit: proposal file
        |
 [7] Vendor Guard (code + CRS) -> bank changes, new vendors, OFAC,
        vendor onboarding checks (10d), probation rules
        |
 [8] Runtime validators (code) -> schema, citations, recomputed numbers,
        balanced entry, invariants, trace completeness. LLM reviewer on
        low-confidence cases only.
        |
 [9] Approver / Controller (Claude role-play, separate identity)
        - approve, reject, or ask; agent re-plans on rejection
        - approval limits by amount; SLA timer -> reminder -> backup approver
        |
 [10] Poster (code) -> Beancount double entry
        - REFUSES if requester == approver, over approver's limit,
          or period is locked
        - checks subledger = GL AP control after every post
        |
 [11] Trace + audit log -> every step, live on dashboard

 After case closes:
 [12] Memory Writer -> updates supplier memory from trusted signals only
 [13] Skill Evolution (Droid) -> propose diff + run replay -> eval gate -> controller approves -> new version
```

**Rules that make it hireable (say these in the pitch):**

- All math in code. The LLM never computes totals.
- Reader has no tools, so a poisoned PDF can't trigger anything.
- Agent proposes, a different role approves, code posts.
- Agent can never edit bank details or initiate payment.
- Every decision cites its source and records skill version + memory version.
- Failed fetches are never guessed; they show as "evidence missing."

**Stack:**

- Ledger: Beancount (Fava as viewer).
- Live state: SpacetimeDB.
- LLM: Claude (Reader, Approver, Controller, LLM judge with separate rubric prompt). Droid on Claude for Investigator.
- Skills and memory files in git for diffable history.

**Where Factory Droid runs (3 triggers, each with its own tool allowlist):**

| Job | Trigger | Can touch |
| --- | --- | --- |
| Investigator | New exception after Matcher | Read-only case folder + calc script; writes scratchpad + proposal only |
| Skill evolution | Controller rejection pattern or failed test | Copy of skills repo + replay harness; output is a diff, never merged by Droid |
| Adapter generation (P2) | Format drift confirmed in quarantine | Quarantined payloads (values redacted) + fixtures; output is mapping file + tests |

**Not Droid, on purpose:** Reader (must have zero tools), Approver/Controller and LLM judge (must stay independent of the agent they judge), supplier email drafts (one call), deterministic stages (code).

---

## 5. Sandbox (per case)

- **Read-only mounts:** case documents, ledger snapshot (version recorded), this supplier's memory file, the selected skill.
- **Writable scratchpad:** Droid's working directory. Archived into the audit trail when the case closes, then wiped.
- **Only exit:** structured proposal file (recommendation, citations, proposed journal entry). Code validates it.
- **Enforced by the system, not the prompt:** file permissions or container + Droid permission handler at lowest autonomy, using the skill's tool allowlist.
- **No network, no secrets** inside.
- **Scratchpad is untrusted:** nothing reads it as instructions.
- **One sandbox per case:** one supplier's poisoned doc is never visible in another's case.
- **Scratch code allowed, but:** any number used in a decision is recomputed by a vetted tool before it goes in the proposal.

---

## 6. Skills (pluggable and self-evolving)

```
skills/
  ap-3way-match/       # full skill (build first)
    SKILL.md           # when it applies, steps, what to cite, when to escalate
    policy.yaml        # tolerances, approval limits, materiality (code enforces)
    tools.yaml         # allowlist -> Droid permission handler
    tests/             # planted cases + answer key
  vendor-bank-change/  # thin skill (build second)
  statement-recon/     # later
  cash-application/    # later
```

- **Router in code** picks the skill from event type. A document can never choose its own skill.
- **No matching skill = escalate.** Covers the judges' surprise scenario.
- **Skills are written by the team only.** Never loaded from incoming docs.

**Self-evolving loop:**

1. **Observe:** controller rejects/edits, repeated escalations, failed tests, contradicting outcomes.
2. **Propose:** Droid, in a sandbox with a copy of the skills repo, drafts a diff to SKILL.md / policy.yaml or a new skill, cites the cases behind it, and runs the replay itself.
3. **Validate:** replay against test set + past resolved cases (eval gate, section 9).
4. **Approve:** controller sees diff + replay results.
5. **Version:** git, one-click rollback, every decision records the skill version used.

**Guardrails:**

- Ratchet: tightening can be proposed freely; loosening needs controller + second sign-off; some limits are locked.
- Learn only from trusted signals (human decisions, verified outcomes), never from incoming documents.
- Every learned rule links to its cases and approver.
- New skills start in shadow mode (recommend only, always escalate) until they pass an accuracy bar.

---

## 7. Dedup (two layers)

**Layer 1: document dedup (same invoice twice?)** Runs after Reader, again right before payment.

| Check | Catches |
| --- | --- |
| PDF file hash | Same file via email + portal |
| Vendor ID + normalized invoice no | INV-0042 vs 42 vs inv 42 |
| Line-item hash (SKU, qty, unit price) | Resend with a new number |
| Fuzzy: same vendor, amount, dates within N days, inv no edit distance \<= 2 | Typos, INV-2291-A |
| Paid history | Already paid |
| Vendor master: same bank account or tax ID on two records | Duplicate vendors (also fraud signal) |

**Layer 2: case dedup (already triaged?)**

**One case per discrepancy, not per invoice.** An invoice with a short delivery and an unapproved freight line becomes one parent invoice case with two sub-cases. Dedup and partial payment both work per sub-case.

**Fingerprint (strict key):** hash of canonical vendor ID (aliases resolved) + PO number + normalized invoice number + discrepancy type (qty_short, price_over, unapproved_freight, fx_gap, duplicate_invoice, bank_change...) + affected line (SKU). Stored alongside: amount delta in cents, period, and an **evidence hash** (sorted hashes of every attached source document).

**Matching levels:**

| Level | Rule | Result |
| --- | --- | --- |
| 1. Exact | Same fingerprint | Same case (attach / skip / reopen per table below) |
| 2. Correction | Same vendor + PO + type + SKU, different invoice number, doc dedup links them | Linked as "corrected invoice"; evidence changed, so reopen the delta |
| 3. Pattern | Same vendor + type, different PO or period | Separate case, linked as "related pattern" (feeds memory, e.g. expedite fees) |
| 4. Borderline | Partial overlap | LLM explains, human confirms link or split |

**Example:** Formosa INV-881 bills 1,000 wafers, 940 received -> case F1 (qty_short). Same invoice arrives as CSV via SFTP -> doc dedup links the file, exact fingerprint -> attached to F1, no new case. Freight line on INV-881 -> sub-case F2 (unapproved_freight). Formosa sends corrected INV-881-R for 940 -> level 2 correction, evidence changed -> F1 reopened and resolved.

| Found | Status | Action |
| --- | --- | --- |
| No |  | New case |
| Yes | Resolved, evidence unchanged | Don't re-triage; cite prior resolution |
| Yes | Resolved, evidence changed | Reopen, triage only the difference |
| Yes | Resolved, follow-up overdue | Reopen (e.g. credit note never arrived) |
| Yes | In progress | Attach evidence to open case |
| Yes | Rejected/disputed | Keep prior decision unless new evidence |

**Details:**

- Resolutions carry follow-ups with due dates; overdue = auto-reopen.
- Unique constraint on fingerprint + short lease so two agents can't work one case.
- Insert-or-get on the fingerprint is atomic, so the same doc arriving on two channels at once creates one case.
- Humans can split or merge cases in the UI; every split/merge is logged in the trace and becomes an eval case.
- Idempotency keys on supplier emails and journal entries.
- Exact fingerprint first, fuzzy + LLM explanation for borderline; include period so recurring monthly fees stay separate.
- LLM explains borderline matches only (recurring charges are the big false positive). Never auto-reject: hold and show both side by side.

---

## 8. Memory (modeled on Claude's memory)

**Folders, one file per subject:**

| Folder | Holds |
| --- | --- |
| company | Entity, currencies, fiscal calendar, approval chain |
| controller-preferences | "Escalate short-pays over $50k," "3-line explanations" |
| counterparties/ | One file per supplier/customer |
| people/ | Controller, approver, warehouse lead |
| open-matters/ | Kestrel amendment dispute, overdue Formosa credit note, Q3 close |
| patterns/ | FX handling, expedite policy |

**File format:**

```markdown
---
name: aerolane-freight
description: Aerolane Freight, shipping vendor; recurring unapproved expedite fees; check before approving freight invoices
aliases: [Aerolane, Aerolane Freight Ltd, AFL]
sources: [erp, memory-writer]
updated: 2026-10-24
---
- [system-of-record] Payment terms Net 30; approved bank account on file (last 4: 7731)
- [computed: cases #41, #57, #63] 3 unapproved expedite fees this year, all rejected
- [controller: M. Chen, 2026-09-14] Hold any expedite fee without signed approval
- [case #63] Promised credit note CN-118 by 2026-10-20; not received
```

Aliases also feed vendor dedup.

**Four kinds of memory:**

- **Facts:** from system of record, always read fresh, never "remembered."
- **Case history:** from case registry, automatic.
- **Profile/patterns:** computed by code from case history.
- **Vendor rules:** only via skill evolution, controller-approved.
- **Working memory:** per-case scratchpad, wiped.

**Write rules:**

- Separate Memory Writer runs after each case closes. Investigator reads only.
- Only trusted signals: human decisions, verified outcomes, system-of-record changes.
- Never written from incoming documents or emails.
- Every line: provenance tag + valid-from date.
- Read-before-write with version token; small targeted edits; history kept ("Net 45, previously Net 30").
- Corrections propagate; forget removes derived lines too.
- Size caps: roll older entries into summaries.
- Never store: full bank account numbers (last 4 only), instructions that loosen controls.

**Read rules:**

- Agent sees a listing (file + one-line description), loads only the relevant vendor file into the sandbox.
- Lookup by exact vendor ID, never similarity across vendors.
- Memory is context, not evidence. Decisions still need current documents.
- Old patterns fade or expire.
- Audit replay uses memory as of the decision date.

**Storage:** hybrid. Tables for counts and stats, rendered into markdown files. Files in git for diffs.

**Isolation:** per counterparty; per company if multi-tenant (separate namespace, nothing shared).

**Memory UI** (like Claude's settings page): sections for Company, Controller Preferences, Counterparties, Open Matters, People. Each row: summary, last updated, actions: view, edit, forget, history. Two toggles: "Search past cases" and "Generate memory from cases." Import: bootstrap from ERP vendor master + last year's AP.

---

## 9. Evals

**Principle:** deterministic wherever a right answer exists. LLM evals only where code can't judge. Headline number is deterministic.

**Deterministic:**

| Eval | Checks |
| --- | --- |
| Extraction | Reader fields vs answer key |
| Variance | Split matches to the cent |
| Decision | Approve/hold/escalate: catches AND false alarms on clean invoices |
| Dedup | Doc dedup + case dedup take the right action, including correction links, pattern links, and sub-cases |
| Routing | Right skill; unknown event escalates |
| Injection suite | Poisoned docs flagged, zero actions |
| Citation grounding | Cited doc/line exists, quoted number equals source |
| Control invariants (100%) | Debits = credits; no post without approval; requester != approver; approval within limit; no posting into locked periods; AP subledger = GL control; no writes outside scratchpad; no network; bank details never changed; re-runs send no duplicates |
| Materiality | Below-threshold diffs auto-accepted, above escalated, vs answer key |
| Trace completeness | No decision with missing steps or citations to failed fetches |
| Memory: with vs without | Decision changes only where history matters |
| Memory: poisoning | False vendor claims never change memory or rules |
| Memory: isolation | One vendor's doc never appears in another's trace |
| API: classification | Planted one-off errors vs real format changes, vs answer key |
| API: mapping | Proposed mapping vs known-correct mapping |
| API: backward compat | Old-format fixtures still parse |
| API: adversarial | Spoofed change adding bank fields never approved without vendor confirmation |
| Ingest validation | Spoofed file types, .xlsm macros, CSV formula injection, vendor on wrong channel, bad manifest counts: all quarantined |
| Format coverage | Extraction accuracy reported per format (PDF, image, CSV, XLSX, API) |
| Missing files | Expected-but-missing vendor files raise alerts on schedule |
| Onboarding | Clean vendor approved; duplicate under new name, sanctioned entity, bank matching an employee, look-alike domain, missing tax form all held, vs answer key |
| Probation | New vendors get tighter checks until probation ends |

**LLM-judged (rubric, separate prompt/model, averaged over runs, checked against 5 to 10 hand labels):**

- Explanation quality (which source trusted and why)
- Supplier email (right ask, correct facts, no internal leaks)
- Escalation timing and clarity
- Defending decisions: skeptical auditor pushes back; holds when right, changes when pushback is valid
- Skill proposals: evidence-backed, not overfit
- Voice calls (if Cartesia): disclosed AI, right language, got the answer

**Consistency:** run each case 3 times; report decision stability %.

**Where they run:**

1. **Offline harness** -> scoreboard on dashboard.
2. **Skill evolution gate** -> no regressions, invariants 100%, LLM scores not worse, then controller.
3. **Runtime** -> deterministic validators block every proposal; LLM reviewer only on low confidence; disagreement = escalate.

---

## 10. Tracing and visualization

**Each step records:** case ID, step ID, parent, agent/role, skill + version, memory version, tool, inputs/outputs (as doc references), status (ok / retried / failed / blocked / escalated), error, time, tokens, cost, sandbox events, eval results. Bank numbers masked.

**Views:**

1. **Live pipeline:** nodes colored by status as the case moves.
2. **Case timeline:** steps in order with durations, retries, stalls.
3. **Step detail:** inputs, outputs, Droid plan, scratchpad diffs, citations (click to highlight source line).
4. **Failures panel:** grouped by type + what the agent did next.
5. **Decision lineage:** decision -> evidence -> rule -> skill version -> memory version -> approver.
6. **Run comparison:** same case 3 runs side by side.
7. **Scoreboard:** catch rate, false alarm rate, invariant pass rate, citation grounding, decision stability, current skill versions; before/after when a skill evolves.
8. **Business metrics:** dollars caught, hours saved (estimate), on-time payment rate, exceptions per vendor, time to resolve.
9. **Controls:** kill switch, approval queue with SLA timers and at-risk due dates.

**Failure handling:**

| Type | Example | Agent does |
| --- | --- | --- |
| Fetch failed | Receiving log missing, CRS timeout | Retry once, mark "evidence missing," escalate |
| Parse failed | Unreadable scan | Flag, request clean copy |
| Validation blocked | Citation doesn't match source | Block, re-investigate |
| Permission denied | Write outside scratchpad | Log, continue via proposal path |
| Low confidence | Two plausible explanations | Escalate with both |

Built on SpacetimeDB, not an off-the-shelf tracer (finance-specific views + counts toward Spacetime).

---

## 10b. Self-evolving intake: channels, formats, and API (P0 to P2)

**Channels (how data arrives) vs formats (what arrives).** Any channel can carry any format.

| Channel | Connector | Auth / trust check |
| --- | --- | --- |
| API | Push endpoint per vendor | API key per vendor (mTLS in production) |
| Email | Inbox (simulated as folder of .eml files tonight) | Sender allowlist, SPF/DKIM/DMARC result, look-alike domain check |
| SFTP | Poll per-vendor folder | Per-vendor account + key auth |
| S3 | Poll or event on per-vendor prefix | Bucket policy per vendor |
| ERP | Pull via API (mock with Mockoon/Prism, or Odoo/ERPNext schema) | Service account, read-only |

| Format | Path | Can self-evolve? |
| --- | --- | --- |
| API JSON | Versioned adapter | Yes |
| CSV | Versioned adapter (column map) | Yes |
| XLSX | Versioned adapter (sheet + column map) | Yes |
| ERP export | Versioned adapter | Yes |
| PDF | Reader (Claude, no tools) | No: layout changes covered by extraction evals |
| Image / scan | Reader (Claude vision, no tools) | No |
| Email body | Reader | No |

**Guardrail:** the agent evolves **adapters**, never **connectors**. Adding a new SFTP server, bucket, inbox, or API endpoint is a human decision. The agent can notice "files now arriving in a new folder or name pattern" and propose it, but a human configures it.

**Ingest validation (deterministic, before anything is parsed):**

- **Source:** authenticated channel; vendor accepted only from its registered channels (a Penang invoice from an unknown address is flagged).
- **File safety:** type checked by content, not extension; size limits; reject macro-enabled spreadsheets (.xlsm) and password-protected files; zip-bomb and malware scan hook (stub tonight, labeled).
- **Integrity:** checksum; duplicate file hash (feeds dedup); SFTP/S3 batch manifest counts match.
- **Encoding:** UTF-8/BOM handling, delimiter detection for CSV.
- **CSV/XLSX injection:** cells starting with = + - @ are neutralized before display or export.
- **Content:** schema, types, required fields, line totals = invoice total, ISO currency codes, plausible dates, known vendor ID.
- **Time:** expected-file schedule per vendor; "Kestrel's daily file didn't arrive" raises an alert.
- **Provenance on every record:** channel, file hash, received time, adapter version.

Failures go to **quarantine** with the reason, never silently dropped.

### Format evolution (API, CSV, XLSX, ERP exports)

Vendors sometimes change their format. The agent decides if it's a one-off error or a real new format, proposes an adapter update, and gets human (and sometimes vendor) approval.

**Core rule:** the core API and internal schema never change. Each vendor + channel + format has **versioned adapters** in front of it. The agent only proposes a new adapter version. A CSV with renamed or reordered columns, or an XLSX with a new sheet, is handled exactly like an API format change.

**Loop:**

1. **Detect:** payload fails validation or has unknown fields -> **quarantine** (stored raw, not processed, not dropped).
2. **Classify (mostly code):**

| Signal | Points to |
| --- | --- |
| One bad payload, others from vendor fine | Occasional error -> clear error back, ask for resend |
| Missing required field, shape unchanged | Occasional error |
| Same new shape across N payloads in a window | New format |
| Version header / content type changed | New format |
| Fields renamed or nested, meaning mappable | New format |

3. **Propose:** Droid in the sandbox writes adapter v(N+1) + tests from quarantined payloads and old fixtures. LLM proposes the field mapping and flags ambiguity. Sees field names and structure, values redacted where possible.
4. **Validate (eval gate):** quarantined payloads pass invariants; old fixtures still parse; totals match the same invoice's PDF if available.
5. **Risk tier decides approval:**

| Change touches | Approval |
| --- | --- |
| Optional / non-financial fields | Human approver |
| Amounts, currency, tax, vendor identity | Approver + controller |
| Bank or payment fields | Approver + controller + vendor confirmation via contact on file |

6. **Confirm with vendor** through the verified contact on file, never by replying to the sender. **Vendor denies the change = security incident** (possible stolen API credentials).
7. **Roll out:** shadow mode first, then promote. Per-vendor version pin, one-click rollback.
8. **Release quarantine:** reprocess through normal pipeline; case dedup + idempotency prevent double processing.
9. **Remember:** vendor memory gets "API format v3 since Oct 24, confirmed by \[contact\]."

**Adapter style:** declarative mapping file (JSON field map) by default; Droid-written code only for transforms the map can't express, with stricter review.

**Security:**

- A "new format" that adds payment fields is treated as a possible attack. Never auto-mapped.
- Payload values are data, never instructions.
- The agent that proposes an adapter can't deploy it.

**Scope for tonight:** one vendor (Kestrel), one API change (v2 -> v3) and one XLSX statement with renamed columns, declarative mapping, mock sender script. SFTP, S3, and ERP simulated as watched folders / mock API, labeled simulated.

---

## 10c. Finance operations controls

**P0: code checks, enforced by validators and the Poster (each under 30 min)**

| Control | Rule |
| --- | --- |
| Materiality | Differences below threshold in policy.yaml (e.g. $50 or 0.1%) auto-accepted and logged; above becomes an exception. Stops the agent escalating everything. |
| Approval limits | Matrix by amount (simulated): AP lead up to $100k, controller above, CFO above a higher limit. Poster refuses over-limit approvals. |
| Locked periods | Nothing posts into a closed month. Late invoice dated in a closed month posts to the current period with a note. |
| Subledger tie-out | Sum of open vendor balances = GL AP control account, checked after every posting. |

**P1**

- **Approval SLAs:** timer per approval -> reminder -> escalate to backup approver. Dashboard shows payment due dates at risk. Backup must still differ from requester and be within limit.
- **Pay the undisputed part:** split the invoice; clean lines get paid on time, disputed amount held as its own case. Avoids holding a wafer shipment over a freight dispute.
- **Queue priority:** sort by due date, amount, early-pay discount, supplier criticality (Formosa = critical).
- **Supplier reply loop:** replies go through the Reader (untrusted), link to the case by thread + case reference, then resolve or update the follow-up.
- **Kill switch + handoff:** pause all agent actions (global or per vendor); a human can take over any case; the agent can resume a case a human left half done, from case state + notes. Every handoff appears in the trace.
- **Business metrics panel:** dollars caught, hours saved (labeled as estimate), on-time payment rate, exceptions per vendor, average time to resolve.

**P2**

- **Auditor view:** Claude-played auditor asks about a past decision; system exports an evidence pack (docs, trace, skill + memory versions, approvals) as of the decision date.
- **Accrual reversal:** goods received but not billed get accrued, reversed when the bill arrives.
- **Confidence calibration:** define "low confidence" numerically; check confidence against actual accuracy on the test set.
- **LLM outage fallback:** if Claude is unavailable, cases queue for humans and nothing is auto-approved.

---

## 10d. Vendor onboarding (vendor-master seat)

The vendor-master clerk seat's main job. Without it, the seat claim in our pitch is hollow.

**1. Request starts inside.** Someone at Helix (procurement, engineering) requests the vendor. Vendors never self-sign-up (common fraud entry point). After the internal request, the vendor gets an invite link.

**2. Collect:** legal name, address, tax form (W-9 US / W-8BEN-E foreign), bank details + bank letter, contacts, payment terms, currency, data channels they'll use, one sample invoice or file.

**3. Verify (Vendor Guard):**

| Check | Catches |
| --- | --- |
| Business registry + credit (CRS) | Shell companies, very new registrations |
| Sanctions screening (CRS OFAC) | Sanctioned entities (critical for a chip company) |
| Liens, judgments, bankruptcies (CRS) | Financially risky suppliers |
| Duplicate vendor check | Same tax ID, bank, or address as an existing vendor under a new name |
| Bank account vs employee records | Insider fraud: employee account set up as a vendor |
| Callback via phone number from an independent source, not the form | Fake bank details |
| Email domain age + match to company website | Look-alike domains |
| Tax form present and valid | Missing paperwork |

**4. Risk tier:** from check results, expected spend, country. High risk also needs controller approval.

**5. Approve:** requester can't approve; agent can't approve its own onboarding; vendor-master changes always need a second person.

**6. Activate:**

- Vendor master record created (system of record).
- Channels configured by a human (adapters-not-connectors rule).
- Adapter v1 bootstrapped from the sample file via the intake evolution loop (10b).
- Memory file created with aliases (legal + trade names) for dedup.
- Expected-file schedule set for missing-file alerts.

**7. Probation:** first 90 days or first N invoices: tighter tolerances, always full 3-way match, no payment until first delivery confirmed.

**8. Ongoing:**

- Periodic re-screening (sanctions lists change).
- Expiring documents flagged (tax forms, insurance certificates).
- Dormant vendors deactivated after inactivity (favorite fraud target).
- Bank detail changes reuse the step 3 checks.

**Simulated tonight:** employee records table, callbacks (logged as a human task), bank letter verification.

---

## 11. Data plan

1. **Base:** Northwind company documents (invoices, POs, shipping orders linked by order ID), re-skinned as wafers, HBM, substrates, freight.
2. **World:** 4 suppliers, POs, receiving log, contracts, 1 amendment with effective date, last quarter's history, seeded memory files.
3. **Generator** plants \~30 cases: qty > received, price vs PO/amendment date, unapproved freight, duplicate invoices (each dedup type), currency mismatch (fixed rate table, labeled simulated), name typos and unit mismatches, overdue follow-ups, tiny below-materiality differences, a late invoice dated in a closed month, an invoice above the AP lead's limit, a mixed invoice with one disputed line, supplier reply emails, plus clean invoices and legit look-alikes (recurring fees).
4. **Attacks:** poisoned PDF (hidden white text), look-alike bank-change email, vendor email making false claims (memory poisoning test). **Onboarding cases:** clean new vendor, "Penang Advanced Packaging Sdn Bhd" (same tax ID as Penang Pack & Test, different bank), sanctioned entity (CRS test identity), bank account matching an employee, look-alike domain, missing tax form. Plus a small employee records table.
5. **Render** PDFs in 3+ layouts, plus 2 scanned-image invoices. **Structured files:** supplier statements as CSV and XLSX in 2 layouts (one with renamed columns), one .xlsm with a macro, one CSV with a formula-injection cell. **Channels:** .eml emails with attachments, SFTP and S3 drop folders, mock ERP export. **API payloads:** Kestrel v2 and v3 formats, a few one-off broken payloads from Aerolane, one spoofed v3 payload adding a bank field, plus a mock sender script.
6. **Answer key** for every case. Report real score, misses included.
7. **Optional proof:** a score on a public benchmark from Hyphenate's list (e.g. Invoice Sandbox Benchmark) if one fits.
8. **"Add case" form** for judges' own scenario.
9. Ask Hyphenate booth what their live scenario looks like.

Until the full set is ready, everyone builds against 5 hand-made cases.

---

## 12. Demo moments (in order)

| Hyphenate phrase | Moment |
| --- | --- |
| **Catches what others missed** (OPEN VIDEO HERE) | Penang bank change day before big payment: look-alike domain, CRS check, payment held, escalated. |
| Recovers | CRS check times out: red node, retry, "verification incomplete," still held. |
| Sources that disagree | Kestrel amended price before effective date: PO wins, cited. |
| Time + memory | Aerolane 3rd expedite fee: loads memory, cites cases #41, #57, held under rule. Same case with memory off would pass. |
| Self-evolving | Controller rejects twice, agent proposes rule, replay shows both caught, controller approves, skill v8 holds the next one. |
| Dedup | Aerolane resends paid INV-2291 as INV-2291-A: linked by line-item hash, side by side. |
| Case dedup + time | Formosa resend: resolved case found, credit note overdue, only follow-up reopened. |
| Limits | Agent tries to post its own proposal: blocked. Tries to write ledger from sandbox: permission denied. |
| Working with others | Controller rejects short-pay; agent re-plans, asks for corrected invoice. |
| Approvals stall | Approver doesn't respond; SLA timer escalates to backup; dashboard shows the due date at risk. |
| Pay what's clean | Formosa invoice with one disputed freight line: clean lines paid on time, $X freight held as its own case. |
| Limits (amount) | Over-limit invoice approved by AP lead is refused by Poster, routed to controller. |
| Security | Poisoned PDF flagged, nothing executes. Macro-enabled XLSX and a CSV with a formula-injection cell quarantined at intake. |
| Every format, every channel | Same Formosa invoice arrives as PDF by email and as CSV by SFTP: both normalized, dedup links them, one case. |
| Vendor onboarding | "Penang Advanced Packaging Sdn Bhd" requests onboarding: same tax ID as existing Penang Pack & Test, different bank account. Held, escalated, callback required. |
| Defends a decision | "Why did you hold this?" -> PO line, receiving row, memory entry, skill version. |
| Self-evolving API (P2) | Kestrel moves to API v3: first payload quarantined; Aerolane's one broken payload bounced as a one-off; after 3 consistent payloads, adapter v3 proposed with diff + passing replay, confirmation sent to Kestrel's contact on file, human approves, held invoices reprocessed. Spoofed v3 with a bank field: held for out-of-band verification. |
| Proof | Scoreboard on screen. |

---

## 13. Priorities (cut from the bottom)

**P0: must work for the demo** Reader, Matcher, Investigator in sandbox, Approver/Controller with rejection + re-plan, Poster with segregation of duties, basic doc dedup, case registry lookup, Vendor Guard (domain + history), poisoned PDF, live pipeline view, deterministic scoreboard, 30-case data set, materiality thresholds, approval limits, locked periods, subledger tie-out, PDF + image via Reader, CSV/XLSX parsers, API + email channels, basic ingest validation (type by content, size, vendor-channel binding, quarantine).

**P1: makes it win** Memory files + writer + memory UI, skills folder + router + 2 skills, self-evolving loop with eval gate, follow-up auto-reopen, LLM evals + consistency, failures panel, decision lineage, full dedup layers, approval SLAs + backup approver, pay undisputed part, queue priority, supplier reply loop, kill switch + handoff, business metrics panel, SFTP/S3/ERP connectors (simulated), full ingest validation (macros, injection, manifests, missing-file alerts), vendor onboarding flow (duplicate vendor, bank vs employee, domain checks, approval with segregation of duties, probation rules).

**P2: if time allows** CRS (including onboarding checks), Coinbase, Cartesia, onboarding extras (adapter from sample file, re-screening, document expiry, dormant vendor deactivation), self-evolving intake for API + CSV/XLSX (one vendor, one change each), auditor view + evidence pack, accrual reversal, confidence calibration, LLM outage fallback, run comparison view, memory history diffs, statement-recon and cash-application skills, benchmark score.

---

## 14. Team split (4 people)

| Person | Owns |
| --- | --- |
| **A** | Reader, doc dedup, case registry + fingerprints, Matcher, Poster, Beancount, invariants. Later: CRS in Vendor Guard. |
| **B** | Sandbox, Droid Investigator, skills + router, Approver/Controller role-play, skill evolution loop. |
| **C** | Data generator + answer key, eval harness (deterministic + LLM + consistency), Memory Writer. |
| **D** | Booths first (CRS, Coinbase, Cartesia, Hyphenate). Then SpacetimeDB, tracing, dashboard, memory UI, scoreboard. Later: Coinbase/Cartesia if P0 and P1 are done. |

**Finance controls (10c):** A owns P0 invariants (materiality, limits, locked periods, tie-out) and pay-undisputed-part. B owns approval SLAs, backup approver, kill switch + handoff, supplier reply loop. D owns queue priority and business metrics panel.

**Intake (10b):** A owns P0 parsers (CSV/XLSX), API + email channels, and basic ingest validation. C adds every format and channel to the data set. Simulated SFTP/S3/ERP connectors and full validation (P1) go to whoever finishes first.

**Vendor onboarding (10d):** A owns the checks in Vendor Guard (and CRS later). B owns the approval flow and probation rules. C adds onboarding cases + employee table to the data set. D adds the onboarding screen to the dashboard.

**P2 format evolution:** whoever finishes P1 first; B reviews the Droid integration.

**Everyone at the end:** video, READMEs, Devpost, sponsor writeups.

---

## 15. Timeline (Saturday into Sunday)

| By | Milestone |
| --- | --- |
| **Now** | D visits booths. Accounts created/verified. Talk to one real finance person. Skills folder structure set up. |
| **Midnight** | P0 works end to end on 5 hand-made cases. |
| **2 AM** | P0 on full test set. **Cut-off: if P0 isn't solid, no P1/P2.** |
| **2 to 6 AM** | P1, then P2. |
| **6 AM** | **Feature freeze.** Anything not working is dropped. |
| **6 to 8 AM** | Record video (open with the moment), READMEs, Devpost, sponsor writeups. |
| **8:30 AM** | Submit. Do not wait for 9. |

---

## 16. Submission checklist

**Devpost (everyone):** project image, GitHub repo, video, opt into each track, Commit form.

**README must include:**

- One line on the seats
- Architecture diagram + controls + known limitations
- Where and how Droid runs (Factory)
- Sandbox, skills, memory, dedup, evals in brief
- What's real vs simulated + answer-key score (Hyphenate)
- Cartesia features + limitations (if entered)
- No API keys or secrets

**Coinbase writeup (if entered):** primary track = Payment Agents; who it's for; Coinbase tools used; architecture; biggest blocker, workaround, one missing capability. Keep a notes file while building.

**Before accepting any cash prize:** email your DSO.

---

## 17. Pitch (3 minutes)

1. **0:00 to 0:30** The moment: bank-change catch, live.
2. **0:30 to 0:50** The seats and the company. Why AP exceptions cost real money.
3. **0:50 to 2:00** One case on the live pipeline: invoice in, dedup + registry check, gap explained with citations, memory cited, controller rejects, agent re-plans, entry posted.
4. **2:00 to 2:30** Why you'd hire it: sandbox, math in code, separate approver, skills that improve only with sign-off, full trace.
5. **2:30 to 3:00** Proof: scoreboard, what's real vs simulated, what's next.

**Q&A prep:**

- "What if the LLM gets the math wrong?" It never does math; validators recompute.
- "What if an invoice contains instructions?" Reader has no tools; show the poisoned PDF.
- "Why trust the PO over the invoice?" Policy + amendment effective date, cited.
- "Can it learn bad habits?" Learns only from human decisions, eval gate, controller approval, can't loosen controls on its own.
- "What does it remember and why?" Open the memory page, show provenance and history.
- "What if a vendor changes its API?" Quarantine, classify, propose a versioned adapter, human approves; payment-field changes need vendor confirmation. Same detect, diagnose, plan, execute loop as a self-healing network.
- "What if the approver is on vacation?" SLA timer escalates to a backup who is still within limits and isn't the requester.
- "Won't it escalate everything?" Materiality thresholds: small differences are accepted and logged.
- "Will holding invoices hurt supply?" It pays the undisputed part on time and holds only the disputed amount.
- "Can we stop it?" Kill switch, per vendor or global; humans can take over any case.
- "How do you handle every format and channel?" Connectors validate the source, structured files go through versioned adapters, PDFs and images through the Reader, all into one canonical schema with provenance.
- "Can the agent add new data sources?" No. It evolves adapters; humans configure connectors.
- "How do new vendors get in?" Internal request only, verified (duplicates, sanctions, bank vs employees, callback), approved by a second person, then probation.
- "What's simulated?" FX rates, supplier emails, approvers, vendor API senders, approval limits, SFTP/S3/ERP (watched folders and mock API), malware scan hook, employee records, callbacks. Ledger, matching, dedup, controls, evals are real.
- "Path to production?" Swap Beancount for the ERP via API; same controls, sandbox, and gates.

---

## 18. Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Droid setup fails | Plain Claude agent with same sandbox; drop Factory track. |
| SpacetimeDB setup > 1 hour | SQLite + polling; drop Spacetime track. |
| CRS has no business test data | Skip CRS; Vendor Guard uses domain + history. |
| Coinbase eligibility unclear | Skip Coinbase. |
| Skill evolution not ready | Show a pre-approved v8 diff + replay results as a recorded clip. |
| Live demo breaks | Pre-recorded video + replay from saved trace. |
| Judges' scenario breaks the agent | It escalates: still a pass on "knowing when to ask." |
| Real SFTP/S3/ERP setup too slow | Simulate as watched folders and a mock API, labeled simulated. |
| API evolution not ready | Show quarantine + one-off vs new-format classification only; mapping approval as a recorded clip. |
| Scope too big | Cut from P2 up, never from P0. |

---

## 19. Engineering guidelines (copy into the repo's CLAUDE.md)

For everyone and every coding agent working on ReconAI. Based on the Karpathy-inspired Claude Code guidelines (forrestchang/andrej-karpathy-skills, MIT).

### 1. Think before coding

- State assumptions explicitly. If uncertain, ask instead of guessing.
- If a request has more than one reading, list them; don't pick one silently.
- If a simpler approach exists, say so and push back.
- If confused, stop and name what's unclear.

### 2. Simplicity first

- Minimum code that solves the problem. Nothing speculative.
- No features, abstractions, or configurability nobody asked for.
- No error handling for impossible cases.
- Test: would a senior engineer call this overcomplicated? If yes, simplify.

### 3. Surgical changes

- Touch only what the task needs. Don't reformat or refactor adjacent code.
- Match the existing style.
- Remove only what your own change made unused. Mention other dead code; don't delete it.
- Test: every changed line traces to the task.

### 4. Goal-driven execution

- Turn tasks into checkable goals: "add validation" becomes "write failing tests for bad inputs, then make them pass."
- For multi-step work, write the plan with a check per step:
  1. \[step\] -> verify: \[check\]
  2. \[step\] -> verify: \[check\]
- Loop until the checks pass.

### ReconAI-specific rules

- **Ownership:** only edit your own folders (section 14). `contracts/` changes must be announced to the team first.
- **Money:** all amounts in integer cents or Decimal, never floats. No arithmetic in prompts; LLMs never compute totals.
- **Untrusted input:** document, email, and payload text never goes into a prompt that has tools.
- **Every stage** implements the shared Stage interface and logs through the trace helper.
- **Verify with fixtures:** `make run CASE=...` on the relevant case, and `make eval` must show no regressions and 100% invariants before merging.
- **Don't delete someone else's stub;** replace only your own.
- **No secrets in the repo.** Use `.env`; keep `.env.example` updated.
- **Small PRs, merged often.**

### Hackathon tradeoff

These rules favor caution over speed. Apply full rigor to contracts, money logic, controls, and security. For UI tweaks and obvious one-liners, use judgment and keep moving.