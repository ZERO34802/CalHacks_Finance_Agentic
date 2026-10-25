// Insights: one screen, no tabs. Proof the agents work, what they caught, where the money goes, and time/cash.
// Nothing here repeats Home (cash-out forecast, sign-offs, discount scheduling) or the Bills table.
import { Box, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useViewportSize } from "@mantine/hooks";
import { useEffect, useState, type ReactNode } from "react";
import type { ApReport, Bill, EvalResult, Scoreboard } from "../../types/contracts";
import { ap } from "../api";
import { useApp } from "../context";
import { shortName, usdShort, when } from "../format";
import { HEAD_BG, HEAD_BORDER } from "../parts";

const pct = (r: number | null | undefined) => (r == null ? "—" : `${Math.round(r * 100)}%`);
const border = "1px solid var(--mantine-color-gray-2)";

/** Card header strip: tinted, bottom border, so the title reads as a header and never merges with the rows. */
function Head({ title, right }: { title: ReactNode; right?: ReactNode }) {
  return (
    <Card.Section inheritPadding py="sm" bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER }}>
      <Group justify="space-between" wrap="nowrap" gap="sm">
        <Text fw={600} fz={17} lh={1.3} truncate>{title}</Text>
        {right}
      </Group>
    </Card.Section>
  );
}

const cardStyle = { minHeight: 0, display: "flex", flexDirection: "column" as const, overflow: "hidden" };
const scroll = { flex: 1, minHeight: 0, overflowY: "auto" as const };

// Answer-key scenarios, grouped the way a controller thinks about risk. A case counts in every group it matches.
const DIFF = ["qty_short", "price_over", "unapproved_freight", "total_mismatch", "currency_mismatch"];
const GROUPS: [string, (r: EvalResult) => boolean][] = [
  ["Fraud and injection", (r) => r.expected.tags.some((t) => ["attack", "injection", "memory-poisoning", "csv-injection", "macro", "unregistered-channel"].includes(t))],
  ["Duplicate invoices", (r) => r.expected.tags.some((t) => ["dedup", "correction"].includes(t))],
  ["Price, quantity, freight gaps", (r) => r.expected.discrepancies.some((d) => DIFF.includes(d))],
  ["Approval limits and periods", (r) => r.expected.tags.some((t) => ["controls", "over-limit", "locked-period", "sla", "controller-reject"].includes(t))],
  ["Bad files at intake", (r) => r.expected.tags.some((t) => ["ingest", "missing-file", "manifest", "encoding"].includes(t))],
  ["Follow-ups and memory", (r) => r.expected.tags.some((t) => ["followup", "memory-matters", "skill-evolution"].includes(t))],
  ["Clean bills, no false alarm", (r) => r.expected.tags.includes("clean")],
];

// Live issues by reason (counts only: per-reason dollars would need FX in the browser).
const REASONS: { label: string; codes: string[]; bad?: boolean }[] = [
  { label: "Bank change", codes: ["bank_mismatch", "lookalike_domain"], bad: true },
  { label: "Prompt injection", codes: ["embedded_instructions"], bad: true },
  { label: "Duplicate invoice", codes: ["duplicate"] },
  { label: "Not on the PO", codes: ["not_on_po"] },
  { label: "Short delivery", codes: ["qty_short"] },
  { label: "Price above PO", codes: ["price_over"] },
  { label: "Total or FX off", codes: ["total_mismatch", "currency_mismatch"] },
  { label: "No matching PO", codes: ["no_po"] },
];
const flagged = (b: Bill) => !!b.recommendation && b.recommendation !== "approve";

// row padding comes from --row-py on the page root: tighter on short screens so cards scroll less
function Row({ children, first }: { children: ReactNode; first?: boolean }) {
  return <Group justify="space-between" wrap="nowrap" gap="md" style={{ paddingBlock: "var(--row-py)", borderTop: first ? undefined : border }}>{children}</Group>;
}

function Bar({ value, max, color = "brand.6" }: { value: number; max: number; color?: string }) {
  return (
    <Box style={{ flex: 1, height: 8, borderRadius: 4, background: "var(--mantine-color-gray-1)", minWidth: 40 }}>
      <Box h={8} style={{ width: `${max ? Math.max(2, (value / max) * 100) : 0}%`, borderRadius: 4, background: `var(--mantine-color-${color.replace(".", "-")})` }} />
    </Box>
  );
}

