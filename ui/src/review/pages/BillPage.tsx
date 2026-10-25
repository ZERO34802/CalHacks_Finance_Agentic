// One bill, three panes (layout modelled on bill-pay review screens):
//   left   bill list grouped by stage, search, Prev/Next (K / J)
//   centre verdict + checks, payment status, vendor, bill details, line items + GL coding, payment method,
//          approvals chain; tabs for Activity, Agent trace, Emails (sent to the vendor automatically), Ask ReconAI; sticky actions
//   right  the invoice as extracted, every document, the email. Supplier text is UNTRUSTED: plain text only.
import {
  ActionIcon, Alert, Anchor, Badge, Box, Button, Card, Group, Loader, Paper, ScrollArea, Select, SimpleGrid, Stack, Stepper,
  Table, Tabs, Text, Textarea, TextInput, ThemeIcon, Timeline, Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconArrowLeft, IconCheck, IconCircleCheck, IconMail, IconSparkles, IconX } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ApprovalDecision, BillDetail, ChatMessage, OutboundEmail, PaymentBatch, ReviewPacket } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, day, due, findingColor, PEOPLE, shortName, STAGES, stage, stepColor, when, type Seat } from "../format";
import { EmailCard, emailGist, emailStatus } from "../emails";
import { Avatarish, StageBadge } from "../parts";

const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

type Msg = ChatMessage & { source?: string };
const METHOD: Record<string, string> = { ach: "ACH (direct deposit)", wire: "Domestic wire", intl_wire: "International wire (SWIFT)", check: "Check by mail" };
const ORDER = ["needs_review", "on_hold", "blocked", "ready_to_pay", "scheduled", "processing", "paid", "rejected"];
const H = "calc(100vh - 60px)";
const pendingQ: { current: string | null } = { current: null };
const payChoice: { method: string | null; date: string | null } = { method: null, date: null };

export default function BillPage({ id, tab: tabParam }: { id: string; tab?: string }) {
  const { lastEvent, refresh } = useApp();
  const [d, setD] = useState<BillDetail | null>(null);
  const [packet, setPacket] = useState<ReviewPacket | null>(null);
  const [tab, setTab] = useState<string>(tabParam === "ask" ? "ask" : "overview");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [emails, setEmails] = useState<OutboundEmail[]>([]);
  const loadEmails = () => { ap.emails({ case_id: id }).then(setEmails).catch(() => setEmails([])); };
  const load = () => {
    ap.bill(id).then(setD).catch(() => setD(null));
    ap.review(id).then(setPacket).catch(() => setPacket(null));
    loadEmails();
  };
  useEffect(load, [id]);
  useEffect(() => { if (tabParam === "ask") setTab("ask"); }, [tabParam]);
  useEffect(() => { if (lastEvent?.case_id === id) load(); }, [lastEvent]);
  const after = (text?: string) => { if (text) setMsgs((m) => [...m, { role: "assistant", content: text, source: "system" }]); load(); refresh(); };

  return (
    <Box style={{ display: "grid", gridTemplateColumns: "270px minmax(0, 1fr) minmax(0, 0.85fr)", height: H }}>
      <BillList id={id} />
      <Box style={{ display: "flex", flexDirection: "column", minHeight: 0, borderRight: "1px solid var(--mantine-color-gray-3)" }}>
        {!d || !packet ? <Group justify="center" mt="xl"><Loader /></Group> : (
          <>
            <ScrollArea style={{ flex: 1 }} px="xl" pt="lg">
              <Text c="dimmed" fz="sm">{STAGES[d.bill.stage]?.label}</Text>
              <Group justify="space-between" align="flex-start" mb="xs" wrap="nowrap">
                <Text fz={30} fw={650} lh={1.15}>{shortName(d.bill.vendor_name)} {d.bill.invoice_no ? `INV# ${d.bill.invoice_no}` : `· ${d.bill.case_id}`}</Text>
                <Box style={{ flexShrink: 0 }} pt={8}><StageBadge stage={d.bill.stage} /></Box>
              </Group>
              <Tabs value={tab} onChange={(t) => setTab(t ?? "overview")} mb="lg">
                <Tabs.List>
                  <Tabs.Tab value="overview">Overview</Tabs.Tab>
                  <Tabs.Tab value="activity" rightSection={<Badge size="xs" variant="light">{d.activity.length}</Badge>}>Activity</Tabs.Tab>
                  <Tabs.Tab value="trace">Agent trace</Tabs.Tab>
                  <Tabs.Tab value="emails" leftSection={<IconMail size={14} />} rightSection={emails.length ? <Badge size="xs" variant="light">{emails.length}</Badge> : null}>Emails</Tabs.Tab>
                  <Tabs.Tab value="ask" leftSection={<IconSparkles size={14} />}>Ask ReconAI</Tabs.Tab>
                </Tabs.List>
              </Tabs>
              {d.bill.stage === "processing" ? <Running packet={packet} />
                : tab === "overview" ? <Overview d={d} packet={packet} emails={emails} onEmails={() => setTab("emails")} onAsk={(q) => { pendingQ.current = q; setTab("ask"); }} />
                  : tab === "activity" ? <Activity d={d} />
                    : tab === "trace" ? <Trace packet={packet} />
                      : tab === "emails" ? <Emails id={id} emails={emails} reload={loadEmails} />
                      : <Chat id={id} packet={packet} msgs={msgs} setMsgs={setMsgs} />}
              <Box h={40} />
            </ScrollArea>
            <ActionBar d={d} onDone={after} />
          </>
        )}
      </Box>
      <DocPane packet={packet} d={d} />
    </Box>
  );
}

