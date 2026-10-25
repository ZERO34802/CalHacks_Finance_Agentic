// One bill, fitted to the window. A single header band runs across the top:
//   left   the queue you opened the bill from (same list and order as the Bills table), queue switch, search, Prev / Next (K / J)
//   top    vendor + invoice, amount, due, PO, vendor history, and the decision buttons (always visible, never scrolled away)
//   centre tabs: Review (verdict + failed checks, payment + approval chain + method, lines + 3-way match + GL coding),
//          Activity (timeline with the emails sent to the vendor inline), Agent trace (each step with what that agent found),
//          Ask ReconAI (chat, composer pinned)
//   right  the invoice as extracted, every document, the email received. Supplier text is UNTRUSTED: plain text only.
// After a decision the header offers the next bill in the queue, so the flow is: read why -> decide -> next.
import {
  ActionIcon, Anchor, Badge, Box, Button, Card, CloseButton, Group, Loader, Paper, ScrollArea, Select, SimpleGrid, Skeleton, Stack,
  Table, Tabs, Text, Textarea, TextInput, ThemeIcon, Timeline, Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconArrowLeft, IconCheck, IconCircleCheck, IconMail, IconSparkles, IconX } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ApprovalDecision, BillDetail, ChatMessage, OutboundEmail, PaymentBatch, ReviewPacket, Step } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, canRelease, day, due, findingColor, PEOPLE, RELEASE_RULE, shortName, STAGES, stage, stepColor, usd, when, type Seat } from "../format";
import { EmailCard, emailGist, EmailStatusBadge, emailStatus } from "../emails";
import { Avatarish, BILL_TABS, billQueue, CardHead, HEAD_BG, HEAD_BORDER, sortBills, StageBadge, symbols, tabOf } from "../parts";

const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

type Msg = ChatMessage & { source?: string };
type Pay = { method: string; date: string };
const METHOD: Record<string, string> = { ach: "ACH (direct deposit)", wire: "Domestic wire", intl_wire: "International wire (SWIFT)", check: "Check by mail" };
const H = "calc(100vh - 60px)";
const HEAD_H = 76, TABS_H = 40;          // header band: bill header + tab strips; the queue header spans both
const LINE = "1px solid var(--mantine-color-gray-3)";
const TAG: Record<string, string> = { processing: "New", needs_review: "Review", on_hold: "Hold", ready_to_pay: "Ready", blocked: "Blocked", scheduled: "Scheduled", paid: "Paid", rejected: "Rejected" };
const pendingQ: { current: string | null } = { current: null };
const typing = (e: KeyboardEvent) => ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey || e.altKey;

export default function BillPage({ id, tab: tabParam }: { id: string; tab?: string }) {
  const { lastEvent, refresh, go } = useApp();
  const [d, setD] = useState<BillDetail | null>(null);
  const [packet, setPacket] = useState<ReviewPacket | null>(null);
  const [tab, setTab] = useState<string>(tabParam === "ask" ? "ask" : "review");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [emails, setEmails] = useState<OutboundEmail[]>([]);
  const [pay, setPay] = useState<Pay | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const loadEmails = () => { ap.emails({ case_id: id }).then(setEmails).catch(() => setEmails([])); };
  const load = () => {
    ap.bill(id).then(setD).catch(() => setD(null));
    ap.review(id).then(setPacket).catch(() => setPacket(null));
    loadEmails();
  };
  useEffect(load, [id]);
  useEffect(() => { if (tabParam === "ask") setTab("ask"); }, [tabParam]);
  useEffect(() => { if (lastEvent?.case_id === id) load(); }, [lastEvent]);
  // payment method + date start from the bill (or the early-pay window) and are what "Approve & schedule" uses
  useEffect(() => {
    if (!d || pay) return;
    const off = d.bill.discount && ["available", "needs_approval"].includes(d.bill.discount.status) ? d.bill.discount : null;
    setPay({ method: d.bill.payment?.method ?? d.default_method ?? "ach", date: (d.bill.payment?.pay_date ?? off?.pay_by ?? d.est_pay_date ?? "").slice(0, 10) });
  }, [d]);
  const after = (text?: string) => { if (text) { setMsgs((m) => [...m, { role: "assistant", content: text, source: "system" }]); setDone(text); } load(); refresh(); };

  const q = useQueue(id);
  const idx = q.ids.indexOf(id);
  const prev = idx > 0 ? q.ids[idx - 1] : undefined;
  const next = idx >= 0 ? q.ids[idx + 1] : q.ids[0];
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (typing(e)) return;
      if (e.key.toLowerCase() === "k" && prev) go(`bill/${prev}`);
      if (e.key.toLowerCase() === "j" && next) go(`bill/${next}`);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [prev, next]);

  const ready = !!d && !!packet;
  const shown = new Set(emails.map((e) => e.id));
  const activityCount = d ? d.activity.filter((a) => !(emails.length && a.text.startsWith("Emailed "))).length + shown.size : 0;
  return (
    <Box style={{ display: "grid", gridTemplateColumns: "248px minmax(0, 1fr) minmax(0, 0.8fr)", gridTemplateRows: `${HEAD_H}px minmax(0, 1fr)`, height: H }}>
      <BillList id={id} q={q} idx={idx} prev={prev} next={next} />

      <Box px="lg" bg={HEAD_BG} style={{ gridColumn: "2 / 4", display: "flex", alignItems: "center", minWidth: 0 }}>
        {ready ? <BillHead d={d} done={done} next={next} queueTab={q.tab} onDismiss={() => setDone(null)}
          actions={<Actions d={d} pay={pay} onDone={after} />} /> : <HeadSkeleton />}
      </Box>

      {/* centre */}
      <Box style={{ display: "flex", flexDirection: "column", minHeight: 0, borderRight: LINE }}>
        <Tabs value={tab} onChange={(t) => setTab(t ?? "review")} bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER, flexShrink: 0 }}>
          <Tabs.List h={TABS_H} px="md" style={{ flexWrap: "nowrap" }}>
            <Tabs.Tab value="review">Review</Tabs.Tab>
            <Tabs.Tab value="activity" rightSection={ready ? <Badge size="xs" variant="light">{activityCount}</Badge> : null}>Activity</Tabs.Tab>
            <Tabs.Tab value="trace" rightSection={packet ? <Badge size="xs" variant="light">{packet.trace.filter((s) => !s.parent_id).length}</Badge> : null}>Agent trace</Tabs.Tab>
            <Tabs.Tab value="ask" leftSection={<IconSparkles size={14} />}>Ask ReconAI</Tabs.Tab>
          </Tabs.List>
        </Tabs>
        {!ready ? <BodySkeleton />
          : d.bill.stage === "processing" ? <ScrollArea style={{ flex: 1 }} p="lg"><Running packet={packet} /></ScrollArea>
            : tab === "ask" ? <Chat id={id} packet={packet} msgs={msgs} setMsgs={setMsgs} />
              : (
                <ScrollArea style={{ flex: 1 }} type="auto">
                  <Box p="lg">
                    {tab === "review" ? <Review d={d} packet={packet} emails={emails} pay={pay} setPay={setPay} openTab={setTab} onAsk={(x) => { pendingQ.current = x; setTab("ask"); }} />
                      : tab === "activity" ? <Activity id={id} d={d} emails={emails} reload={loadEmails} />
                        : <Trace packet={packet} />}
                  </Box>
                </ScrollArea>
              )}
      </Box>

      <DocPane packet={packet} d={d} />
    </Box>
  );
}

