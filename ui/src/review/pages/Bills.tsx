// Bill Pay > Bills, organised by lifecycle stage: Overview · For approval · For payment · History.
// For approval: bulk approve (limits enforced server-side). For payment: Review payments drawer to schedule
// approved bills and release scheduled runs (AP leads approve; a controller, CFO or CTO releases). Bank rail is SIMULATED; the Coinbase rail
// sends real USDC on Base Sepolia testnet (scaled-down amounts).
import { Alert, Avatar, Badge, Button, Card, Checkbox, Chip, Divider, Drawer, Group, ScrollArea, Stack, Tabs, Text, TextInput, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconSearch } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import type { ApprovalDecision, PaymentBatch } from "../../types/contracts";
import { ap } from "../api";
import { fmtUsdc, microOf, microUsdc, OnchainLine, TreasuryCard, useTreasury } from "../coinbase";
import { me, useApp } from "../context";
import { amount, canRelease, day, RELEASE_RULE, shortName, STAGES, sumMoney, usd, when } from "../format";
import { Avatarish, BillsTable } from "../parts";

const TABS: Record<string, { label: string; stages: string[] }> = {
  overview: { label: "Overview", stages: ["processing", "needs_review", "on_hold", "ready_to_pay", "blocked", "scheduled", "paid", "rejected"] },
  approval: { label: "For approval", stages: ["needs_review", "on_hold"] },
  payment: { label: "For payment", stages: ["ready_to_pay", "blocked", "scheduled"] },
  history: { label: "History", stages: ["paid", "rejected"] },
};
const METHOD = { ach: "ACH (direct deposit)", wire: "Domestic wire", intl_wire: "International wire", check: "Check by mail" } as Record<string, string>;
const today = () => new Date().toISOString().slice(0, 10);

