// Vendors: the vendor master (terms, tax, risk, memory, advance payments) and vendor onboarding with CRS checks.
// Bank details: last 4 only. New vendors: requested inside Helix, verified, approved by a second person.
import { Alert, Badge, Button, Card, Drawer, Group, NumberInput, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Textarea, ThemeIcon, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconCheck, IconClockPause, IconMinus, IconPlus, IconX } from "@tabler/icons-react";
import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import type { MemoryEntry, OnboardingCase, OnboardingRequestIn, Prepayment, PrepaymentQuote, Vendor } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, day, PEOPLE, RISK, shortName, sumMoney, usd, when, type Seat } from "../format";
import { Avatarish, BillsTable } from "../parts";

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const pctText = (p?: string | null) => (p ? `${(Number(p) * 100).toFixed(1).replace(/\.0$/, "")}%` : "");
const terms = (v: Vendor) => (v.terms?.discount_pct ? `${pctText(v.terms.discount_pct).replace("%", "")}/${v.terms.discount_days} net ${v.terms.net_days}` : `net ${v.terms?.net_days ?? 30}`);

export default function Vendors({ openId }: { openId?: string }) {
  const { vendors, bills } = useApp();
  const [tab, setTab] = useState<string>("vendors");
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [open, setOpen] = useState<Vendor | null>(null);
  const [onb, setOnb] = useState<OnboardingCase[]>([]);
  const loadOnb = () => { ap.onboarding().then(setOnb).catch(() => {}); };
  useEffect(() => { ap.memory().then(setMemory).catch(() => {}); loadOnb(); }, []);
  useEffect(() => { if (openId && vendors[openId]) setOpen(vendors[openId]); }, [openId, vendors]);
  const list = Object.values(vendors);
  const of = (v: Vendor) => bills.filter((b) => b.vendor_id === v.id);
  const openUsd = (v: Vendor) => sumMoney(of(v).filter((b) => !["paid", "rejected"].includes(b.stage)).map((b) => b.amount_usd));
  const risk = (v: Vendor) => (of(v).some((b) => b.risk === "high") ? "high" : of(v).some((b) => b.risk === "medium") ? "medium" : "low");
  const pending = onb.filter((c) => c.status === "needs_review").length;

  return (
    <>
      <Text fz={34} fw={650} lh={1.1} mb="md">Vendors</Text>
      <Tabs value={tab} onChange={(t) => setTab(t ?? "vendors")} mb="md">
        <Tabs.List>
          <Tabs.Tab value="vendors">Vendor master · {list.length}</Tabs.Tab>
          <Tabs.Tab value="onboarding" rightSection={pending ? <Badge size="xs" color="violet" circle>{pending}</Badge> : null}>Onboarding</Tabs.Tab>
        </Tabs.List>
      </Tabs>

      {tab === "vendors" ? (
        <Card withBorder padding={0}>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead bg="gray.0"><Table.Tr><Table.Th>Vendor</Table.Th><Table.Th>Country</Table.Th><Table.Th>Pays to</Table.Th><Table.Th>Terms</Table.Th><Table.Th>Tax</Table.Th>
              <Table.Th ta="right">Open balance</Table.Th><Table.Th>Risk</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {list.map((v) => (
                <Table.Tr key={v.id} style={{ cursor: "pointer" }} onClick={() => setOpen(v)}>
                  <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={v.name} /><div><Text fz="sm" fw={500}>{shortName(v.name)}</Text><Text fz="xs" c="dimmed">{v.email_domain}</Text></div></Group></Table.Td>
                  <Table.Td><Text fz="sm">{v.country} · {v.currency}</Text>{v.critical && <Badge size="xs" variant="light">critical</Badge>}{v.on_probation && <Badge size="xs" color="orange" variant="light">probation</Badge>}</Table.Td>
                  <Table.Td ff="monospace" fz="sm">{v.country === "US" ? "ACH" : "Intl wire"} •••• {v.bank_last4}</Table.Td>
                  <Table.Td><Text fz="sm">{terms(v)}</Text>{v.terms?.prepay_discount_pct && <Text fz="xs" c="dimmed">{pctText(v.terms.prepay_discount_pct)} off prepayments</Text>}</Table.Td>
                  <Table.Td><Text fz="sm" ff="monospace">{v.tax_id ?? "missing"}</Text><Text fz="xs" c="dimmed">{v.country === "US" ? "W-9" : "W-8BEN-E"}</Text></Table.Td>
                  <Table.Td ta="right" ff="monospace">{usd(openUsd(v))}</Table.Td>
                  <Table.Td><Badge variant="light" color={RISK[risk(v)]}>{risk(v)}</Badge></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      ) : <Onboarding cases={onb} reload={loadOnb} />}

      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size="xl" title={open ? <Text fw={650} fz="lg">{open.name}</Text> : null}>
        {open && (
          <Stack>
            <Table fz="sm"><Table.Tbody>
              <Table.Tr><Table.Td c="dimmed">Also known as</Table.Td><Table.Td>{open.aliases.join(" · ") || "—"}</Table.Td></Table.Tr>
              <Table.Tr><Table.Td c="dimmed">Bank on file</Table.Td><Table.Td ff="monospace">•••• {open.bank_last4} ({open.country === "US" ? "ACH" : "international wire"})</Table.Td></Table.Tr>
              <Table.Tr><Table.Td c="dimmed">Domain</Table.Td><Table.Td ff="monospace">{open.email_domain}</Table.Td></Table.Tr>
              <Table.Tr><Table.Td c="dimmed">Tax ID</Table.Td><Table.Td ff="monospace">{open.tax_id ?? "missing"} · {open.country === "US" ? "W-9" : "W-8BEN-E"}</Table.Td></Table.Tr>
              <Table.Tr><Table.Td c="dimmed">Payment terms</Table.Td><Table.Td>{terms(open)}{open.terms && <Text fz="xs" c="dimmed">{open.terms.source}</Text>}</Table.Td></Table.Tr>
              <Table.Tr><Table.Td c="dimmed">Status</Table.Td><Table.Td>{open.on_probation ? "Probation (tighter checks)" : "Active"}{open.critical ? " · critical supplier" : ""}</Table.Td></Table.Tr>
            </Table.Tbody></Table>
            {of(open).flatMap((b) => b.signals).filter((s) => s.code === "bank_mismatch").map((s, i) =>
              <Alert key={i} color="red" variant="light" title="Bank change requested">{s.detail}</Alert>)}
            <AdvancePayments v={open} />
            <div><Text fw={600} mb="xs">What the agents remember</Text>
              {memory.filter((m) => m.subject === slug(shortName(open.name))).map((m) => (
                <Group key={m.id} justify="space-between" align="flex-start" py={6} style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }} wrap="nowrap">
                  <Text fz="sm">{m.text}</Text><Text fz="xs" c="brand.7" ff="monospace" ta="right" miw={180}>{m.provenance}<br /><Text span c="dimmed" fz="xs">since {day(m.valid_from)}</Text></Text>
                </Group>
              ))}
              {!memory.some((m) => m.subject === slug(shortName(open.name))) && <Text fz="sm" c="dimmed">Nothing remembered yet.</Text>}
            </div>
            <div><Text fw={600} mb="xs">Bills</Text><BillsTable bills={of(open)} footer={false} /></div>
          </Stack>
        )}
      </Drawer>
    </>
  );
}

/* advance payments: buy vendor credit at a discount; a controller approves; credit is applied to later bills */
function AdvancePayments({ v }: { v: Vendor }) {
  const { seat, refresh } = useApp();
  const [list, setList] = useState<Prepayment[]>([]);
  const [credit, setCredit] = useState<string | number>("");
  const [note, setNote] = useState("");
  const [q, setQ] = useState<PrepaymentQuote | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const who = me(seat);
  const load = () => { ap.prepayments(v.id).then(setList).catch(() => {}); };
  useEffect(() => { load(); setCredit(""); setQ(null); }, [v.id]);
  useEffect(() => {
    const val = String(credit);
    if (!val || Number(val) <= 0) { setQ(null); return; }
    const t = setTimeout(() => { ap.prepayQuote(v.id, val).then(setQ).catch(() => setQ(null)); }, 250);
    return () => clearTimeout(t);
  }, [credit, v.id]);
  const offered = !!v.terms?.prepay_discount_pct;
  const balance = sumMoney(list.filter((p) => p.status === "paid").map((p) => p.remaining));
  const canApprove = ["controller", "cfo"].includes(seat);

  const request = async () => {
    setBusy("req");
    try {
      await ap.requestPrepayment(v.id, String(credit), who.email, note);
      notifications.show({ color: "brand", title: "Advance payment requested", message: "A controller or CFO (not you) must approve it." });
      setCredit(""); setNote(""); load();
    } catch (e) { notifications.show({ color: "red", title: "Can't request", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(null); }
  };
  const decide = async (p: Prepayment, decision: "approved" | "rejected") => {
    setBusy(p.id + decision);
    try {
      await ap.decidePrepayment(p.id, { approver: who.email, role: who.role, decision, comment: "" });
      notifications.show({ color: decision === "approved" ? "green" : "gray", title: decision === "approved" ? "Paid (simulated) · credit opened" : "Rejected",
        message: `${amount(p.credit_amount, p.currency)} of credit with ${shortName(v.name)}` });
      load(); refresh();
    } catch (e) { notifications.show({ color: "red", title: "Not allowed", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(null); }
  };

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" mb={4}><Text fw={600}>Advance payments</Text><Text fz="sm">Prepaid credit <b>{amount(balance, v.currency)}</b></Text></Group>
      {!offered ? <Text fz="sm" c="dimmed">This vendor's contract has no advance-payment discount.</Text> : (
        <>
          <Text fz="xs" c="dimmed" mb="sm">{pctText(v.terms!.prepay_discount_pct)} off when Helix pays in advance · up to {usd(v.terms!.prepay_cap_usd)} open at once ·
            credit is applied automatically to this vendor's next bills. Prepayments skip the 3-way match, so a controller or CFO must approve.</Text>
          {v.on_probation ? <Alert color="orange" variant="light">Vendors on probation can't be prepaid.</Alert> : (
            <Group align="flex-end" gap="sm">
              <NumberInput label={`Credit wanted (${v.currency})`} value={credit} onChange={setCredit} min={0} thousandSeparator="," decimalScale={2} w={200} />
              <TextInput label="Reason" placeholder="e.g. Q1 allocation" value={note} onChange={(e) => setNote(e.currentTarget.value)} style={{ flex: 1 }} />
              <Button disabled={!q?.allowed} loading={busy === "req"} onClick={request}>Request</Button>
            </Group>
          )}
          {q && <Text fz="sm" mt="xs" c={q.allowed ? "green.8" : "red.7"}>{q.allowed
            ? `Pay ${amount(q.cash_amount, q.currency)} now for ${amount(q.credit_amount, q.currency)} of credit · save ${amount(q.discount_amount, q.currency)}${q.cap_remaining_usd ? ` · ${usd(q.cap_remaining_usd)} of cap left` : ""}`
            : q.reason}</Text>}
        </>
      )}
      {list.length > 0 && (
        <Table fz="xs" mt="sm" verticalSpacing={6}>
          <Table.Thead><Table.Tr><Table.Th>Requested</Table.Th><Table.Th ta="right">Credit</Table.Th><Table.Th ta="right">Cash</Table.Th><Table.Th ta="right">Left</Table.Th><Table.Th>Status</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>{list.map((p) => (
            <Table.Tr key={p.id}>
              <Table.Td>{p.requested_by.split("@")[0]} · {when(p.requested_at)}{p.note && <Text fz={10} c="dimmed">{p.note}</Text>}</Table.Td>
              <Table.Td ta="right" ff="monospace">{amount(p.credit_amount)}</Table.Td><Table.Td ta="right" ff="monospace">{amount(p.cash_amount)}</Table.Td>
              <Table.Td ta="right" ff="monospace">{amount(p.remaining)}</Table.Td>
              <Table.Td><Badge size="xs" variant="light" color={p.status === "paid" ? "green" : p.status === "rejected" ? "gray" : "violet"}>{p.status === "paid" ? "paid · credit open" : p.status}</Badge>
                {p.applied.length > 0 && <Text fz={10} c="dimmed">applied to {p.applied.map((a) => a.case_id).join(", ")}</Text>}</Table.Td>
              <Table.Td>{p.status === "requested" && (
                <Group gap={4} wrap="nowrap">
                  <Tooltip label={p.requested_by === who.email ? "You requested it" : "Needs a controller or CFO"} disabled={p.requested_by !== who.email && canApprove}>
                    <Button size="compact-xs" color="green" disabled={p.requested_by === who.email || !canApprove} loading={busy === p.id + "approved"} onClick={() => decide(p, "approved")}>Approve & pay</Button>
                  </Tooltip>
                  <Button size="compact-xs" variant="default" loading={busy === p.id + "rejected"} onClick={() => decide(p, "rejected")}>Reject</Button>
                </Group>)}</Table.Td>
            </Table.Tr>))}</Table.Tbody>
        </Table>
      )}
    </Card>
  );
}

/* onboarding */
const CHECK_ICON: Record<string, { c: string; i: ReactNode }> = {
  pass: { c: "green", i: <IconCheck size={14} /> }, warn: { c: "orange", i: <IconAlertTriangle size={14} /> }, fail: { c: "red", i: <IconX size={14} /> },
  not_covered: { c: "gray", i: <IconMinus size={14} /> }, incomplete: { c: "yellow", i: <IconClockPause size={14} /> },
};

function Onboarding({ cases, reload }: { cases: OnboardingCase[]; reload: () => void }) {
  const [form, setForm] = useState(false);
  const [open, setOpen] = useState<OnboardingCase | null>(null);
  return (
    <>
      <Group justify="space-between" mb="sm">
        <Text c="dimmed" fz="sm">Vendors never sign themselves up. Someone at Helix requests them; ReconAI runs CRS and code checks; a second person approves.</Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setForm(true)}>New vendor request</Button>
      </Group>
      <Card withBorder padding={0}>
        {cases.length === 0 ? <Text c="dimmed" fz="sm" ta="center" py="xl">No requests yet.</Text> : (
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead bg="gray.0"><Table.Tr><Table.Th>Vendor</Table.Th><Table.Th>Requested by</Table.Th><Table.Th>Checks</Table.Th><Table.Th>Risk</Table.Th><Table.Th>Status</Table.Th><Table.Th>Needs</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{cases.map((c) => {
              const fails = c.checks.filter((x) => x.status === "fail").length;
              const warns = c.checks.filter((x) => ["warn", "incomplete", "not_covered"].includes(x.status)).length;
              return (
                <Table.Tr key={c.id} style={{ cursor: "pointer" }} onClick={() => setOpen(c)}>
                  <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={c.request.legal_name} /><div><Text fz="sm" fw={500}>{c.request.legal_name}</Text><Text fz="xs" c="dimmed">{c.request.country} · {c.request.email_domain}</Text></div></Group></Table.Td>
                  <Table.Td><Text fz="sm">{c.request.requested_by.split("@")[0]}</Text><Text fz="xs" c="dimmed">{when(c.created_at)}</Text></Table.Td>
                  <Table.Td><Group gap={4}>{fails > 0 && <Badge size="sm" color="red" variant="light">{fails} failed</Badge>}{warns > 0 && <Badge size="sm" color="orange" variant="light">{warns} to review</Badge>}
                    {!fails && !warns && <Badge size="sm" color="green" variant="light">all passed</Badge>}</Group></Table.Td>
                  <Table.Td><Badge variant="light" color={RISK[c.risk_tier]}>{c.risk_tier}</Badge></Table.Td>
                  <Table.Td><Badge variant="light" color={c.status === "approved" ? "green" : c.status === "rejected" ? "gray" : "violet"}>{c.status.replace("_", " ")}</Badge></Table.Td>
                  <Table.Td><Text fz="sm">{c.status === "needs_review" ? PEOPLE[c.needs as Seat]?.title : "—"}</Text></Table.Td>
                </Table.Tr>);
            })}</Table.Tbody>
          </Table>
        )}
      </Card>
      <RequestForm opened={form} onClose={() => setForm(false)} onDone={(c) => { setForm(false); reload(); setOpen(c); }} />
      <CaseDrawer c={open} onClose={() => setOpen(null)} onDone={(c) => { reload(); setOpen(c); }} />
    </>
  );
}

const BLANK: OnboardingRequestIn = { legal_name: "", country: "US", currency: "USD", tax_id: "", address: "", city: "", state: "", zip: "", email_domain: "",
  website: "", bank_last4: "", contact_name: "", contact_phone: "", expected_annual_spend_usd: "0", requested_by: "" };

function RequestForm({ opened, onClose, onDone }: { opened: boolean; onClose: () => void; onDone: (c: OnboardingCase) => void }) {
  const { seat } = useApp();
  const [samples, setSamples] = useState<{ label: string; request: OnboardingRequestIn }[]>([]);
  const [r, setR] = useState<OnboardingRequestIn>(BLANK);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (opened) { ap.onboardingSamples().then(setSamples).catch(() => {}); setR({ ...BLANK, requested_by: me(seat).email }); } }, [opened]);
  const f = (k: keyof OnboardingRequestIn) => ({ value: (r[k] as string | null) ?? "", onChange: (e: ChangeEvent<HTMLInputElement>) => setR({ ...r, [k]: e.currentTarget.value }) });
  const submit = async () => {
    setBusy(true);
    try { onDone(await ap.submitOnboarding({ ...r, tax_id: r.tax_id || null, bank_last4: r.bank_last4.slice(-4) })); }
    catch (e) { notifications.show({ color: "red", title: "Couldn't submit", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(false); }
  };
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="lg" title={<Text fw={650} fz="lg">New vendor request</Text>}>
      <Stack>
        <Select label="Load a sample request (fictional businesses)" placeholder="Pick one" clearable
          data={samples.map((s, i) => ({ value: String(i), label: s.label }))} onChange={(v) => v != null && setR(samples[Number(v)].request)} />
        <SimpleGrid cols={2}>
          <TextInput label="Legal name" required {...f("legal_name")} />
          <TextInput label="Country (ISO)" required {...f("country")} />
          <TextInput label="Tax ID (W-9 / W-8BEN-E)" {...f("tax_id")} />
          <TextInput label="Currency" {...f("currency")} />
          <TextInput label="Street address" {...f("address")} />
          <TextInput label="City" {...f("city")} />
          <TextInput label="State" {...f("state")} />
          <TextInput label="ZIP" {...f("zip")} />
          <TextInput label="Email domain" required {...f("email_domain")} />
          <TextInput label="Bank account (last 4 only)" required maxLength={4} {...f("bank_last4")} />
          <TextInput label="Contact name" {...f("contact_name")} />
          <TextInput label="Contact phone" {...f("contact_phone")} />
          <TextInput label="Expected annual spend (USD)" {...f("expected_annual_spend_usd")} />
          <TextInput label="Requested by" {...f("requested_by")} />
        </SimpleGrid>
        <Alert variant="light" color="gray">On submit, ReconAI runs CRS business identity, credit, public-record and sanctions checks, plus duplicate-vendor, employee-bank, look-alike-domain and tax-form checks.</Alert>
        <Button loading={busy} disabled={!r.legal_name || !r.email_domain || r.bank_last4.length < 4} onClick={submit}>Submit and run checks</Button>
      </Stack>
    </Drawer>
  );
}