/* left: bill list */
function BillList({ id }: { id: string }) {
  const { bills, go } = useApp();
  const [q, setQ] = useState("");
  const n = q.trim().toLowerCase();
  const sorted = useMemo(() => ORDER.flatMap((s) => bills.filter((b) => b.stage === s)), [bills]);
  const shown = sorted.filter((b) => !n || `${b.vendor_name} ${b.invoice_no}`.toLowerCase().includes(n));
  const idx = sorted.findIndex((b) => b.case_id === id);
  const prev = sorted[idx - 1], next = sorted[idx + 1];
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key.toLowerCase() === "k" && prev) go(`bill/${prev.case_id}`);
      if (e.key.toLowerCase() === "j" && next) go(`bill/${next.case_id}`);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [prev, next]);
  return (
    <Box bg="gray.0" style={{ display: "flex", flexDirection: "column", borderRight: "1px solid var(--mantine-color-gray-3)", minHeight: 0 }}>
      <Stack gap="xs" p="sm">
        <Anchor fz="sm" onClick={() => go("bills")}><Group gap={4}><IconArrowLeft size={14} />Bill Pay</Group></Anchor>
        <TextInput size="xs" placeholder="Search bills" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      </Stack>
      <ScrollArea style={{ flex: 1 }}>
        {ORDER.map((s) => {
          const xs = shown.filter((b) => b.stage === s);
          if (!xs.length) return null;
          return (
            <div key={s}>
              <Text fz="xs" fw={600} c="dimmed" tt="uppercase" px="sm" pt="sm" pb={4}>{STAGES[s].label}</Text>
              {xs.map((b) => (
                <Box key={b.case_id} px="sm" py={8} bg={b.case_id === id ? "gray.2" : undefined} style={{ cursor: "pointer", borderRadius: 6, margin: "0 6px" }}
                  onClick={() => go(`bill/${b.case_id}`)}>
                  <Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} size={24} />
                    <div style={{ minWidth: 0, flex: 1 }}><Text fz="sm" fw={500} truncate>{shortName(b.vendor_name)}</Text>
                      <Text fz="xs" c="dimmed" truncate>{b.amount ? `${amount(b.payable ?? b.amount, b.currency)} · Due ${day(b.due_date)}` : `not read · ${b.case_id}`}</Text></div>
                    {b.risk === "high" && <IconAlertTriangle size={14} color="var(--mantine-color-red-6)" />}
                  </Group>
                </Box>
              ))}
            </div>
          );
        })}
      </ScrollArea>
      <Group justify="space-between" p="sm" style={{ borderTop: "1px solid var(--mantine-color-gray-3)" }}>
        <Button size="compact-sm" variant="subtle" disabled={!prev} onClick={() => prev && go(`bill/${prev.case_id}`)}>Prev <Badge ml={6} size="xs" variant="default">K</Badge></Button>
        <Button size="compact-sm" variant="subtle" disabled={!next} onClick={() => next && go(`bill/${next.case_id}`)}>Next <Badge ml={6} size="xs" variant="default">J</Badge></Button>
      </Group>
    </Box>
  );
}

/* centre: overview */
const VERDICT = {
  ready: { title: "Ready to approve", color: "green", icon: <IconCircleCheck size={18} /> },
  review: { title: "Review recommended", color: "orange", icon: <IconAlertTriangle size={18} /> },
  risk: { title: "Higher risk of fraud", color: "red", icon: <IconAlertTriangle size={18} /> },
} as const;

