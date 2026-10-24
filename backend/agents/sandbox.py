"""Per-case, per-run sandbox for the Investigator. Owner: B. (CLAUDE.md section 5)

Layout under .data/sandboxes/<case_id>/<run_id>/:
  ro/                      read-only (chmod 0444 files, 0555 dirs)
    case.json              canonical extracted JSON only: invoice, PO, receipts, discrepancies with
                           citations, dedup links, document metadata. NEVER raw document text.
    erp.json               system-of-record snapshot for this vendor (+ snapshot_version)
    memory.md              this vendor's memory file only (exact vendor-master lookup)
    policy_recommendation.json   the floor computed by code
    preferences.md         controller preferences (e.g. explanation length)
    review_feedback.json   only on a re-plan: the reviewer's rejection reason
    skill/SKILL.md, skill/policy.yaml
  scratch/                 writable by the permission rule (Droid runs read-only today); archived then wiped
  proposal.json            written by CODE from the agent's validated structured output

The Droid settings file (OS sandbox policy) is written next to the sandbox, outside its CWD.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from decimal import Decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.agents.skills import Skill
from backend.core.config import ROOT
from backend.core.stage import Ctx
from contracts import Case, Decision, MemoryFolder, Vendor

SANDBOX_ROOT = ROOT / ".data" / "sandboxes"
RO_FILE, RO_DIR = 0o444, 0o555
LEGAL = re.compile(r"[\s,.]+(co|ltd|inc|corp|llc|plc|gmbh|sdn bhd|bhd|limited|company)\b\.?", re.I)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def vendor_memory(ctx: Ctx, vendor: Optional[Vendor]) -> tuple[Optional[str], list[str], Optional[str]]:
    """(subject, lines, memory_version) for exactly this vendor.

    Lookup is by exact vendor-master name/alias slug (also with legal suffixes like "Co., Ltd." removed) ->
    memory subject. Deterministic, never similarity across vendors.
    """
    if vendor is None or memory_off():
        return None, [], None
    names = [vendor.name, *vendor.aliases]
    candidates = [_slug(n) for n in names] + [_slug(LEGAL.sub("", n)) for n in names]
    for subject in dict.fromkeys(candidates):
        entries = ctx.store.list_memory(subject)
        if entries:
            lines = [f"- [{e.provenance} | {e.valid_from}] {e.text}" for e in entries]
            ver = f"{subject}@v{max(e.version for e in entries)}:{_sha(chr(10).join(lines).encode())[:8]}"
            return subject, lines, ver
    return None, [], None


def memory_off() -> bool:
    """RECONAI_MEMORY=off: C's 'with vs without memory' eval. No vendor memory, no preferences."""
    return os.environ.get("RECONAI_MEMORY", "on").lower() == "off"


def controller_preferences(ctx: Ctx) -> list[str]:
    if memory_off():
        return []
    return [f"- [{m.provenance} | {m.valid_from}] {m.text}" for m in ctx.store.list_memory()
            if m.folder == MemoryFolder.controller_preferences]


def usd_equivalents(case: Case, ctx: Ctx) -> dict[str, Any]:
    """USD amounts computed by code (SIMULATED policy fx table) so the agent never converts currencies."""
    if case.invoice is None or case.invoice.currency not in ctx.policy.fx_rates:
        return {"available": False}
    rate = ctx.policy.fx_rates[case.invoice.currency]
    q = lambda v: str((v * rate).quantize(Decimal("0.01")))  # noqa: E731
    return {"available": True, "currency": case.invoice.currency, "fx_rate_to_usd": str(rate),
            "fx_note": "SIMULATED fixed rate table (config/policy.yaml)",
            "invoice_total_usd": q(case.invoice.total),
            "discrepancy_delta_usd": [{"type": d.type.value, "sku": d.sku, "delta_usd": q(d.delta)}
                                      for d in case.discrepancies if d.delta is not None],
            "approval_limits_usd": {k: str(v) for k, v in ctx.policy.approval_limits.items()}}


# Explicit, stable projections: only these fields are mounted (and hashed into the Droid cache key), so additive
# contract changes never change what the agent sees or invalidate cached runs. The field sets equal the P0
# contract, so mounts (and Droid cache keys) are byte-identical to the P0 eval run.
F_INVOICE = ("doc_id", "vendor_id", "invoice_no", "invoice_date", "due_date", "currency", "po_number", "total",
             "bank_last4", "flags")
