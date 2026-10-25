// Vendors: the vendor master (terms, tax, risk, memory, advance payments) and vendor onboarding with CRS checks.
// Bank details: last 4 only. New vendors: requested inside Helix, verified, approved by a second person.
// Layout: the page fits the window; picking a vendor splits it into a short list and a sectioned vendor panel.
import { ActionIcon, Alert, Anchor, Badge, Box, Button, Card, Checkbox, Collapse, Drawer, Group, NumberInput, ScrollArea, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Textarea, ThemeIcon, Tooltip, UnstyledButton, parseThemeColor, useMantineTheme } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconBrandSlack, IconCheck, IconChevronRight, IconCircleCheck, IconClockPause, IconFileText, IconMinus, IconPlus, IconShieldExclamation, IconX } from "@tabler/icons-react";
import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import type { Bill, MemoryEntry, OnboardingCase, OnboardingRequestIn, OutboundEmail, Prepayment, PrepaymentQuote, Vendor, VendorContract } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, currencySymbol, day, PEOPLE, RISK, shortName, sumMoney, usd, when, type Seat } from "../format";
import { EmailCard, EmailStatusBadge } from "../emails";
import { Avatarish, CardHead, HEAD_BG, HEAD_BORDER, StageBadge } from "../parts";

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const pctText = (p?: string | null) => (p ? `${(Number(p) * 100).toFixed(1).replace(/\.0$/, "")}%` : "");
const terms = (v: Vendor) => (v.terms?.discount_pct ? `${pctText(v.terms.discount_pct).replace("%", "")}/${v.terms.discount_days} net ${v.terms.net_days}` : `net ${v.terms?.net_days ?? 30}`);
const method = (v: Vendor) => (v.country === "US" ? "ACH" : "International wire");
const taxForm = (v: Vendor) => (v.country === "US" ? "W-9" : "W-8BEN-E");
const CLOSED = ["paid", "rejected"];
const WAITING = ["needs_review", "on_hold", "blocked"];
/** Backend prose says "USD 15,200.00" or "15200.00 USD"; show "$15,200.00" like every other amount. */
const sym = (s: string) => s
  .replace(/\b(USD|TWD|MYR|KRW|EUR) (-?\d[\d,]*(?:\.\d+)?)/g, (_, c: string, n: string) => amount(n.replace(/,/g, ""), c))
  .replace(/(-?\d[\d,]*\.\d{2}) (USD|TWD|MYR|KRW|EUR)\b/g, (_, n: string, c: string) => amount(n.replace(/,/g, ""), c));
const dayShort = (iso: string) => day(iso).replace(`, ${new Date().getFullYear()}`, "");
const STAGE_ORDER = ["processing", "needs_review", "on_hold", "blocked", "ready_to_pay", "scheduled", "partially_paid", "failed", "paid", "rejected"];
const byStage = (bs: Bill[]) => [...bs].sort((a, b) => STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage) || (a.days_to_due ?? 9999) - (b.days_to_due ?? 9999));
/** A sticky table header paints its own background, so resolve the shared header tint to a CSS colour. */
const useHeadBg = () => parseThemeColor({ color: HEAD_BG, theme: useMantineTheme() }).value;
const PAGE_H = "calc(100vh - 124px)";   // 60px header + 2 x 32px shell padding

