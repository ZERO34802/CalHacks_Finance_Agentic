"""Store contract tests. Run against SQLite always, and against SpacetimeDB when it is reachable.

Spacetime uses a separate database (RECONAI_SPACETIME_TEST_DB, default `reconai-test`) so tests never wipe
the dev database. Publish it once with:
  spacetime publish reconai-test -s local --module-path spacetime/spacetimedb --yes=skip-login
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.evals.fixtures import seed
from backend.store import get_store
from backend.store.spacetime import reachable
from backend.store.sqlite import SQLiteStore
from contracts import (Case, CaseStatus, Channel, DocKind, Document, MemoryEntry, MemoryFolder, Scoreboard, Step,
                       StepStatus)

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
TEST_DB = os.environ.get("RECONAI_SPACETIME_TEST_DB", "reconai-test")


@pytest.fixture(params=["sqlite", "spacetime"])
def store(request):
    if request.param == "sqlite":
        yield SQLiteStore(":memory:")
        return
    if not reachable(db=TEST_DB):
        pytest.skip("SpacetimeDB not reachable (spacetime start + publish reconai-test)")
    s = get_store("spacetime", db=TEST_DB)
    s.reset(keep_scoreboards=False)
    yield s
    s.reset(keep_scoreboards=False)


def _doc(i: int, sha: str) -> Document:
    return Document(id=f"d{i}", kind=DocKind.invoice, channel=Channel.email, filename=f"f{i}.pdf", sha256=sha,
                    mime="application/pdf", received_at=T0, text="it's untrusted 'quoted' text")


def _case(cid: str, vendor: str = "V-KESTREL", docs=()) -> Case:
    return Case(id=cid, vendor_id=vendor, documents=list(docs), created_at=T0)


def test_cases_roundtrip_and_filter(store):
    store.save_case(_case("c2", "V-FORMOSA"))
    store.save_case(_case("c1", docs=[_doc(1, "aa")]))
    c1 = store.get_case("c1")
    assert c1 is not None and c1.documents[0].text == "it's untrusted 'quoted' text"
    assert [c.id for c in store.list_cases()] == ["c1", "c2"]
    assert [c.id for c in store.list_cases("V-FORMOSA")] == ["c2"]
    assert store.get_case("nope") is None
    c1.status = CaseStatus.escalated
    store.save_case(c1)  # upsert
    assert store.get_case("c1").status == CaseStatus.escalated and len(store.list_cases()) == 2


def test_find_documents_by_hash(store):
    store.save_case(_case("c1", docs=[_doc(1, "same"), _doc(2, "other")]))
    store.save_case(_case("c2", docs=[_doc(1, "same")]))
    hits = store.find_documents("same")
    assert [(cid, d.id) for cid, d in hits] == [("c1", "d1"), ("c2", "d1")]
    assert store.find_documents("missing") == []


def test_claim_fingerprint_insert_or_get(store):
    assert store.claim_fingerprint("fp-1", "c1") == "c1"
    assert store.claim_fingerprint("fp-1", "c2") == "c1"  # existing owner wins
    assert store.claim_fingerprint("fp-2", "c2") == "c2"


def test_claim_fingerprint_concurrent(store):
    owners: list[str] = []
    threads = [threading.Thread(target=lambda i=i: owners.append(store.claim_fingerprint("fp-race", f"c{i}")))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(owners)) == 1


def _step(sid: str, case_id: str, run_id: str, seq: int, status=StepStatus.running) -> Step:
    return Step(id=sid, case_id=case_id, run_id=run_id, seq=seq, stage=f"s{seq}", status=status, started_at=T0)


def test_steps_upsert_order_and_latest_run(store):
    store.append_step(_step("a2", "c1", "run_a", 2))
    store.append_step(_step("a1", "c1", "run_a", 1))
    store.append_step(_step("a1", "c1", "run_a", 1, StepStatus.ok))  # finish = upsert
    store.append_step(_step("b0", "c1", "run_b", 0))
    store.append_step(_step("x0", "c9", "run_b", 0))
    run_a = store.list_steps("c1", "run_a")
    assert [s.id for s in run_a] == ["a1", "a2"] and run_a[0].status == StepStatus.ok
    assert [s.id for s in store.list_steps("c1")] == ["b0"]  # latest run
    assert store.list_steps("nobody") == []


def test_world_vendors_memory_scoreboards(store):
    seed(store)
    assert store.get_po("PO-5501").vendor_id == "V-FORMOSA"
    assert [r.po_number for r in store.list_receipts("PO-8900")] == ["PO-8900", "PO-8900"]
    assert {t.unit_price for t in store.list_contract_terms("V-KESTREL")} >= {Decimal("1180.00"), Decimal("1240.00")}
    assert store.list_paid("V-AEROLANE")[0].invoice_no == "INV-2291"
    assert any(e.email == "m.chen@helix.example" for e in store.list_employees())
    assert store.get_vendor("V-PENANG").bank_last4 == "4418" and len(store.list_vendors()) == 5
    assert store.list_memory("aerolane-freight")
    store.save_memory(MemoryEntry(id="x:0", folder=MemoryFolder.patterns, subject="x", text="t", provenance="test",
                                  valid_from="2026-10-01"))
    assert [m.id for m in store.list_memory("x")] == ["x:0"]
    for i, at in enumerate([T0, T0.replace(hour=11), T0.replace(hour=10)]):
        store.save_scoreboard(Scoreboard(run_id=f"r{i}", at=at, total=0, passed=0, catch_rate=1, false_alarm_rate=0,
                                         invariant_pass_rate=1, results=[]))
    assert store.latest_scoreboard().run_id == "r1"


def test_records_roundtrip_and_delete_memory(store):
    from contracts import Alert, Controls
    a1 = Alert(id="a1", kind="missing_file", vendor_id="V-KESTREL", at=T0, message="it's late")
    a2 = Alert(id="a2", kind="payment_at_risk", case_id="case_46", at=T0, message="due soon")
    store.put_record("alert", "a2", a2, idx="case_46")
    store.put_record("alert", "a1", a1, idx="V-KESTREL")
    assert [a.id for a in store.list_records(Alert, "alert")] == ["a1", "a2"]
    assert [a.id for a in store.list_records(Alert, "alert", idx="case_46")] == ["a2"]
    assert store.get_record(Alert, "alert", "a1").message == "it's late"
    assert store.get_record(Alert, "alert", "zz") is None
    store.put_record("controls", "global", Controls(paused_vendors=["V-KESTREL"]))
    store.put_record("controls", "global", Controls())  # upsert
    assert store.get_record(Controls, "controls", "global").paused_vendors == []
    with pytest.raises(AssertionError):
        store.put_record("po", "x", a1)  # reserved world kinds
    m = MemoryEntry(id="y:0", folder=MemoryFolder.patterns, subject="y", text="t", provenance="test",
                    valid_from="2026-10-01")
    store.save_memory(m)
    store.delete_memory("y:0")
    store.delete_memory("never-existed")
    assert store.list_memory("y") == []


def test_reset_keeps_scoreboards(store):
    store.save_case(_case("c1", docs=[_doc(1, "h")]))
    store.claim_fingerprint("fp", "c1")
    store.append_step(_step("s", "c1", "r", 0))
    store.save_scoreboard(Scoreboard(run_id="r", at=T0, total=0, passed=0, catch_rate=1, false_alarm_rate=0,
                                     invariant_pass_rate=1, results=[]))
    store.reset(keep_scoreboards=True)
    assert store.list_cases() == [] and store.find_documents("h") == [] and store.list_steps("c1") == []
    assert store.claim_fingerprint("fp", "c2") == "c2"
    assert store.latest_scoreboard().run_id == "r"


def test_factory_default_is_sqlite(monkeypatch):
    monkeypatch.delenv("RECONAI_STORE", raising=False)
    assert isinstance(get_store(path=":memory:"), SQLiteStore)
    with pytest.raises(ValueError):
        get_store("mongo")