/* the queue: the list the bill was opened from (snapshot), else the lifecycle tab the bill is in */
type Queue = { tab: string; ids: string[]; setTab: (t: string) => void };
function useQueue(id: string): Queue {
  const { bills } = useApp();
  const [qtab, setQtab] = useState(() => (billQueue.ids.includes(id) ? billQueue.tab : ""));
  const cur = bills.find((b) => b.case_id === id);
  const t = qtab || (cur ? tabOf(cur.stage) : "");
  const ids = useMemo(() => {
    if (!t) return [];
    if (billQueue.tab === t && billQueue.ids.includes(id)) return billQueue.ids;
    return sortBills(bills.filter((b) => BILL_TABS[t].stages.includes(b.stage))).map((b) => b.case_id);
  }, [t, bills, id]);
  useEffect(() => { if (t && ids.length) { billQueue.tab = t; billQueue.ids = ids; if (!qtab) setQtab(t); } }, [t, ids]);
  return { tab: t, ids, setTab: setQtab };
}

/* left: the queue */
function BillList({ id, q, idx, prev, next }: { id: string; q: Queue; idx: number; prev?: string; next?: string }) {
  const { bills, go } = useApp();
  const [s, setS] = useState("");
  const n = s.trim().toLowerCase();
  const byId = useMemo(() => new Map(bills.map((b) => [b.case_id, b])), [bills]);
  const rows = q.ids.map((x) => byId.get(x)).filter((b) => !!b && (!n || `${b.vendor_name} ${b.invoice_no}`.toLowerCase().includes(n)));
  const multi = new Set(rows.map((b) => b!.stage)).size > 1;
  const active = useRef<HTMLDivElement>(null);
  useEffect(() => { active.current?.scrollIntoView({ block: "nearest" }); }, [q.ids.length]);
  return (
    <Box bg="gray.0" style={{ gridRow: "1 / 3", display: "flex", flexDirection: "column", borderRight: LINE, minHeight: 0 }}>
      <Stack gap={8} px="sm" justify="center" h={HEAD_H + TABS_H} bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER, flexShrink: 0 }}>
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Anchor fz="sm" fw={500} onClick={() => go(q.tab && q.tab !== "overview" ? `bills/${q.tab}` : "bills")}><Group gap={4} wrap="nowrap"><IconArrowLeft size={14} />Bills</Group></Anchor>
          <Select size="xs" w={140} allowDeselect={false} value={q.tab || null} onChange={(v) => v && q.setTab(v)} aria-label="Queue" comboboxProps={{ withinPortal: true }}
            data={Object.entries(BILL_TABS).map(([k, t]) => ({ value: k, label: `${k === "overview" ? "All bills" : t.label} · ${bills.filter((b) => t.stages.includes(b.stage)).length}` }))} />
        </Group>
        <TextInput size="xs" placeholder="Search this list" value={s} onChange={(e) => setS(e.currentTarget.value)} />
      </Stack>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Box py={6}>
          {rows.map((b) => b && (
            <Box key={b.case_id} ref={b.case_id === id ? active : undefined} px="sm" py={7} mx={6} bg={b.case_id === id ? "brand.0" : undefined}
              style={{ cursor: "pointer", borderRadius: 6, borderLeft: `3px solid ${b.case_id === id ? "var(--mantine-color-brand-6)" : "transparent"}` }}
              onClick={() => go(`bill/${b.case_id}`)}>
              <Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} size={24} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Group gap={4} wrap="nowrap"><Text fz="sm" fw={500} truncate style={{ flex: 1 }}>{shortName(b.vendor_name)}</Text>
                    {b.risk === "high" && <IconAlertTriangle size={13} color="var(--mantine-color-red-6)" style={{ flexShrink: 0 }} />}</Group>
                  <Group gap={4} wrap="nowrap" justify="space-between">
                    <Text fz="xs" c="dimmed" truncate>{b.amount ? `${amount(b.payable ?? b.amount, b.currency)} · ${day(b.due_date).replace(/, \d{4}$/, "")}` : "not read"}</Text>
                    {multi && <Text fz={10} fw={600} c={`${STAGES[b.stage]?.color ?? "gray"}.7`} style={{ flexShrink: 0 }}>{TAG[b.stage] ?? STAGES[b.stage]?.label}</Text>}
                  </Group>
                </div>
              </Group>
            </Box>
          ))}
          {!rows.length && <Text fz="sm" c="dimmed" px="sm" py="md">Nothing here.</Text>}
        </Box>
      </ScrollArea>
      <Group justify="space-between" px="sm" py={8} style={{ borderTop: LINE }} wrap="nowrap">
        <Button size="compact-sm" variant="subtle" disabled={!prev} onClick={() => prev && go(`bill/${prev}`)}>Prev <Badge ml={6} size="xs" variant="default">K</Badge></Button>
        <Text fz="xs" c="dimmed">{idx >= 0 ? `${idx + 1} / ${q.ids.length}` : `${q.ids.length}`}</Text>
        <Button size="compact-sm" variant="subtle" disabled={!next} onClick={() => next && go(`bill/${next}`)}>Next <Badge ml={6} size="xs" variant="default">J</Badge></Button>
      </Group>
    </Box>
  );
}