export default function Vendors({ openId }: { openId?: string }) {
  const { vendors, bills, go } = useApp();
  const headBg = useHeadBg();
  const [tab, setTab] = useState<string>("vendors");
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [onb, setOnb] = useState<OnboardingCase[]>([]);
  const [form, setForm] = useState(false);
  const loadOnb = () => { ap.onboarding().then(setOnb).catch(() => {}); };
  useEffect(() => { ap.memory().then(setMemory).catch(() => {}); loadOnb(); }, []);
  useEffect(() => { if (openId) setTab("vendors"); }, [openId]);
  const list = Object.values(vendors);
  const open = openId ? vendors[openId] ?? null : null;
  const of = (v: Vendor) => bills.filter((b) => b.vendor_id === v.id);
  const live = (v: Vendor) => of(v).filter((b) => !CLOSED.includes(b.stage));
  const openUsd = (v: Vendor) => sumMoney(live(v).map((b) => b.payable_usd ?? b.amount_usd));
  // risk of what is still open: a rejected duplicate is already handled
  const risk = (v: Vendor) => (live(v).some((b) => b.risk === "high") ? "high" : live(v).some((b) => b.risk === "medium") ? "medium" : "low");
  const waiting = (v: Vendor) => live(v).filter((b) => WAITING.includes(b.stage)).length;
  const pending = onb.filter((c) => c.status === "needs_review").length;
  const select = (id: string | null) => go(id ? `vendors/${id}` : "vendors");

  return (
    <Box style={{ height: PAGE_H, minHeight: 560, display: "flex", flexDirection: "column", gap: "var(--mantine-spacing-md)" }}>
      <Group justify="space-between" align="flex-end" wrap="nowrap" style={{ flexShrink: 0 }}>
        <Group gap="xl" align="flex-end" wrap="nowrap">
          <Text fz={26} fw={650} lh={1.1}>Vendors</Text>
          <Tabs value={tab} onChange={(t) => { setTab(t ?? "vendors"); if (t === "onboarding" && openId) select(null); }}>
            <Tabs.List style={{ borderBottom: 0 }}>
              <Tabs.Tab value="vendors">Vendor master · {list.length}</Tabs.Tab>
              <Tabs.Tab value="onboarding" rightSection={pending ? <Badge size="xs" color="violet" circle>{pending}</Badge> : null}>Onboarding</Tabs.Tab>
            </Tabs.List>
          </Tabs>
        </Group>
        {tab === "onboarding" && <Button size="sm" leftSection={<IconPlus size={16} />} onClick={() => setForm(true)}>New vendor request</Button>}
      </Group>

      {tab === "onboarding" ? <Onboarding cases={onb} reload={loadOnb} form={form} setForm={setForm} /> : open ? (
        <Box style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "clamp(240px, 20vw, 300px) minmax(0, 1fr)", gap: "var(--mantine-spacing-md)" }}>
          <Card withBorder padding={0} style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <CardHead title="All vendors" mb={0} px="md" />
            <ScrollArea style={{ flex: 1 }}>
              {list.map((v) => (
                <UnstyledButton key={v.id} onClick={() => select(v.id)} w="100%" px="md" py={10}
                  bg={v.id === open.id ? "brand.0" : undefined} style={{ borderBottom: "1px solid var(--mantine-color-gray-2)", borderLeft: `3px solid ${v.id === open.id ? "var(--mantine-color-brand-6)" : "transparent"}` }}>
                  <Group gap="sm" wrap="nowrap">
                    <Avatarish name={v.name} size={28} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Text fz="sm" fw={500} truncate>{shortName(v.name)}</Text>
                      <Text fz="xs" c="dimmed">{usd(openUsd(v))} open{waiting(v) ? ` · ${waiting(v)} waiting` : ""}</Text>
                    </div>
                    <Tooltip label={`${risk(v)} risk`}><Box w={8} h={8} style={{ flexShrink: 0, borderRadius: 8, background: `var(--mantine-color-${RISK[risk(v)]}-${risk(v) === "low" ? 3 : 6})` }} /></Tooltip>
                  </Group>
                </UnstyledButton>
              ))}
            </ScrollArea>
          </Card>
          <VendorPanel key={open.id} v={open} bills={of(open)} openUsd={openUsd(open)} risk={risk(open)}
            memory={memory.filter((m) => m.subject === slug(shortName(open.name)))} onClose={() => select(null)} />
        </Box>
      ) : (
        <Card withBorder padding={0} style={{ flex: "0 1 auto", minHeight: 0, display: "flex", flexDirection: "column" }}>
          <Box style={{ overflow: "auto", minHeight: 0 }}>
            <Table highlightOnHover verticalSpacing="sm" stickyHeader styles={{ th: { background: headBg } }}>
              <Table.Thead style={{ zIndex: 1 }}>
                <Table.Tr style={{ borderBottom: HEAD_BORDER }}><Table.Th>Vendor</Table.Th><Table.Th ta="right">Open balance</Table.Th><Table.Th>Waiting on us</Table.Th><Table.Th>Terms</Table.Th><Table.Th>Pays to</Table.Th><Table.Th>Risk</Table.Th><Table.Th w={28} /></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.map((v) => (
                  <Table.Tr key={v.id} style={{ cursor: "pointer" }} onClick={() => select(v.id)}>
                    <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={v.name} />
                      <div><Group gap={6}><Text fz="sm" fw={500}>{shortName(v.name)}</Text><StatusBadges v={v} size="xs" /></Group>
                        <Text fz="xs" c="dimmed">{v.country} · {v.email_domain}</Text></div></Group></Table.Td>
                    <Table.Td ta="right" ff="monospace" fz="sm">{usd(openUsd(v))}</Table.Td>
                    <Table.Td>{waiting(v) ? <Text fz="sm">{waiting(v)} bill{waiting(v) === 1 ? "" : "s"}</Text> : <Text fz="sm" c="dimmed">—</Text>}</Table.Td>
                    <Table.Td><Text fz="sm">{terms(v)}</Text>{v.terms?.prepay_discount_pct && <Text fz="xs" c="dimmed">{pctText(v.terms.prepay_discount_pct)} off prepaying</Text>}</Table.Td>
                    <Table.Td><Text fz="sm" ff="monospace">•••• {v.bank_last4}</Text><Text fz="xs" c="dimmed">{method(v)}</Text></Table.Td>
                    <Table.Td><Badge variant="light" color={RISK[risk(v)]}>{risk(v)}</Badge></Table.Td>
                    <Table.Td><IconChevronRight size={16} color="var(--mantine-color-gray-5)" /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Box>
        </Card>
      )}
    </Box>
  );
}

function StatusBadges({ v, size = "sm" }: { v: Vendor; size?: "xs" | "sm" }) {
  return (
    <>
      {v.critical && <Badge size={size} variant="light" tt="none">Critical supplier</Badge>}
      {v.on_probation && <Tooltip label="New vendor: tighter checks, full 3-way match, no prepayments">
        <Badge size={size} variant="light" color="orange" tt="none">Probation{v.probation_until ? ` until ${day(v.probation_until)}` : ""}</Badge></Tooltip>}
    </>
  );
}

/* ---------- the vendor panel: who / anything wrong, money, then sections behind tabs ---------- */