function Overview({ d, packet, emails, onEmails, onAsk }: { d: BillDetail; packet: ReviewPacket; emails: OutboundEmail[]; onEmails: () => void; onAsk: (q: string) => void }) {
  const { vendors, go } = useApp();
  const b = d.bill, v = vendors[b.vendor_id], cur = b.currency;
  const vd = VERDICT[d.verdict as keyof typeof VERDICT] ?? VERDICT.review;
  const failed = d.checks.filter((c) => !c.passed), passed = d.checks.filter((c) => c.passed);
  const [showAll, setShowAll] = useState(false);
  const po = b.po_number ?? "—";
  const sent = emails.filter((e) => e.kind === "supplier_discrepancy").at(-1);
  return (
    <Stack gap="xl">
      <Card withBorder padding="lg" style={{ borderColor: `var(--mantine-color-${vd.color}-4)` }} bg={d.verdict === "risk" ? "red.0" : undefined}>
        <Group gap={8} mb={6} c={`${vd.color}.8`}>{vd.icon}<Text fw={650} fz="lg">{vd.title}</Text></Group>
        <Text fz="sm">{d.verdict_text}</Text>
        {failed.length > 0 && (
          <Stack gap={6} mt="sm">
            {failed.map((c) => (
              <Group key={c.name} gap={8} wrap="nowrap" align="flex-start">
                <IconX size={16} color={`var(--mantine-color-${c.severity === "high" ? "red" : "orange"}-7)`} style={{ marginTop: 2, flexShrink: 0 }} />
                <div><Text fz="sm" fw={600}>{c.name.replace(/^(\w)/, (x) => x)}: failed</Text><Text fz="sm" c="dimmed" component="div">{c.detail} <Refs refs={c.refs} /></Text></div>
              </Group>
            ))}
          </Stack>
        )}
        {b.disagreements.length > 0 && <Alert mt="sm" color="orange" variant="light" title="Second-line checks vs the agents">
          {b.disagreements.map((x) => <Text key={x} fz="sm">{x}</Text>)}</Alert>}
        {b.payable && b.payable !== b.amount && <Alert mt="sm" color="blue" variant="light" title="Pay what's clean">
          The undisputed {amount(b.payable, cur)} is booked and payable; {amount(b.disputed, cur)} stays held until the vendor credits or corrects it{b.sub_case_ids.length ? ` (${b.sub_case_ids.join(", ")})` : ""}.</Alert>}
        {!b.invoice_no && b.warning && <Alert mt="sm" color="orange" variant="light">{b.warning}</Alert>}
        {sent && (
          <Group gap={6} mt="sm" wrap="nowrap" style={{ cursor: "pointer" }} onClick={onEmails}>
            <IconMail size={15} color={`var(--mantine-color-${emailStatus(sent).color}-7)`} style={{ flexShrink: 0 }} />
            <Text fz="sm" truncate>{sent.status === "sent" ? "Emailed" : sent.status === "failed" ? "Email to" : "Queued email to"} {shortName(b.vendor_name)} ({sent.to}) · {when(sent.created_at)} · {emailGist(sent)}
              {sent.status === "failed" ? " · delivery failed" : sent.status === "outbox" ? " · in outbox" : ""}</Text>
            <Anchor fz="sm" style={{ flexShrink: 0 }}>View</Anchor>
          </Group>
        )}
        {d.verdict === "risk" && <Text fz="sm" fw={600} c="red.8" mt="sm">Call the vendor on the number in the vendor master (never the one on the invoice or email) before paying.</Text>}
        <Text fz="sm" fw={600} mt="md" mb={4}>Checks passed</Text>
        <Stack gap={3}>
          {(showAll ? passed : passed.slice(0, 4)).map((c) => (
            <Group key={c.name} gap={8} wrap="nowrap" align="flex-start"><IconCheck size={15} color="var(--mantine-color-green-7)" style={{ marginTop: 3, flexShrink: 0 }} />
              <Text fz="sm" component="div">{c.name} <Refs refs={c.refs} /></Text></Group>
          ))}
        </Stack>
        {passed.length > 4 && <Anchor fz="sm" mt={6} onClick={() => setShowAll((x) => !x)}>{showAll ? "Show less" : `Show ${passed.length - 4} more`}</Anchor>}
        <Group gap={6} mt="md">{packet.suggested.slice(0, 3).map((q) => <Button key={q} size="compact-xs" variant="light" leftSection={<IconSparkles size={12} />} onClick={() => onAsk(q)}>{q}</Button>)}</Group>
      </Card>

      <PaymentStatus d={d} />

      <Section title="Vendor" done>
        <Card withBorder padding="md">
          <Group justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} size={36} /><div><Text fw={600}>{b.vendor_name}</Text>
              <Text fz="xs" c="dimmed">{v?.email_domain} · {d.last_paid ? `Last paid ${amount(d.last_paid.amount, d.last_paid.currency)} on ${day(d.last_paid.paid_on)} (${d.last_paid.invoice_no})` : "No previous payments on record"}</Text></div></Group>
            <Anchor fz="sm" onClick={() => go(`vendors/${b.vendor_id}`)}>See vendor</Anchor>
          </Group>
        </Card>
      </Section>

      <Section title="Bill details" done>
        <SimpleGrid cols={2}>
          <TextInput label="Invoice #" value={b.invoice_no ?? ""} readOnly />
          <TextInput label="Purchase order" value={po} readOnly />
          <TextInput label="Invoice date" value={day(b.invoice_date)} readOnly />
          <TextInput label="Due date" value={`${day(b.due_date)} · ${due(b.days_to_due)}`} readOnly />
        </SimpleGrid>
        <Text fz="xs" c="dimmed" mt={6}>Accounting date {day(b.invoice_date)} (period open). Fields extracted by the Reader (Claude, no tools).</Text>
      </Section>

      <Section title="Line items" done>
        <Stack gap="sm">
          {d.gl.map((g, i) => {
            const m = d.match.find((r) => r.sku === g.sku);
            const risk = m && Number(m.amount_at_risk) > 0;
            return (
              <Card key={g.line_no} withBorder padding="sm" style={{ borderColor: risk ? "var(--mantine-color-orange-4)" : undefined }}>
                <Group justify="space-between" wrap="nowrap"><Group gap="sm" wrap="nowrap"><Text fz="sm" c="dimmed" ff="monospace">{String(i + 1).padStart(2, "0")}</Text>
                  <div><Text fz="sm" fw={500}>{g.description}</Text><Text fz="xs" c="dimmed" ff="monospace">{g.sku}</Text></div></Group>
                  <Text fz="sm" ff="monospace" fw={600}>{amount(g.amount, cur)}</Text></Group>
                <SimpleGrid cols={2} mt="xs">
                  <TextInput size="xs" label="Accounting category" value={g.account} readOnly description={g.basis}
                    leftSection={<IconSparkles size={13} color="var(--mantine-color-brand-6)" />} />
                  {m && <TextInput size="xs" label="Ordered · received · billed" readOnly error={risk ? `${amount(m.amount_at_risk, cur)} at risk` : undefined}
                    value={`${m.ordered == null ? "not on PO" : Number(m.ordered).toLocaleString()} · ${Number(m.received).toLocaleString()} · ${Number(m.billed).toLocaleString()} @ ${amount(m.invoice_price)}${m.po_price && m.price_variance && Number(m.price_variance) !== 0 ? ` (PO ${amount(m.po_price)})` : ""}`} />}
                </SimpleGrid>
              </Card>
            );
          })}
        </Stack>
      </Section>

      <Section title="Payment method"><PaymentFields d={d} /></Section>

      <Section title="Approvals">
        <Card withBorder padding="md">
          <Stack gap="md">
            {d.approval_steps.map((s) => (
              <Group key={s.step} gap="md" wrap="nowrap" align="flex-start">
                <ThemeIcon radius="xl" size={28} variant={s.status === "done" ? "filled" : "light"}
                  color={s.status === "done" ? "green" : s.status === "rejected" ? "red" : s.status === "on_hold" ? "yellow" : s.status === "waiting" ? "violet" : "gray"}>
                  {s.status === "done" ? <IconCheck size={15} /> : s.step}</ThemeIcon>
                <div style={{ flex: 1 }}>
                  <Group justify="space-between"><Text fz="sm" fw={600}>{s.label}</Text>
                    <Badge size="xs" variant="light" color={s.status === "done" ? "green" : s.status === "waiting" ? "violet" : s.status === "rejected" ? "red" : "gray"}>{s.status.replace("_", " ")}</Badge></Group>
                  <Text fz="sm">{s.who}</Text>
                  {s.note && <Text fz="xs" c="dimmed">{s.note}</Text>}
                </div>
              </Group>
            ))}
          </Stack>
        </Card>
      </Section>
    </Stack>
  );
}

