"""[0a] Connectors + ingest validation -> Case with Documents. Owner: A.

Deterministic, before anything is parsed:
- source: vendor-channel binding (email exact domain / API key / SFTP account) and the vendor must list
  the channel; SPF/DKIM/DMARC recorded from Authentication-Results (DMARC fail on a bound domain = quarantine)
- file safety: type by content (magic bytes), extension spoofing, size limit, macros (vbaProject.bin),
  password-protected containers, zip-bomb guard (malware scan hook: STUB, labeled)
- integrity: sha256 per file / attachment
- structured payloads (CSV / XLSX / API JSON) must pass their adapter (schema, types, required fields,
  ISO currency, plausible dates); formula injection in a money cell = quarantine

Any failure -> case.status=quarantined, quarantine_reason, decision=escalate, document text dropped.
Look-alike sender domain: NOT quarantined; the case is bound to the vendor it imitates + a note
(Vendor Guard raises lookalike_domain). Unknown sender -> vendor_id "V-UNKNOWN".
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from email import policy as email_policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

from backend.core.stage import Ctx
from backend.evals.fixtures import WORLD, api_keys
from backend.intake.adapters import IngestError, erp_vendor_id, parse_structured
from backend.intake.raw import put_raw
from backend.intake.sniff import Sniff, check_extension, sniff
from backend.pipeline.lib.ids import levenshtein
from contracts import Case, CaseFixture, CaseStatus, Channel, Decision, DocKind, Document, InboundItem, Vendor

UNKNOWN_VENDOR = "V-UNKNOWN"
LOOKALIKE_MAX_RATIO = 0.25          # normalized edit distance to call a domain a look-alike
INVOICE_KINDS = {"pdf", "png", "jpeg", "csv", "xlsx", "json"}
STRUCTURED = {"csv", "xlsx", "json"}
_SUFFIX_LABELS = {"com", "co", "net", "org", "io", "biz", "info", "tw", "kr", "my", "us", "uk", "jp", "cn", "sg",
                  "de", "hk", "example"}


def sftp_accounts() -> dict[str, str]:
    """SIMULATED SFTP account -> vendor_id (data/world/sftp_accounts.json)."""
    p = WORLD / "sftp_accounts.json"
    return json.loads(p.read_text()) if p.exists() else {}


def s3_prefixes() -> dict[str, str]:
    """SIMULATED S3 bucket prefix -> vendor_id (data/world/s3_prefixes.json; empty if absent)."""
    p = WORLD / "s3_prefixes.json"
    return json.loads(p.read_text()) if p.exists() else {}


def s3_owner(prefix: str) -> Optional[str]:
    m = s3_prefixes()
    if prefix in m:
        return m[prefix]
    best = max((k for k in m if prefix.startswith(k)), key=len, default=None)  # longest registered prefix
    return m[best] if best else None


MANIFEST = "manifest.json"


def check_manifest(fx: CaseFixture, folder: Path) -> tuple[list[str], set[str]]:
    """SFTP batch manifest: count, missing files, sha256. Any problem quarantines the whole batch.
    Returns (problems, manifest item paths)."""
    items = [i for i in fx.inbound if i.channel == Channel.sftp]
    mans = [i for i in items if Path(i.path).name == MANIFEST]
    if not mans:
        return [], set()
    problems: list[str] = []
    files = [i for i in items if Path(i.path).name != MANIFEST]
    try:
        m = json.loads((folder / mans[0].path).read_bytes().decode("utf-8-sig"))
        listed = {str(f["path"]): str(f["sha256"]).lower() for f in m["files"]}
        count = int(m["count"])
    except Exception as e:
        return [f"manifest {mans[0].path}: unreadable ({type(e).__name__})"], {i.path for i in mans}
    if count != len(files) or count != len(listed):
        problems.append(f"manifest count {count} != {len(files)} files received / {len(listed)} listed")
    by_name = {i.path: i for i in files} | {Path(i.path).name: i for i in files}
    for path, sha in listed.items():
        item = by_name.get(path) or by_name.get(Path(path).name)
        f = (folder / item.path) if item else None
        if f is None or not f.is_file():
            problems.append(f"manifest lists {path} but it was not received")
        elif _sha(f.read_bytes()) != sha:
            problems.append(f"manifest sha256 mismatch for {path}")
    for i in files:
        if i.path not in listed and Path(i.path).name not in listed:
            problems.append(f"{i.path} received but not in the manifest")
    return [f"batch manifest: {p}" for p in problems], {i.path for i in mans}


def malware_scan(data: bytes) -> Optional[str]:
    """STUB hook (labeled simulated): a real AV/sandbox scan goes here. Returns a reason to quarantine."""
    return None


# --- domain binding -----------------------------------------------------------

def domain_core(domain: str) -> str:
    labels = [x for x in domain.lower().strip(".").split(".") if x]
    while len(labels) > 1 and labels[-1] in _SUFFIX_LABELS:
        labels.pop()
    if len(labels) > 1 and labels[0] in {"www", "mail", "email", "smtp", "mx"}:
        labels = labels[1:]
    return re.sub(r"[^a-z0-9]", "", "".join(labels))


def closest_vendor(domain: str, vendors: list[Vendor]) -> Optional[tuple[Vendor, float]]:
    """Vendor whose domain the sender's domain imitates (normalized edit distance, or containment)."""
    core = domain_core(domain)
    best: Optional[tuple[Vendor, float]] = None
    for v in vendors:
        vc = domain_core(v.email_domain)
        if not core or not vc:
            continue
        ratio = levenshtein(core, vc) / max(len(core), len(vc))
        if len(vc) >= 5 and vc in core:
            ratio = min(ratio, 0.2)
        if best is None or ratio < best[1]:
            best = (v, ratio)
    return best if best and best[1] <= LOOKALIKE_MAX_RATIO else None