function VendorPanel({ v, bills, openUsd, risk, memory, onClose }: { v: Vendor; bills: Bill[]; openUsd: string; risk: string; memory: MemoryEntry[]; onClose: () => void }) {
  const { go } = useApp();
  const [section, setSection] = useState<string>("overview");
  const [prepays, setPrepays] = useState<Prepayment[]>([]);
  const [emails, setEmails] = useState<OutboundEmail[]>([]);
  const loadPrepays = () => { ap.prepayments(v.id).then(setPrepays).catch(() => {}); };
  useEffect(() => { loadPrepays(); ap.emails({ vendor_id: v.id }).then(setEmails).catch(() => setEmails([])); }, [v.id]);

  const open = bills.filter((b) => !CLOSED.includes(b.stage));
  const inv = (caseId: string) => bills.find((b) => b.case_id === caseId)?.invoice_no ?? caseId.replace("case_", "case ");
  const lines = memory.map((m) => plain(m, inv)).sort((a, b) => a.rank - b.rank);
  const overdue = lines.filter((l) => l.overdue).length;
  const bank = bills.flatMap((b) => b.signals.filter((s) => s.code === "bank_mismatch").map((s) => ({ b, s })));
  const security = open.flatMap((b) => b.signals.filter((s) => s.severity === "high" && s.code !== "bank_mismatch").map((s) => ({ b, s })));
  const count = (st: string) => open.filter((b) => b.stage === st).length;
  const requested = prepays.filter((p) => p.status === "requested").length;
  const paid = bills.filter((b) => b.payment?.status === "paid").sort((a, b) => (b.payment!.pay_date > a.payment!.pay_date ? 1 : -1))[0];
  const next = bills.filter((b) => b.payment?.status === "scheduled").sort((a, b) => (a.payment!.pay_date > b.payment!.pay_date ? 1 : -1))[0];

  const issues: { label: string; onClick: () => void }[] = [
    ...security.map(({ b, s }) => ({ label: `${s.title} · ${b.invoice_no ?? b.case_id}`, onClick: () => go(`bill/${b.case_id}`) })),
    ...([["needs_review", "need review"], ["on_hold", "on hold"], ["blocked", "payment blocked"]] as const).filter(([st]) => count(st))
      .map(([st, l]) => ({ label: `${count(st)} bill${count(st) === 1 ? "" : "s"} ${count(st) === 1 ? l.replace("need ", "needs ") : l}`, onClick: () => setSection("bills") })),
    ...(overdue ? [{ label: `${overdue} follow-up${overdue === 1 ? "" : "s"} overdue`, onClick: () => setSection("overview") }] : []),
    ...(requested ? [{ label: `${requested} advance payment${requested === 1 ? "" : "s"} awaiting approval`, onClick: () => setSection("advance") }] : []),
  ];

  return (
    <Card withBorder padding={0} style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* (a) who they are */}
      <Group px="md" py="sm" justify="space-between" wrap="nowrap" bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER, flexShrink: 0 }}>
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <Avatarish name={v.name} size={40} />
          <div style={{ minWidth: 0 }}>
            <Group gap={8} wrap="nowrap"><Text fw={650} fz={20} lh={1.2} truncate>{shortName(v.name)}</Text>
              <Badge variant="light" color={RISK[risk]}>{risk} risk</Badge><StatusBadges v={v} /></Group>
            <Tooltip label={`Also known as ${v.aliases.join(", ") || "—"}`} disabled={!v.aliases.length} position="bottom-start">
              <Text fz="xs" c="dimmed" truncate>{v.name} · {v.country} · {v.email_domain}</Text>
            </Tooltip>
          </div>
        </Group>
        <Group gap={6} wrap="nowrap">
          <Tooltip label="Back to all vendors"><ActionIcon variant="subtle" color="gray" onClick={onClose} aria-label="Close vendor"><IconX size={18} /></ActionIcon></Tooltip>
        </Group>
      </Group>

      <Stack gap="sm" px="md" pt="md" style={{ flexShrink: 0 }}>
        {/* (a) anything wrong right now: bank change in red, everything else as one row of links */}
        {bank.map(({ b, s }) => (
          <Alert key={b.case_id} color="red" variant="light" py="xs" icon={<IconShieldExclamation size={20} />}
            title={<Group gap="xs">Bank change requested · {b.invoice_no ?? b.case_id}<Anchor component="button" fz="xs" c="red.8" onClick={() => go(`bill/${b.case_id}`)}>Open bill</Anchor></Group>}>
            <Text fz="sm">{s.detail}</Text>
          </Alert>
        ))}
        {issues.length ? (
          <Group gap={6} px="sm" py={8} bg="brand.0" style={{ borderRadius: "var(--mantine-radius-md)" }}>
            <IconAlertTriangle size={16} color="var(--mantine-color-brand-7)" />
            <Text fz="sm" fw={600} c="brand.8" mr={4}>Needs attention</Text>
            {issues.map((x, i) => (
              <Anchor key={i} component="button" fz="sm" c="brand.8" onClick={x.onClick} underline="hover">{x.label}{i < issues.length - 1 ? " ·" : ""}</Anchor>
            ))}
          </Group>
        ) : !bank.length && (
          <Group gap={6} px="sm" py={8} bg="gray.0" style={{ borderRadius: "var(--mantine-radius-md)" }}>
            <IconCircleCheck size={16} color="var(--mantine-color-brand-7)" /><Text fz="sm" c="dimmed">Nothing needs attention right now.</Text>
          </Group>
        )}

        {/* (b) money */}
        <SimpleGrid cols={4} spacing="sm">
          <Kpi label="Open balance" value={usd(openUsd)} sub={`${open.length} open bill${open.length === 1 ? "" : "s"}`} />
          <Kpi label="Waiting on us" value={String(open.filter((b) => WAITING.includes(b.stage)).length)} sub="bills need a decision" onClick={() => setSection("bills")} />
          {paid ? <Kpi label="Last paid" value={usd(paid.payment!.amount_usd)} sub={day(paid.payment!.pay_date)} />
            : <Kpi label="Next payment" value={next ? usd(next.payment!.amount_usd) : "—"} sub={next ? `scheduled ${dayShort(next.payment!.pay_date)}` : "nothing scheduled"} />}
          <Kpi label="Terms" value={v.terms ? `Net ${v.terms.net_days}` : "Net 30"} tip={v.terms?.source}
            sub={v.terms?.discount_pct ? `${pctText(v.terms.discount_pct)} if paid in ${v.terms.discount_days}d` : "no early-pay discount"} />
        </SimpleGrid>
      </Stack>

      <Tabs value={section} onChange={(t) => setSection(t ?? "overview")} mt="sm" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <Tabs.List px="md" style={{ flexShrink: 0 }}>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="bills">Bills · {bills.length}</Tabs.Tab>
          <Tabs.Tab value="advance" rightSection={requested ? <Badge size="xs" circle>{requested}</Badge> : null}>Advance payments</Tabs.Tab>
          <Tabs.Tab value="emails">Emails · {emails.length}</Tabs.Tab>
        </Tabs.List>
        <ScrollArea style={{ flex: 1 }} type="auto">
          <Box p="md">
            {section === "overview" && <Overview v={v} lines={lines} />}
            {section === "bills" && <VendorBills bills={bills} />}
            {section === "advance" && <AdvancePayments v={v} list={prepays} reload={loadPrepays} />}
            {section === "emails" && <VendorEmails list={emails} />}
          </Box>
        </ScrollArea>
      </Tabs>
    </Card>
  );
}

