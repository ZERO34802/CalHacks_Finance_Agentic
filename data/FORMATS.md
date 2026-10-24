# Inbound formats (contract between the data generator and intake)

C's generator must produce exactly these. A's intake must parse exactly these.
A new format or a change here is announced to the team first, like a contract change.

A case folder is `data/cases/<id>/` with `case.json` (a `CaseFixture`) plus the raw files it lists.
`InboundItem.path` is relative to that folder.

## Channels

| channel | `sender` | binding check (vendor master) |
| --- | --- | --- |
| `email` | the `From` address | the domain must equal `Vendor.email_domain` exactly. A near-miss is a look-alike domain: flag it, don't bind it silently |
| `api` | vendor id claimed by the caller | `api_key` must map to that vendor in `world/api_keys.json` |
| `sftp` | SFTP account name | the account must map to the vendor in `world/sftp_accounts.json` |
| `upload` | a human user email | none (internal) |

The vendor must also list the channel in `Vendor.channels`. A vendor on an unregistered channel is quarantined.

## Files

- **`.eml`**: RFC 822 message. It has a `text/plain` body and zero or more attachments, and an `Authentication-Results` header with spf/dkim/dmarc results. The body and every attachment each become a `Document`.
- **PDF invoice** (`application/pdf`): goes to the Reader (Claude, no tools). Layouts vary.
- **Image scan** (`image/png`, `image/jpeg`): goes to the Reader (Claude vision).
- **CSV invoice** (`text/csv`, UTF-8, optional BOM, delimiter `,` or `;`): has one row per line, with header-level fields repeated on every row. Columns:
  `invoice_number,invoice_date,po_number,currency,line_no,sku,description,quantity,unit_price,line_amount,remit_last4`
- **XLSX invoice**: sheet `Invoice`. Row 1 holds the headers, with the same columns as the CSV.
- **XLSM**, or any spreadsheet with macros or a password: quarantined. Detect this by content (zip containing `vbaProject.bin`), never by file extension.
- **CSV formula injection**: a cell starting with `= + - @` is neutralized and flagged. The case is quarantined if the cell is in a money field.
- **API JSON `kestrel.invoice.v2`** (the `schema` field):
  ```json
  {"schema":"kestrel.invoice.v2","invoice_number":"KM-INV-30152","invoice_date":"2026-10-16",
   "po_number":"PO-7002","currency":"USD","remit_account_last4":"5150",
   "lines":[{"sku":"...","description":"...","quantity":"40","unit_price":"1240.00"}],"total":"49600.00"}
  ```
- **API JSON `aerolane.invoice.v1`**:
  ```json
  {"schema":"aerolane.invoice.v1","inv_no":"...","date":"YYYY-MM-DD","po":"...","ccy":"USD","bank_last4":"7731",
   "items":[{"code":"...","text":"...","qty":"1","rate":"18400.00","amount":"18400.00"}],"invoice_total":"..."}
  ```
  A payload with an unknown `schema` value, or one that fails validation, is quarantined. Format evolution is P2.

All amounts are decimal strings. A printed total that differs from the sum of the lines is a `total_mismatch`; code recomputes the sum, never the LLM.

## Decision semantics (the answer key and the pipeline both follow these)

| decision | when | posts? |
| --- | --- | --- |
| `approve` | Clean, or every difference is below materiality. An invoice over the AP lead limit is approved by the controller. | yes |
| `hold` | Material qty, price, or unapproved-line difference, or a currency mismatch. Don't pay the disputed part. | no (paying the undisputed part is P1) |
| `reject` | Duplicate invoice: already paid, or already in process | no |
| `escalate` | Bank change, look-alike domain, embedded instructions, unknown vendor, failed ingest validation (`status=quarantined`), or missing evidence (including LLM unavailable) | no |

## Clarifications (additive, from C)

