// Bills, organised by lifecycle: Overview · For approval → For payment → History. The page fits the window:
// the table scrolls inside its card, header and actions stay pinned.
// For approval: bulk approve / hold / reject (limits enforced server-side).
// For payment: the payment panel sits next to the bills it pays. Tick approved bills -> schedule a run -> someone
// other than the preparer releases it. Bank rail is SIMULATED; the Coinbase rail sends USDC on Base Sepolia testnet
// (scaled-down amounts).
import { Avatar, Badge, Box, Button, Card, Checkbox, Chip, Group, ScrollArea, Stack, Text, TextInput, Tooltip, UnstyledButton } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconChevronRight, IconSearch } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import type { ApprovalDecision, Bill, PaymentBatch } from "../../types/contracts";
import { ap } from "../api";
import { fmtUsdc, microOf, microUsdc, OnchainLine, TreasuryBar, useTreasury } from "../coinbase";
import { me, useApp } from "../context";
import { amount, day, PEOPLE, shortName, STAGES, sumMoney, usd, usdShort, when, type Seat } from "../format";
import { Avatarish, BILL_TABS, billQueue, BillsFooter, BillsTable, HEAD_BG, HEAD_BORDER, sortBills } from "../parts";

const METHOD = { ach: "ACH", wire: "Domestic wire", intl_wire: "Intl wire", check: "Check" } as Record<string, string>;
const today = () => new Date().toISOString().slice(0, 10);
const strip = { background: `var(--mantine-color-${HEAD_BG.replace(".", "-")})`, borderBottom: HEAD_BORDER } as const;

export default function Bills({ tab: tabParam }: { tab?: string }) {
  const { bills, go, seat, refresh } = useApp();
  const tab = tabParam && BILL_TABS[tabParam] ? tabParam : "overview";
  const [chips, setChips] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setChips([]); setSelected([]); setHighlight([]); }, [tab]);
  const who = me(seat);

  const inTab = useMemo(() => sortBills(bills.filter((b) => BILL_TABS[tab].stages.includes(b.stage))), [bills, tab]);
  const n = q.trim().toLowerCase();
  const shown = inTab.filter((b) => (!chips.length || chips.includes(b.stage)) && (!n || `${b.vendor_name} ${b.invoice_no}`.toLowerCase().includes(n)));
  const present = BILL_TABS[tab].stages.filter((s) => inTab.some((b) => b.stage === s));
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  // the bill page's list and K / J walk exactly this list, in this order
  const open = (id: string) => { billQueue.tab = tab; billQueue.ids = shown.map((b) => b.case_id); go(`bill/${id}`); };

  const bulk = async (dec: ApprovalDecision) => {
    setBusy(true);
    const res = await Promise.allSettled(selected.map((id) => ap.decide(id, { approver: who.email, role: who.role, decision: dec, comment: "bulk", scope: null })));
    const bad = res.map((r, i) => (r.status === "rejected" ? `${selected[i]}: ${(r.reason as Error).message}` : null)).filter(Boolean);
    notifications.show({ color: bad.length ? "orange" : "brand", title: `${res.length - bad.length} of ${res.length} recorded`, message: bad.join(" · ") || "Done." });
    setSelected([]); setBusy(false); refresh();
  };

  const payment = tab === "payment";
  const selTotal = usd(sumMoney(bills.filter((b) => selected.includes(b.case_id)).map((b) => b.payable_usd ?? b.amount_usd)));
  return (
    // fits the window exactly (60px header + 2 x 32px shell padding): only the table rows and the run list scroll
    <Box style={{ height: "calc(100vh - 124px)", minHeight: 560, display: "flex", flexDirection: "column", gap: "var(--mantine-spacing-md)" }}>
      <Text fz={26} fw={650} lh={1.1}>Bills</Text>
      <Lifecycle tab={tab} />

      <Box style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: payment ? "minmax(0, 1fr) clamp(340px, 28vw, 420px)" : "minmax(0, 1fr)", gap: "var(--mantine-spacing-md)" }}>
        <Card withBorder padding={0} style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          <Group px="sm" py={8} justify="space-between" wrap="nowrap" style={strip}>
            <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
              <TextInput size="xs" w={200} leftSection={<IconSearch size={14} />} placeholder="Search vendor or invoice" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
              {present.length > 1 && (
                <Chip.Group multiple value={chips} onChange={setChips}>
                  <Group gap={6} wrap="nowrap">{present.map((s) => <Chip key={s} value={s} size="xs" variant="outline">{STAGES[s].label} · {inTab.filter((b) => b.stage === s).length}</Chip>)}</Group>
                </Chip.Group>
              )}
            </Group>
            {tab === "approval" && (
              <Group gap="xs" wrap="nowrap">
                {selected.length > 0 && <Text fz="xs" c="dimmed">{selected.length} selected</Text>}
                <Button size="xs" disabled={!selected.length} loading={busy} onClick={() => bulk("approved")}>Approve</Button>
                <Button size="xs" variant="default" disabled={!selected.length} loading={busy} onClick={() => bulk("ask")}>Hold</Button>
                <Button size="xs" variant="light" color="red" disabled={!selected.length} loading={busy} onClick={() => bulk("rejected")}>Reject</Button>
              </Group>
            )}
            {payment && selected.length > 0 && <Text fz="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{selected.length} selected · {selTotal}</Text>}
          </Group>
          <ScrollArea style={{ flex: 1 }} type="auto">
            <BillsTable bills={shown} footer={false} compact={payment} highlight={highlight} onOpen={open}
              select={tab === "approval" || payment ? { selected, toggle, all: setSelected, can: payment ? (b) => b.stage === "ready_to_pay" : undefined } : undefined}
              extra={tab === "approval" ? { head: "Needs", cell: (b) => <Group gap={4} wrap="nowrap"><Text fz="xs">{PEOPLE[b.needs as Seat]?.title ?? "—"}</Text>{b.sla_breached && <Badge size="xs" color="red">SLA</Badge>}</Group> }
                : payment ? { head: "Payment", cell: (b) => <PayCell b={b} /> } : undefined} />
          </ScrollArea>
          <BillsFooter bills={shown}>{payment && <Text fz="xs" c="dimmed">Tick approved bills to schedule them →</Text>}</BillsFooter>
        </Card>
        {payment && <PaymentPanel selected={selected} onHover={setHighlight} onDone={() => { setSelected([]); refresh(); }} />}
      </Box>
    </Box>
  );
}