function Refs({ refs }: { refs: string[] }) {
  return <>{refs.slice(0, 4).map((r) => <Badge key={r} size="xs" variant="default" ml={4} tt="none">{r}</Badge>)}</>;
}

function Section({ title, done, children }: { title: string; done?: boolean; children: ReactNode }) {
  return <div><Group gap="xs" mb="sm"><Text fw={650} fz="lg">{title}</Text>{done && <Badge size="sm" color="green" variant="light">Complete</Badge>}</Group>{children}</div>;
}

function PaymentStatus({ d }: { d: BillDetail }) {
  const s = d.bill.stage;
  const active = s === "paid" ? 4 : s === "scheduled" ? 2 : s === "ready_to_pay" ? 1 : 0;
  const label: Record<string, string> = { needs_review: "Awaiting approval", on_hold: "On hold", blocked: "Payment blocked", ready_to_pay: "Approved, not scheduled",
    scheduled: "Scheduled", rejected: "Rejected", processing: "Processing", failed: "Payment failed",
    paid: d.bill.payment?.rail === "coinbase" ? `Paid via Coinbase${d.bill.payment.network === "sandbox" ? " (sandbox)" : " (testnet)"}` : "Paid (simulated bank)" };
  return (
    <div>
      <Group justify="space-between" mb="xs">
        <div><Text fz="xs" c="dimmed">Payment status</Text><Text fz="xl" fw={600} c={s === "blocked" || s === "rejected" ? "red.7" : undefined}>{label[s] ?? s}</Text></div>
        {d.bill.payable && <div style={{ textAlign: "right" }}><Text fz="xs" c="dimmed">Booked, to pay</Text><Text fz="xl" fw={600}>{amount(d.bill.payable, d.bill.currency)}</Text></div>}
        <div style={{ textAlign: "right" }}><Text fz="xs" c="dimmed">Estimated payment date</Text><Text fz="xl" fw={600}>{day(d.est_pay_date)}</Text></div>
      </Group>
      <Stepper active={active} size="xs" color={s === "blocked" ? "red" : "brand"}>
        <Stepper.Step label="Awaiting approval" /><Stepper.Step label="Approved" /><Stepper.Step label="Scheduled" /><Stepper.Step label="Paid" />
      </Stepper>
      {d.bill.payment_block && <Alert mt="sm" color="red" variant="light" title="Payment guard">{d.bill.payment_block}</Alert>}
    </div>
  );
}

