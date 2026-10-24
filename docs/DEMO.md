# ReconAI demo script (3 min pitch + live Q&A)

Everything here runs on the 48 fixtures in `data/cases/` and is checked by `make eval`.

## Before you go on stage (15 min before)

```bash
make setup                       # once
cp config/.env.example .env      # then add ANTHROPIC_API_KEY, FACTORY_API_KEY
make clean
RECONAI_LLM=replay RECONAI_DROID=replay make eval   # fills the store from the response cache: free and fast
make api                         # terminal 1 (RECONAI_DEMO_PACE=0.35 makes steps visibly tick)
make ui                          # terminal 2, ui/.env: VITE_API_URL=http://localhost:8000
```

- **Backup:** a pre-recorded video, plus `make run CASE=case_04` in a terminal, which prints the full trace.
- **Live calls:** if the venue network is bad, keep `RECONAI_LLM=replay` and `RECONAI_DROID=replay`. Every demo case is already cached.

## The pitch, beat by beat

| Time | Beat | Case | What to show | Line to say |
| --- | --- | --- | --- | --- |
| 0:00 | **The moment** | case_04 | Penang invoice for $3.3M from `penang-packtest.com`. The bill is marked "Higher risk of fraud": look-alike domain, bank ****9902 ≠ master ****4418, payment held, callback follow-up | "The day before a $3.3M payment, the bank details changed. It caught it, and it can't be talked out of it." |
| 0:30 | Who it replaces | — | Home screen | "It fills two seats at a fabless chip company: AP specialist and vendor-master clerk." |
| 0:50 | One case live | case_02 | Send it from the fixtures (`POST /intake`) and watch the pipeline over WS: Reader → dedup → registry → matcher (60 wafers short) → Droid investigator → controller → Poster pays the undisputed TWD 17.48M and holds 1.116M | "Every number is computed in code. The agent explains which source wins and cites it." |
| 1:30 | Controller says no | case_43 → 45 | The controller rejects, the agent re-plans; after a second similar rejection, Droid proposes a skill change, the replay passes the gate, the controller approves, and v3 holds case_45 up front | "It learns only from humans, and only through an eval gate and a sign-off." |
| 1:50 | Time + memory | case_36, case_42 | The credit note never came, so the case reopens on its own. A $45 expedite fee is held because memory says this vendor has done it before (it approves with `RECONAI_MEMORY=off`) | "It remembers every supplier, with the provenance for each fact." |
| 2:00 | Why you'd hire it | case_31, case_27 | A poisoned PDF: hidden white text is flagged and nothing runs. A macro workbook is quarantined before parsing | "The Reader has no tools. Agent proposes, a different role approves, code posts." |
| 2:30 | Proof | — | Scoreboard: catch rate, false alarms, invariants, a breakdown by format and channel, and the misses shown | "Here is the answer-key score, and here is what's simulated." |

## Q&A: the case to open for each question

| Question | Show |
| --- | --- |
| "What if the LLM gets the math wrong?" | case_26: printed total ≠ sum of lines; code recomputes and holds |
| "Why trust the PO over the invoice?" | case_03 vs case_09: same amendment, before vs after its effective date |
| "Duplicates?" | case_14 (same file on two channels), case_15 (`42` = `INV-0042`), case_05 (`INV-2291-A`), case_24 (a monthly fee that is **not** a duplicate) |
| "Won't it escalate everything?" | case_20/21: below materiality, auto-accepted and logged. False alarm rate on the scoreboard |
| "Will holding hurt supply?" | case_02/07/11: the undisputed part is paid and only the delta is held |
| "Approver on vacation?" | case_46 → 47: SLA breach, routed to the backup controller, payment-at-risk alert |
| "Can we stop it?" | `POST /controls {"paused_vendors":["V-KESTREL"]}`; then any Kestrel case stops at the gate. Handoff/release via `/cases/{id}/handoff` and `/release` |
| "New vendors?" | Vendors → Onboarding: "Penang Advanced Packaging" has the same tax ID as an existing vendor and is held |
| "Vendor changes its format?" | case_29: unknown schema quarantined (format evolution is P2) |
| "What's simulated?" | See the README section "Real vs simulated" |
| Judges' own scenario | Vendors / "Add case": unknown events escalate. Escalating counts as a pass for "knowing when to ask". |