def parse_auth_results(header: Optional[str]) -> dict[str, str]:
    out = {"spf": "none", "dkim": "none", "dmarc": "none"}
    for k in out:
        m = re.search(rf"\b{k}\s*=\s*([a-z]+)", header or "", re.I)
        if m:
            out[k] = m.group(1).lower()
    return out


@dataclass
class Binding:
    vendor_id: Optional[str]            # None = channel carries no vendor identity (upload)
    how: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lookalike: bool = False


def bind_email(sender: str, vendors: list[Vendor]) -> Binding:
    addr = parseaddr(sender or "")[1].lower()
    domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
    for v in vendors:
        if domain and domain == v.email_domain.lower():
            return Binding(v.id, f"email domain {domain}")
    hit = closest_vendor(domain, vendors) if domain else None
    if hit:
        v, ratio = hit
        return Binding(v.id, f"look-alike of {v.email_domain}", lookalike=True, notes=[
            f"intake: sender domain {domain!r} is a look-alike of {v.name} ({v.email_domain}); "
            f"normalized edit distance {ratio:.2f}. Bound to {v.id} for review, NOT trusted."])
    return Binding(UNKNOWN_VENDOR, "unknown sender",
                   notes=[f"intake: sender {addr or sender!r} matches no vendor domain; vendor unknown"])


def bind(item: InboundItem, sender: Optional[str], vendors: list[Vendor],
         slack_users: Optional[dict[str, str]] = None) -> Binding:
    by_id = {v.id: v for v in vendors}
    if item.channel == Channel.email:
        b = bind_email(sender or "", vendors)
    elif item.channel == Channel.api:
        owner = api_keys().get(item.api_key or "")
        if owner is None:
            return Binding(None, "api", problems=["API key missing or not registered"])
        b = Binding(owner, "api key")
        if item.sender and item.sender != owner:
            b.problems.append(f"API caller claims vendor {item.sender} but key belongs to {owner}")
    elif item.channel == Channel.sftp:
        owner = sftp_accounts().get(item.sender or "")
        if owner is None:
            return Binding(None, "sftp", problems=[f"SFTP account {item.sender!r} not registered"])
        b = Binding(owner, f"sftp account {item.sender}")
    elif item.channel == Channel.s3:  # SIMULATED connector: watched prefix per vendor
        owner = s3_owner(item.sender or "")
        if owner is None:
            return Binding(None, "s3", problems=[f"S3 prefix {item.sender!r} not registered"])
        b = Binding(owner, f"s3 prefix {item.sender} (SIMULATED)")
    elif item.channel == Channel.erp:  # SIMULATED internal ERP export; vendor bound from the payload
        return Binding(None, "erp export (internal, SIMULATED)")
    elif item.channel == Channel.slack:  # the vendor's registered Slack user (set at Slack onboarding)
        owner = (slack_users or {}).get(item.sender or "")
        if owner is None:
            return Binding(None, "slack", problems=[f"Slack user {item.sender!r} is not a vendor's registered contact"])
        b = Binding(owner, f"slack user {item.sender}")
    elif item.channel == Channel.upload:
        return Binding(None, f"internal upload by {item.sender}",
                       notes=[f"intake: internal upload by {item.sender}; vendor bound from document"])
    else:
        return Binding(None, item.channel.value, problems=[f"channel {item.channel.value} has no configured connector"])
    v = by_id.get(b.vendor_id or "")
    if v is not None and item.channel not in v.channels:
        b.problems.append(f"vendor {v.id} is not registered on channel {item.channel.value}")
    return b