export default function Bills({ tab: tabParam }: { tab?: string }) {
  const { bills, go, seat, refresh } = useApp();
  const tab = tabParam && TABS[tabParam] ? tabParam : "overview";
  const [chips, setChips] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setChips([]); setSelected([]); }, [tab]);
  const who = me(seat);

  const inTab = bills.filter((b) => TABS[tab].stages.includes(b.stage));
  const n = q.trim().toLowerCase();
  const shown = inTab.filter((b) => (!chips.length || chips.includes(b.stage)) && (!n || `${b.vendor_name} ${b.invoice_no}`.toLowerCase().includes(n)));
  const present = TABS[tab].stages.filter((s) => inTab.some((b) => b.stage === s));
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const bulk = async (dec: ApprovalDecision) => {
    setBusy(true);
    const res = await Promise.allSettled(selected.map((id) => ap.decide(id, { approver: who.email, role: who.role, decision: dec, comment: "bulk", scope: null })));
    const bad = res.map((r, i) => (r.status === "rejected" ? `${selected[i]}: ${(r.reason as Error).message}` : null)).filter(Boolean);
    notifications.show({ color: bad.length ? "orange" : "brand", title: `${res.length - bad.length} of ${res.length} recorded`, message: bad.join(" · ") || "Done." });
    setSelected([]); setBusy(false); refresh();
  };

  return (
    <>
      <Text c="dimmed" fz="sm">Bill Pay</Text>
      <Group justify="space-between" align="flex-end" mb="md">
        <Text fz={34} fw={650} lh={1.1}>Bills</Text>
        {tab === "payment" && <Button onClick={() => setDrawer(true)}>Review payments</Button>}
      </Group>
      <Tabs value={tab} onChange={(t) => go(t === "overview" ? "bills" : `bills/${t}`)} mb="md">
        <Tabs.List>
          {Object.entries(TABS).map(([k, t]) => {
            const c = bills.filter((b) => t.stages.includes(b.stage)).length;
            return <Tabs.Tab key={k} value={k} rightSection={k !== "overview" && c ? <Badge size="xs" variant="light" circle>{c}</Badge> : null}>{t.label}</Tabs.Tab>;
          })}
        </Tabs.List>
      </Tabs>
      <Card withBorder padding={0}>
        <Group p="sm" justify="space-between">
          <Group gap="sm">
            <TextInput size="xs" w={240} leftSection={<IconSearch size={14} />} placeholder="Search or filter…" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
            {present.length > 1 && (
              <Chip.Group multiple value={chips} onChange={setChips}>
                <Group gap={6}>{present.map((s) => <Chip key={s} value={s} size="xs" variant="outline">{STAGES[s].label} · {inTab.filter((b) => b.stage === s).length}</Chip>)}</Group>
              </Chip.Group>
            )}
          </Group>
          {tab === "approval" && (
            <Group gap="xs">
              <Text fz="xs" c="dimmed">{selected.length ? `${selected.length} selected` : `Signed in as ${who.title}`}</Text>
              <Button size="xs" disabled={!selected.length} loading={busy} onClick={() => bulk("approved")}>Approve</Button>
              <Button size="xs" variant="light" color="yellow" disabled={!selected.length} loading={busy} onClick={() => bulk("ask")}>Hold</Button>
              <Button size="xs" variant="light" color="red" disabled={!selected.length} loading={busy} onClick={() => bulk("rejected")}>Reject</Button>
            </Group>
          )}
          {tab === "payment" && (
            <Group gap="xs"><Text fz="xs" c="dimmed">{selected.length ? `${selected.length} selected · ${usd(sumMoney(bills.filter((b) => selected.includes(b.case_id)).map((b) => b.payable_usd ?? b.amount_usd)))}` : "Select approved bills to schedule"}</Text>
              <Button size="xs" disabled={!selected.length} onClick={() => setDrawer(true)}>Schedule selected</Button></Group>
          )}
        </Group>
        <BillsTable bills={shown}
          select={tab === "approval" || tab === "payment" ? { selected, toggle, all: setSelected, can: tab === "payment" ? (b) => b.stage === "ready_to_pay" : undefined } : undefined}
          extra={tab === "approval" ? { head: "Needs", cell: (b) => <Text fz="xs">{b.needs === "approver" ? "AP lead" : b.needs === "controller" ? "Controller" : b.needs === "cfo" ? "CFO" : "—"}{b.sla_breached && <Badge ml={6} size="xs" color="red">SLA</Badge>}</Text> }
            : tab === "payment" ? { head: "Payment", cell: (b) => b.payment ? <Text fz="xs">{METHOD[b.payment.method]} · {day(b.payment.pay_date)}</Text> : b.payment_block ? <Text fz="xs" c="red">blocked</Text> : <Text fz="xs" c="dimmed">not scheduled</Text> } : undefined} />
      </Card>
      <ReviewPayments opened={drawer} onClose={() => setDrawer(false)} selected={selected} onDone={() => { setSelected([]); refresh(); }} />
    </>
  );
}