F_LINE = ("line_no", "sku", "description", "qty", "unit_price", "amount")
F_PO = ("doc_id", "po_number", "vendor_id", "po_date", "currency", "requester")
F_POLINE = ("line_no", "sku", "description", "qty", "unit_price")
F_RECEIPT = ("doc_id", "po_number", "received_date", "received_by")
F_DISC = ("type", "line_no", "sku", "material", "expected", "actual", "delta", "original_type", "fingerprint")
F_CITE = ("doc_id", "locator", "quote")
F_LINK = ("type", "case_id", "invoice_no", "reason")
F_DOC = ("id", "kind", "channel", "filename", "mime", "sha256")
F_VENDOR = ("id", "name", "aliases", "country", "currency", "email_domain", "bank_last4", "channels", "critical",
            "on_probation")
F_TERM = ("doc_id", "vendor_id", "sku", "unit_price", "currency", "effective_from")
F_PAID = ("vendor_id", "invoice_no", "po_number", "total", "currency", "paid_on", "line_hash")


def pick(obj, fields: tuple[str, ...]) -> Optional[dict[str, Any]]:
    if obj is None:
        return None
    d = obj.model_dump(mode="json")
    return {k: d.get(k) for k in fields}


def canonical_case(case: Case) -> dict[str, Any]:
    """Extracted, structured facts only. Document.text (untrusted) is never included."""
    inv = pick(case.invoice, F_INVOICE)
    if inv is not None:
        inv["lines"] = [pick(li, F_LINE) for li in case.invoice.lines]
    po = pick(case.po, F_PO)
    if po is not None:
        po["lines"] = [pick(pl, F_POLINE) for pl in case.po.lines]
    receipts = []
    for r in case.receipts:
        rd = pick(r, F_RECEIPT)
        rd["lines"] = [{"sku": rl.sku, "qty_received": str(rl.qty_received)} for rl in r.lines]
        receipts.append(rd)
    discs = []
    for d in case.discrepancies:
        dd = pick(d, F_DISC)
        dd["citations"] = [pick(c, F_CITE) for c in d.citations]
        discs.append(dd)
    return {"id": case.id, "vendor_id": case.vendor_id, "as_of": str(case.as_of) if case.as_of else None,
            "skill": case.skill, "invoice": inv, "po": po, "receipts": receipts, "discrepancies": discs,
            "links": [pick(lk, F_LINK) for lk in case.links],
            "documents": [pick(d, F_DOC) for d in case.documents]}


def erp_snapshot(case: Case, ctx: Ctx, vendor: Optional[Vendor]) -> dict[str, Any]:
    vid = vendor.id if vendor else case.vendor_id
    po = case.po or (ctx.store.get_po(case.invoice.po_number) if case.invoice and case.invoice.po_number else None)
    po_d = pick(po, F_PO)
    if po_d is not None:
        po_d["lines"] = [pick(pl, F_POLINE) for pl in po.lines]
    receipts = []
    for r in (ctx.store.list_receipts(po.po_number) if po else []):
        rd = pick(r, F_RECEIPT)
        rd["lines"] = [{"sku": rl.sku, "qty_received": str(rl.qty_received)} for rl in r.lines]
        receipts.append(rd)
    snap = {
        "vendor_master": pick(vendor, F_VENDOR),
        "po": po_d,
        "receipts": receipts,
        "contract_terms": [pick(t, F_TERM) for t in ctx.store.list_contract_terms(vid)],
        "paid_history": [pick(p, F_PAID) for p in ctx.store.list_paid(vid)],
        "ledger": {"system": "beancount", "note": "reference only; agents never write the ledger"},
    }
    snap["snapshot_version"] = "erp:" + _sha(json.dumps(snap, sort_keys=True).encode())[:12]
    return snap


