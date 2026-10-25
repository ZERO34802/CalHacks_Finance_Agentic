// Purchasing: Helix's purchase orders and goods receipts, from the ERP (Odoo when connected, else the built-in ERP).
// POs come from onboarded vendors' contracts; receipts are counted by a Helix person (never the vendor) and feed the 3-way match.
import { Alert, Anchor, Badge, Button, Card, Drawer, Group, Loader, Stack, Table, Text, TextInput, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconExternalLink, IconPackage, IconPackageImport, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ErpStatus, PurchaseOrderView } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, day, shortName } from "../format";
import { Avatarish } from "../parts";

const PO_STATUS: Record<string, { label: string; color: string }> = {
  ordered: { label: "Ordered", color: "blue" },
  partially_received: { label: "Partially received", color: "orange" },
  received: { label: "Received", color: "brand" },
  invoiced: { label: "Invoiced", color: "violet" },
  paid: { label: "Paid", color: "green" },
};
const SOURCE: Record<string, string> = { app: "ReconAI app", slack: "Slack", erp: "Odoo" };

// Exact quantity math on Decimal strings (6 dp, BigInt). Quantities only; money is never computed here.
const SCALE = 1_000_000n;
const toMicro = (v: string | null | undefined) => {
  if (!v) return 0n;
  const neg = v.startsWith("-");
  const [i, f = ""] = v.replace("-", "").split(".");
  const n = BigInt(i || "0") * SCALE + BigInt((f + "000000").slice(0, 6));
  return neg ? -n : n;
};
const fromMicro = (n: bigint) => {
  const neg = n < 0n, a = neg ? -n : n;
  const f = String(a % SCALE).padStart(6, "0").replace(/0+$/, "");
  return `${neg ? "-" : ""}${a / SCALE}${f ? `.${f}` : ""}`;
};
const qty = (v: string | null | undefined) => fromMicro(toMicro(v));
const remaining = (v: PurchaseOrderView, sku: string, ordered: string) => {
  const r = toMicro(ordered) - toMicro(v.received[sku]);
  return r > 0n ? r : 0n;
};
/** "odoo:purchase.order:12:P00012" -> "P00012"; "odoo:stock.picking:3:WH/IN/00003" -> "WH/IN/00003" */
const refName = (ref: string | null | undefined) => (ref ? ref.split(":").slice(3).join(":") || ref.split(":").slice(1).join(" #") : null);