function Kpi({ label, value, sub, tip, onClick }: { label: string; value: string; sub?: string; tip?: string; onClick?: () => void }) {
  const body = (
    <Box p="sm" style={{ border: "1px solid var(--mantine-color-gray-3)", borderRadius: "var(--mantine-radius-md)", cursor: onClick ? "pointer" : undefined, height: "100%" }} onClick={onClick}>
      <Text fz="xs" c="dimmed" fw={500}>{label}</Text>
      <Text fz={22} fw={600} lh={1.25} style={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{value}</Text>
      {sub && <Text fz="xs" c="dimmed" truncate>{sub}</Text>}
    </Box>
  );
  return tip ? <Tooltip label={tip}>{body}</Tooltip> : body;
}

/* (c) how we pay + (d) what ReconAI knows */
function Overview({ v, lines }: { v: Vendor; lines: Line[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? lines : lines.slice(0, 5);
  return (
    <Box style={{ display: "grid", gridTemplateColumns: "minmax(170px, 0.8fr) minmax(0, 2.2fr)", gap: "var(--mantine-spacing-md)", alignItems: "start" }}>
      <Card withBorder padding="md">
        <CardHead title="How we pay" mb="sm" />
        <Stack gap="sm">
          <Field label="Bank on file" value={`•••• ${v.bank_last4}`} sub={method(v)} mono />
          {v.wallet_address && <Field label="Payout wallet" value={short(v.wallet_address)} sub="Coinbase · testnet (simulated)" mono tip={v.wallet_address} />}
          <Field label="Tax ID" value={v.tax_id ?? "Missing"} sub={`${taxForm(v)} on file`} mono />
          <Field label="Contact on file" value={v.contact_email ?? "None"} sub={v.email_domain} />
        </Stack>
      </Card>

      <Card withBorder padding="md">
        <CardHead title="What ReconAI knows" mb="xs" right={lines.length > 0 && <Text fz="xs" c="dimmed">{lines.length} line{lines.length === 1 ? "" : "s"}</Text>} />
        {lines.length === 0 ? <Text fz="sm" c="dimmed">Nothing remembered yet.</Text> : (
          <>
            {shown.map((l, i) => (
              <Group key={l.id} justify="space-between" wrap="nowrap" gap="md" py={8} style={{ borderTop: i ? "1px solid var(--mantine-color-gray-2)" : undefined }}>
                <Tooltip label={l.text} multiline maw={460} disabled={l.text.length < 90} openDelay={300}>
                  <Text fz="sm" lineClamp={2} c={l.overdue ? "brand.8" : undefined} fw={l.overdue || l.rank === 0 ? 500 : undefined}>{l.text}</Text>
                </Tooltip>
                <Tooltip label={<><Text fz="xs" ff="monospace">{l.provenance}</Text><Text fz="xs">since {day(l.since)}</Text></>} position="left">
                  <Badge size="sm" variant="light" color={l.rank === 0 ? "brand" : "gray"} tt="none" style={{ flexShrink: 0 }}>{l.source}</Badge>
                </Tooltip>
              </Group>
            ))}
            {lines.length > 5 && <Anchor fz="sm" mt={4} component="button" onClick={() => setAll((x) => !x)}>{all ? "Show fewer" : `Show all ${lines.length}`}</Anchor>}
          </>
        )}
      </Card>
    </Box>
  );
}

function Field({ label, value, sub, mono, tip }: { label: string; value: string; sub?: string; mono?: boolean; tip?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <Text fz="xs" c="dimmed">{label}</Text>
      <Tooltip label={tip ?? value} disabled={!tip && value.length < 24}><Text fz="sm" fw={500} ff={mono ? "monospace" : undefined} truncate>{value}</Text></Tooltip>
      {sub && <Text fz="xs" c="dimmed" truncate>{sub}</Text>}
    </div>
  );
}

/** A memory line in plain language, with a short source label; the raw provenance stays available on hover. */
type Line = { id: string; text: string; source: string; provenance: string; since: string; rank: number; overdue: boolean };
const FOLLOW = /^(case_\d+): (\w+) due (\d{4}-\d{2}-\d{2}) overdue \(not received\)$/;
const DECISION = /^(approver|controller) (approved|rejected)( \(undisputed part only\))? on (case_\d+) \(([^)]+)\):\s*(?:\[[^\]]*\]\s*)?(.*)$/;
const singular = (w: string) => (w.endsWith("ies") ? `${w.slice(0, -3)}y` : /(ch|sh|ss)es$/.test(w) ? w.slice(0, -2) : w.slice(0, -1));
function plain(m: MemoryEntry, inv: (caseId: string) => string): Line {
  const p = m.provenance;
  const base = { id: m.id, provenance: p, since: m.valid_from, overdue: false };
  const f = m.text.match(FOLLOW);
  if (f) {
    const late = f[3] < new Date().toISOString().slice(0, 10);
    return { ...base, rank: 1, overdue: late, source: "Open follow-up",
      text: `${f[2].replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())} for ${inv(f[1])} not received · ${late ? "overdue since" : "due"} ${dayShort(f[3])}` };
  }
  const d = m.text.match(DECISION);
  if (d) {
    const split = d[6].match(/pay undisputed ([\d.]+) (\w{3}); hold ([\d.]+)/);
    const who = d[1] === "controller" ? "Controller" : "Approver";
    return { ...base, rank: 4, source: `${who} decision`,
      text: split ? `${d[5]}: paid the undisputed ${amount(split[1], split[2])}, held ${amount(split[3], split[2])}` : `${d[5]}: ${d[2]} · ${sym(d[6])}` };
  }
  if (p.startsWith("controller") || p.startsWith("approver")) return { ...base, rank: 0, source: p.startsWith("controller") ? "Controller rule" : "Approver rule", text: sym(m.text) };
  if (p.startsWith("computed") || p.startsWith("case")) {
    let t = m.text.replace(/ in case history/, "");
    if (/^1 /.test(t)) { const w = t.split(" "); const k = w.findIndex((x, i) => i > 0 && i < 4 && x.endsWith("s")); if (k > 0) w[k] = singular(w[k]); t = w.join(" "); }
    return { ...base, rank: 2, source: "From cases", text: sym(t) };
  }
  return { ...base, rank: 3, source: p.startsWith("system") ? "System of record" : p, text: sym(m.text) };
}

/* (e) bills from this vendor */
function VendorBills({ bills }: { bills: Bill[] }) {
  const { go } = useApp();
  if (!bills.length) return <Text fz="sm" c="dimmed">No bills from this vendor yet.</Text>;
  return (
    <Card withBorder padding={0}>
      {byStage(bills).map((b, i) => {
        const why = b.payment_block ?? b.warning ?? b.signals[0]?.title ?? "";
        return (
          <UnstyledButton key={b.case_id} w="100%" px="md" py={10} onClick={() => go(`bill/${b.case_id}`)} style={{ borderTop: i ? "1px solid var(--mantine-color-gray-2)" : undefined }}>
            <Group wrap="nowrap" gap="md">
              <div style={{ flex: 1, minWidth: 0 }}>
                <Group gap={6} wrap="nowrap"><Text fz="sm" fw={500} ff="monospace">{b.invoice_no ?? "Not read yet"}</Text>
                  {b.risk === "high" && !CLOSED.includes(b.stage) && <IconAlertTriangle size={14} color="var(--mantine-color-red-7)" />}</Group>
                <Text fz="xs" c="dimmed" truncate>{why ? sym(why) : b.due_date ? `Due ${day(b.due_date)}` : `Invoiced ${day(b.invoice_date)}`}</Text>
              </div>
              <Group w={130} justify="flex-end" style={{ flexShrink: 0 }}><StageBadge stage={b.stage} /></Group>
              <Text fz="sm" ff="monospace" ta="right" w={150} style={{ flexShrink: 0 }}>{b.amount ? amount(b.amount, b.currency) : "—"}</Text>
              <IconChevronRight size={16} color="var(--mantine-color-gray-5)" style={{ flexShrink: 0 }} />
            </Group>
          </UnstyledButton>
        );
      })}
    </Card>
  );
}

const short = (a: string) => (a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);

/* (g) emails: subjects first, the body on click */
function VendorEmails({ list }: { list: OutboundEmail[] }) {
  const [shown, setShown] = useState<string | null>(null);
  if (!list.length) return <Text fz="sm" c="dimmed">No emails sent to this vendor yet.</Text>;
  return (
    <Stack gap="sm">{list.map((e) => (
      <div key={e.id} onClick={() => setShown(shown === e.id ? null : e.id)} style={{ cursor: "pointer" }}>
        <EmailCard e={e} body={shown === e.id} />
      </div>))}
    </Stack>
  );
}

/* (f) advance payments: buy vendor credit at a discount; a controller approves; credit is applied to later bills */
function AdvancePayments({ v, list, reload }: { v: Vendor; list: Prepayment[]; reload: () => void }) {
  const { seat, refresh } = useApp();
  const [form, setForm] = useState(false);
  const [credit, setCredit] = useState<string | number>("");
  const [note, setNote] = useState("");
  const [q, setQ] = useState<PrepaymentQuote | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const who = me(seat);
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
      setCredit(""); setNote(""); setForm(false); reload();
    } catch (e) { notifications.show({ color: "red", title: "Can't request", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(null); }
  };
  const decide = async (p: Prepayment, decision: "approved" | "rejected") => {
    setBusy(p.id + decision);
    try {
      await ap.decidePrepayment(p.id, { approver: who.email, role: who.role, decision, comment: "" });
      notifications.show({ color: decision === "approved" ? "green" : "gray", title: decision === "approved" ? "Paid (simulated) · credit opened" : "Rejected",
        message: `${amount(p.credit_amount, p.currency)} of credit with ${shortName(v.name)}` });
      reload(); refresh();
    } catch (e) { notifications.show({ color: "red", title: "Not allowed", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(null); }
  };

  return (
    <Card withBorder padding="md">
      <CardHead title="Advance payments" mb="sm"
        right={offered && !v.on_probation && !form && <Button size="compact-sm" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setForm(true)}>New request</Button>} />
      {!offered ? <Text fz="sm" c="dimmed">Not in this vendor's contract.</Text> : (
        <>
          <SimpleGrid cols={3} spacing="md" mb="sm">
            <Field label="Discount for paying ahead" value={pctText(v.terms!.prepay_discount_pct)} sub="credit applies to the next bills" />
            <Field label="Cap (open at once)" value={usd(v.terms!.prepay_cap_usd)} mono />
            <Field label="Prepaid credit open" value={amount(balance, v.currency)} mono />
          </SimpleGrid>
          {v.on_probation && <Alert color="orange" variant="light" py="xs">Vendors on probation can't be prepaid.</Alert>}
          <Collapse in={form && !v.on_probation}>
            <Box p="sm" mb="sm" bg="gray.0" style={{ borderRadius: "var(--mantine-radius-md)" }}>
              <Group align="flex-end" gap="sm">
                <NumberInput label={`Credit wanted (${currencySymbol(v.currency).trim()})`} value={credit} onChange={setCredit} min={0} thousandSeparator="," decimalScale={2} w={200} />
                <TextInput label="Reason" placeholder="e.g. Q1 allocation" value={note} onChange={(e) => setNote(e.currentTarget.value)} style={{ flex: 1 }} />
                <Button disabled={!q?.allowed} loading={busy === "req"} onClick={request}>Request</Button>
                <Button variant="default" onClick={() => { setForm(false); setCredit(""); setNote(""); }}>Cancel</Button>
              </Group>
              {q && <Text fz="sm" mt="xs" c={q.allowed ? "green.8" : "red.7"}>{q.allowed
                ? `Pay ${amount(q.cash_amount, q.currency)} now for ${amount(q.credit_amount, q.currency)} of credit · save ${amount(q.discount_amount, q.currency)}${q.cap_remaining_usd ? ` · ${usd(q.cap_remaining_usd)} of cap left` : ""}`
                : q.reason}</Text>}
              <Text fz="xs" c="dimmed" mt="xs">Skips the 3-way match, so a controller or CFO other than you approves it.</Text>
            </Box>
          </Collapse>
        </>
      )}
      {list.length > 0 ? (
        <Table fz="xs" verticalSpacing={6}>
          <Table.Thead><Table.Tr><Table.Th>Requested</Table.Th><Table.Th ta="right">Credit</Table.Th><Table.Th ta="right">Cash</Table.Th><Table.Th ta="right">Left</Table.Th><Table.Th>Status</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>{list.map((p) => (
            <Table.Tr key={p.id}>
              <Table.Td>{p.requested_by.split("@")[0]} · {when(p.requested_at)}{p.note && <Text fz={10} c="dimmed">{p.note}</Text>}</Table.Td>
              <Table.Td ta="right" ff="monospace">{amount(p.credit_amount, p.currency)}</Table.Td><Table.Td ta="right" ff="monospace">{amount(p.cash_amount, p.currency)}</Table.Td>
              <Table.Td ta="right" ff="monospace">{amount(p.remaining, p.currency)}</Table.Td>
              <Table.Td><Badge size="xs" variant="light" color={p.status === "paid" ? "green" : p.status === "rejected" ? "gray" : "violet"}>{p.status === "paid" ? "paid · credit open" : p.status}</Badge>
                {p.applied.length > 0 && <Tooltip label={p.applied.map((a) => a.case_id).join(", ")}><Text fz={10} c="dimmed">applied to {p.applied.length} bill{p.applied.length === 1 ? "" : "s"}</Text></Tooltip>}</Table.Td>
              <Table.Td>{p.status === "requested" && (
                <Group gap={4} wrap="nowrap">
                  <Tooltip label={p.requested_by === who.email ? "You requested it" : "Needs a controller or CFO"} disabled={p.requested_by !== who.email && canApprove}>
                    <Button size="compact-xs" color="green" disabled={p.requested_by === who.email || !canApprove} loading={busy === p.id + "approved"} onClick={() => decide(p, "approved")}>Approve & pay</Button>
                  </Tooltip>
                  <Button size="compact-xs" variant="default" loading={busy === p.id + "rejected"} onClick={() => decide(p, "rejected")}>Reject</Button>
                </Group>)}</Table.Td>
            </Table.Tr>))}</Table.Tbody>
        </Table>
      ) : offered && <Text fz="sm" c="dimmed">No advance payments yet.</Text>}
    </Card>
  );
}


/* onboarding */
const CHECK_ICON: Record<string, { c: string; i: ReactNode }> = {
  pass: { c: "green", i: <IconCheck size={14} /> }, warn: { c: "orange", i: <IconAlertTriangle size={14} /> }, fail: { c: "red", i: <IconX size={14} /> },
  not_covered: { c: "gray", i: <IconMinus size={14} /> }, incomplete: { c: "yellow", i: <IconClockPause size={14} /> },
};

function Onboarding({ cases, reload, form, setForm }: { cases: OnboardingCase[]; reload: () => void; form: boolean; setForm: (x: boolean) => void }) {
  const headBg = useHeadBg();
  const [open, setOpen] = useState<OnboardingCase | null>(null);
  const [contracts, setContracts] = useState<VendorContract[]>([]);
  const [emails, setEmails] = useState<OutboundEmail[]>([]);
  useEffect(() => { ap.contracts().then(setContracts).catch(() => {}); ap.emails().then(setEmails).catch(() => {}); }, [cases]);
  return (
    <>
      <Card withBorder padding={0} style={{ flex: "0 1 auto", minHeight: 0, display: "flex", flexDirection: "column" }}>
        {cases.length === 0 ? (
          <Stack align="center" gap={6} py={48}>
            <Text fw={600}>No vendor requests yet</Text>
            <Text c="dimmed" fz="sm">Requested inside Helix, checked by CRS and code, approved by a second person.</Text>
          </Stack>
        ) : (
          <Box style={{ overflow: "auto", minHeight: 0 }}>
          <Table highlightOnHover verticalSpacing="sm" stickyHeader styles={{ th: { background: headBg } }}>
            <Table.Thead style={{ zIndex: 1 }}><Table.Tr style={{ borderBottom: HEAD_BORDER }}><Table.Th>Vendor</Table.Th><Table.Th>Requested by</Table.Th><Table.Th>Checks</Table.Th><Table.Th>Risk</Table.Th><Table.Th>Status</Table.Th><Table.Th>Needs</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{cases.map((c) => {
              const fails = c.checks.filter((x) => x.status === "fail").length;
              const warns = c.checks.filter((x) => ["warn", "incomplete", "not_covered"].includes(x.status)).length;
              return (
                <Table.Tr key={c.id} style={{ cursor: "pointer" }} onClick={() => setOpen(c)}>
                  <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={c.request.legal_name} /><div><Group gap={6}><Text fz="sm" fw={500}>{c.request.legal_name}</Text><SourceBadge c={c} /></Group>
                    <Text fz="xs" c="dimmed">{c.request.country} · {c.request.email_domain}{c.contract_id ? ` · contract ${c.contract_id}` : ""}</Text></div></Group></Table.Td>
                  <Table.Td><Text fz="sm">{c.request.requested_by.split("@")[0]}</Text><Text fz="xs" c="dimmed">{when(c.created_at)}</Text></Table.Td>
                  <Table.Td><Group gap={4}>{fails > 0 && <Badge size="sm" color="red" variant="light">{fails} failed</Badge>}{warns > 0 && <Badge size="sm" color="orange" variant="light">{warns} to review</Badge>}
                    {!fails && !warns && <Badge size="sm" color="green" variant="light">all passed</Badge>}</Group></Table.Td>
                  <Table.Td><Badge variant="light" color={RISK[c.risk_tier]}>{c.risk_tier}</Badge></Table.Td>
                  <Table.Td><Badge variant="light" color={c.status === "approved" ? "green" : c.status === "rejected" ? "gray" : "violet"}>{c.status.replace("_", " ")}</Badge>
                    {c.auto_approved && <Badge size="xs" variant="light" color="brand" ml={4} tt="none">auto-approved by policy</Badge>}</Table.Td>
                  <Table.Td><Text fz="sm">{c.status === "needs_review" ? PEOPLE[c.needs as Seat]?.title : "—"}</Text></Table.Td>
                </Table.Tr>);
            })}</Table.Tbody>
          </Table>
          </Box>
        )}
      </Card>
      <RequestForm opened={form} onClose={() => setForm(false)} onDone={(c) => { setForm(false); reload(); setOpen(c); }} />
      <CaseDrawer c={open} onClose={() => setOpen(null)} onDone={(c) => { reload(); setOpen(c); }}
        contract={contracts.find((k) => k.id === open?.contract_id) ?? null}
        confirmation={emails.filter((e) => e.kind === "onboarding_confirmation" && (e.id === open?.confirmation_email_id || (!!open?.vendor_id && e.vendor_id === open.vendor_id))).at(-1) ?? null} />
    </>
  );
}

const BLANK: OnboardingRequestIn = { legal_name: "", country: "US", currency: "USD", tax_id: "", address: "", city: "", state: "", zip: "", email_domain: "",
  website: "", bank_last4: "", contact_name: "", contact_phone: "", expected_annual_spend_usd: "0", requested_by: "", tax_form: null, trade_names: [], contact_email: "",
  principal_persona: null, credit_consent: false };

function RequestForm({ opened, onClose, onDone }: { opened: boolean; onClose: () => void; onDone: (c: OnboardingCase) => void }) {
  const { seat } = useApp();
  const [samples, setSamples] = useState<{ label: string; request: OnboardingRequestIn }[]>([]);
  const [personas, setPersonas] = useState<{ id: string; name: string; profile: string; decision: string }[]>([]);
  const [r, setR] = useState<OnboardingRequestIn>(BLANK);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (opened) { ap.onboardingSamples().then(setSamples).catch(() => {}); ap.crsPersonas().then(setPersonas).catch(() => {}); setR({ ...BLANK, requested_by: me(seat).email }); } }, [opened]);
  const f = (k: keyof OnboardingRequestIn) => ({ value: (r[k] as string | null) ?? "", onChange: (e: ChangeEvent<HTMLInputElement>) => setR({ ...r, [k]: e.currentTarget.value }) });
  const submit = async () => {
    setBusy(true);
    try { onDone(await ap.submitOnboarding({ ...r, tax_id: r.tax_id || null, contact_email: r.contact_email || null, bank_last4: r.bank_last4.slice(-4) })); }
    catch (e) { notifications.show({ color: "red", title: "Couldn't submit", message: e instanceof Error ? e.message : String(e) }); } finally { setBusy(false); }
  };
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="lg" title={<Text fw={650} fz="lg">New vendor request</Text>}>
      <Stack>
        <Select label="Load a sample request (fictional businesses)" placeholder="Pick one" clearable
          data={samples.map((s, i) => ({ value: String(i), label: s.label }))} onChange={(v) => v != null && setR({ ...BLANK, ...samples[Number(v)].request })} />
        <Select label="Owner / authorized signer (CRS sandbox test persona)" placeholder="Pick who plays the owner" clearable searchable
          value={r.principal_persona ?? null} onChange={(v) => setR({ ...r, principal_persona: v })}
          data={personas.map((p) => ({ value: p.id, label: `${p.id} · ${p.name} · ${p.profile}` }))}
          description="ReconAI verifies the person behind the company with CRS: identity, fraud signals, court records, phone. Sandbox personas only; no real person is looked up." />
        <Checkbox label="The owner consents to a soft credit check (no score impact)" checked={!!r.credit_consent}
          onChange={(e) => setR({ ...r, credit_consent: e.currentTarget.checked })} />
        <SimpleGrid cols={2}>
          <TextInput label="Legal name" required {...f("legal_name")} />
          <TextInput label="Country (ISO)" required {...f("country")} />
          <TextInput label="Tax ID" {...f("tax_id")} />
          <Select label="Tax form received" placeholder="None yet" clearable value={r.tax_form ?? null} onChange={(v) => setR({ ...r, tax_form: v })}
            data={["W-9", "W-8BEN-E"]} description="W-9 for US vendors, W-8BEN-E otherwise" />
          <TextInput label="Currency" {...f("currency")} />
          <TextInput label="Street address" {...f("address")} />
          <TextInput label="City" {...f("city")} />
          <TextInput label="State" {...f("state")} />
          <TextInput label="ZIP" {...f("zip")} />
          <TextInput label="Email domain" required {...f("email_domain")} />
          <TextInput label="Bank account (last 4 only)" required maxLength={4} {...f("bank_last4")} />
          <TextInput label="Contact name" {...f("contact_name")} />
          <TextInput label="Contact phone" {...f("contact_phone")} />
          <TextInput label="Contact email (confirmation goes here)" type="email" {...f("contact_email")} description="Becomes the verified contact on file once approved" />
          <TextInput label="Expected annual spend (USD)" {...f("expected_annual_spend_usd")} />
          <TextInput label="Requested by" {...f("requested_by")} />
        </SimpleGrid>
        <Alert variant="light" color="gray">On submit, ReconAI runs CRS on the owner (TransUnion identity, AtData fraud risk, PitchPoint bankruptcies/liens/judgments, AccurateAppend phone lookup, and an Experian soft pull if consented), plus duplicate-vendor, sanctions-list, employee-bank, look-alike-domain and tax-form checks.</Alert>
        <Button loading={busy} disabled={!r.legal_name || !r.email_domain || r.bank_last4.length < 4} onClick={submit}>Submit and run checks</Button>
      </Stack>
    </Drawer>
  );
}