/* The four tabs as one connected flow: Overview | For approval → For payment → History, each with its count and value. */
function Lifecycle({ tab }: { tab: string }) {
  const { bills, go, seat } = useApp();
  const of = (k: string) => bills.filter((b) => BILL_TABS[k].stages.includes(b.stage));
  const val = (bs: Bill[]) => usdShort(sumMoney(bs.map((b) => b.payable_usd ?? b.amount_usd)));
  const count = (k: string, s: string) => of(k).filter((b) => b.stage === s).length;
  const mine = of("approval").filter((b) => b.needs === seat).length;
  const sub: Record<string, string> = {
    overview: `${bills.filter((b) => !["paid", "rejected"].includes(b.stage)).length} open`,
    approval: `${val(of("approval"))}${mine ? ` · ${mine} need you` : ""}`,
    payment: `${val(of("payment"))} · ${count("payment", "ready_to_pay")} to schedule`,
    history: `${count("history", "paid")} paid · ${count("history", "rejected")} rejected`,
  };
  return (
    <Group gap={6} wrap="nowrap" role="tablist">
      {Object.entries(BILL_TABS).map(([k, t], i) => {
        const on = k === tab;
        return (
          <Group key={k} gap={6} wrap="nowrap" style={{ flex: k === "overview" ? 0.8 : 1 }}>
            {i > 1 && <IconChevronRight size={16} color="var(--mantine-color-gray-5)" style={{ flexShrink: 0 }} />}
            {i === 1 && <Box w={10} />}
            <UnstyledButton role="tab" aria-selected={on} onClick={() => go(k === "overview" ? "bills" : `bills/${k}`)} px="md" py={8}
              style={{ flex: 1, borderRadius: 8, border: `1px solid var(--mantine-color-${on ? "brand-6" : "gray-3"})`, background: on ? "var(--mantine-color-brand-0)" : "white" }}>
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text fz="sm" fw={600} c={on ? "brand.8" : undefined}>{t.label}</Text>
                <Text fz="sm" fw={600} ff="monospace" c={on ? "brand.8" : "dimmed"}>{of(k).length}</Text>
              </Group>
              <Text fz="xs" c="dimmed" truncate>{sub[k]}</Text>
            </UnstyledButton>
          </Group>
        );
      })}
    </Group>
  );
}

