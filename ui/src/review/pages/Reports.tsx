// Insights > Reports: Spending · AP aging · Efficiency (incl. agent accuracy vs the answer key).
import { BarChart, DonutChart } from "@mantine/charts";
import { Badge, Button, Card, Grid, Group, SimpleGrid, Table, Tabs, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import type { ApReport, Scoreboard } from "../../types/contracts";
import { ap } from "../api";
import { useApp } from "../context";
import { amount, day, due, shortName, usd, usdShort } from "../format";
import { Avatarish, Stat, StageBadge } from "../parts";

const COLORS = ["brand.7", "violet.5", "orange.5", "cyan.6", "pink.5"];

export default function Reports() {
  const { bills, go } = useApp();
  const [tab, setTab] = useState<string>("aging");
  const [rep, setRep] = useState<ApReport | null>(null);
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => { ap.report().then(setRep).catch(() => {}); ap.scoreboard().then(setBoard).catch(() => setBoard(null)); }, [bills]);
  const grade = async () => { setRunning(true); try { setBoard(await ap.runEval()); } finally { setRunning(false); } };
  if (!rep) return null;
  const n = (v: string) => Number(v);   // chart geometry only; totals come from the backend
  const outstanding = bills.filter((b) => !["paid", "rejected", "processing"].includes(b.stage)).sort((a, b) => (a.due_date ?? "").localeCompare(b.due_date ?? ""));

  return (
    <>
      <Text c="dimmed" fz="sm">Insights</Text>
      <Text fz={34} fw={650} lh={1.1} mb="md">Reports</Text>
      <Tabs value={tab} onChange={(t) => setTab(t ?? "aging")} mb="lg">
        <Tabs.List><Tabs.Tab value="spending">Spending</Tabs.Tab><Tabs.Tab value="aging">AP aging</Tabs.Tab><Tabs.Tab value="efficiency">Efficiency</Tabs.Tab></Tabs.List>
      </Tabs>

      {tab === "aging" && (
        <Grid gutter="lg">
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Card withBorder padding="lg"><Text fz="xs" c="dimmed">All time</Text><Text fw={600} mb="sm">AP aging · bills by days past due</Text>
              <BarChart h={280} data={rep.aging.map((a) => ({ bucket: a.label, Bills: a.count }))} dataKey="bucket" series={[{ name: "Bills", color: "brand.6" }]}
                withBarValueLabel />
              <Group gap="lg" mt="sm">{rep.aging.map((a) => <Text key={a.label} fz="xs" c="dimmed">{a.label}: <b>{usdShort(a.amount_usd)}</b></Text>)}</Group>
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Card withBorder padding={0}><Text fz="xs" c="dimmed" px="lg" pt="lg">All time</Text><Text fw={600} px="lg" mb="sm">Outstanding bills</Text>
              <Table highlightOnHover verticalSpacing="sm">
                <Table.Thead bg="gray.0"><Table.Tr><Table.Th>Payee</Table.Th><Table.Th>Due ↑</Table.Th><Table.Th>Status</Table.Th><Table.Th ta="right">Outstanding</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>{outstanding.map((b) => (
                  <Table.Tr key={b.case_id} style={{ cursor: "pointer" }} onClick={() => go(`bill/${b.case_id}`)}>
                    <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} size={24} /><Text fz="sm">{shortName(b.vendor_name)}</Text></Group></Table.Td>
                    <Table.Td><Text fz="sm">{day(b.due_date)}</Text><Text fz="xs" c="dimmed">{due(b.days_to_due)}</Text></Table.Td>
                    <Table.Td><StageBadge stage={b.stage} /></Table.Td>
                    <Table.Td ta="right" ff="monospace" fz="sm">{amount(b.amount, b.currency)}</Table.Td>
                  </Table.Tr>))}</Table.Tbody>
              </Table>
            </Card>
          </Grid.Col>
          <Grid.Col span={12}>
            <Card withBorder padding="lg"><Text fw={600}>Cash out by week</Text><Text fz="xs" c="dimmed" mb="sm">Open bills by due week, approved vs still pending · USD at simulated FX</Text>
              <BarChart h={220} type="stacked" withLegend data={rep.forecast.map((w) => ({ week: w.week_start.slice(5), Approved: n(w.approved_usd), Pending: n(w.pending_usd) }))}
                dataKey="week" series={[{ name: "Approved", color: "brand.7" }, { name: "Pending", color: "violet.4" }]} valueFormatter={(v) => usdShort(v)} />
            </Card>
          </Grid.Col>
        </Grid>
      )}

      {tab === "spending" && (
        <Grid gutter="lg">
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Card withBorder padding="lg"><Text fw={600} mb="sm">Spend by vendor</Text>
              <BarChart h={240} orientation="vertical" data={rep.by_vendor.map((r) => ({ vendor: shortName(r.label), USD: n(r.amount_usd) }))} dataKey="vendor"
                series={[{ name: "USD", color: "brand.7" }]} valueFormatter={(v) => usdShort(v)} yAxisProps={{ width: 150 }} />
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Card withBorder padding="lg"><Text fw={600} mb="sm">Spend by GL account</Text>
              <Group align="center" wrap="nowrap">
                <DonutChart size={160} thickness={26} data={rep.by_gl.map((r, i) => ({ name: r.label, value: n(r.amount_usd), color: COLORS[i % COLORS.length] }))} valueFormatter={(v) => usdShort(v)} />
                <Table fz="xs"><Table.Tbody>{rep.by_gl.map((r, i) => (
                  <Table.Tr key={r.label}><Table.Td><Badge size="xs" color={COLORS[i % COLORS.length]} circle /> {r.label}</Table.Td><Table.Td ta="right" ff="monospace">{usd(r.amount_usd)}</Table.Td></Table.Tr>
                ))}</Table.Tbody></Table>
              </Group>
            </Card>
          </Grid.Col>
        </Grid>
      )}

      {tab === "efficiency" && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
            <Stat label="Touchless" value={rep.touchless_rate == null ? "—" : `${Math.round(rep.touchless_rate * 100)}%`} sub="cleared with no human step" color="brand.7" />
            <Stat label="Caught before payment" value={usdShort(rep.caught_usd)} sub="held, rejected or high-risk" />
            <Stat label="Waiting on a human" value={rep.needs_review} sub="for approval" />
            <Stat label="Payment-blocked" value={rep.blocked} sub="by the payment guard" color={rep.blocked ? "red.7" : undefined} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 2, md: 3 }} mb="lg">
            <Stat label="Discounts captured" value={usdShort(rep.discounts_captured_usd)} sub="early-pay terms earned" color="green.8" />
            <Stat label="Discounts available" value={usdShort(rep.discounts_available_usd)} sub="still inside the window" color="brand.7" />
            <Stat label="Discounts missed" value={usdShort(rep.discounts_missed_usd)} sub="window closed before payment" color={Number(rep.discounts_missed_usd) ? "red.7" : undefined} />
          </SimpleGrid>
          <Card withBorder padding="lg">
            <Group justify="space-between" mb="sm"><div><Text fw={600}>Agent accuracy</Text><Text fz="xs" c="dimmed">Graded against the answer key. Misses are shown, not hidden.</Text></div>
              <Button size="xs" variant="light" loading={running} onClick={grade}>Grade again</Button></Group>
            {board ? (
              <>
                <SimpleGrid cols={4} mb="sm">
                  <Stat label="Cases right" value={`${board.passed}/${board.total}`} />
                  <Stat label="Exceptions caught" value={`${Math.round(board.catch_rate * 100)}%`} />
                  <Stat label="False alarms" value={`${Math.round(board.false_alarm_rate * 100)}%`} />
                  <Stat label="Controls held" value={`${Math.round(board.invariant_pass_rate * 100)}%`} color={board.invariant_pass_rate === 1 ? "brand.7" : "red.7"} />
                </SimpleGrid>
                <Table fz="sm"><Table.Thead><Table.Tr><Table.Th>Case</Table.Th><Table.Th>Expected</Table.Th><Table.Th>Agents did</Table.Th><Table.Th>Missed checks</Table.Th></Table.Tr></Table.Thead>
                  <Table.Tbody>{board.results.map((r) => (
                    <Table.Tr key={r.case_id}><Table.Td>{r.passed ? "✓" : "✕"} {r.case_id}</Table.Td><Table.Td>{r.expected.decision}</Table.Td><Table.Td>{r.actual_decision ?? "—"}</Table.Td>
                      <Table.Td c="dimmed" fz="xs">{Object.entries(r.checks).filter(([, ok]) => !ok).map(([k]) => k).join(", ") || "—"}</Table.Td></Table.Tr>
                  ))}</Table.Tbody></Table>
              </>
            ) : <Text fz="sm" c="dimmed">Not graded yet.</Text>}
          </Card>
        </>
      )}
    </>
  );
}