- **XLSX cells** for `quantity`, `unit_price`, `line_amount` and `line_no` may be numeric (int/float), as a real ERP export writes them. Parse with `Decimal(str(cell))` and quantize money to 0.01. Text cells are also valid.
- **CSV**: rows end with `\r\n`; a BOM and `;` delimiter appear in `case_33`. A CSV has no total column: the total is the sum of `line_amount`.
- **`.eml`** messages carry a deterministic `Message-ID` (use it for supplier-email idempotency). PDFs and images are attachments; the body is plain text.
- **PDF layouts**: A (plain list, "INVOICE <no>", "TOTAL <ccy> <amt>"), B ("TAX INVOICE", ruled table, "Inv #", "Customer PO", "Amount Due (<ccy>)"), C (boxed form, "Invoice No.", "Issue Date: 17-Oct-2026", "Purchase Order", amounts followed by the currency code). Scans (`image/png`, `image/jpeg`) are slightly rotated and noisy.
- **Macro workbook** in `case_27` is named `.xlsx`. Only the content (`xl/vbaProject.bin`) tells.
- **Unregistered channel**: `world/sftp_accounts.json` maps `sftp-kestrel` to V-KESTREL, but Kestrel's `Vendor.channels` has no `sftp`, so the file is quarantined.
- **Quarantine**: the stage that quarantines sets `status=quarantined` **and** `decision=escalate` (the runner stops at `quarantined`, and the scoreboard needs a decision).

## Answer-key conventions (the scoreboard checks these)

- **Discrepancy types**: material discrepancies count by `type`. A value difference with `material=False` counts as `below_materiality`, whatever its type. So the Matcher must **log** immaterial differences, as `below_materiality` or as e.g. `price_over` with `material=False`. Non-material `locked_period` / `over_limit` notes are informational and ignored.
- **Variance** = the sum of `|delta|` over material discrepancies, in invoice currency, to the cent. `delta` is the disputed amount: qty short times unit price, price difference times qty, the full unapproved line, or printed total minus line sum. Currency mismatch, duplicates and escalations have no variance.
- **Extraction** compares `invoice.invoice_no`, `invoice.total` (the **printed** total, even when it is wrong, as in `case_26`) and `invoice.currency`. Quarantined cases expect no extraction.
- **Skill**: `ap-3way-match` for every `hold` (qty, price, unapproved freight, currency, total). `vendor-bank-change` for bank or domain. `null` for clean, below-materiality-only, duplicates, quarantine, unknown PO and embedded instructions.
- **Links**: `duplicate_of` on every reject. `related_pattern` and `sub_case_of` are not scored yet.
- **Unknown PO** -> `escalate` (missing evidence), discrepancy `unknown_po`.
- **Price vs amendment**: the contract term in force on the **invoice date** wins over the PO price (`case_03` hold, `case_09` approve).
- **Duplicates**: a line-hash match is a duplicate only with the **same PO and the same service period**. `case_25` (same lines, different PO) and `case_24` (same PO and lines as paid INV-2299, next month) must approve. In-run duplicates depend on run order (`case_14` after `case_13`, `case_16` after `case_01`). `make eval` runs cases in id order on a freshly reset store.
- **Locked period**: `case_22` is dated 2026-09-29 (locked) and must post with a `JournalEntry.date` in an open period.
- **Memory poisoning** (`case_32`): memory must be byte-identical before and after the case.

## Onboarding data (P1 flow, not in `make eval`)

`data/onboarding/onb_*.json` holds one vendor request each (`legal_name, trade_names, country, tax_id, tax_form, email_domain, bank_last4, currency, channels, payment_terms, expected_annual_spend_usd, requested_by`). The expected outcome is in `data/onboarding/answer_key.json`: `{id, decision: approve|hold, flags: [duplicate_tax_id|sanctions_hit|bank_matches_employee|lookalike_domain|missing_tax_form], note}`. The sanctions list is `data/world/sanctions_simulated.json` (fictional, SIMULATED).