function PayCell({ b }: { b: Bill }) {
  if (b.payment) return <Tooltip label={`${b.payment.batch_id} · ${METHOD[b.payment.method] ?? b.payment.method}`}><div><Text fz="xs">{day(b.payment.pay_date).replace(/, \d{4}$/, "")}</Text><Text fz={10} c="dimmed">{METHOD[b.payment.method] ?? b.payment.method}</Text></div></Tooltip>;
  return b.stage === "blocked" ? <Text fz="xs" fw={600} c="red.7">Blocked</Text> : <Text fz="xs" fw={600} c="brand.7">Ready</Text>;
}

/* Right of the For payment table: schedule what's ticked (pinned top), runs waiting for release (scrolls), release (pinned bottom). */
function PaymentPanel({ selected, onHover, onDone }: { selected: string[]; onHover: (ids: string[]) => void; onDone: () => void }) {
  const { bills, vendors, seat, lastEvent } = useApp();
  const [runs, setRuns] = useState<PaymentBatch[]>([]);
  const [date, setDate] = useState(today());
  const [pick, setPick] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [wallets, setWallets] = useState<Record<string, string | null>>({});
  const who = me(seat);
  const tr = useTreasury(true);
  useEffect(() => { ap.runs().then(setRuns).catch(() => {}); }, [lastEvent, bills]);
  const toSchedule = bills.filter((b) => selected.includes(b.case_id) && b.stage === "ready_to_pay");
  const scheduled = runs.filter((r) => r.status === "scheduled");
  const partial = runs.filter((r) => r.status === "partially_paid");
  const onchain = runs.filter((r) => r.status === "paid" && r.rail === "coinbase").sort((a, b) => (b.released_at ?? "").localeCompare(a.released_at ?? "")).slice(0, 5);
  const vname = (id: string) => shortName(vendors[id]?.name ?? id);
  const noWallet = (r: PaymentBatch) => [...new Set(r.payments.filter((p) => p.status !== "paid" && !(wallets[p.vendor_id] ?? vendors[p.vendor_id]?.wallet_address)).map((p) => vname(p.vendor_id)))];
  const scale = tr.t?.usd_scale ?? "0.000001";
  const need = (rs: PaymentBatch[]) => rs.flatMap((r) => r.payments.filter((p) => p.status !== "paid")).reduce((n, p) => n + microUsdc(p.amount_usd, scale), 0n);
  useEffect(() => { setPick(scheduled.filter((r) => r.created_by !== who.email).map((r) => r.id)); }, [scheduled.map((r) => r.id).join(), seat]);
  const byDate = useMemo(() => {
    const m = new Map<string, PaymentBatch[]>();
    scheduled.forEach((r) => m.set(r.pay_date, [...(m.get(r.pay_date) ?? []), r]));
    return [...m.entries()].sort();
  }, [runs]);

  const schedule = async () => {
    setBusy(true);
    try {
      const r = await ap.createRun(toSchedule.map((b) => b.case_id), date, who.email);
      notifications.show({ color: "brand", title: `${r.id} scheduled for ${day(r.pay_date)}`, message: `${r.payments.length} bill(s) · ${usd(r.total_usd)}. Someone other than you must release it.` });
      onDone(); setRuns(await ap.runs());
    } catch (e) { notifications.show({ color: "red", title: "Can't schedule", message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  };
  const release = async (ids: string[], rail: "bank" | "coinbase") => {
    setBusy(true);
    const res = await Promise.allSettled(ids.map((id) => ap.release(id, who.email, rail)));
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
  const pickedNeed = need(picked);
  const lowFunds = tr.live && tr.t ? microOf(tr.t.balances.USDC ?? "0") < pickedNeed : false;
  const missing = [...new Set(picked.flatMap(noWallet))];
  const hover = (r: PaymentBatch | null) => onHover(r ? r.payments.map((p) => p.case_id) : []);
  const seg = { borderBottom: "1px solid var(--mantine-color-gray-2)" } as const;
  const label = (t: string, right?: string) => (
    <Group justify="space-between" mb={6}><Text fz="xs" fw={600} c="dimmed" tt="uppercase">{t}</Text>{right && <Text fz="xs" c="dimmed">{right}</Text>}</Group>
  );

  return (
    <Card withBorder padding={0} style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Box px="sm" py={8} style={strip}>
        <Text fw={600} fz={17} lh={1.3} mb={4}>Payment runs</Text>
        <TreasuryBar tr={tr} onWallets={(vs) => setWallets(Object.fromEntries(vs.map((v) => [v.id, v.wallet_address])))} />
      </Box>

      {/* 1. schedule what's ticked in the table */}
      <Box p="sm" style={seg}>
        {label("Schedule", toSchedule.length ? `${toSchedule.length} bill${toSchedule.length > 1 ? "s" : ""}` : undefined)}
        {!toSchedule.length ? <Text fz="sm" c="dimmed">Tick approved bills in the table.</Text> : (
          <>
            <ScrollArea.Autosize mah={132} type="auto" offsetScrollbars>
              {toSchedule.map((b) => {
                const v = vendors[b.vendor_id];
                const off = b.discount?.status === "available" ? b.discount : null;
                return (
                  <Group key={b.case_id} justify="space-between" py={4} wrap="nowrap" gap="xs">
                    <div style={{ minWidth: 0 }}><Text fz="sm" fw={500} truncate>{shortName(b.vendor_name)}</Text>
                      <Text fz="xs" c={off ? (date <= off.pay_by ? "brand.7" : "orange.8") : b.credit_available ? "blue.8" : "dimmed"} truncate>
                        {off ? (date <= off.pay_by ? `saves ${amount(off.discount_amount, b.currency)}` : `pay by ${day(off.pay_by)} to save ${amount(off.discount_amount, b.currency)}`)
                          : b.credit_available ? `${amount(b.credit_available, b.currency)} credit applied`
                            : `${v?.country === "US" ? METHOD.ach : METHOD.intl_wire} → •••• ${v?.bank_last4 ?? "—"}`}</Text></div>
                    <Text fz="sm" ff="monospace" style={{ flexShrink: 0 }}>{amount(b.payable ?? b.amount, b.currency)}</Text>
                  </Group>
                );
              })}
            </ScrollArea.Autosize>
            <Group gap="xs" mt="xs" wrap="nowrap">
              <TextInput type="date" size="xs" value={date} min={today()} onChange={(e) => setDate(e.currentTarget.value)} aria-label="Payment date" style={{ flex: 1 }} />
              <Button size="xs" loading={busy} onClick={schedule}>Schedule {usd(sumMoney(toSchedule.map((b) => b.payable_usd ?? b.amount_usd)))}</Button>
            </Group>
          </>
        )}
      </Box>

      {/* 2. runs waiting for a second person */}
      <ScrollArea style={{ flex: 1 }} type="auto" onMouseLeave={() => hover(null)}>
        <Box p="sm">
          {label("Waiting for release", `${scheduled.length} run${scheduled.length === 1 ? "" : "s"} · ${usd(sumMoney(scheduled.map((r) => r.total_usd)))}`)}
          {!byDate.length && <Text fz="sm" c="dimmed">Nothing scheduled.</Text>}
          {byDate.map(([d, rs]) => (
            <div key={d}>
              <Text fz="xs" fw={600} mt={8} mb={4}>{day(d)}</Text>
              <Stack gap={6}>
                {rs.map((r) => {
                  const mineRun = r.created_by === who.email;
                  const nw = tr.live ? noWallet(r) : [];
                  const on = pick.includes(r.id);
                  return (
                    <Box key={r.id} p={8} onMouseEnter={() => hover(r)}
                      style={{ border: `1px solid var(--mantine-color-${on ? "brand-3" : "gray-3"})`, borderRadius: 8, background: on ? "var(--mantine-color-brand-0)" : undefined }}>
                      <Group gap="sm" wrap="nowrap">
                        <Tooltip label="You prepared this run: someone else must release it" disabled={!mineRun}><span><Checkbox size="xs" checked={on} disabled={mineRun}
                          onChange={() => setPick((p) => (p.includes(r.id) ? p.filter((x) => x !== r.id) : [...p, r.id]))} aria-label={`Release ${r.id}`} /></span></Tooltip>
                        <Avatar.Group>{r.payments.slice(0, 3).map((p) => <Avatarish key={p.id} name={vendors[p.vendor_id]?.name ?? p.vendor_id} size={22} />)}</Avatar.Group>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <Text fz="sm" fw={500} truncate>{[...new Set(r.payments.map((p) => vname(p.vendor_id)))].join(", ")}</Text>
                          <Text fz="xs" c="dimmed" truncate>{mineRun ? "Prepared by you" : `By ${r.created_by.split("@")[0]}`} · {[...new Set(r.payments.map((p) => METHOD[p.method] ?? p.method))].join(", ")}</Text>
                        </div>
                        <Text fz="sm" ff="monospace" style={{ flexShrink: 0 }}>{usd(r.total_usd)}</Text>
                      </Group>
                      {nw.length > 0 && <Text fz="xs" c="orange.8" mt={4} truncate>No payout wallet for {nw.join(", ")}: bank only</Text>}
                    </Box>
                  );
                })}
              </Stack>
            </div>
          ))}

          {partial.length > 0 && <>
            <Box mt="md">{label("Partially paid on Coinbase")}</Box>
            {partial.map((r) => {
              const mineRun = r.created_by === who.email;
              return (
                <Box key={r.id} p={8} mb={6} style={{ border: "1px solid var(--mantine-color-orange-4)", borderRadius: 8 }}>
                  <Group justify="space-between" mb={4} wrap="nowrap"><Text fz="sm" fw={500}>{r.id} · {usd(r.total_usd)}</Text>
                    <Badge size="xs" color="orange" variant="light">{r.payments.filter((p) => p.status === "paid").length}/{r.payments.length} paid</Badge></Group>
                  {r.payments.map((p) => <OnchainLine key={p.id} p={p} vendor={vname(p.vendor_id)} />)}
                  <Group justify="flex-end" mt={4}>
                    <Tooltip label={mineRun ? "You prepared this run" : "Coinbase isn't configured"} disabled={!mineRun && tr.live}>
                      <span><Button size="compact-xs" color="orange" variant="light" disabled={mineRun || !tr.live} loading={busy} onClick={() => release([r.id], "coinbase")}>Retry failed</Button></span>
                    </Tooltip>
                  </Group>
                </Box>
              );
            })}
          </>}

          {onchain.length > 0 && <>
            <Box mt="md">{label(`Paid via Coinbase · ${tr.sandbox ? "sandbox" : "testnet"}`)}</Box>
            {onchain.map((r) => (
              <Box key={r.id} p={8} mb={6} style={{ border: "1px solid var(--mantine-color-gray-3)", borderRadius: 8 }}>
                <Group justify="space-between" mb={2} wrap="nowrap"><Text fz="sm" fw={500}>{r.id} · {usd(r.total_usd)}</Text>
                  <Text fz={10} c="dimmed">{r.released_by?.split("@")[0]}{r.released_at && ` · ${when(r.released_at)}`}</Text></Group>
                {r.payments.map((p) => <OnchainLine key={p.id} p={p} vendor={vname(p.vendor_id)} />)}
              </Box>
            ))}
          </>}
        </Box>
      </ScrollArea>

      {/* 3. release: always visible */}
      <Box p="sm" style={{ borderTop: HEAD_BORDER }}>
        {tr.live && picked.length > 0 && (lowFunds || missing.length > 0) && (
          <Text fz="xs" c="orange.8" mb={6}>
            {lowFunds ? `Treasury has ${fmtUsdc(microOf(tr.t?.balances.USDC ?? "0"))}, needs ${fmtUsdc(pickedNeed)}. ` : ""}
            {missing.length ? `No payout wallet: ${missing.join(", ")}.` : ""}
          </Text>
        )}
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <div style={{ whiteSpace: "nowrap" }}><Text fz="xs" c="dimmed">Release · {picked.length}</Text>
            <Text fz={20} fw={600} lh={1.2}>{usd(sumMoney(picked.map((r) => r.total_usd)))}</Text></div>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label="Simulated bank transfer to the vendor master's account"><Button size="xs" variant="default" disabled={!picked.length} loading={busy} onClick={() => release(picked.map((r) => r.id), "bank")}>Bank · simulated</Button></Tooltip>
            <Tooltip multiline w={260} label={tr.live ? `USDC on ${tr.sandbox ? "the sandbox ledger" : "Base Sepolia testnet"}, scaled down${picked.length ? ` (${fmtUsdc(pickedNeed)})` : ""}. Always to the vendor master's wallet.` : "Coinbase isn't configured (CDP keys missing)"}>
              <span><Button size="xs" disabled={!picked.length || !tr.live} loading={busy} onClick={() => release(picked.map((r) => r.id), "coinbase")}>Coinbase · USDC</Button></span>
            </Tooltip>
          </Group>
        </Group>
      </Box>
    </Card>
  );
}