/* top: who, what, how much, when, and the decision */
function BillHead({ d, actions, done, next, queueTab, onDismiss }: { d: BillDetail; actions: ReactNode; done: string | null; next?: string; queueTab: string; onDismiss: () => void }) {
  const { go } = useApp();
  const b = d.bill;
  const split = b.payable && b.payable !== b.amount;
  const meta = [b.po_number, b.invoice_date && `Invoiced ${day(b.invoice_date)}`, b.due_date && `Due ${day(b.due_date)} (${due(b.days_to_due)})`,
    d.last_paid ? `Last paid ${amount(d.last_paid.amount, d.last_paid.currency)} on ${day(d.last_paid.paid_on)}` : "First bill from this vendor"].filter(Boolean).join(" · ");
  return (
    <Group justify="space-between" wrap="nowrap" gap="lg" w="100%">
      <div style={{ minWidth: 0, flex: 1 }}>
        <Text fz={21} fw={650} lh={1.2} truncate>{shortName(b.vendor_name)} {b.invoice_no ? `· ${b.invoice_no}` : `· ${b.case_id}`}</Text>
        <Group gap={8} wrap="nowrap" mt={4}>
          <StageBadge stage={b.stage} />
          <Text fz="xs" c="dimmed" truncate>{meta} · <Anchor fz="xs" onClick={() => go(`vendors/${b.vendor_id}`)}>Vendor</Anchor></Text>
        </Group>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <Text fz={21} fw={650} ff="monospace" lh={1.2}>{b.amount ? amount(b.amount, b.currency) : "—"}</Text>
        <Text fz="xs" c="dimmed">{split ? `pay ${amount(b.payable, b.currency)} · ${amount(b.disputed, b.currency)} held` : b.currency && b.currency !== "USD" ? `≈ ${usd(b.amount_usd)}` : " "}</Text>
      </div>
      <Box style={{ flexShrink: 0 }}>
        {done ? (
          <Group gap="xs" wrap="nowrap">
            <IconCircleCheck size={18} color="var(--mantine-color-brand-7)" style={{ flexShrink: 0 }} />
            <Tooltip label={done} multiline w={320}><Text fz="sm" truncate maw={260}>{done}</Text></Tooltip>
            {next ? <Button size="sm" onClick={() => go(`bill/${next}`)} rightSection={<Badge size="xs" variant="white">J</Badge>}>Next bill</Button>
              : <Button size="sm" variant="default" onClick={() => go(queueTab && queueTab !== "overview" ? `bills/${queueTab}` : "bills")}>Back to Bills</Button>}
            <CloseButton size="sm" onClick={onDismiss} aria-label="Show this bill's actions" />
          </Group>
        ) : actions}
      </Box>
    </Group>
  );
}

function HeadSkeleton() {
  return (
    <Group justify="space-between" w="100%" wrap="nowrap">
      <div style={{ flex: 1 }}><Skeleton h={24} w="45%" /><Skeleton h={12} w="65%" mt={8} /></div>
      <Skeleton h={24} w={150} /><Skeleton h={36} w={300} />
    </Group>
  );
}
function BodySkeleton() {
  return (
    <Box p="lg" style={{ flex: 1 }}>
      <Skeleton h={200} radius="md" />
      <Skeleton h={220} mt="md" radius="md" />
      <Skeleton h={120} mt="md" radius="md" />
    </Box>
  );
}

/* centre: review */
const VERDICT = {
  ready: { title: "Ready to approve", color: "brand", icon: <IconCircleCheck size={18} /> },
  review: { title: "Review recommended", color: "orange", icon: <IconAlertTriangle size={18} /> },
  risk: { title: "Higher risk of fraud", color: "red", icon: <IconAlertTriangle size={18} /> },
} as const;