function CaseDrawer({ c, onClose, onDone }: { c: OnboardingCase | null; onClose: () => void; onDone: (c: OnboardingCase) => void }) {
  const { seat } = useApp();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  if (!c) return null;
  const who = me(seat);
  const act = async (what: "approved" | "rejected" | "recheck") => {
    setBusy(what);
    try {
      const out = what === "recheck" ? await ap.recheckOnboarding(c.id) : await ap.decideOnboarding(c.id, { approver: who.email, role: who.role, decision: what, comment });
      notifications.show({ color: what === "approved" ? "green" : "gray",
        title: what === "approved" ? `${out.request.legal_name} added (on probation)` : what === "recheck" ? "Checks re-run" : "Rejected", message: out.vendor_id ?? "" });
      onDone(out);
    } catch (e) { notifications.show({ color: "red", title: "Not allowed", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(null); }
  };
  const blocked = c.checks.some((x) => x.status === "fail" && ["Sanctions (OFAC)", "Bank account vs employees"].includes(x.name));
  return (
    <Drawer opened onClose={onClose} position="right" size="xl"
      title={<Group gap="sm"><Text fw={650} fz="lg">{c.request.legal_name}</Text><Badge variant="light" color={RISK[c.risk_tier]}>{c.risk_tier} risk</Badge></Group>}>
      <Stack>
        <Text fz="sm" c="dimmed">{c.request.country} · {c.request.email_domain} · bank •••• {c.request.bank_last4} · requested by {c.request.requested_by} · {when(c.created_at)}</Text>
        {c.crs_mode === "simulated" && <Alert variant="light" color="yellow">CRS is in simulated sandbox mode (no CRS credentials configured). Results come from fictional test businesses.</Alert>}
        <Card withBorder padding="sm">
          <Stack gap="sm">{c.checks.map((x) => (
            <Group key={x.name} gap="sm" wrap="nowrap" align="flex-start">
              <ThemeIcon size="sm" radius="xl" color={CHECK_ICON[x.status].c} variant={x.status === "pass" ? "filled" : "light"}>{CHECK_ICON[x.status].i}</ThemeIcon>
              <div style={{ flex: 1 }}>
                <Group gap={6}><Text fz="sm" fw={600}>{x.name}</Text><Badge size="xs" variant="default" tt="none">{x.provider}{x.simulated ? " · simulated" : ""}</Badge>
                  <Badge size="xs" variant="light" color={CHECK_ICON[x.status].c}>{x.status.replace("_", " ")}</Badge></Group>
                <Text fz="sm" c="dimmed">{x.detail}</Text>
              </div>
            </Group>))}</Stack>
        </Card>
        {c.status === "needs_review" ? (
          <Card withBorder padding="md">
            <Text fw={600} mb={4}>Decision</Text>
            <Text fz="sm" c="dimmed" mb="sm">{c.risk_tier === "low" ? "Low risk: any AP lead or above can approve." : `${c.risk_tier[0].toUpperCase()}${c.risk_tier.slice(1)} risk: needs a controller.`} The requester can't approve. Approved vendors start on probation.
              {blocked && " A sanctions or employee-bank match can't be approved here."}</Text>
            <Textarea placeholder="Note for the audit trail" value={comment} onChange={(e) => setComment(e.currentTarget.value)} mb="sm" autosize minRows={2} />
            <Group>
              <Button color="green" loading={busy === "approved"} disabled={blocked} onClick={() => act("approved")}>Approve vendor</Button>
              <Button variant="outline" color="red" loading={busy === "rejected"} onClick={() => act("rejected")}>Reject</Button>
              {c.checks.some((x) => x.status === "incomplete") && <Button variant="default" loading={busy === "recheck"} onClick={() => act("recheck")}>Re-run checks</Button>}
            </Group>
          </Card>
        ) : <Alert color={c.status === "approved" ? "green" : "gray"} variant="light" title={c.status === "approved" ? `Approved · added as ${c.vendor_id} (probation)` : "Rejected"}>
          by {c.decided_by} · {c.decided_at && when(c.decided_at)}{c.decision_comment && ` · “${c.decision_comment}”`}</Alert>}
      </Stack>
    </Drawer>
  );
}