# --- ingest -----------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest(fx: CaseFixture, folder: Path, ctx: Ctx) -> Case:
    vendors = ctx.store.list_vendors()
    docs: list[Document] = []
    problems: list[str] = []
    notes: list[str] = []
    item_log: list[dict] = []
    invoice_vendors: list[str] = []
    other_vendors: list[str] = []
    root = folder.resolve()

    def add_doc(item: InboundItem, filename: str, data: bytes, s: Sniff, kind: DocKind,
                text: Optional[str], sender: Optional[str], subject: Optional[str] = None) -> Document:
        put_raw(data)
        d = Document(id=f"{fx.id}-d{len(docs) + 1}", kind=kind, channel=item.channel, filename=filename,
                     sha256=_sha(data), mime=s.mime, received_at=item.received_at, text=text, sender=sender,
                     subject=subject)
        docs.append(d)
        return d

    def check_file(where: str, filename: str, data: bytes, structured_ok: bool = True, lenient: bool = False) -> Sniff:
        """lenient (Slack uploads): a CSV/XLSX in a layout no adapter knows goes to the Reader instead of quarantine."""
        s = sniff(data)
        for reason in (s.reject, check_extension(filename, s), malware_scan(data)):
            if reason:
                problems.append(f"{where}: {reason}")
        if s.reject is None and s.kind in STRUCTURED and structured_ok:
            try:
                inv, _ = parse_structured(s.kind, data, "probe", "probe")
                for f in inv.flags:
                    if f.startswith("formula_injection"):
                        notes.append(f"intake: {where}: {f} (cell neutralized)")
            except IngestError as e:
                if lenient:
                    notes.append(f"intake: {where}: {s.kind} layout not recognised ({e}); the Reader will extract it")
                else:
                    problems.append(f"{where}: {e}")
        return s

    slack_users: dict[str, str] = {}
    if any(i.channel == Channel.slack for i in fx.inbound):
        from backend.slack.models import VENDOR_USER_KIND, VendorUser
        slack_users = {u.slack_user: u.vendor_id for u in ctx.store.list_records(VendorUser, VENDOR_USER_KIND)
                       if u.vendor_id}
    man_problems, manifest_paths = check_manifest(fx, folder)
    problems.extend(man_problems)
    for item in fx.inbound:
        if item.path in manifest_paths:
            item_log.append({"path": item.path, "channel": item.channel.value, "manifest": True})
            continue
        path = (folder / item.path).resolve()
        log: dict = {"path": item.path, "channel": item.channel.value}
        item_log.append(log)
        if root not in path.parents and path != root:
            problems.append(f"{item.path}: path escapes the case folder")
            continue
        if not path.is_file():
            problems.append(f"{item.path}: inbound file missing (evidence missing)")
            continue
        data = path.read_bytes()
        log["sha256"] = _sha(data)
        sender = item.sender
        if item.channel == Channel.email:
            s = sniff(data)
            if s.kind != "eml":
                problems.append(f"{item.path}: email channel item is not an RFC 822 message ({s.kind})")
                continue
            msg = BytesParser(policy=email_policy.default).parsebytes(data)
            sender = parseaddr(str(msg.get("From", "")))[1] or item.sender
            if item.sender and sender.lower() != parseaddr(item.sender)[1].lower():
                notes.append(f"intake: {item.path}: envelope sender {item.sender!r} != From {sender!r}")
            auth = parse_auth_results(str(msg.get("Authentication-Results", "")))
            log["auth"] = auth
            b = bind(item, sender, vendors)
            if not b.lookalike and b.vendor_id not in (None, UNKNOWN_VENDOR) and (
                    auth["dmarc"] == "fail" or (auth["spf"] == "fail" and auth["dkim"] == "fail")):
                b.problems.append(f"sender authentication failed (spf={auth['spf']} dkim={auth['dkim']} "
                                  f"dmarc={auth['dmarc']})")
            if b.lookalike or b.vendor_id == UNKNOWN_VENDOR:
                notes.append(f"intake: {item.path}: auth spf={auth['spf']} dkim={auth['dkim']} dmarc={auth['dmarc']}")
            body = msg.get_body(preferencelist=("plain",))
            body_text = body.get_content() if body else ""
            subject = str(msg.get("Subject", "")) or None
            add_doc(item, item.path, data, Sniff("eml", "message/rfc822"), DocKind.email, body_text, sender, subject)
            has_invoice = False
            for part in msg.iter_attachments():
                name = part.get_filename() or "attachment"
                payload = part.get_payload(decode=True) or b""
                ps = check_file(f"{item.path}/{name}", name, payload)
                kind = DocKind.invoice if ps.kind in INVOICE_KINDS else DocKind.email
                has_invoice |= kind == DocKind.invoice
                text = payload.decode("utf-8-sig", "replace") if ps.kind in {"csv", "json", "text"} else None
                add_doc(item, name, payload, ps, kind, text, sender, subject)
            # a body-only email may itself be the invoice; Reader decides
            if b.vendor_id:
                (invoice_vendors if has_invoice else other_vendors).append(b.vendor_id)
        else:
            b = bind(item, sender, vendors, slack_users)
            if item.channel == Channel.erp:
                vid = erp_vendor_id(data)
                if vid is None or vid not in {v.id for v in vendors}:
                    b.problems.append(f"ERP export names unknown vendor {vid!r}")
                else:
                    b.vendor_id = vid
            s = check_file(item.path, Path(item.path).name, data, lenient=item.channel == Channel.slack)
            if item.channel in (Channel.api, Channel.erp) and s.kind != "json":
                problems.append(f"{item.path}: {item.channel.value} payload is not JSON ({s.kind})")
            if s.kind == "eml":
                problems.append(f"{item.path}: email message on non-email channel {item.channel.value}")
            kind = DocKind.invoice if s.kind in INVOICE_KINDS else DocKind.statement
            text = data.decode("utf-8-sig", "replace") if s.kind in {"csv", "json", "text"} else None
            if s.kind == "xlsx" and item.channel == Channel.slack:  # text rendering for the Reader fallback
                from backend.intake.adapters import xlsx_text
                text = xlsx_text(data)
            add_doc(item, Path(item.path).name, data, s, kind, text, sender)
            if b.vendor_id:
                invoice_vendors.append(b.vendor_id)
        log["binding"] = b.how
        log["vendor_id"] = b.vendor_id
        problems.extend(f"{item.path}: {p}" for p in b.problems)
        notes.extend(b.notes)

    bound = [v for v in invoice_vendors + other_vendors if v]
    known = [v for v in bound if v != UNKNOWN_VENDOR]
    vendor_id = known[0] if known else (bound[0] if bound else UNKNOWN_VENDOR)
    if len(set(known)) > 1:
        notes.append(f"intake: inbound items bind to different vendors {sorted(set(known))}; using {vendor_id}")
    for d in docs:
        d.vendor_id = vendor_id

    case = Case(id=fx.id, vendor_id=vendor_id, documents=docs, as_of=fx.as_of,
                created_at=min((i.received_at for i in fx.inbound), default=ctx.now()), notes=notes)
    if problems:
        case.status, case.decision = CaseStatus.quarantined, Decision.escalate
        case.quarantine_reason = "; ".join(problems)
        for d in case.documents:
            d.text = None  # nothing parsed from a quarantined case
        case.notes.append(f"intake: QUARANTINED: {case.quarantine_reason}")
    try:  # ingest may be called outside a trace step (API, tests)
        ctx.trace.annotate(inputs=[i.path for i in fx.inbound], outputs=[d.id for d in docs],
                           detail={"items": item_log, "vendor_id": vendor_id, "problems": problems,
                                   "quarantined": bool(problems), "malware_scan": "stub (simulated)"})
    except RuntimeError:
        pass
    return case