function SourceBadge({ c }: { c: OnboardingCase }) {
  return c.source === "slack" ? <Badge size="xs" variant="light" color="grape" tt="none" leftSection={<IconBrandSlack size={11} />}>Slack</Badge> : null;
}

function ContractCard({ k, id }: { k: VendorContract | null; id: string }) {
  const t = k?.terms;
  return (
    <Card withBorder padding="md">
      <CardHead mb="xs" title={<Group gap={6} wrap="nowrap"><IconFileText size={16} /><Anchor fz="sm" fw={600} href={ap.contractPdfUrl(id)} target="_blank" rel="noopener noreferrer">Contract {id} (PDF)</Anchor></Group>}
        right={k && <Group gap={6}><Badge size="xs" variant="light" color={k.status === "onboarded" ? "green" : k.status === "held" ? "red" : "gray"}>{k.status}</Badge>
          <Text fz="xs" c="dimmed">{k.channel} · {k.accepted_by ? `accepted by ${k.accepted_by}` : `requested by ${k.requested_by}`}</Text></Group>} />
      {k && (
        <>
          <Table fz="xs" verticalSpacing={4}>
            <Table.Thead><Table.Tr><Table.Th>Item</Table.Th><Table.Th ta="right">Qty</Table.Th><Table.Th ta="right">Unit price</Table.Th><Table.Th ta="right">Amount</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{k.items.map((it, i) => (
              <Table.Tr key={i}><Table.Td>{String(it.description ?? "")}{it.sku != null && <Text fz={10} c="dimmed" ff="monospace">{String(it.sku)}</Text>}</Table.Td>
                <Table.Td ta="right">{it.qty != null ? `${Number(it.qty).toLocaleString()} ${String(it.unit ?? "")}` : ""}</Table.Td>
                <Table.Td ta="right" ff="monospace">{amount(it.unit_price as string | null)}</Table.Td><Table.Td ta="right" ff="monospace">{amount(it.amount as string | null)}</Table.Td></Table.Tr>))}</Table.Tbody>
          </Table>
          <Group justify="space-between" mt="xs">
            <Text fz="xs" c="dimmed">{t ? `net ${t.net_days}${t.discount_pct ? ` · ${pctText(t.discount_pct)} if paid in ${t.discount_days}d` : ""}${t.prepay_discount_pct ? ` · ${pctText(t.prepay_discount_pct)} off prepayments` : ""}` : ""}
              {k.delivery ? ` · ${k.delivery}` : ""}{k.warranty ? ` · ${k.warranty}` : ""}</Text>
            <Text fz="sm" fw={600}>Total {amount(k.total, k.currency)}</Text>
          </Group>
          {k.other_terms.length > 0 && <Text fz="xs" c="dimmed" mt={4}>{k.other_terms.join(" · ")}</Text>}
        </>
      )}
    </Card>
  );
}