function PaymentFields({ d }: { d: BillDetail }) {
  const { vendors } = useApp();
  const b = d.bill, v = vendors[b.vendor_id];
  const locked = !!b.payment || ["paid", "rejected"].includes(b.stage);
  const [method, setMethod] = useState<string>(b.payment?.method ?? d.default_method ?? "ach");
  const off = b.discount && ["available", "needs_approval"].includes(b.discount.status) ? b.discount : null;
  const [date, setDate] = useState<string>((b.payment?.pay_date ?? off?.pay_by ?? d.est_pay_date ?? "").slice(0, 10));
  payChoice.method = method; payChoice.date = date;
  const inWindow = off && date && date <= off.pay_by;
  return (
    <Stack gap="sm">
      {off && !locked && (
        <Alert color="green" variant="light" icon={<IconSparkles size={16} />} title={`Pay by ${day(off.pay_by)} to save ${amount(off.discount_amount, off.currency)}`}>
          Contract terms {off.terms} · ≈{off.annualized_return_pct}% annualized return for paying early.
          {inWindow ? " The payment date below is inside the window." : " The payment date below is after the window: no discount."}
        </Alert>
      )}
      {b.payment && Number(b.payment.discount_amount) > 0 && <Alert color="green" variant="light">Early-payment discount captured: {amount(b.payment.discount_amount, b.currency)}.</Alert>}
      {b.payment && Number(b.payment.credit_applied) > 0 && <Alert color="blue" variant="light">Advance-payment credit applied: {amount(b.payment.credit_applied, b.currency)}. Cash paid {amount(b.payment.amount, b.currency)}.</Alert>}
      {!b.payment && b.credit_available && <Alert color="blue" variant="light">This vendor has {amount(b.credit_available, b.currency)} of prepaid credit. It's applied automatically when you schedule.</Alert>}
      <Select label="Payment method" value={method} onChange={(x) => x && setMethod(x)} disabled={locked} allowDeselect={false}
        data={Object.entries(METHOD).map(([k, l]) => ({ value: k, label: l, disabled: !d.pay_methods.includes(k) }))}
        description={v?.country === "US" ? "US vendor: ACH, domestic wire or check" : `${v?.country ?? ""} vendor: international wire only`} />
      <SimpleGrid cols={2}>
        <TextInput label="Pay from account" value="Helix operating · USD •••• 0042 (simulated)" readOnly />
        <TextInput label="Send payment to" value={`Vendor master •••• ${v?.bank_last4 ?? "—"}`} readOnly
          description={d.invoice_bank_last4 && d.invoice_bank_last4 !== v?.bank_last4 ? `Not •••• ${d.invoice_bank_last4} printed on the invoice` : undefined} />
      </SimpleGrid>
      <TextInput type="date" label="Payment date" value={date} onChange={(e) => setDate(e.currentTarget.value)} disabled={locked} w={220} />
      <Textarea label="Memo for vendor" value={d.statement_descriptor} readOnly autosize minRows={1} description="Shown on the vendor's bank statement"
        leftSection={<IconSparkles size={13} color="var(--mantine-color-brand-6)" />} />
    </Stack>
  );
}

/* centre: sticky actions */
function ActionBar({ d, onDone }: { d: BillDetail; onDone: (text?: string) => void }) {
  const { seat } = useApp();
  const b = d.bill, who = me(seat);
  const [busy, setBusy] = useState<string | null>(null);
  const [run, setRun] = useState<PaymentBatch | null>(null);
  useEffect(() => {
    if (b.payment) ap.runs().then((rs) => setRun(rs.find((r) => r.id === b.payment!.batch_id) ?? null)).catch(() => {});
    else setRun(null);
  }, [b.payment?.batch_id, b.payment?.status]);
  const canSign = b.needs === seat && !!b.invoice_no;   // nothing to approve when no invoice was read
  const fail = (e: unknown, title: string) => notifications.show({ color: "red", title, message: e instanceof Error ? e.message : String(e) });

  const decide = async (dec: ApprovalDecision) => {
    setBusy(dec);
    try {
      await ap.decide(b.case_id, { approver: who.email, role: who.role, decision: dec, comment: "", scope: null });
      const text = dec === "rejected" ? `Rejected by ${who.name}. Nothing will be paid.` : `Put on hold by ${who.name}. Nothing is paid until it's resolved.`;
      notifications.show({ color: dec === "rejected" ? "red" : "yellow", title: "Recorded", message: text }); onDone(text);
    } catch (e) { fail(e, "Not allowed"); } finally { setBusy(null); }
  };
  const schedule = async (approveFirst: boolean) => {
    setBusy("schedule");
    try {
      let cur = b;
      if (approveFirst) {
        await ap.decide(b.case_id, { approver: who.email, role: who.role, decision: "approved", comment: "", scope: null });
        cur = (await ap.bill(b.case_id)).bill;   // the Poster booked it (or refused): read the result
      }
      if (cur.stage !== "ready_to_pay") {
        const why = cur.payment_block ?? cur.warning ?? "not payable yet";
        notifications.show({ color: "orange", title: "Approved, but not payable yet", message: why });
        onDone(`Approved by ${who.name}. Not scheduled: ${why}`); return;
      }
      const r = await ap.createRun([b.case_id], payChoice.date || new Date().toISOString().slice(0, 10), who.email,
        { [b.case_id]: payChoice.method ?? d.default_method ?? "ach" });
      const text = `${approveFirst ? `Approved by ${who.name} and s` : "S"}cheduled in ${r.id} for ${day(r.pay_date)}. Someone other than ${who.name} must release it.`;
      notifications.show({ color: "brand", title: "Scheduled", message: text }); onDone(text);
    } catch (e) { fail(e, approveFirst ? "Couldn't approve & schedule" : "Couldn't schedule"); onDone(); } finally { setBusy(null); }
  };
  const release = async (rail: "bank" | "coinbase") => {
    if (!run) return;
    setBusy(rail);
    try {
      const r = await ap.release(run.id, who.email, rail);
      const p = r.payments.find((x) => x.case_id === b.case_id);
      const t = rail === "coinbase"
        ? (p?.status === "paid" ? `Released by ${who.name} via Coinbase: ${p.onchain_amount} USDC sent to ${short(p.payee_address)}${p.network === "sandbox" ? " (sandbox, simulated)" : ""} · tx ${short(p.tx_hash)}.`
          : `Coinbase transfer failed: ${p?.error ?? "see Review payments"}. Retry from Bills → For payment.`)
        : `Released by ${who.name}. Paid (simulated bank transfer).`;
      notifications.show({ color: p?.status === "paid" || rail === "bank" ? "green" : "red", title: p?.status === "failed" ? "Not paid" : "Paid", message: t, autoClose: 9000 });
      onDone(t);
    } catch (e) { fail(e, rail === "coinbase" ? "Can't release via Coinbase" : "Can't release"); } finally { setBusy(null); }
  };

  let left: ReactNode = null, right: ReactNode = null;
  if (b.stage === "needs_review" || b.stage === "on_hold") {
    left = <Text fz="xs" c="dimmed" truncate>Needs {PEOPLE[b.needs as Seat]?.title ?? b.needs} · you're {who.title}{b.waiting_hours != null && ` · ${b.waiting_hours}h of 24h SLA`}</Text>;
    right = <>
      <Button variant="default" loading={busy === "ask"} onClick={() => decide("ask")}>Hold</Button>
      <Button variant="outline" color="red" leftSection={<IconX size={15} />} loading={busy === "rejected"} onClick={() => decide("rejected")}>Reject</Button>
      <Tooltip label={!b.invoice_no ? "No invoice was read: reject, or ask the vendor to resend." : `Approval needs the ${PEOPLE[b.needs as Seat]?.title}. Switch person (top right).`} disabled={canSign}>
        <Button color="green" disabled={!canSign} loading={busy === "schedule"} leftSection={<IconCheck size={16} />} onClick={() => schedule(true)}>Approve & schedule</Button>
      </Tooltip></>;
  } else if (b.stage === "ready_to_pay") {
    left = <Text fz="xs" c="dimmed">Approved by {b.approved_by}</Text>;
    right = <Button loading={busy === "schedule"} onClick={() => schedule(false)}>Schedule payment</Button>;
  } else if (b.stage === "blocked") {
    left = <Text fz="xs" c="red.7">Blocked by the payment guard</Text>;
    right = <><Button variant="default" loading={busy === "ask"} onClick={() => decide("ask")}>Hold & verify</Button>
      <Button variant="outline" color="red" leftSection={<IconX size={15} />} loading={busy === "rejected"} onClick={() => decide("rejected")}>Reject</Button></>;
  } else if (b.stage === "scheduled") {
    const self = run?.created_by === who.email;
    left = <Text fz="xs" c="dimmed">{run ? `${run.id} · prepared by ${run.created_by}` : "Scheduled"}</Text>;
    right = <Tooltip label="You prepared this payment. Someone else must release it." disabled={!self}>
      <Group gap="xs" wrap="nowrap">
        <Button variant="default" disabled={self || !run} loading={busy === "bank"} onClick={() => release("bank")}>Release · bank (simulated)</Button>
        <Button color="green" disabled={self || !run} loading={busy === "coinbase"} onClick={() => release("coinbase")}>Release via Coinbase (USDC)</Button>
      </Group></Tooltip>;
  } else if (b.stage === "paid") {
    const pm = b.payment;
    left = pm?.rail === "coinbase"
      ? <Text fz="xs" c="dimmed" truncate>Paid via Coinbase · {pm.onchain_amount} USDC → {short(pm.payee_address)} · tx {pm.explorer_url
          ? <Anchor href={pm.explorer_url} target="_blank" fz="xs">{short(pm.tx_hash)}</Anchor> : short(pm.tx_hash)}{pm.network === "sandbox" ? " (sandbox, simulated)" : " · Base Sepolia testnet"}</Text>
      : <Text fz="xs" c="dimmed">Paid {pm && day(pm.pay_date)} · {pm && METHOD[pm.method]} → •••• {pm?.pay_to_last4} (simulated)</Text>;
  } else if (b.stage === "rejected") {
    left = <Text fz="xs" c="dimmed">Rejected. Nothing will be paid.</Text>;
  }
  return (
    <Group justify="space-between" px="xl" py="sm" style={{ borderTop: "1px solid var(--mantine-color-gray-3)" }} bg="white" wrap="nowrap">
      <Box style={{ minWidth: 0, flex: 1 }}>{left}</Box>
      <Group gap="xs" wrap="nowrap">{right}</Group>
    </Group>
  );
}

/* centre: other tabs */
function Running({ packet }: { packet: ReviewPacket }) {
  const top = packet.trace.filter((s) => !s.parent_id);
  return (
    <Card withBorder padding="lg">
      <Group mb="md"><Loader size="sm" /><div><Text fw={600}>ReconAI is reconciling this invoice</Text>
        <Text c="dimmed" fz="sm">It runs in the background. You'll get a notification when it's ready.</Text></div></Group>
      <Timeline active={top.length - 1} bulletSize={22}>{top.map((s) => <Timeline.Item key={s.id} title={stage(s.stage)} bullet={<Text fz={10}>{s.seq + 1}</Text>}><Text c="dimmed" fz="xs">{s.status}</Text></Timeline.Item>)}</Timeline>
    </Card>
  );
}

function Activity({ d }: { d: BillDetail }) {
  return (
    <Timeline active={d.activity.length} bulletSize={14} lineWidth={2}>
      {d.activity.map((a, i) => <Timeline.Item key={i} title={<Text fz="sm">{a.text}</Text>}><Text fz="xs" c="dimmed">{a.actor} · {when(a.at)}</Text></Timeline.Item>)}
    </Timeline>
  );
}

function Emails({ id, emails, reload }: { id: string; emails: OutboundEmail[]; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      const out = await ap.sendCaseEmails(id);
      const ok = out.filter((e) => e.status === "sent").length;
      notifications.show({ color: ok === out.length ? "green" : "orange", title: "Delivery retried", message: `${ok} of ${out.length} sent` });
      reload();
    } catch (e) { notifications.show({ color: "red", title: "Couldn't retry", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(false); }
  };
  if (!emails.length) return <Text fz="sm" c="dimmed">No emails sent for this bill. When the agents flag a mismatch, ReconAI emails the vendor's contact on file with the reasoning.</Text>;
  return (
    <Stack>
      <Group justify="space-between">
        <Text fz="sm" c="dimmed">Sent automatically when the agents flagged this bill. Always to the contact on file, never the invoice's reply-to.</Text>
        {emails.some((e) => e.status !== "sent") && <Button size="compact-sm" variant="light" loading={busy} onClick={retry}>Retry delivery</Button>}
      </Group>
      {emails.map((e) => <EmailCard key={e.id} e={e} />)}
    </Stack>
  );
}

function Trace({ packet }: { packet: ReviewPacket }) {
  const steps = packet.trace.filter((s) => !s.parent_id);
  return (
    <Stack>
      <Text fw={600}>What each agent reported</Text>
      <Stack gap={6}>
        {packet.findings.map((f, i) => (
          <Group key={`${f.check}-${i}`} gap="sm" wrap="nowrap" align="flex-start">
            <ThemeIcon size="sm" radius="xl" color={findingColor(f.status)} variant={f.status === "unchecked" ? "light" : "filled"}>{f.status === "ok" ? "✓" : f.status === "flag" ? "!" : "?"}</ThemeIcon>
            <div><Group gap={6}><Text fz="sm" fw={600}>{f.check}</Text><Text fz="xs" c="dimmed">{f.agent}</Text>
              {f.status === "unchecked" && <Badge size="xs" variant="light" color="gray">not checked</Badge>}</Group><Text fz="sm" c="dimmed">{f.detail}</Text></div>
          </Group>
        ))}
      </Stack>
      <Text fw={600} mt="md">Step by step</Text>
      <Timeline active={steps.length} bulletSize={22} lineWidth={2}>
        {steps.map((s) => (
          <Timeline.Item key={s.id} color={stepColor(s.status)} bullet={<Text fz={9}>{s.seq + 1}</Text>}
            title={<Group gap={6}><Text fz="sm" fw={500}>{stage(s.stage)}</Text><Badge size="xs" variant="light" color={stepColor(s.status)}>{s.status}</Badge>
              {s.detail.stub === true && <Badge size="xs" variant="outline" color="gray">placeholder</Badge>}</Group>}>
            <Text fz="xs" c="dimmed">{s.role} · {s.duration_ms ?? "…"} ms{s.skill ? ` · ${s.skill}@${s.skill_version}` : ""}{s.error ? ` · ${s.error}` : ""}</Text>
            {Object.entries(s.detail).filter(([k]) => k !== "stub").length > 0 &&
              <Text fz="xs" ff="monospace" c="dimmed" style={{ wordBreak: "break-word" }}>{Object.entries(s.detail).filter(([k]) => k !== "stub").map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ").slice(0, 600)}</Text>}
          </Timeline.Item>
        ))}
      </Timeline>
    </Stack>
  );
}

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
    <Stack gap="md">
      <Paper withBorder p="md" radius="lg"><Group gap={6} mb={6}><IconSparkles size={16} color="var(--mantine-color-brand-6)" /><Text fw={600} fz="sm">ReconAI</Text>
        <Text fz="xs" c="dimmed">answers from this bill's record only</Text></Group><Text fz="sm">{packet.summary}</Text>
        <Group gap={6} mt="sm">{packet.suggested.map((q) => <Button key={q} size="compact-xs" variant="light" onClick={() => ask(q)}>{q}</Button>)}</Group></Paper>
      {msgs.map((m, i) => m.role === "user"
        ? <Group key={i} justify="flex-end"><Paper bg="brand.0" px="md" py="xs" radius="lg" maw="80%"><Text fz="sm">{m.content}</Text></Paper></Group>
        : <Paper key={i} withBorder px="md" py="sm" radius="lg" maw="92%"><Text fz="sm" style={{ whiteSpace: "pre-wrap" }}>{m.content}</Text>
          {m.source && m.source !== "system" && <Text fz={10} c="dimmed" mt={6}>{m.source === "claude" ? "Claude · from the case record" : m.source === "offline" ? "From the case record (offline mode: no Claude API key)" : m.source}</Text>}</Paper>)}
      {busy && <Group gap="xs"><Loader size="xs" /><Text fz="sm" c="dimmed">Checking the record…</Text></Group>}
      <div ref={end} />
      <Group gap="xs" align="flex-end">
        <Textarea flex={1} autosize minRows={1} maxRows={4} placeholder="Ask about this bill…" value={draft} onChange={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }} />
        <ActionIcon size="lg" onClick={() => ask(draft)} disabled={busy || !draft.trim()} aria-label="Send">↑</ActionIcon>
      </Group>
    </Stack>
  );
}

/* right: the documents */
function DocPane({ packet, d }: { packet: ReviewPacket | null; d: BillDetail | null }) {
  const { vendors } = useApp();
  const [tab, setTab] = useState<string>("invoice");
  if (!packet || !d) return <Box bg="gray.1" />;
  const emails = packet.files.filter((f) => f.kind === "email");
  const b = d.bill, v = vendors[b.vendor_id];
  const changed = d.invoice_bank_last4 && v && d.invoice_bank_last4 !== v.bank_last4;
  return (
    <Box bg="gray.1" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Tabs value={tab} onChange={(t) => setTab(t ?? "invoice")} bg="white">
        <Tabs.List grow>
          <Tabs.Tab value="invoice">Invoice</Tabs.Tab>
          <Tabs.Tab value="docs">Documents · {packet.files.length}</Tabs.Tab>
          {emails.length > 0 && <Tabs.Tab value="email" color="red">Email</Tabs.Tab>}
        </Tabs.List>
      </Tabs>
      <ScrollArea style={{ flex: 1 }} p="lg">
        {tab === "invoice" && (
          <Paper shadow="md" p="xl" radius={2} maw={560} mx="auto">
            <Group justify="space-between" align="flex-start">
              <Box bg="dark.7" c="white" px="sm" py={6} style={{ borderRadius: 2 }}><Text fw={700} fz="sm">{shortName(b.vendor_name).toUpperCase()}</Text></Box>
              <Stack gap={0} align="flex-end"><Text fz="xs">Invoice <b>{b.invoice_no}</b></Text><Text fz="xs">Date {day(b.invoice_date)}</Text><Text fz="xs">Due {day(b.due_date)}</Text></Stack>
            </Group>
            <SimpleGrid cols={2} mt="lg"><div><Text fz={10} c="dimmed" tt="uppercase">From</Text><Text fz="xs">{b.vendor_name}</Text><Text fz="xs" c="dimmed">{v?.country}</Text></div>
              <div><Text fz={10} c="dimmed" tt="uppercase">Bill to</Text><Text fz="xs">Helix Silicon, Inc.</Text><Text fz="xs" c="dimmed">Accounts Payable</Text></div></SimpleGrid>
            <Table mt="lg" fz="xs" withTableBorder>
              <Table.Thead bg="gray.1"><Table.Tr><Table.Th>Item</Table.Th><Table.Th ta="right">Qty</Table.Th><Table.Th ta="right">Unit</Table.Th><Table.Th ta="right">Total</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>{d.match.map((m) => <Table.Tr key={m.sku}><Table.Td>{m.description}<Text fz={10} c="dimmed">{m.sku}</Text></Table.Td>
                <Table.Td ta="right">{Number(m.billed).toLocaleString()}</Table.Td><Table.Td ta="right">{amount(m.invoice_price)}</Table.Td>
                <Table.Td ta="right">{amount(d.gl.find((g) => g.sku === m.sku)?.amount)}</Table.Td></Table.Tr>)}</Table.Tbody>
            </Table>
            <Group justify="flex-end" mt="sm"><Text fw={700} fz="sm">Total {amount(b.amount, b.currency)}</Text></Group>
            {!b.invoice_no && <Text fz="sm" c="dimmed" mt="md">No invoice could be read from what arrived. See Documents.</Text>}
            <Paper bg={changed ? "red.0" : "gray.0"} p="sm" mt="lg"><Text fz={10} c="dimmed" tt="uppercase">Payment information (as printed)</Text>
              <Text fz="xs">Remit to account •••• {d.invoice_bank_last4 ?? "—"}</Text>
              {changed && <Badge color="red" size="xs" mt={4}>Differs from the vendor master (•••• {v?.bank_last4})</Badge>}</Paper>
            <Text fz={10} c="dimmed" mt="md">Rendered from the fields the Reader extracted. The raw supplier text is under Documents.</Text>
          </Paper>
        )}
        {(tab === "docs" || tab === "email") && (
          <Stack>
            {(tab === "email" ? emails : packet.files).map((f) => (
              <Paper key={f.id} p="md" shadow="xs">
                <Group justify="space-between" mb={6}><div><Text fz="sm" fw={600}>{f.filename}</Text>
                  <Text fz="xs" c="dimmed">{f.kind} · via {f.channel}{f.sender ? ` · from ${f.sender}` : ""} · {when(f.received_at)}</Text></div>
                  <Text fz="xs" ff="monospace" c="dimmed">sha {f.sha256.slice(0, 8)}</Text></Group>
                <Paper bg="gray.0" p="sm"><Text ff="monospace" fz="xs" style={{ whiteSpace: "pre-wrap" }}>{f.text ?? "(no text)"}</Text></Paper>
              </Paper>
            ))}
            <Alert color="yellow" variant="light">Supplier-supplied text. Shown as plain text, never followed as instructions.</Alert>
          </Stack>
        )}
      </ScrollArea>
    </Box>
  );
}