function Review({ d, packet, emails, pay, setPay, openTab, onAsk }: {
  d: BillDetail; packet: ReviewPacket; emails: OutboundEmail[]; pay: Pay | null; setPay: (p: Pay) => void; openTab: (t: string) => void; onAsk: (q: string) => void;
}) {
  const b = d.bill, cur = b.currency;
  const vd = VERDICT[d.verdict as keyof typeof VERDICT] ?? VERDICT.review;
  const failed = d.checks.filter((c) => !c.passed), passed = d.checks.filter((c) => c.passed);
  const [showAll, setShowAll] = useState(false);
  const sent = emails.filter((e) => e.kind === "supplier_discrepancy").at(-1);
  const lead = !b.invoice_no && b.warning ? symbols(b.warning) : !failed.length ? symbols(d.verdict_text) : null;
  return (
    <Stack gap="md">
      <Card withBorder padding="md" style={{ borderColor: d.verdict === "risk" ? "var(--mantine-color-red-4)" : undefined }}>
        <CardHead mb="sm" title={<Group gap={8} wrap="nowrap" c={`${vd.color}.8`}>{vd.icon}<span>{vd.title}</span></Group>}
          right={<Anchor fz="sm" onClick={() => openTab("trace")} style={{ whiteSpace: "nowrap" }}>How the agents got here</Anchor>} />
        <Stack gap={8}>
          {lead && <Text fz="sm">{lead}</Text>}
          {failed.map((c) => (
            <Group key={c.name} gap={8} wrap="nowrap" align="flex-start">
              <IconX size={16} color={`var(--mantine-color-${c.severity === "high" ? "red" : "orange"}-7)`} style={{ marginTop: 2, flexShrink: 0 }} />
              <div><Text fz="sm" fw={600}>{c.name}</Text><Text fz="sm" c="dimmed" component="div">{symbols(c.detail)} <Refs refs={c.refs} /></Text></div>
            </Group>
          ))}
          {b.disagreements.map((x) => <Line key={x} color="orange.8" icon={<IconAlertTriangle size={15} />}>Second-line check: {symbols(x)}</Line>)}
          {b.payable && b.payable !== b.amount && <Line color="blue.8" icon={<IconCheck size={15} />}>
            Paying the clean {amount(b.payable, cur)}; {amount(b.disputed, cur)} held until the vendor credits or corrects it{b.sub_case_ids.length ? ` (${b.sub_case_ids.join(", ")})` : ""}.</Line>}
          {d.verdict === "risk" && <Text fz="sm" fw={600} c="red.8">Call the vendor on the number in the vendor master, never the one on the invoice or email, before paying.</Text>}
          {sent && (
            <Group gap={6} wrap="nowrap" style={{ cursor: "pointer" }} onClick={() => openTab("activity")}>
              <IconMail size={15} color={`var(--mantine-color-${emailStatus(sent).color}-7)`} style={{ flexShrink: 0 }} />
              <Text fz="sm" truncate>{sent.status === "sent" ? "Emailed" : sent.status === "failed" ? "Email failed to" : "Queued email to"} {sent.to} · {emailGist(sent)}</Text>
              <Anchor fz="sm" style={{ flexShrink: 0 }}>View</Anchor>
            </Group>
          )}
          {passed.length > 0 && (
            <div>
              <Anchor fz="sm" onClick={() => setShowAll((x) => !x)}><Group gap={6} wrap="nowrap"><IconCheck size={15} />{passed.length} check{passed.length > 1 ? "s" : ""} passed{showAll ? "" : ": show"}</Group></Anchor>
              {showAll && <Stack gap={3} mt={6} pl={21}>{passed.map((c) => <Text key={c.name} fz="sm" component="div">{c.name} <Refs refs={c.refs} /></Text>)}</Stack>}
            </div>
          )}
          <Group gap={6}>{packet.suggested.slice(0, 2).map((x) => <Button key={x} size="compact-xs" variant="light" leftSection={<IconSparkles size={12} />} onClick={() => onAsk(x)}>{x}</Button>)}</Group>
        </Stack>
      </Card>

      <PaymentCard d={d} pay={pay} setPay={setPay} />

      {d.gl.length > 0 && (
        <Card withBorder padding={0}>
          <CardHead px="md" mb={0} title="Lines" right={<Text fz="xs" c="dimmed">3-way match · invoice, {b.po_number ?? "PO"}, receipt</Text>} />
          <Table fz="sm" verticalSpacing={8} horizontalSpacing="md">
            <Table.Thead><Table.Tr>
              <Table.Th><Text fz="xs" fw={600} c="dimmed" tt="uppercase">Item · GL account</Text></Table.Th>
              <Table.Th ta="right"><Text fz="xs" fw={600} c="dimmed" tt="uppercase">Ord · rec · billed</Text></Table.Th>
              <Table.Th ta="right"><Text fz="xs" fw={600} c="dimmed" tt="uppercase">Unit</Text></Table.Th>
              <Table.Th ta="right"><Text fz="xs" fw={600} c="dimmed" tt="uppercase">Amount</Text></Table.Th>
            </Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.gl.map((g) => {
                const m = d.match.find((r) => r.sku === g.sku);
                const risk = m && Number(m.amount_at_risk) > 0;
                const pv = m?.po_price && m.price_variance && Number(m.price_variance) !== 0;
                return (
                  <Table.Tr key={g.line_no}>
                    <Table.Td><Text fz="sm" fw={500}>{g.description}</Text>
                      <Tooltip label={g.basis} disabled={!g.basis}><Text fz="xs" c="dimmed" ff="monospace">{g.sku} · <IconSparkles size={11} color="var(--mantine-color-brand-6)" /> {g.account}</Text></Tooltip></Table.Td>
                    <Table.Td ta="right"><Text fz="sm" ff="monospace" c={risk ? "red.7" : undefined}>
                      {m ? `${m.ordered == null ? "not on PO" : Number(m.ordered).toLocaleString()} · ${Number(m.received).toLocaleString()} · ${Number(m.billed).toLocaleString()}` : "—"}</Text></Table.Td>
                    <Table.Td ta="right"><Text fz="sm" ff="monospace">{m ? amount(m.invoice_price, cur) : "—"}</Text>
                      {pv && <Text fz="xs" c="red.7">PO {amount(m.po_price, cur)}</Text>}</Table.Td>
                    <Table.Td ta="right"><Text fz="sm" ff="monospace" fw={600}>{amount(g.amount, cur)}</Text>
                      {risk && <Text fz="xs" c="red.7">{amount(m.amount_at_risk, cur)} at risk</Text>}</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}

const Line = ({ color, icon, children }: { color: string; icon: ReactNode; children: ReactNode }) => (
  <Group gap={8} wrap="nowrap" align="flex-start" c={color}><Box mt={2} style={{ flexShrink: 0 }}>{icon}</Box><Text fz="sm" c={color}>{children}</Text></Group>
);

function Refs({ refs }: { refs: string[] }) {
  return <>{refs.slice(0, 4).map((r) => <Badge key={r} size="xs" variant="default" ml={4} tt="none">{r}</Badge>)}</>;
}

/* payment: where it stands (approval chain -> release -> paid), and how it will be paid */
function PaymentCard({ d, pay, setPay }: { d: BillDetail; pay: Pay | null; setPay: (p: Pay) => void }) {
  const { vendors } = useApp();
  const b = d.bill, v = vendors[b.vendor_id], s = b.stage;
  const locked = !!b.payment || ["paid", "rejected"].includes(s);
  const off = b.discount && ["available", "needs_approval"].includes(b.discount.status) ? b.discount : null;
  const steps = d.approval_steps;
  const active = s === "paid" ? steps.length : Math.max(0, steps.findIndex((x) => x.status !== "done"));
  const waiting = steps[active];
  const label: Record<string, string> = { needs_review: "Awaiting approval", on_hold: "On hold", blocked: "Payment blocked", ready_to_pay: "Approved, not scheduled",
    scheduled: `Scheduled for ${day(b.payment?.pay_date ?? d.est_pay_date)}`, rejected: "Rejected", processing: "Processing", failed: "Payment failed",
    paid: b.payment?.rail === "coinbase" ? `Paid via Coinbase${b.payment.network === "sandbox" ? " (sandbox)" : " (testnet)"}` : "Paid (simulated bank)" };
  const inWindow = off && pay?.date && pay.date <= off.pay_by;
  const mismatch = d.invoice_bank_last4 && d.invoice_bank_last4 !== v?.bank_last4;
  return (
    <Card withBorder padding="md">
      <CardHead mb="sm" title="Payment" right={<Text fz="sm" fw={600} c={s === "blocked" || s === "rejected" ? "red.7" : "brand.8"}>{label[s] ?? s}</Text>} />
      <Group gap={8} wrap="nowrap" mb={8}>
        {steps.map((x, i) => {
          const ok = s === "paid" || x.status === "done", bad = x.status === "rejected" || (i === active && s === "blocked");
          return (
            <Group key={x.step} gap={8} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
              <ThemeIcon size={22} radius="xl" variant={ok ? "filled" : "light"} color={bad ? "red" : ok || i === active ? "brand" : "gray"} style={{ flexShrink: 0 }}>
                {ok ? <IconCheck size={13} /> : <Text fz={11} fw={600}>{x.step}</Text>}</ThemeIcon>
              <Tooltip label={x.who} disabled={!x.who}><div style={{ minWidth: 0 }}><Text fz="xs" fw={600} truncate c={i === active && s !== "paid" ? "brand.8" : undefined}>{x.label}</Text>
                <Text fz={10} c="dimmed" truncate>{x.who}</Text></div></Tooltip>
              {i < steps.length - 1 && <Box style={{ flex: 1, minWidth: 12, height: 1, background: "var(--mantine-color-gray-3)" }} />}
            </Group>
          );
        })}
      </Group>
      {waiting?.note && s !== "paid" && <Text fz="xs" c="dimmed" mb={6}>{symbols(waiting.note)}</Text>}
      {(s === "ready_to_pay" || s === "scheduled") && <Text fz="xs" c="dimmed" mb={6}>{RELEASE_RULE}</Text>}
      {b.payment_block && <Line color="red.8" icon={<IconAlertTriangle size={15} />}>{symbols(b.payment_block)}</Line>}
      {off && !locked && <Line color="brand.8" icon={<IconSparkles size={15} />}>
        Pay by {day(off.pay_by)} to save {amount(off.discount_amount, off.currency)} ({off.terms}, ≈{off.annualized_return_pct}%/yr){inWindow ? ": the date below is in the window" : ": the date below misses it"}</Line>}
      {b.payment && Number(b.payment.discount_amount) > 0 && <Line color="brand.8" icon={<IconCheck size={15} />}>Early-payment discount captured: {amount(b.payment.discount_amount, b.currency)}</Line>}
      {b.payment && Number(b.payment.credit_applied) > 0 && <Line color="blue.8" icon={<IconCheck size={15} />}>Prepaid credit applied {amount(b.payment.credit_applied, b.currency)} · cash {amount(b.payment.amount, b.currency)}</Line>}
      {!b.payment && b.credit_available && <Line color="blue.8" icon={<IconCheck size={15} />}>{amount(b.credit_available, b.currency)} prepaid credit is applied when scheduled</Line>}
      <SimpleGrid cols={2} spacing="sm" verticalSpacing={8} mt="sm">
        <Select size="xs" label="Method" value={pay?.method ?? null} onChange={(x) => x && pay && setPay({ ...pay, method: x })} disabled={locked} allowDeselect={false}
          data={Object.entries(METHOD).map(([k, l]) => ({ value: k, label: l, disabled: !d.pay_methods.includes(k) }))} />
        <TextInput size="xs" type="date" label="Payment date" value={pay?.date ?? ""} onChange={(e) => pay && setPay({ ...pay, date: e.currentTarget.value })} disabled={locked} />
        <TextInput size="xs" label="From" value="Helix operating •••• 0042 (simulated)" readOnly />
        <TextInput size="xs" label="To (vendor master)" value={`•••• ${v?.bank_last4 ?? "—"}`} readOnly
          error={mismatch ? `Not •••• ${d.invoice_bank_last4} printed on the invoice` : undefined} />
      </SimpleGrid>
      <Textarea size="xs" mt={8} label="Memo on the vendor's statement" value={d.statement_descriptor} readOnly autosize minRows={1} />
    </Card>
  );
}

/* top right: the decision for this stage */
function Actions({ d, pay, onDone }: { d: BillDetail; pay: Pay | null; onDone: (text?: string) => void }) {
  const { seat } = useApp();
  const b = d.bill, who = me(seat);
  const [busy, setBusy] = useState<string | null>(null);
  const [run, setRun] = useState<PaymentBatch | null>(null);
  useEffect(() => {
    if (b.payment) ap.runs().then((rs) => setRun(rs.find((r) => r.id === b.payment!.batch_id) ?? null)).catch(() => {});
    else setRun(null);
  }, [b.payment?.batch_id, b.payment?.status]);
  const releaser = canRelease(who.role);
  const top = (x: string) => x === "cfo" || x === "cto";   // the CTO has the CFO's authority
  const canSign = (b.needs === seat || (top(b.needs) && top(seat))) && !!b.invoice_no;   // nothing to approve when no invoice was read
  const fail = (e: unknown, title: string) => notifications.show({ color: "red", title, message: e instanceof Error ? e.message : String(e) });

  const decide = async (dec: ApprovalDecision) => {
    setBusy(dec);
    try {
      await ap.decide(b.case_id, { approver: who.email, role: who.role, decision: dec, comment: "", scope: null });
      const text = dec === "rejected" ? `Rejected by ${who.name}. Nothing will be paid.` : `Put on hold by ${who.name}. Nothing is paid until it's resolved.`;
      notifications.show({ color: dec === "rejected" ? "red" : "yellow", title: "Recorded", message: text }); onDone(text);
    } catch (e) { fail(e, "Not allowed"); } finally { setBusy(null); }
  };
  const schedule = async (approveFirst: boolean, releaseRail?: "coinbase") => {
    setBusy(releaseRail ? "approve_release" : "schedule");
    try {
      let cur = b;
      if (approveFirst) {
        await ap.decide(b.case_id, { approver: who.email, role: who.role, decision: "approved", comment: "", scope: null });
        cur = (await ap.bill(b.case_id)).bill;   // the Poster booked it (or refused): read the result
      }
      if (cur.stage !== "ready_to_pay") {
        const why = symbols(cur.payment_block ?? cur.warning ?? "not payable yet");
        notifications.show({ color: "orange", title: "Approved, but not payable yet", message: why });
        onDone(`Approved by ${who.name}. Not scheduled: ${why}`); return;
      }
      const todayIso = new Date().toISOString().slice(0, 10);
      const r = await ap.createRun([b.case_id], releaseRail ? todayIso : pay?.date || todayIso, who.email,
        { [b.case_id]: pay?.method ?? d.default_method ?? "ach" });
      if (releaseRail) { await release(releaseRail, r); return; }
      const text = `${approveFirst ? `Approved by ${who.name} and s` : "S"}cheduled in ${r.id} for ${day(r.pay_date)}. ${releaser ? "You can release it when it's due." : "A controller, CFO or CTO releases it."}`;
      notifications.show({ color: "brand", title: "Scheduled", message: text }); onDone(text);
    } catch (e) { fail(e, releaseRail ? "Couldn't approve & release" : approveFirst ? "Couldn't approve & schedule" : "Couldn't schedule"); onDone(); } finally { setBusy(null); }
  };
  const release = async (rail: "bank" | "coinbase", target: PaymentBatch | null = run) => {
    if (!target) return;
    setBusy(rail);
    try {
      const r = await ap.release(target.id, who.email, rail, who.role);
      const p = r.payments.find((x) => x.case_id === b.case_id);
      const t = rail === "coinbase"
        ? (p?.status === "paid" ? `Released by ${who.name} via Coinbase: ${p.onchain_amount} USDC sent to ${short(p.payee_address)}${p.network === "sandbox" ? " (sandbox, simulated)" : ""} · tx ${short(p.tx_hash)}.`
          : `Coinbase transfer failed: ${p?.error ?? "see Bills → For payment"}. Retry from Bills → For payment.`)
        : `Released by ${who.name}. Paid (simulated bank transfer).`;
      notifications.show({ color: p?.status === "paid" || rail === "bank" ? "green" : "red", title: p?.status === "failed" ? "Not paid" : "Paid", message: t, autoClose: 9000 });
      onDone(t);
    } catch (e) { fail(e, rail === "coinbase" ? "Can't release via Coinbase" : "Can't release"); onDone(); } finally { setBusy(null); }
  };

  let note: ReactNode = null, buttons: ReactNode = null;
  if (b.stage === "needs_review" || b.stage === "on_hold") {
    note = `Needs ${PEOPLE[b.needs as Seat]?.title ?? b.needs} · you're ${who.title}${b.waiting_hours != null ? ` · ${b.waiting_hours}h of 24h SLA` : ""}`;
    buttons = <>
      <Button variant="default" loading={busy === "ask"} onClick={() => decide("ask")}>Hold</Button>
      <Button variant="outline" color="red" leftSection={<IconX size={15} />} loading={busy === "rejected"} onClick={() => decide("rejected")}>Reject</Button>
      <Tooltip label={!b.invoice_no ? "No invoice was read: reject, or ask the vendor to resend." : `Approval needs the ${PEOPLE[b.needs as Seat]?.title}. Switch person (top right).`} disabled={canSign}>
        <Button variant={releaser ? "default" : "filled"} disabled={!canSign} loading={busy === "schedule"} leftSection={<IconCheck size={16} />} onClick={() => schedule(true)}>Approve & schedule</Button>
      </Tooltip>
      {releaser && canSign && <Tooltip label="Approve, schedule for today and release on Coinbase in one step (you have release authority)">
        <Button loading={busy === "approve_release" || busy === "coinbase"} leftSection={<IconCheck size={16} />} onClick={() => schedule(true, "coinbase")}>Approve & release via Coinbase</Button>
      </Tooltip>}</>;
  } else if (b.stage === "ready_to_pay") {
    note = `Approved by ${b.approved_by}`;
    buttons = <Button loading={busy === "schedule"} onClick={() => schedule(false)}>Schedule payment</Button>;
  } else if (b.stage === "blocked") {
    note = <Text span fz="xs" c="red.7">Blocked by the payment guard</Text>;
    buttons = <><Button variant="default" loading={busy === "ask"} onClick={() => decide("ask")}>Hold & verify</Button>
      <Button variant="outline" color="red" leftSection={<IconX size={15} />} loading={busy === "rejected"} onClick={() => decide("rejected")}>Reject</Button></>;
  } else if (b.stage === "scheduled") {
    note = !run ? "Scheduled" : releaser ? `${run.id} · scheduled by ${run.created_by.split("@")[0]}` : "Needs a controller, CFO or CTO to release";
    buttons = <Tooltip label={RELEASE_RULE} disabled={releaser}>
      <Group gap="xs" wrap="nowrap">
        <Button variant="default" disabled={!releaser || !run} loading={busy === "bank"} onClick={() => release("bank")}>Release · bank (simulated)</Button>
        <Button disabled={!releaser || !run} loading={busy === "coinbase"} onClick={() => release("coinbase")}>Release · USDC</Button>
      </Group></Tooltip>;
  } else if (b.stage === "paid") {
    const pm = b.payment;
    note = pm?.rail === "coinbase"
      ? <>Paid via Coinbase · {pm.onchain_amount} USDC → {short(pm.payee_address)} · tx {pm.explorer_url
          ? <Anchor href={pm.explorer_url} target="_blank" fz="xs">{short(pm.tx_hash)}</Anchor> : short(pm.tx_hash)}{pm.network === "sandbox" ? " (sandbox, simulated)" : " · Base Sepolia testnet"}</>
      : <>Paid {pm && day(pm.pay_date)} · {pm && METHOD[pm.method]} → •••• {pm?.pay_to_last4} (simulated)</>;
  } else if (b.stage === "rejected") {
    note = "Rejected. Nothing will be paid.";
  }
  return (
    <Stack gap={4} align="flex-end">
      {buttons && <Group gap="xs" wrap="nowrap">{buttons}</Group>}
      {note && <Text fz={buttons ? "xs" : "sm"} c="dimmed" truncate maw={460} component="div">{note}</Text>}
    </Stack>
  );
}

/* centre: other tabs */
function Running({ packet }: { packet: ReviewPacket }) {
  const top = packet.trace.filter((s) => !s.parent_id);
  return (
    <Card withBorder padding="lg">
      <Group mb="md"><Loader size="sm" /><Text fw={600}>ReconAI is reconciling this invoice</Text></Group>
      <Timeline active={top.length - 1} bulletSize={22}>{top.map((s, i) => <Timeline.Item key={s.id} title={stepName(s.stage)} bullet={<Text fz={10}>{i + 1}</Text>}><Text c="dimmed" fz="xs">{s.status}</Text></Timeline.Item>)}</Timeline>
    </Card>
  );
}

/* activity: one timeline, the emails sent to the vendor inline where they happened */
function Activity({ id, d, emails, reload }: { id: string; d: BillDetail; emails: OutboundEmail[]; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [openIds, setOpenIds] = useState<string[]>([]);
  const retry = async () => {
    setBusy(true);
    try {
      const out = await ap.sendCaseEmails(id);
      const ok = out.filter((e) => e.status === "sent").length;
      notifications.show({ color: ok === out.length ? "green" : "orange", title: "Delivery retried", message: `${ok} of ${out.length} sent` });
      reload();
    } catch (e) { notifications.show({ color: "red", title: "Couldn't retry", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(false); }
  };
  const items = [
    ...d.activity.filter((a) => !(emails.length && a.text.startsWith("Emailed "))).map((a) => ({ at: a.at, a, e: null as OutboundEmail | null })),
    ...emails.map((e) => ({ at: e.created_at, a: null, e })),
  ].sort((x, y) => x.at.localeCompare(y.at));
  return (
    <Stack gap="md">
      {emails.some((e) => e.status !== "sent") && (
        <Group justify="space-between"><Text fz="sm" c="orange.8">An email to the vendor wasn't delivered.</Text>
          <Button size="compact-sm" variant="light" loading={busy} onClick={retry}>Retry delivery</Button></Group>
      )}
      <Timeline active={items.length} bulletSize={18} lineWidth={2}>
        {items.map((it, i) => it.e ? (
          <Timeline.Item key={it.e.id} bullet={<IconMail size={11} />}
            title={<Group gap={6} wrap="nowrap"><Text fz="sm" truncate>Emailed {it.e.to}: {emailGist(it.e)}</Text><EmailStatusBadge e={it.e} /></Group>}>
            <Text fz="xs" c="dimmed">ReconAI · {when(it.e.created_at)} · always to the contact on file ·{" "}
              <Anchor fz="xs" onClick={() => setOpenIds((o) => (o.includes(it.e!.id) ? o.filter((x) => x !== it.e!.id) : [...o, it.e!.id]))}>{openIds.includes(it.e.id) ? "hide" : "read"}</Anchor></Text>
            {openIds.includes(it.e.id) && <Box mt={6}><EmailCard e={it.e} /></Box>}
          </Timeline.Item>
        ) : (
          <Timeline.Item key={i} title={<Text fz="sm">{symbols(it.a!.text)}</Text>}><Text fz="xs" c="dimmed">{it.a!.actor} · {when(it.a!.at)}</Text></Timeline.Item>
        ))}
      </Timeline>
    </Stack>
  );
}

const stepName = (st: string) => {
  const l = stage(st);
  return l !== st ? l : (st.split(".").pop() ?? st).replace(/^a_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
};

/* agent trace: every step in order, with what that agent concluded inline (no second list telling the same story) */
function Trace({ packet }: { packet: ReviewPacket }) {
  const [open, setOpen] = useState<string[]>([]);
  const top = packet.trace.filter((s) => !s.parent_id);
  const kids = (s: Step) => packet.trace.filter((x) => x.parent_id === s.id);
  const used = new Set<number>();
  const found = new Map(top.map((s) => {
    const i = packet.findings.findIndex((f, j) => !used.has(j) && f.agent === stage(s.stage));
    if (i >= 0) used.add(i);
    return [s.id, i >= 0 ? packet.findings[i] : null] as const;
  }));
  const rest = packet.findings.filter((_, j) => !used.has(j));
  const tech = (s: Step) => Object.entries(s.detail).filter(([k]) => k !== "stub").map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ").slice(0, 900);
  return (
    <Timeline active={top.length + rest.length} bulletSize={22} lineWidth={2}>
      {top.map((s, i) => {
        const f = found.get(s.id), t = tech(s), ks = kids(s);
        return (
          <Timeline.Item key={s.id} color={stepColor(s.status)} bullet={<Text fz={10}>{i + 1}</Text>}
            title={<Group gap={6} wrap="nowrap" justify="space-between">
              <Group gap={6} wrap="nowrap"><Text fz="sm" fw={600}>{stepName(s.stage)}</Text>
                {s.status !== "ok" && <Badge size="xs" variant="light" color={stepColor(s.status)}>{s.status}</Badge>}
                {f && f.status !== "ok" && <Badge size="xs" variant="light" color={findingColor(f.status)}>{f.status === "unchecked" ? "not checked" : f.status}</Badge>}
                {s.detail.stub === true && <Badge size="xs" variant="outline" color="gray">placeholder</Badge>}</Group>
              <Text fz="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{s.skill ? `${s.skill}@${s.skill_version} · ` : ""}{s.duration_ms ?? "…"} ms</Text>
            </Group>}>
            {f && <Text fz="sm" c={f.status === "flag" ? "red.8" : undefined}><b>{f.check}:</b> {symbols(f.detail)}</Text>}
            {s.error && <Text fz="xs" c="red.7">{s.error}</Text>}
            {ks.length > 0 && <Text fz="xs" c="dimmed">↳ {ks.map((k) => `${stepName(k.stage)} (${k.status})`).join(", ")}</Text>}
            {t && <Anchor fz="xs" onClick={() => setOpen((o) => (o.includes(s.id) ? o.filter((x) => x !== s.id) : [...o, s.id]))}>{open.includes(s.id) ? "Hide details" : "Details"}</Anchor>}
            {open.includes(s.id) && <Text fz="xs" ff="monospace" c="dimmed" style={{ wordBreak: "break-word" }}>{s.role} · {t}</Text>}
          </Timeline.Item>
        );
      })}
      {rest.map((f, i) => (
        <Timeline.Item key={`r${i}`} color={findingColor(f.status)} bullet={<Text fz={10}>•</Text>}
          title={<Group gap={6}><Text fz="sm" fw={600}>{f.agent}</Text>{f.status !== "ok" && <Badge size="xs" variant="light" color={findingColor(f.status)}>{f.status}</Badge>}</Group>}>
          <Text fz="sm" c={f.status === "flag" ? "red.8" : undefined}><b>{f.check}:</b> {symbols(f.detail)}</Text>
        </Timeline.Item>
      ))}
    </Timeline>
  );
}

/* ask: messages scroll, the composer stays pinned */
function Chat({ id, packet, msgs, setMsgs }: { id: string; packet: ReviewPacket; msgs: Msg[]; setMsgs: (f: (m: Msg[]) => Msg[]) => void }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (msgs.length || busy) end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length, busy]);
  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    const history = [...msgs.filter((m) => m.source !== "system"), { role: "user", content: q.trim() }].map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: q.trim() }]); setDraft(""); setBusy(true);
    try { const r = await ap.chat(id, history); setMsgs((m) => [...m, { role: "assistant", content: r.content, source: r.source }]); }
    catch (e) { setMsgs((m) => [...m, { role: "assistant", content: `Couldn't answer: ${e}`, source: "error" }]); } finally { setBusy(false); }
  };
  useEffect(() => { if (pendingQ.current) { const q = pendingQ.current; pendingQ.current = null; ask(q); } }, []);
  return (
    <>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack gap="md" p="lg">
          <Paper withBorder p="md" radius="lg"><Group gap={6} mb={6}><IconSparkles size={16} color="var(--mantine-color-brand-6)" /><Text fw={600} fz="sm">ReconAI</Text>
            <Text fz="xs" c="dimmed">answers from this bill's record only</Text></Group><Text fz="sm">{symbols(packet.summary)}</Text>
            <Group gap={6} mt="sm">{packet.suggested.map((q) => <Button key={q} size="compact-xs" variant="light" onClick={() => ask(q)}>{q}</Button>)}</Group></Paper>
          {msgs.map((m, i) => m.role === "user"
            ? <Group key={i} justify="flex-end"><Paper bg="brand.0" px="md" py="xs" radius="lg" maw="80%"><Text fz="sm">{m.content}</Text></Paper></Group>
            : <Paper key={i} withBorder px="md" py="sm" radius="lg" maw="92%"><Text fz="sm" style={{ whiteSpace: "pre-wrap" }}>{m.content}</Text>
              {m.source && m.source !== "system" && <Text fz={10} c="dimmed" mt={6}>{m.source === "claude" ? "Claude · from the case record" : m.source === "offline" ? "From the case record (offline mode: no Claude API key)" : m.source}</Text>}</Paper>)}
          {busy && <Group gap="xs"><Loader size="xs" /><Text fz="sm" c="dimmed">Checking the record…</Text></Group>}
          <div ref={end} />
        </Stack>
      </ScrollArea>
      <Group gap="xs" align="flex-end" px="lg" py="sm" style={{ borderTop: LINE, flexShrink: 0 }}>
        <Textarea flex={1} autosize minRows={1} maxRows={4} placeholder="Ask about this bill…" value={draft} onChange={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }} />
        <ActionIcon size="lg" onClick={() => ask(draft)} disabled={busy || !draft.trim()} aria-label="Send">↑</ActionIcon>
      </Group>
    </>
  );
}

/* right: the documents */
function DocPane({ packet, d }: { packet: ReviewPacket | null; d: BillDetail | null }) {
  const { vendors } = useApp();
  const [tab, setTab] = useState<string>("invoice");
  const emails = packet?.files.filter((f) => f.kind === "email") ?? [];
  const strip = (
    <Tabs value={tab} onChange={(t) => setTab(t ?? "invoice")} bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER, flexShrink: 0 }}>
      <Tabs.List h={TABS_H} grow>
        <Tabs.Tab value="invoice">Invoice</Tabs.Tab>
        <Tabs.Tab value="docs">Documents{packet ? ` · ${packet.files.length}` : ""}</Tabs.Tab>
        {emails.length > 0 && <Tabs.Tab value="email">Email received</Tabs.Tab>}
      </Tabs.List>
    </Tabs>
  );
  if (!packet || !d) return (
    <Box bg="gray.1" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      {strip}
      <Box p="lg"><Paper shadow="md" radius={2} maw={560} mx="auto" p="xl"><Skeleton h={28} w={150} /><Skeleton h={12} mt="xl" /><Skeleton h={12} mt="sm" w="80%" /><Skeleton h={120} mt="xl" /></Paper></Box>
    </Box>
  );
  const b = d.bill, v = vendors[b.vendor_id];
  const changed = d.invoice_bank_last4 && v && d.invoice_bank_last4 !== v.bank_last4;
  return (
    <Box bg="gray.1" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      {strip}
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Box p="lg">
          {tab === "invoice" && (
            <Paper shadow="md" p="xl" radius={2} maw={560} mx="auto">
              <Group justify="space-between" align="flex-start">
                <Box bg="dark.7" c="white" px="sm" py={6} style={{ borderRadius: 2 }}><Text fw={700} fz="sm">{shortName(b.vendor_name).toUpperCase()}</Text></Box>
                <Stack gap={0} align="flex-end"><Text fz="xs">Invoice <b>{b.invoice_no ?? "—"}</b></Text><Text fz="xs">Date {day(b.invoice_date)}</Text><Text fz="xs">Due {day(b.due_date)}</Text></Stack>
              </Group>
              <SimpleGrid cols={2} mt="lg"><div><Text fz={10} c="dimmed" tt="uppercase">From</Text><Text fz="xs">{b.vendor_name}</Text><Text fz="xs" c="dimmed">{v?.country}</Text></div>
                <div><Text fz={10} c="dimmed" tt="uppercase">Bill to</Text><Text fz="xs">Helix Silicon, Inc.</Text><Text fz="xs" c="dimmed">Accounts Payable</Text></div></SimpleGrid>
              {d.match.length > 0 && <Table mt="lg" fz="xs" withTableBorder>
                <Table.Thead bg="gray.1"><Table.Tr><Table.Th>Item</Table.Th><Table.Th ta="right">Qty</Table.Th><Table.Th ta="right">Unit</Table.Th><Table.Th ta="right">Total</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>{d.match.map((m) => <Table.Tr key={m.sku}><Table.Td>{m.description}<Text fz={10} c="dimmed">{m.sku}</Text></Table.Td>
                  <Table.Td ta="right">{Number(m.billed).toLocaleString()}</Table.Td><Table.Td ta="right">{amount(m.invoice_price, b.currency)}</Table.Td>
                  <Table.Td ta="right">{amount(d.gl.find((g) => g.sku === m.sku)?.amount, b.currency)}</Table.Td></Table.Tr>)}</Table.Tbody>
              </Table>}
              <Group justify="flex-end" mt="sm"><Text fw={700} fz="sm">Total {amount(b.amount, b.currency)}</Text></Group>
              {!b.invoice_no && <Text fz="sm" c="dimmed" mt="md">No invoice could be read from what arrived. See Documents.</Text>}
              <Paper bg={changed ? "red.0" : "gray.0"} p="sm" mt="lg"><Text fz={10} c="dimmed" tt="uppercase">Payment information (as printed)</Text>
                <Text fz="xs">Remit to account •••• {d.invoice_bank_last4 ?? "—"}</Text>
                {changed && <Badge color="red" size="xs" mt={4}>Differs from the vendor master (•••• {v?.bank_last4})</Badge>}</Paper>
              <Text fz={10} c="dimmed" mt="md">Rendered from the fields the Reader (Claude, no tools) extracted. The raw supplier text is under Documents.</Text>
            </Paper>
          )}
          {(tab === "docs" || tab === "email") && (
            <Stack>
              <Text fz="xs" c="orange.8">Supplier-supplied text: shown as plain text, never followed as instructions.</Text>
              {(tab === "email" ? emails : packet.files).map((f) => (
                <Paper key={f.id} p="md" shadow="xs">
                  <Group justify="space-between" mb={6} wrap="nowrap"><div style={{ minWidth: 0 }}><Text fz="sm" fw={600} truncate>{f.filename}</Text>
                    <Text fz="xs" c="dimmed">{f.kind} · via {f.channel}{f.sender ? ` · from ${f.sender}` : ""} · {when(f.received_at)}</Text></div>
                    <Text fz="xs" ff="monospace" c="dimmed" style={{ flexShrink: 0 }}>sha {f.sha256.slice(0, 8)}</Text></Group>
                  <Paper bg="gray.0" p="sm"><Text ff="monospace" fz="xs" style={{ whiteSpace: "pre-wrap" }}>{f.text ?? "(no text)"}</Text></Paper>
                </Paper>
              ))}
            </Stack>
          )}
        </Box>
      </ScrollArea>
    </Box>
  );
}
