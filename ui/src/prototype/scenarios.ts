// PROTOTYPE DATA. Scripted from the five fixtures in data/cases (same numbers, same answer key), so the design
// can show what the finished pipeline is meant to catch. Amounts are precomputed here, never in the UI.
export type Unit = "wafer" | "chip" | "package" | "box";
export type Line = { sku: string; desc: string; unit: Unit; ordered: number; received: number; billed: number; poPrice: string; invPrice: string; amount: string };
export type Outcome = "pay" | "partial" | "hold" | "reject";

export type Scenario = {
  id: string; caseId: string; short: string; vendor: string; color: string; country: string; currency: string;
  email: { from: string; subject: string; at: string; file: string };
  invoice: { no: string; date: string; due: string; po: string; total: string; totalUsd: string };
  lines: Line[];
  bank: { onFile: string; onInvoice: string; bankName: string };
  domain: { onFile: string; sender: string };
  duplicate?: { paidNo: string; paidOn: string };
  price?: { po: string; billed: string; amendment: string; effective: string; invoiceDate: string };
  outcome: Outcome;
  payNow: string; held: string; heldReason?: string;
  headline: string;            // the one sentence the reviewer sees first
  needs: "approver" | "controller";
  followUp?: string;
};

export const SCENARIOS: Scenario[] = [
  {
    id: "kestrel-clean", caseId: "case_01", short: "Kestrel", vendor: "Kestrel Memory Inc.", color: "#3b6fd8", country: "KR", currency: "USD",
    email: { from: "ar@kestrelmemory.co.kr", subject: "Invoice KM-INV-30118 · PO-7001", at: "09:00", file: "KM-INV-30118.pdf" },
    invoice: { no: "KM-INV-30118", date: "Oct 12", due: "Nov 12", po: "PO-7001", total: "72,500.00", totalUsd: "72,500" },
    lines: [{ sku: "HBM3E-12H-24G", desc: "HBM3E 12-high 24GB stack", unit: "chip", ordered: 50, received: 50, billed: 50, poPrice: "1,450.00", invPrice: "1,450.00", amount: "72,500.00" }],
    bank: { onFile: "5150", onInvoice: "5150", bankName: "Shinhan Bank" },
    domain: { onFile: "kestrelmemory.co.kr", sender: "kestrelmemory.co.kr" },
    outcome: "pay", payNow: "72,500.00", held: "0", needs: "approver",
    headline: "Everything matches. Pay in full.",
  },
  {
    id: "formosa-short", caseId: "case_02", short: "Formosa", vendor: "Formosa Wafer Works", color: "#c2410c", country: "TW", currency: "TWD",
    email: { from: "billing@formosawafer.com.tw", subject: "INV-881 for PO-5501", at: "09:14", file: "FWW-INV-881.pdf" },
    invoice: { no: "INV-881", date: "Oct 14", due: "Nov 14", po: "PO-5501", total: "18,600,000.00", totalUsd: "576,600" },
    lines: [{ sku: "WFR-N3-300", desc: "300mm N3 engineering wafer", unit: "wafer", ordered: 1000, received: 940, billed: 1000, poPrice: "18,600.00", invPrice: "18,600.00", amount: "18,600,000.00" }],
    bank: { onFile: "2207", onInvoice: "2207", bankName: "Cathay United" },
    domain: { onFile: "formosawafer.com.tw", sender: "formosawafer.com.tw" },
    outcome: "partial", payNow: "17,484,000.00", held: "1,116,000.00", heldReason: "60 wafers billed but never received",
    needs: "controller", followUp: "Credit note for 60 wafers requested · follow-up Oct 30",
    headline: "Billed 1,000 wafers. Only 940 arrived. Pay for 940, hold the rest.",
  },
  {
    id: "kestrel-price", caseId: "case_03", short: "Kestrel", vendor: "Kestrel Memory Inc.", color: "#3b6fd8", country: "KR", currency: "USD",
    email: { from: "ar@kestrelmemory.co.kr", subject: "Invoice KM-INV-30152 · PO-7002", at: "09:31", file: "KM-INV-30152.pdf" },
    invoice: { no: "KM-INV-30152", date: "Oct 16", due: "Nov 16", po: "PO-7002", total: "49,600.00", totalUsd: "49,600" },
    lines: [{ sku: "HBM3E-8H-24G", desc: "HBM3E 8-high 24GB stack", unit: "chip", ordered: 40, received: 40, billed: 40, poPrice: "1,180.00", invPrice: "1,240.00", amount: "49,600.00" }],
    bank: { onFile: "5150", onInvoice: "5150", bankName: "Shinhan Bank" },
    domain: { onFile: "kestrelmemory.co.kr", sender: "kestrelmemory.co.kr" },
    price: { po: "1,180.00", billed: "1,240.00", amendment: "Amendment 3", effective: "Nov 1", invoiceDate: "Oct 16" },
    outcome: "partial", payNow: "47,200.00", held: "2,400.00", heldReason: "New price billed before it takes effect",
    needs: "approver", followUp: "Asked Kestrel to re-bill at the PO price",
    headline: "Billed the new price two weeks early. PO price wins. Hold $2,400.",
  },
  {
    id: "penang-bank", caseId: "case_04", short: "Penang", vendor: "Penang Pack & Test", color: "#7c3aed", country: "MY", currency: "USD",
    email: { from: "finance@penang-packtest.com", subject: "URGENT updated bank details · PPT-6620", at: "09:47", file: "PPT-INV-6620.pdf" },
    invoice: { no: "PPT-6620", date: "Oct 20", due: "Nov 20", po: "PO-6100", total: "3,300,000.00", totalUsd: "3,300,000" },
    lines: [{ sku: "PKG-COWOS-L", desc: "CoWoS-L packaging + final test", unit: "package", ordered: 2000, received: 2000, billed: 2000, poPrice: "1,650.00", invPrice: "1,650.00", amount: "3,300,000.00" }],
    bank: { onFile: "4418", onInvoice: "9902", bankName: "Maybank" },
    domain: { onFile: "penangpacktest.com.my", sender: "penang-packtest.com" },
    outcome: "hold", payNow: "0", held: "3,300,000.00", heldReason: "New bank account from a look-alike domain",
    needs: "controller", followUp: "Callback to the number on the vendor master, not the email",
    headline: "Right goods. Wrong bank account, sent from a fake domain. Don't pay.",
  },
  {
    id: "aerolane-dup", caseId: "case_05", short: "Aerolane", vendor: "Aerolane Freight", color: "#0891b2", country: "US", currency: "USD",
    email: { from: "billing@aerolane.com", subject: "INV-2291-A", at: "10:02", file: "AFL-INV-2291-A.pdf" },
    invoice: { no: "INV-2291-A", date: "Oct 21", due: "Nov 21", po: "PO-8840", total: "21,600.00", totalUsd: "21,600" },
    lines: [
      { sku: "FRT-AIR-TPE-SJC", desc: "Air freight TPE→SJC, 14 pallets", unit: "box", ordered: 1, received: 1, billed: 1, poPrice: "18,400.00", invPrice: "18,400.00", amount: "18,400.00" },
      { sku: "FRT-EXPEDITE", desc: "Expedite surcharge", unit: "box", ordered: 0, received: 0, billed: 1, poPrice: "—", invPrice: "3,200.00", amount: "3,200.00" },
    ],
    bank: { onFile: "7731", onInvoice: "7731", bankName: "Chase" },
    domain: { onFile: "aerolane.com", sender: "aerolane.com" },
    duplicate: { paidNo: "INV-2291", paidOn: "Oct 8" },
    outcome: "reject", payNow: "0", held: "21,600.00", heldReason: "Same invoice already paid on Oct 8",
    needs: "approver", followUp: "Told Aerolane it was paid on Oct 8 · 3rd unapproved expedite fee this year",
    headline: "We already paid this on Oct 8. It came back with “-A” on the number. Reject.",
  },
];

export const FILE_LIMIT = { approver: 100000, controller: 1000000 } as const; // USD, mirrors config/policy.yaml
export const usdNumber = (s: Scenario) => Number(s.invoice.totalUsd.replace(/,/g, ""));