export default function Reports() {
  const { bills } = useApp();
  const [rep, setRep] = useState<ApReport | null>(null);
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => { ap.report().then(setRep).catch(() => {}); ap.scoreboard().then(setBoard).catch(() => setBoard(null)); }, [bills]);
  const grade = async () => { setRunning(true); try { setBoard(await ap.runEval()); } finally { setRunning(false); } };
  const { height } = useViewportSize();
  if (!rep) return null;

  // spend: display shares only (Number for geometry/percent); totals come from the backend
  const spend = rep.by_vendor.map((r) => ({ ...r, n: Number(r.amount_usd) }));
  const spendTotal = spend.reduce((s, r) => s + r.n, 0);
  const share = (v: number) => (spendTotal ? Math.round((v / spendTotal) * 100) : 0);
  const vendorFlags = (name: string) => { const xs = bills.filter((b) => b.vendor_name === name); return { n: xs.length, f: xs.filter(flagged).length }; };
  const worst = spend.map((r) => ({ name: r.label, ...vendorFlags(r.label) })).filter((v) => v.n >= 3).sort((a, b) => b.f / b.n - a.f / a.n)[0];

  const reasons = REASONS.map((r) => ({ ...r, count: bills.filter((b) => b.signals.some((s) => r.codes.includes(s.code))).length }))
    .concat([{ label: "Unsafe file", codes: [], count: bills.filter((b) => b.case_status === "quarantined").length }])
    .filter((r) => r.count > 0).sort((a, b) => Number(!!b.bad) - Number(!!a.bad) || b.count - a.count);   // fraud first, then most frequent
  const maxReason = Math.max(1, ...reasons.map((r) => r.count));

  const late = rep.aging.filter((a) => a.label !== "Not due" && a.count > 0);
  const m = board?.metrics;
  const misses = board?.results.filter((r) => !r.passed) ?? [];
  const tags = board?.results.flatMap((r) => r.expected.tags) ?? [];
  const NAMES: Record<string, string> = { pdf: "PDF", image: "Scan", csv: "CSV", xlsx: "XLSX", api: "API", eml: "Email", erp: "ERP", email: "Email", sftp: "SFTP", s3: "S3" };
  const list = (p: string) => [...new Set(tags.filter((t) => t.startsWith(p) && t !== `${p}none`).map((t) => t.slice(p.length)))].map((k) => NAMES[k] ?? k).join(" · ");

  return (
    <Box style={{ height: "calc(100vh - 124px)", minHeight: 600, display: "flex", flexDirection: "column", ["--row-py" as string]: height > 0 && height < 860 ? "4px" : "6px" }}>
      <Text fz={26} fw={650} mb="lg">Insights</Text>

      <Box style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0, 5fr) minmax(0, 7fr)", gap: "var(--mantine-spacing-lg)" }}>
        {/* 1. Proof: graded against the answer key, misses shown */}
        <Card withBorder padding="md" style={cardStyle}>
          <Head title="Agent accuracy" right={<Button size="compact-sm" variant="default" loading={running} onClick={grade}>Re-run</Button>} />
          {board ? (
            <>
              <Group grow gap="md" py="md" style={{ borderBottom: border }}>
                {([["Cases right", `${board.passed}/${board.total}`, board.passed === board.total ? "brand.7" : "red.7"],
                  ["Caught", pct(board.catch_rate), undefined], ["False alarms", pct(board.false_alarm_rate), board.false_alarm_rate ? "red.7" : undefined],
                  ["Controls held", pct(board.invariant_pass_rate), board.invariant_pass_rate === 1 ? undefined : "red.7"]] as const).map(([l, v, c]) => (
                  <div key={l}><Text fz={26} fw={600} lh={1.1} c={c}>{v}</Text><Text fz="xs" c="dimmed" mt={4} style={{ whiteSpace: "nowrap" }}>{l}</Text></div>
                ))}
              </Group>
              <Box style={scroll} pt={4}>
                {misses.map((r) => (
                  <Row key={r.case_id}><Text fz="sm" c="red.7" truncate>{r.case_id}: expected {r.expected.decision ?? "—"}, got {r.actual_decision ?? "—"}</Text>
                    <Text fz="xs" c="dimmed" truncate>{Object.entries(r.checks).filter(([, ok]) => !ok).map(([k]) => k).join(", ")}</Text></Row>
                ))}
                {GROUPS.map(([label, test], i) => {
                  const xs = board.results.filter(test), ok = xs.filter((r) => r.passed).length;
                  return xs.length ? <Row key={label} first={i === 0 && !misses.length}><Text fz="sm">{label}</Text>
                    <Text fz="sm" fw={600} c={ok === xs.length ? "brand.7" : "red.7"}>{ok}/{xs.length}</Text></Row> : null;
                })}
                {!!board.onboarding.length && <Row><Text fz="sm">Vendor onboarding</Text>
                  <Text fz="sm" fw={600} c={board.onboarding.every((r) => r.passed) ? "brand.7" : "red.7"}>{board.onboarding.filter((r) => r.passed).length}/{board.onboarding.length}</Text></Row>}
                <Row><Text fz="sm" c="dimmed">Formats</Text><Text fz="sm" c="dimmed" truncate>{list("format:")}</Text></Row>
                <Row><Text fz="sm" c="dimmed">Channels</Text><Text fz="sm" c="dimmed" truncate>{list("channel:")}</Text></Row>
              </Box>
              <Text fz="xs" c="dimmed" pt="sm" style={{ borderTop: border }}>
                {misses.length ? `${misses.length} missed` : "No misses"} · graded {when(board.at)}
              </Text>
            </>
          ) : <Text fz="sm" c="dimmed" pt="md">Not graded yet.</Text>}
        </Card>

        <Box style={{ minHeight: 0, display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--mantine-spacing-lg)" }}>
          {/* 2. Where the money goes, and which vendors cause the work */}
          <Card withBorder padding="md" style={cardStyle}>
            <Head title="Where the money goes" />
            {spend[0] && <Text fz="sm" c="dimmed" pt={8} pb={2}>
              {shortName(spend[0].label)} is {share(spend[0].n)}% of spend{worst ? ` · ${shortName(worst.name).split(" ")[0]} has the most flags` : ""}
            </Text>}
            <Box style={scroll}>
              {spend.map((r, i) => {
                const v = vendorFlags(r.label);
                return (
                  <Row key={r.label} first={i === 0}>
                    <Text fz="sm" w={150} truncate style={{ flexShrink: 0 }}>{shortName(r.label)}</Text>
                    <Bar value={r.n} max={spend[0].n} />
                    <Text fz="sm" fw={500} w={64} ta="right" style={{ flexShrink: 0 }}>{usdShort(r.amount_usd)}</Text>
                    <Text fz="sm" c="dimmed" w={40} ta="right" style={{ flexShrink: 0 }}>{share(r.n)}%</Text>
                    <Text fz="sm" w={92} ta="right" style={{ flexShrink: 0 }} c={v.f ? undefined : "dimmed"}>{v.f}/{v.n} flagged</Text>
                  </Row>
                );
              })}
            </Box>
          </Card>

          <Box style={{ minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "var(--mantine-spacing-lg)" }}>
            {/* 3. What the checks stopped, by reason */}
            <Card withBorder padding="md" style={cardStyle}>
              <Head title="Issues caught" right={<Text fz="sm" fw={600} c="brand.7">{usdShort(rep.caught_usd)} stopped</Text>} />
              <Box style={scroll} pt={4}>
                {reasons.map((r, i) => (
                  <Row key={r.label} first={i === 0}>
                    <Text fz="sm" c={r.bad ? "red.7" : undefined} truncate style={{ flex: "0 1 auto", minWidth: 0 }}>{r.label}</Text>
                    <Group gap="sm" wrap="nowrap" w={92} style={{ flexShrink: 0 }}>
                      <Bar value={r.count} max={maxReason} color={r.bad ? "red.6" : "brand.4"} />
                      <Text fz="sm" fw={600} w={20} ta="right">{r.count}</Text>
                    </Group>
                  </Row>
                ))}
                {!reasons.length && <Text fz="sm" c="dimmed">Nothing caught yet.</Text>}
              </Box>
            </Card>

            {/* 4. Time and cash */}
            <Card withBorder padding="md" style={cardStyle}>
              <Head title="Time and cash" />
              <Stack gap={0} style={scroll} pt={4}>
                <Row first><Text fz="sm">Open AP</Text><Text fz="sm" fw={600} style={{ whiteSpace: "nowrap" }}>{usdShort(rep.open_usd)}
                  <Text span fz="sm" fw={400} c={Number(rep.overdue_usd) ? "red.7" : "dimmed"}> · {usdShort(rep.overdue_usd)} overdue</Text></Text></Row>
                {late.map((a) => <Row key={a.label}><Text fz="sm" c="dimmed" pl="sm">{a.label}</Text><Text fz="sm">{usdShort(a.amount_usd)} · {a.count}</Text></Row>)}
                <Row><Text fz="sm">Discounts</Text><Text fz="sm" fw={600} c="brand.7" style={{ whiteSpace: "nowrap" }}>{usdShort(rep.discounts_captured_usd)}
                  <Text span fz="sm" fw={400} c={Number(rep.discounts_missed_usd) ? "red.7" : "dimmed"}> · {usdShort(rep.discounts_missed_usd)} missed</Text></Text></Row>
                {m && <>
                  <Row><Text fz="sm">Paid on time</Text><Text fz="sm" fw={600}>{pct(m.on_time_payment_rate)}</Text></Row>
                  <Row><Text fz="sm">Avg time to resolve</Text><Text fz="sm" fw={600}>{m.avg_time_to_resolve_hours == null ? "—" : `${m.avg_time_to_resolve_hours}h`}</Text></Row>
                  <Row><Text fz="sm">Hours saved <Text span fz="xs" c="dimmed">est.</Text></Text><Text fz="sm" fw={600}>{Math.round(Number(m.hours_saved_est))}h</Text></Row>
                </>}
              </Stack>
            </Card>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