export default function Purchasing({ openPo }: { openPo?: string }) {
  const { go, bills } = useApp();
  const [status, setStatus] = useState<ErpStatus | null>(null);
  const [pos, setPos] = useState<PurchaseOrderView[] | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(() => {
    setLoading(true);
    ap.erpStatus().then(setStatus).catch(() => setStatus(null));
    ap.purchaseOrders().then(setPos).catch(() => setPos([])).finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  const open = pos?.find((p) => p.po.po_number === openPo) ?? null;
  const billLabel = (id: string) => bills.find((b) => b.case_id === id)?.invoice_no ?? id;

  return (
    <>
      <Group justify="space-between" align="flex-end" mb="md">
        <div>
          <Text fz={34} fw={650} lh={1.1}>Purchasing</Text>
          <Text c="dimmed" fz="sm" mt={4}>Purchase orders and goods receipts: the first two legs of the 3-way match.</Text>
        </div>
        <Group gap="sm">
          <ErpChip s={status} />
          <Button variant="default" size="xs" leftSection={loading ? <Loader size={12} /> : <IconRefresh size={14} />} onClick={load}>Refresh</Button>
        </Group>
      </Group>

      {pos === null ? <Group justify="center" py="xl"><Loader /></Group> : pos.length === 0 ? (
        <Card withBorder py="xl">
          <Stack align="center" gap="xs" maw={520} mx="auto" ta="center">
            <IconPackage size={36} color="var(--mantine-color-gray-5)" />
            <Text fw={600}>No purchase orders yet</Text>
            <Text fz="sm" c="dimmed">POs are created automatically when the vendor on a Slack-negotiated contract is onboarded:
              the agreed items, quantities and prices become a confirmed PO in the ERP{status?.mode === "odoo" ? " (Odoo)" : ""}, and the contract
              prices become what the Matcher checks bills against.</Text>
          </Stack>
        </Card>
      ) : (
        <Card withBorder padding={0}>
          <Table.ScrollContainer minWidth={960}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead bg="gray.0"><Table.Tr><Table.Th>PO</Table.Th><Table.Th>Vendor</Table.Th><Table.Th>Lines · received / ordered</Table.Th>
                <Table.Th ta="right">Total</Table.Th><Table.Th>Status</Table.Th><Table.Th>Bills</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {pos.map((v) => (
                  <Table.Tr key={v.po.po_number} style={{ cursor: "pointer" }} onClick={() => go(`purchasing/${v.po.po_number}`)}>
                    <Table.Td><Text fz="sm" fw={600} ff="monospace">{v.po.po_number}</Text>
                      <Text fz="xs" c="dimmed">{day(v.po.po_date)}{v.po.erp_ref && <> · {v.erp_url
                        ? <Anchor href={v.erp_url} target="_blank" fz="xs" onClick={(e) => e.stopPropagation()}>Odoo {refName(v.po.erp_ref)}</Anchor>
                        : refName(v.po.erp_ref)}</>}</Text></Table.Td>
                    <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={v.vendor_name} size={26} /><div>
                      <Text fz="sm" fw={500}>{shortName(v.vendor_name)}</Text>
                      {v.po.contract_id && <Text fz="xs" c="dimmed" ff="monospace">{v.po.contract_id}</Text>}</div></Group></Table.Td>
                    <Table.Td>{v.po.lines.map((ln) => (
                      <Text key={ln.sku} fz="xs"><Text span ff="monospace" fz="xs">{ln.sku}</Text>{" "}
                        <Text span fz="xs" c={toMicro(v.received[ln.sku]) >= toMicro(ln.qty) ? "brand.7" : toMicro(v.received[ln.sku]) > 0n ? "orange.8" : "dimmed"}>
                          {qty(v.received[ln.sku] ?? "0")} / {qty(ln.qty)}</Text></Text>))}</Table.Td>
                    <Table.Td ta="right" ff="monospace" fz="sm">{amount(v.total, v.po.currency)}</Table.Td>
                    <Table.Td><Badge variant="light" color={PO_STATUS[v.status]?.color ?? "gray"}>{PO_STATUS[v.status]?.label ?? v.status}</Badge></Table.Td>
                    <Table.Td>{v.invoices.length ? <Group gap={4}>{v.invoices.map((id) => (
                      <Badge key={id} variant="outline" size="sm" style={{ cursor: "pointer" }}
                        onClick={(e) => { e.stopPropagation(); go(`bill/${id}`); }}>{billLabel(id)}</Badge>))}</Group>
                      : <Text fz="xs" c="dimmed">none yet</Text>}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Card>
      )}

      <Drawer opened={!!open} onClose={() => go("purchasing")} position="right" size="xl"
        title={open ? <Group gap="sm"><Text fw={650} fz="lg">{open.po.po_number}</Text>
          <Badge variant="light" color={PO_STATUS[open.status]?.color ?? "gray"}>{PO_STATUS[open.status]?.label ?? open.status}</Badge></Group> : null}>
        {open && <PoDetail v={open} onDone={load} billLabel={billLabel} />}
      </Drawer>
    </>
  );
}

function ErpChip({ s }: { s: ErpStatus | null }) {
  if (!s) return <Badge variant="light" color="gray">ERP · checking</Badge>;
  if (s.mode === "odoo" && s.connected) return (
    <Tooltip label={s.note}><Badge variant="light" color="brand" size="lg" leftSection={<IconExternalLink size={12} />}
      component="a" href={s.url ?? "#"} target="_blank" style={{ cursor: "pointer" }}>Odoo · connected{s.database ? ` · ${s.database}` : ""}</Badge></Tooltip>);
  if (s.mode === "odoo") return <Tooltip label={s.note} multiline w={320}><Badge variant="light" color="red" size="lg">Odoo · unreachable</Badge></Tooltip>;
  return <Tooltip label={s.note} multiline w={320}><Badge variant="light" color="gray" size="lg">Simulated ERP</Badge></Tooltip>;
}

function PoDetail({ v, onDone, billLabel }: { v: PurchaseOrderView; onDone: () => void; billLabel: (id: string) => string }) {
  const { seat, go, refresh } = useApp();
  const who = me(seat);
  const defaults = useMemo(() => Object.fromEntries(v.po.lines.map((ln) => [ln.sku, fromMicro(remaining(v, ln.sku, ln.qty))])), [v]);
  const [form, setForm] = useState<Record<string, string>>(defaults);
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(defaults), [defaults]);
  const open = v.po.lines.some((ln) => remaining(v, ln.sku, ln.qty) > 0n);
  const bad = Object.entries(form).filter(([, q]) => q.trim() !== "" && !/^\d+(\.\d{1,6})?$/.test(q.trim())).map(([s]) => s);
  const lines = Object.fromEntries(Object.entries(form).map(([s, q]) => [s, q.trim()]).filter(([, q]) => q && toMicro(q) > 0n));

  const submit = async () => {
    setBusy(true);
    try {
      const r = await ap.receive(v.po.po_number, who.email, lines);
      notifications.show({ color: "brand", title: `Goods receipt recorded for ${v.po.po_number}`,
        message: `${r.lines.map((l) => `${qty(l.qty_received)} × ${l.sku}`).join(", ")} counted by ${who.name}${r.erp_ref ? ` · Odoo ${refName(r.erp_ref)} validated` : ""}.` });
      onDone(); refresh();
    } catch (e) {
      notifications.show({ color: "red", title: "Receipt not recorded", message: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  };

  return (
    <Stack>
      <Table fz="sm"><Table.Tbody>
        <Table.Tr><Table.Td c="dimmed" w={160}>Vendor</Table.Td><Table.Td>{v.vendor_name}</Table.Td></Table.Tr>
        <Table.Tr><Table.Td c="dimmed">Ordered</Table.Td><Table.Td>{day(v.po.po_date)} · requested by {v.po.requester}</Table.Td></Table.Tr>
        {v.po.contract_id && <Table.Tr><Table.Td c="dimmed">Contract</Table.Td><Table.Td ff="monospace">{v.po.contract_id}</Table.Td></Table.Tr>}
        <Table.Tr><Table.Td c="dimmed">ERP record</Table.Td><Table.Td>{v.po.erp_ref
          ? <>{v.erp_url ? <Anchor href={v.erp_url} target="_blank">Odoo {refName(v.po.erp_ref)} <IconExternalLink size={12} /></Anchor> : refName(v.po.erp_ref)}</>
          : <Text span c="dimmed" fz="sm">Built-in ERP (simulated)</Text>}</Table.Td></Table.Tr>
        <Table.Tr><Table.Td c="dimmed">Total</Table.Td><Table.Td ff="monospace">{amount(v.total, v.po.currency)}</Table.Td></Table.Tr>
        <Table.Tr><Table.Td c="dimmed">Bills</Table.Td><Table.Td>{v.invoices.length ? <Group gap={4}>{v.invoices.map((id) => (
          <Badge key={id} variant="outline" style={{ cursor: "pointer" }} onClick={() => go(`bill/${id}`)}>{billLabel(id)}</Badge>))}</Group>
          : <Text span c="dimmed" fz="sm">No bill against this PO yet</Text>}</Table.Td></Table.Tr>
      </Table.Tbody></Table>

      <div>
        <Text fw={600} mb="xs">Lines</Text>
        <Card withBorder padding={0}>
          <Table fz="sm" verticalSpacing="xs">
            <Table.Thead bg="gray.0"><Table.Tr><Table.Th>SKU</Table.Th><Table.Th>Description</Table.Th><Table.Th ta="right">Unit price</Table.Th>
              <Table.Th ta="right">Ordered</Table.Th><Table.Th ta="right">Received</Table.Th>{open && <Table.Th w={130}>Count now</Table.Th>}</Table.Tr></Table.Thead>
            <Table.Tbody>{v.po.lines.map((ln) => {
              const left = remaining(v, ln.sku, ln.qty);
              return (
                <Table.Tr key={ln.sku}>
                  <Table.Td ff="monospace">{ln.sku}</Table.Td><Table.Td>{ln.description || "—"}</Table.Td>
                  <Table.Td ta="right" ff="monospace">{amount(ln.unit_price, v.po.currency)}</Table.Td>
                  <Table.Td ta="right" ff="monospace">{qty(ln.qty)}</Table.Td>
                  <Table.Td ta="right" ff="monospace" c={left === 0n ? "brand.7" : toMicro(v.received[ln.sku]) > 0n ? "orange.8" : undefined}>{qty(v.received[ln.sku] ?? "0")}</Table.Td>
                  {open && <Table.Td>{left > 0n
                    ? <TextInput size="xs" inputMode="decimal" value={form[ln.sku] ?? ""} error={bad.includes(ln.sku)}
                        rightSection={<Text fz={10} c="dimmed">/{fromMicro(left)}</Text>} rightSectionWidth={44}
                        onChange={(e) => { const val = e.currentTarget.value; setForm((f) => ({ ...f, [ln.sku]: val })); }} />
                    : <Text fz="xs" c="brand.7">complete</Text>}</Table.Td>}
                </Table.Tr>
              );
            })}</Table.Tbody>
          </Table>
        </Card>
      </div>

      {open ? (
        <Card withBorder>
          <Group justify="space-between" align="center" wrap="nowrap">
            <div>
              <Text fw={600}>Record goods receipt</Text>
              <Text fz="xs" c="dimmed">Counting as {who.name} ({who.email}). Defaults to what's still open; never more than ordered.
                {v.po.erp_ref ? " Validated in Odoo as a receipt (a partial count leaves a backorder)." : ""}</Text>
            </div>
            <Button leftSection={<IconPackageImport size={16} />} loading={busy} disabled={!!bad.length || !Object.keys(lines).length} onClick={submit}>Record receipt</Button>
          </Group>
        </Card>
      ) : <Alert color="brand" variant="light" title="Fully received">Every line on this PO has arrived. Bills against it are matched against these counts.</Alert>}

      <div>
        <Text fw={600} mb="xs">Receipts · {v.receipts.length}</Text>
        {v.receipts.length === 0 && <Text fz="sm" c="dimmed">Nothing received yet. Receipts come from a Helix person (here, in Slack, or in Odoo), never from the vendor.</Text>}
        {v.receipts.map((r) => (
          <Group key={r.doc_id} justify="space-between" align="flex-start" py={8} wrap="nowrap" style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }}>
            <div>
              <Text fz="sm" fw={500}>{r.lines.map((l) => `${qty(l.qty_received)} × ${l.sku}`).join(" · ")}</Text>
              <Text fz="xs" c="dimmed">{day(r.received_date)} · counted by {r.received_by}</Text>
            </div>
            <Stack gap={2} align="flex-end">
              <Badge size="sm" variant="light" color={r.source === "slack" ? "violet" : r.source === "erp" ? "blue" : "gray"}>{SOURCE[r.source] ?? r.source}</Badge>
              {r.erp_ref && <Text fz={10} c="dimmed" ff="monospace">{refName(r.erp_ref)}</Text>}
            </Stack>
          </Group>
        ))}
      </div>
    </Stack>
  );
}