@dataclass
class Sandbox:
    case_id: str
    run_id: str
    root: Path
    skill: Skill
    manifest: dict[str, str] = field(default_factory=dict)   # relative path -> sha256 (mounted ro files)
    events: list[dict] = field(default_factory=list)          # mounts, permission decisions, violations
    memory_version: Optional[str] = None
    snapshot_version: Optional[str] = None
    autonomy: str = "off"   # Droid autonomy: "off" = read-only (Investigator); skill evolution uses "low"

    @property
    def ro(self) -> Path:
        return self.root / "ro"

    @property
    def scratch(self) -> Path:
        return self.root / "scratch"

    @property
    def proposal_path(self) -> Path:
        return self.root / "proposal.json"

    @property
    def settings_path(self) -> Path:  # outside CWD so the agent can't read or change its own policy
        return self.root.parent / f"{self.root.name}.droid-settings.json"

    def mount_hash(self) -> str:
        return _sha(json.dumps(self.manifest, sort_keys=True).encode())

    def ro_text(self, rel: str) -> str:
        return (self.ro / rel).read_text()

    def may_write(self, path: str) -> bool:
        """Permission-handler rule: only proposal.json and files under scratch/."""
        p = Path(path)
        p = (self.root / p if not p.is_absolute() else p).resolve()
        return p == self.proposal_path.resolve() or self.scratch.resolve() in p.parents

    def event(self, kind: str, **kw) -> None:
        self.events.append({"event": kind, **kw})

    def droid_settings(self) -> dict:
        """OS sandbox (Seatbelt / bubblewrap) policy for the Droid process. No network beyond Factory's own."""
        home = Path.home()
        return {"sandbox": {
            "enabled": True,
            "filesystem": {
                "denyWrite": [str(self.ro)],
                "denyRead": [str(p) for p in (ROOT / ".env", ROOT / "backend", ROOT / "data", ROOT / "config",
                                               ROOT / "contracts", ROOT / ".data" / "reconai.db",
                                               ROOT / ".data" / "llm_cache", home / ".ssh", home / ".aws")],
            },
            "network": {"allowedDomains": []},
        }}

    def archive_and_wipe(self, keep: bool = False) -> dict:
        """Record scratch + proposal (paths, sizes, hashes) for the trace, then delete the sandbox."""
        files = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and not p.is_relative_to(self.ro):
                data = p.read_bytes()
                files.append({"path": str(p.relative_to(self.root)), "bytes": len(data), "sha256": _sha(data)})
        ro_changed = [rel for rel, h in self.manifest.items()
                      if not (self.ro / rel).exists() or _sha((self.ro / rel).read_bytes()) != h]
        archive = {"sandbox": str(self.root.relative_to(ROOT)), "scratch": files, "ro_tampered": ro_changed,
                   "wiped": not keep}
        if not keep:
            wipe(self.root)
            self.settings_path.unlink(missing_ok=True)
            (self.root.parent / f"{self.root.name}.droid.sh").unlink(missing_ok=True)
            try:
                self.root.parent.rmdir()  # case folder, if no other run is using it
            except OSError:
                pass
        return archive


def wipe(path: Path) -> None:
    if not path.exists():
        return
    for p in [path, *path.rglob("*")]:
        try:
            os.chmod(p, stat.S_IRWXU)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)


def build(case: Case, ctx: Ctx, skill: Skill, vendor: Optional[Vendor], policy_rec: Decision, reasons: list[str],
          feedback: Optional[str] = None, attempt: int = 0) -> Sandbox:
    root = SANDBOX_ROOT / case.id / (ctx.run_id if attempt == 0 else f"{ctx.run_id}-replan{attempt}")
    wipe(root)
    sb = Sandbox(case_id=case.id, run_id=ctx.run_id, root=root, skill=skill)
    (sb.ro / "skill").mkdir(parents=True)
    sb.scratch.mkdir()

    subject, lines, sb.memory_version = vendor_memory(ctx, vendor)
    erp = erp_snapshot(case, ctx, vendor)
    sb.snapshot_version = erp["snapshot_version"]
    files: dict[str, str] = {
        "case.json": json.dumps(canonical_case(case), indent=2, sort_keys=True),
        "erp.json": json.dumps(erp, indent=2, sort_keys=True),
        "memory.md": (f"# memory: {subject} ({sb.memory_version})\n" + "\n".join(lines) + "\n") if subject
                     else "# no memory file for this vendor\n",
        "policy_recommendation.json": json.dumps({
            "recommendation": policy_rec.value, "reasons": reasons,
            "order": ["approve", "hold", "reject", "escalate"],
            "rule": "you may recommend a more severe outcome, never a less severe one",
            "usd_equivalents": usd_equivalents(case, ctx)}, indent=2),
        "preferences.md": "# controller preferences (follow them)\n" + "\n".join(controller_preferences(ctx)) + "\n",
        "skill/SKILL.md": skill.skill_md,
        "skill/policy.yaml": skill.policy_yaml,
    }
    if feedback:
        files["review_feedback.json"] = json.dumps({"attempt": attempt, "reviewer_feedback": feedback}, indent=2)
    for rel, text in files.items():
        p = sb.ro / rel
        p.write_text(text)
        os.chmod(p, RO_FILE)
        sb.manifest[rel] = _sha(text.encode())
    os.chmod(sb.ro / "skill", RO_DIR)
    os.chmod(sb.ro, RO_DIR)
    sb.settings_path.write_text(json.dumps(sb.droid_settings(), indent=2))
    sb.event("mounted", files=sorted(sb.manifest), memory=subject, memory_version=sb.memory_version,
             snapshot_version=sb.snapshot_version, skill=skill.ref)
    return sb
