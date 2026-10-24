"""A: intake validation, sniffing, adapters, domain binding."""
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from email.message import EmailMessage

import openpyxl
import pytest

from backend.core.runner import make_ctx
from backend.evals.fixtures import seed
from backend.intake.adapters import IngestError, parse_api, parse_csv, parse_xlsx
from backend.intake.ingest import closest_vendor, ingest
from backend.intake.sniff import check_extension, sniff
from backend.store.sqlite import SQLiteStore
from contracts import CaseFixture, CaseStatus, Channel, Decision, InboundItem

T0 = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)
HEADER = "invoice_number,invoice_date,po_number,currency,line_no,sku,description,quantity,unit_price,line_amount,remit_last4"
CSV_OK = HEADER + "\nINV-881,2026-10-14,PO-5501,TWD,1,WFR-N3-300,300mm wafer,1000,18600.00,18600000.00,2207\n"


@pytest.fixture
def ctx():
    store = SQLiteStore(":memory:")
    seed(store)
    return make_ctx(store)


def xlsx_bytes(rows, sheet="Invoice", macro=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if macro:
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
            for i in zin.infolist():
                zout.writestr(i, zin.read(i))
            zout.writestr("xl/vbaProject.bin", b"\x00fake macro")
        data = out.getvalue()
    return data


def eml(sender, body="Invoice attached", attachments=(), auth="spf=pass; dkim=pass; dmarc=pass"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "ap@helix.example", "Invoice"
    m["Authentication-Results"] = f"mx.helix.example; {auth}"
    m.set_content(body)
    for name, data, mime in attachments:
        a, b = mime.split("/")
        m.add_attachment(data, maintype=a, subtype=b, filename=name)
    return bytes(m)


def run_ingest(ctx, tmp_path, files, items):
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    fx = CaseFixture(id="t_case", title="t", inbound=items, as_of=date(2026, 10, 20))
    return ingest(fx, tmp_path, ctx)


# --- sniffing ---------------------------------------------------------------------

def test_magic_bytes():
    assert sniff(b"%PDF-1.4 ...").kind == "pdf"
    assert sniff(b"\x89PNG\r\n\x1a\n....").kind == "png"
    assert sniff(b"\xff\xd8\xff\xe0....").kind == "jpeg"
    assert sniff(xlsx_bytes([["a"]])).kind == "xlsx"
    s = sniff(xlsx_bytes([["a"]], macro=True))
    assert s.kind == "xlsm" and "vbaProject.bin" in s.reject
    assert sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest").reject
    assert sniff(CSV_OK.encode()).kind == "csv"
    assert sniff(b'{"schema": "x"}').kind == "json"
    assert sniff(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\xff\xff").reject


def test_extension_spoofing():
    assert check_extension("invoice.pdf", sniff(b"MZ\x90\x00binary\xff\xfe")) is not None
    assert check_extension("invoice.pdf", sniff(b"\x89PNG\r\n\x1a\nxx")) is not None
    assert check_extension("invoice.pdf", sniff(b"%PDF-1.7")) is None


# --- adapters -----------------------------------------------------------------------

def test_csv_adapter_and_semicolon_bom():
    inv = parse_csv(CSV_OK.encode(), "d1", "V-FORMOSA")
    assert inv.invoice_no == "INV-881" and inv.total == Decimal("18600000.00") and inv.currency == "TWD"
    assert inv.lines[0].amount == Decimal("18600000.00") and inv.bank_last4 == "2207"
    semi = ("﻿" + CSV_OK.replace(",", ";")).encode()
    assert parse_csv(semi, "d1", "V-FORMOSA").total == Decimal("18600000.00")


def test_csv_line_amount_mismatch_flag():
    bad = CSV_OK.replace("18600000.00", "18700000.00")
    inv = parse_csv(bad.encode(), "d1", "V")
    assert any(f.startswith("line_amount_mismatch:1") for f in inv.flags)
    assert inv.lines[0].amount == Decimal("18600000.00")  # recomputed in code


def test_csv_formula_injection():
    desc = CSV_OK.replace("300mm wafer", '=HYPERLINK("http://x")')
    inv = parse_csv(desc.encode(), "d1", "V")
    assert "formula_injection:description" in inv.flags and inv.lines[0].description.startswith("'=")
    with pytest.raises(IngestError):
        parse_csv(CSV_OK.replace("18600.00,", "=1+2,").encode(), "d1", "V")


def test_csv_missing_columns_rejected():
    with pytest.raises(IngestError):
        parse_csv(b"invoice_number,sku\nX,Y\n", "d1", "V")


def test_xlsx_adapter():
    rows = [HEADER.split(","), ["INV-9", "2026-10-14", "PO-5501", "TWD", 1, "WFR-N3-300", "wafer", 10, 18600, 186000,
                                "2207"]]
    inv = parse_xlsx(xlsx_bytes(rows), "d1", "V-FORMOSA")
    assert inv.total == Decimal("186000.00") and inv.lines[0].qty == Decimal("10")
    with pytest.raises(IngestError):
        parse_xlsx(xlsx_bytes(rows, sheet="Sheet1"), "d1", "V")


def test_api_adapters():
    k = {"schema": "kestrel.invoice.v2", "invoice_number": "KM-1", "invoice_date": "2026-10-16", "po_number": "PO-7002",
         "currency": "USD", "remit_account_last4": "5150",
         "lines": [{"sku": "HBM3E-8H-24G", "description": "x", "quantity": "40", "unit_price": "1240.00"}],
         "total": "49600.00"}
    inv, ver = parse_api(json.dumps(k).encode(), "d1", "V-KESTREL")
    assert ver == "kestrel.invoice.v2" and inv.total == Decimal("49600.00")
    a = {"schema": "aerolane.invoice.v1", "inv_no": "INV-1", "date": "2026-10-01", "po": "PO-8840", "ccy": "USD",
         "bank_last4": "7731", "items": [{"code": "FRT-AIR", "text": "air", "qty": "1", "rate": "18400.00",
                                          "amount": "18400.00"}], "invoice_total": "18400.00"}
    inv, _ = parse_api(json.dumps(a).encode(), "d1", "V-AEROLANE")
    assert inv.lines[0].sku == "FRT-AIR" and inv.total == Decimal("18400.00")
    for bad in ({**k, "schema": "kestrel.invoice.v3"}, {**k, "bank_iban": "XX"}, {**k, "currency": "dollars"},
                {**k, "total": 49600.0}):
        with pytest.raises(IngestError):
            parse_api(json.dumps(bad).encode(), "d1", "V")


# --- ingest / binding ---------------------------------------------------------------

def test_lookalike_domain_binds_to_imitated_vendor(ctx):
    v = ctx.store.list_vendors()
    assert closest_vendor("penang-packtest.com", v)[0].id == "V-PENANG"
    assert closest_vendor("totally-different.org", v) is None


def test_ingest_email_exact_and_lookalike_and_unknown(ctx, tmp_path):
    pdf = b"%PDF-1.4 fake"
    case = run_ingest(ctx, tmp_path, {"a.eml": eml("ar@kestrelmemory.co.kr", attachments=[("i.pdf", pdf, "application/pdf")])},
                      [InboundItem(channel="email", path="a.eml", sender="ar@kestrelmemory.co.kr", received_at=T0)])
    assert case.vendor_id == "V-KESTREL" and case.status == CaseStatus.new and case.as_of == date(2026, 10, 20)
    assert [d.kind.value for d in case.documents] == ["email", "invoice"]

    case = run_ingest(ctx, tmp_path, {"b.eml": eml("x@penang-packtest.com")},
                      [InboundItem(channel="email", path="b.eml", sender="x@penang-packtest.com", received_at=T0)])
    assert case.vendor_id == "V-PENANG" and case.status != CaseStatus.quarantined and not case.discrepancies
    assert any("look-alike" in n for n in case.notes)

    case = run_ingest(ctx, tmp_path, {"c.eml": eml("x@nobody-here.org")},
                      [InboundItem(channel="email", path="c.eml", sender="x@nobody-here.org", received_at=T0)])
    assert case.vendor_id == "V-UNKNOWN" and case.status != CaseStatus.quarantined


def _quarantined(case):
    return case.status == CaseStatus.quarantined and case.decision == Decision.escalate and case.quarantine_reason \
        and all(d.text is None for d in case.documents)


def test_quarantine_xlsm_attachment(ctx, tmp_path):
    data = eml("billing@formosawafer.com.tw", attachments=[("inv.xlsx", xlsx_bytes([["a"]], macro=True),
                                                             "application/vnd.ms-excel")])
    case = run_ingest(ctx, tmp_path, {"m.eml": data},
                      [InboundItem(channel="email", path="m.eml", sender="billing@formosawafer.com.tw", received_at=T0)])
    assert _quarantined(case) and "vbaProject.bin" in case.quarantine_reason


def test_quarantine_spoofed_pdf_and_money_formula(ctx, tmp_path):
    case = run_ingest(ctx, tmp_path, {"inv.pdf": b"MZ\x90\x00\xff\xfe\x00binary"},
                      [InboundItem(channel="sftp", path="inv.pdf", sender="sftp-formosa", received_at=T0)])
    assert _quarantined(case)
    case = run_ingest(ctx, tmp_path, {"inv.csv": CSV_OK.replace("18600.00,", "=1+2,").encode()},
                      [InboundItem(channel="sftp", path="inv.csv", sender="sftp-formosa", received_at=T0)])
    assert _quarantined(case) and "formula injection" in case.quarantine_reason


def test_csv_over_sftp_ok(ctx, tmp_path):
    case = run_ingest(ctx, tmp_path, {"inv.csv": CSV_OK.encode()},
                      [InboundItem(channel="sftp", path="inv.csv", sender="sftp-formosa", received_at=T0)])
    assert case.status == CaseStatus.new and case.vendor_id == "V-FORMOSA"


def test_channel_binding_failures(ctx, tmp_path):
    k = json.dumps({"schema": "kestrel.invoice.v2", "invoice_number": "KM-1", "invoice_date": "2026-10-16",
                    "currency": "USD", "lines": [{"sku": "A", "quantity": "1", "unit_price": "1.00"}],
                    "total": "1.00"}).encode()
    assert _quarantined(run_ingest(ctx, tmp_path, {"k.json": k}, [InboundItem(
        channel="api", path="k.json", sender="V-KESTREL", api_key="bogus", received_at=T0)]))
    # unregistered SFTP account
    assert _quarantined(run_ingest(ctx, tmp_path, {"inv.csv": CSV_OK.encode()}, [InboundItem(
        channel="sftp", path="inv.csv", sender="sftp-penang", received_at=T0)]))
    # valid key, vendor registered on api
    ok = run_ingest(ctx, tmp_path, {"k.json": k}, [InboundItem(
        channel="api", path="k.json", sender="V-KESTREL", api_key="sim-key-kestrel-7f3a", received_at=T0)])
    assert ok.status == CaseStatus.new and ok.vendor_id == "V-KESTREL"
    # valid key, but the vendor is not registered on the API channel
    ctx.store.save_vendor(ctx.store.get_vendor("V-AEROLANE").model_copy(update={"channels": [Channel.email]}))
    a = json.dumps({"schema": "aerolane.invoice.v1", "inv_no": "I", "date": "2026-10-01", "ccy": "USD",
                    "items": [{"code": "A", "qty": "1", "rate": "1.00"}], "invoice_total": "1.00"}).encode()
    bad = run_ingest(ctx, tmp_path, {"a.json": a}, [InboundItem(
        channel="api", path="a.json", sender="V-AEROLANE", api_key="sim-key-aerolane-91c2", received_at=T0)])
    assert _quarantined(bad) and "not registered on channel api" in bad.quarantine_reason


def test_dmarc_fail_on_exact_domain_quarantines(ctx, tmp_path):
    data = eml("ar@kestrelmemory.co.kr", auth="spf=fail; dkim=fail; dmarc=fail")
    case = run_ingest(ctx, tmp_path, {"s.eml": data},
                      [InboundItem(channel="email", path="s.eml", sender="ar@kestrelmemory.co.kr", received_at=T0)])
    assert _quarantined(case) and "authentication failed" in case.quarantine_reason
