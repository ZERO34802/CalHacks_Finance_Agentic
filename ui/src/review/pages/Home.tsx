// Home: what needs me today, what's due, what the agents handled on their own.
import { BarChart } from "@mantine/charts";
import { Badge, Card, Grid, Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import type { ApReport } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, due, shortName, sumMoney, usd, usdShort } from "../format";
import { DiscountCard } from "../discounts";
import { PageHead, RiskDots, StageBadge, Stat } from "../parts";

export default function Home() {
  const { bills, go, seat, lastEvent } = useApp();
  const [rep, setRep] = useState<ApReport | null>(null);
  useEffect(() => { ap.report().then(setRep).catch(() => {}); }, [bills, lastEvent]);
  const who = me(seat);
  const review = bills.filter((b) => b.stage === "needs_review");
  const mine = review.filter((b) => b.needs === seat);
  const attention = bills.filter((b) => ["needs_review", "on_hold", "blocked"].includes(b.stage))
    .sort((a, b) => (a.risk === "high" ? -1 : 0) - (b.risk === "high" ? -1 : 0) || (a.days_to_due ?? 999) - (b.days_to_due ?? 999));
  const processing = bills.filter((b) => b.stage === "processing");

  return (
    <>
      <PageHead title={`Hi ${who.name.split(" ")[0]}`} sub={`Signed in as ${who.title}. Invoices are processed in the background as they arrive.`} />
      <SimpleGrid cols={{ base: 2, md: 5 }} mb="lg">
        <Stat label="Needs your sign-off" value={mine.length} sub={`${review.length} awaiting review in total`} color="violet.7" onClick={() => go("bills/approval")} />
        <Stat label="Ready to pay" value={usdShort(sumMoney(bills.filter((b) => b.stage === "ready_to_pay").map((b) => b.payable_usd ?? b.amount_usd)))} sub={`${bills.filter((b) => b.stage === "ready_to_pay").length} bills`} onClick={() => go("bills/payment")} />
        <Stat label="Payment blocked" value={rep?.blocked ?? "—"} sub="bank, duplicate or hidden-instruction checks" color={rep?.blocked ? "red.7" : undefined} onClick={() => go("bills/payment")} />
        <Stat label="Due in 7 days" value={usdShort(rep?.due_7d_usd)} sub={`open AP ${usdShort(rep?.open_usd)}`} />
        <Stat label="Touchless" value={rep?.touchless_rate == null ? "—" : `${Math.round(rep.touchless_rate * 100)}%`} sub="cleared by agents with no human step" color="brand.7" />
      </SimpleGrid>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 7 }}>
          <DiscountCard />
          <Card withBorder padding="lg" mt="lg">
            <Group justify="space-between" mb="sm"><Text fw={600}>Needs attention</Text><Text fz="sm" c="dimmed">{attention.length}</Text></Group>
            <Stack gap={0}>
              {attention.map((b) => (
                <Group key={b.case_id} justify="space-between" py="sm" style={{ borderTop: "1px solid var(--mantine-color-gray-2)", cursor: "pointer" }} onClick={() => go(`bill/${b.case_id}`)} wrap="nowrap">
                  <div style={{ minWidth: 0 }}>
                    <Group gap={8}><Text fw={500} fz="sm">{shortName(b.vendor_name)}</Text><Text fz="xs" c="dimmed" ff="monospace">{b.invoice_no}</Text></Group>
                    <Text fz="xs" c="dimmed" lineClamp={1}>{b.payment_block ?? b.signals[0]?.title ?? (b.needs !== "nobody" ? `Needs ${b.needs} sign-off` : "")}</Text>
                  </div>
                  <Group gap="sm" wrap="nowrap">
                    <RiskDots bill={b} />
                    <Text fz="sm" ff="monospace" w={150} ta="right">{amount(b.amount, b.currency)}</Text>
                    <StageBadge stage={b.stage} />
                  </Group>
                </Group>
              ))}
              {!attention.length && <Text c="dimmed" fz="sm">Nothing needs attention.</Text>}
            </Stack>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <Stack>
            <Card withBorder padding="lg">
              <Text fw={600} mb={4}>Cash out, next 6 weeks</Text>
              <Text fz="xs" c="dimmed" mb="sm">Open bills by due week, USD at simulated FX</Text>
              {rep && <BarChart h={200} data={rep.forecast.map((w) => ({ week: w.week_start.slice(5), Approved: Number(w.approved_usd), Pending: Number(w.pending_usd) }))}
                dataKey="week" type="stacked" valueFormatter={(v) => usdShort(v)} withLegend legendProps={{ verticalAlign: "bottom" }}
                series={[{ name: "Approved", color: "brand.7" }, { name: "Pending", color: "violet.4" }]} />}
            </Card>
            <Card withBorder padding="lg">
              <Group justify="space-between" mb="xs"><Text fw={600}>Agents</Text><Badge variant="dot" color={processing.length ? "blue" : "gray"}>{processing.length ? `${processing.length} running` : "idle"}</Badge></Group>
              <Text fz="sm" c="dimmed">Caught before payment: <b>{usd(rep?.caught_usd)}</b></Text>
              {processing.map((b) => <Text key={b.case_id} fz="sm" mt={4}>⟳ {shortName(b.vendor_name)} · {b.invoice_no} <Text span c="dimmed" fz="xs">{due(b.days_to_due)}</Text></Text>)}
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>
    </>
  );
}