function ReviewPayments({ opened, onClose, selected, onDone }: { opened: boolean; onClose: () => void; selected: string[]; onDone: () => void }) {
  const { bills, vendors, seat, lastEvent } = useApp();
  const [runs, setRuns] = useState<PaymentBatch[]>([]);
  const [date, setDate] = useState(today());
  const [pick, setPick] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [wallets, setWallets] = useState<Record<string, string | null>>({});
  const who = me(seat);
  const releaser = canRelease(who.role);
  const tr = useTreasury(opened);
  useEffect(() => { if (opened) ap.runs().then(setRuns).catch(() => {}); }, [opened, lastEvent, bills]);
  const toSchedule = bills.filter((b) => selected.includes(b.case_id) && b.stage === "ready_to_pay");
  const scheduled = runs.filter((r) => r.status === "scheduled");
  const partial = runs.filter((r) => r.status === "partially_paid");
  const onchain = runs.filter((r) => r.status === "paid" && r.rail === "coinbase").sort((a, b) => (b.released_at ?? "").localeCompare(a.released_at ?? "")).slice(0, 5);
  const vname = (id: string) => shortName(vendors[id]?.name ?? id);
  const noWallet = (r: PaymentBatch) => [...new Set(r.payments.filter((p) => p.status !== "paid" && !(wallets[p.vendor_id] ?? vendors[p.vendor_id]?.wallet_address)).map((p) => vname(p.vendor_id)))];
  const scale = tr.t?.usd_scale ?? "0.000001";
  const need = (rs: PaymentBatch[]) => rs.flatMap((r) => r.payments.filter((p) => p.status !== "paid")).reduce((n, p) => n + microUsdc(p.amount_usd, scale), 0n);
  useEffect(() => { setPick(releaser ? scheduled.map((r) => r.id) : []); }, [scheduled.map((r) => r.id).join(), seat, opened]);
  const byDate = useMemo(() => {
    const m = new Map<string, PaymentBatch[]>();
    scheduled.forEach((r) => m.set(r.pay_date, [...(m.get(r.pay_date) ?? []), r]));
    return [...m.entries()].sort();
  }, [runs]);

  const schedule = async () => {
    setBusy(true);
    try {
      const r = await ap.createRun(toSchedule.map((b) => b.case_id), date, who.email);
      notifications.show({ color: "brand", title: `${r.id} scheduled for ${day(r.pay_date)}`, message: `${r.payments.length} bill(s) · ${usd(r.total_usd)}. ${releaser ? "Release it below when ready." : "A controller, CFO or CTO releases it."}` });
      onDone(); setRuns(await ap.runs());
    } catch (e) { notifications.show({ color: "red", title: "Can't schedule", message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  };
  const release = async (ids: string[], rail: "bank" | "coinbase") => {
    setBusy(true);
    const res = await Promise.allSettled(ids.map((id) => ap.release(id, who.email, rail, who.role)));
    const bad = res.map((r, i) => (r.status === "rejected" ? `${ids[i]}: ${(r.reason as Error).message}` : null)).filter(Boolean);
    const done = res.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    const failed = done.flatMap((b) => b.payments.filter((p) => p.status === "failed"));
    if (rail === "bank") notifications.show({ color: bad.length ? "orange" : "green", title: `${done.length} run(s) released (simulated)`, message: bad.join(" · ") || "Paid." });
    else notifications.show({ color: bad.length || failed.length ? "orange" : "green", autoClose: 10000,
      title: `${done.length} run(s) sent via Coinbase · testnet`,
      message: [done.length ? `${done.flatMap((b) => b.payments).filter((p) => p.status === "paid" && p.tx_hash).length} USDC transfer(s) confirmed on-chain${failed.length ? `, ${failed.length} failed (retry below)` : ""}.` : "", ...bad].filter(Boolean).join(" · ") });
    onDone(); setRuns(await ap.runs()); setBusy(false);
    if (rail === "coinbase") tr.reload();
  };
  const picked = scheduled.filter((r) => pick.includes(r.id));
  const pickedTotal = sumMoney(picked.map((r) => r.total_usd));
  const pickedNeed = need(picked);
  const lowFunds = tr.live && tr.t ? microOf(tr.t.balances.USDC ?? "0") < pickedNeed : false;
  const missing = [...new Set(picked.flatMap(noWallet))];

  return (
    <Drawer opened={opened} onClose={onClose} position="right" size={560} title={<Text fz={26} fw={650}>Review payments</Text>} scrollAreaComponent={ScrollArea.Autosize}>
      <Stack>
        <TreasuryCard tr={tr} onWallets={(vs) => setWallets(Object.fromEntries(vs.map((v) => [v.id, v.wallet_address])))} />
        {toSchedule.length > 0 && (
          <Card withBorder>
            <Text fw={600} mb={4}>Schedule {toSchedule.length} approved bill{toSchedule.length > 1 ? "s" : ""}</Text>
            <Group justify="space-between" mb="sm"><Text fz={26} fw={600}>{usd(sumMoney(toSchedule.map((b) => b.payable_usd ?? b.amount_usd)))}</Text>
              <TextInput type="date" size="xs" label="Payment date" value={date} min={today()} onChange={(e) => setDate(e.currentTarget.value)} /></Group>
            {toSchedule.map((b) => {
              const v = vendors[b.vendor_id];
              return (
                <Group key={b.case_id} justify="space-between" py={6} style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }} wrap="nowrap">
                  <Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} size={26} /><div><Text fz="sm" fw={500}>{shortName(b.vendor_name)}</Text>
                    <Text fz="xs" c="dimmed">{b.invoice_no} · {v?.country === "US" ? METHOD.ach : METHOD.intl_wire} · to •••• {v?.bank_last4}</Text>
                    {b.discount?.status === "available" && <Text fz="xs" c={date <= b.discount.pay_by ? "green.8" : "orange.8"}>
                      {date <= b.discount.pay_by ? `saves ${amount(b.discount.discount_amount, b.currency)} (pay by ${day(b.discount.pay_by)})` : `pay by ${day(b.discount.pay_by)} to save ${amount(b.discount.discount_amount, b.currency)}`}</Text>}
                    {b.credit_available && <Text fz="xs" c="blue.8">{amount(b.credit_available, b.currency)} prepaid credit will be applied</Text>}</div></Group>
                  <Stack gap={0} align="flex-end"><Text fz="sm" ff="monospace">{amount(b.payable ?? b.amount, b.currency)}</Text>
                    {b.payable && b.payable !== b.amount && <Text fz="xs" c="dimmed">undisputed part of {amount(b.amount, b.currency)}</Text>}</Stack>
                </Group>
              );
            })}
            <Button mt="sm" fullWidth loading={busy} onClick={schedule}>Schedule payments</Button>
          </Card>
        )}
        <div>
          <Group justify="space-between" mb={4}><Text fw={600}>Scheduled, waiting for release</Text><Text fz="sm" c="dimmed">{scheduled.length} run(s)</Text></Group>
          <Text fz="xs" c="dimmed" mb="sm">Signed in as {who.name} ({who.title}). {releaser ? "You can release these runs." : "Approved by AP lead → needs a controller, CFO or CTO to release."}</Text>
          {byDate.length === 0 && <Text fz="sm" c="dimmed">Nothing scheduled.</Text>}
          {byDate.map(([d, rs]) => (
            <div key={d}>
              <Text fw={600} mt="sm">{day(d)}</Text>
              <Text fz="xs" c="dimmed" mb={6}>{rs.reduce((n, r) => n + r.payments.length, 0)} bill(s)</Text>
              {rs.map((r) => {
                const nw = tr.live ? noWallet(r) : [];
                return (
                  <Card key={r.id} withBorder padding="sm" mb="xs" bg={pick.includes(r.id) ? "brand.0" : undefined}>
                    <Group justify="space-between" wrap="nowrap">
                      <Group gap="sm" wrap="nowrap">
                        <Tooltip label={RELEASE_RULE} disabled={releaser}><span><Checkbox checked={pick.includes(r.id)} disabled={!releaser}
                          onChange={() => setPick((p) => (p.includes(r.id) ? p.filter((x) => x !== r.id) : [...p, r.id]))} /></span></Tooltip>
                        <Avatar.Group>{r.payments.slice(0, 3).map((p) => <Avatarish key={p.id} name={vendors[p.vendor_id]?.name ?? p.vendor_id} size={26} />)}</Avatar.Group>
                        <div><Text fz="sm" fw={500}>{r.payments.map((p) => shortName(vendors[p.vendor_id]?.name ?? p.vendor_id)).join(", ")}</Text>
                          <Text fz="xs" c="dimmed">{r.id} · {r.payments.map((p) => `${METHOD[p.method]} → •••• ${p.pay_to_last4}`).join(" · ")}</Text></div>
                      </Group>
                      <Stack gap={0} align="flex-end"><Text fz="sm" ff="monospace">{usd(r.total_usd)}</Text>{r.payments.length > 1 && <Badge size="xs" variant="outline">Batched</Badge>}</Stack>
                    </Group>
                    <Text fz={10} c="dimmed" mt={4}>scheduled by {r.created_by} · {when(r.created_at)}{tr.live && ` · ${fmtUsdc(need([r]))} on ${tr.sandbox ? "sandbox" : "testnet"}`}</Text>
                    {nw.length > 0 && <Text fz="xs" c="orange.8" mt={2}>No payout wallet on file for {nw.join(", ")}: Coinbase release will be refused.</Text>}
                  </Card>
                );
              })}
            </div>
          ))}
        </div>
        {scheduled.length > 0 && <>
          <Divider />
          <Group justify="space-between" align="flex-end">
            <div><Text fz="xs" c="dimmed">Releasing</Text><Text fz={22} fw={600}>{usd(pickedTotal)}</Text>
              {tr.live && picked.length > 0 && <Text fz="xs" c="dimmed">{fmtUsdc(pickedNeed)} via Coinbase · {tr.sandbox ? "sandbox" : "testnet"}</Text>}</div>
            <Group gap="xs">
              <Tooltip label={RELEASE_RULE} disabled={releaser}>
                <span><Button variant="default" disabled={!releaser || !picked.length} loading={busy} onClick={() => release(picked.map((r) => r.id), "bank")}>Release (bank · simulated)</Button></span>
              </Tooltip>
              <Tooltip label={!releaser ? RELEASE_RULE : tr.t ? "Coinbase isn't configured (CDP keys missing)" : "Checking the Coinbase treasury…"} disabled={releaser && tr.live}>
                <span><Button color="green" disabled={!releaser || !picked.length || !tr.live} loading={busy} onClick={() => release(picked.map((r) => r.id), "coinbase")}>Release via Coinbase (USDC)</Button></span>
              </Tooltip>
            </Group>
          </Group>
          {tr.live && picked.length > 0 && lowFunds && <Alert variant="light" color="orange" p="xs">Treasury has {fmtUsdc(microOf(tr.t?.balances.USDC ?? "0"))}; these runs need {fmtUsdc(pickedNeed)}. Fund from the faucet first.</Alert>}
          {tr.live && missing.length > 0 && <Alert variant="light" color="orange" p="xs">{missing.join(", ")} {missing.length > 1 ? "have" : "has"} no payout wallet in the vendor master. Create vendor payout wallets above, or release on the bank rail.</Alert>}
          <Alert variant="light" color="gray">Bank release is simulated. Coinbase sends real USDC on Base Sepolia testnet, scaled down from the USD amount. Payments always go to the vendor master's account or wallet, never one printed on an invoice.</Alert>
        </>}
        {partial.length > 0 && <div>
          <Text fw={600} mb={4}>Partially paid on Coinbase</Text>
          {partial.map((r) => {
            return (
              <Card key={r.id} withBorder padding="sm" mb="xs" style={{ borderColor: "var(--mantine-color-orange-4)" }}>
                <Group justify="space-between" mb={4}><Text fz="sm" fw={500}>{r.id} · {usd(r.total_usd)}</Text>
                  <Badge size="xs" color="orange" variant="light">{r.payments.filter((p) => p.status === "paid").length}/{r.payments.length} paid</Badge></Group>
                {r.payments.map((p) => <OnchainLine key={p.id} p={p} vendor={vname(p.vendor_id)} />)}
                <Group justify="space-between" mt={6}>
                  <Text fz={10} c="dimmed">scheduled by {r.created_by} · released by {r.released_by}{r.released_at && ` · ${when(r.released_at)}`}</Text>
                  <Tooltip label={!releaser ? RELEASE_RULE : "Coinbase isn't configured"} disabled={releaser && tr.live}>
                    <span><Button size="xs" color="orange" variant="light" disabled={!releaser || !tr.live} loading={busy} onClick={() => release([r.id], "coinbase")}>Retry failed on Coinbase</Button></span>
                  </Tooltip>
                </Group>
              </Card>
            );
          })}
        </div>}
        {onchain.length > 0 && <div>
          <Text fw={600} mb={4}>Paid via Coinbase · {tr.sandbox ? "sandbox (simulated)" : "testnet"}</Text>
          {onchain.map((r) => (
            <Card key={r.id} withBorder padding="sm" mb="xs">
              <Group justify="space-between" mb={2}><Text fz="sm" fw={500}>{r.id} · {usd(r.total_usd)}</Text><Text fz={10} c="dimmed">released by {r.released_by}{r.released_at && ` · ${when(r.released_at)}`}</Text></Group>
              {r.payments.map((p) => <OnchainLine key={p.id} p={p} vendor={vname(p.vendor_id)} />)}
            </Card>
          ))}
        </div>}
      </Stack>
    </Drawer>
  );
}