function CaseDrawer({ c, onClose, onDone, contract, confirmation }: { c: OnboardingCase | null; onClose: () => void; onDone: (c: OnboardingCase) => void;
  contract: VendorContract | null; confirmation: OutboundEmail | null }) {
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
      title={<Group gap="sm"><Text fw={650} fz="lg">{c.request.legal_name}</Text><Badge variant="light" color={RISK[c.risk_tier]}>{c.risk_tier} risk</Badge><SourceBadge c={c} />
        {c.auto_approved && <Badge variant="light" color="brand" tt="none">Auto-approved by policy</Badge>}</Group>}>
      <Stack>
        <Text fz="sm" c="dimmed">{c.request.country} · {c.request.email_domain} · bank •••• {c.request.bank_last4}{c.request.contact_email ? ` · contact ${c.request.contact_email}` : ""} · requested by {c.request.requested_by} · {when(c.created_at)}</Text>
        {c.source === "slack" && <Text fz="sm">Negotiated in Slack; the accepted contract is attached and its terms become the vendor's payment terms.</Text>}
        {c.contract_id && <ContractCard k={contract} id={c.contract_id} />}
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
            <CardHead title="Decision" mb="sm" />
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
          {c.auto_approved ? "Auto-approved by policy (low risk, every check passed)" : `by ${c.decided_by}`} · {c.decided_at && when(c.decided_at)}{c.decision_comment && ` · “${c.decision_comment}”`}</Alert>}
        {(confirmation || c.confirmation_email_id) && (
          <div><Group gap="xs" mb="xs"><Text fw={600}>Confirmation email</Text>{confirmation && <EmailStatusBadge e={confirmation} />}</Group>
            {confirmation ? <EmailCard e={confirmation} /> : <Text fz="sm" c="dimmed">{c.confirmation_email_id}</Text>}</div>
        )}
      </Stack>
    </Drawer>
  );
}
