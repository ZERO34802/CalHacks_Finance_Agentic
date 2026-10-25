// Home: what needs me, what cash goes out and when, and what the agents caught. Highest priority first.
import { BarChart } from "@mantine/charts";
import { Alert, Anchor, Box, Card, Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { useViewportSize } from "@mantine/hooks";
import { useEffect, useState } from "react";
import type { ApReport } from "../../types/contracts";
import { ap } from "../api";
import { me, useApp } from "../context";
import { amount, shortName, sumMoney, usdShort } from "../format";
import { DiscountCard } from "../discounts";
import { CardHead, PageHead, Stat } from "../parts";

const week = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

export default function Home() {
  const { bills, go, seat, lastEvent } = useApp();
  const [rep, setRep] = useState<ApReport | null>(null);
  useEffect(() => { ap.report().then(setRep).catch(() => {}); }, [bills, lastEvent]);
  const who = me(seat);
  const top = (x: string) => x === "cfo" || x === "cto";   // the CTO has the CFO's authority
  const mine = bills.filter((b) => b.stage === "needs_review" && (b.needs === seat || (top(b.needs) && top(seat))));
  const fraud = mine.filter((b) => b.risk === "high").length;
  const ready = bills.filter((b) => b.stage === "ready_to_pay");
  const due7 = ready.filter((b) => b.days_to_due != null && b.days_to_due <= 7).length;
  const attention = bills.filter((b) => ["needs_review", "on_hold", "blocked"].includes(b.stage))
    .sort((a, b) => (a.risk === "high" ? -1 : 0) - (b.risk === "high" ? -1 : 0) || (a.days_to_due ?? 999) - (b.days_to_due ?? 999));
  const processing = bills.filter((b) => b.stage === "processing").length;
  const { height } = useViewportSize();
  const short = height > 0 && height < 860;   // smaller laptop screens: one row fewer per list, so nothing scrolls
  // the week with the most cash going out, and how much of it nobody has approved yet (comparison for display only)
  const peak = rep?.forecast.reduce((p, w) => (Number(w.approved_usd) + Number(w.pending_usd) > Number(p.approved_usd) + Number(p.pending_usd) ? w : p), rep.forecast[0]);

  // the page fits the window exactly (60px header + 2 x 32px shell padding); below 640px tall it scrolls instead of clipping
  return (
    <Box style={{ height: "calc(100vh - 124px)", minHeight: 640, display: "flex", flexDirection: "column" }}>
      <PageHead title={`Hi ${who.name.split(" ")[0]}`} sub={processing ? `Reconciling ${processing} new invoice${processing > 1 ? "s" : ""}…` : undefined} />

      {!!rep?.blocked && (
        <Alert color="red" variant="light" mb="lg" style={{ cursor: "pointer" }} onClick={() => go("bills/payment")}
          title={`${rep.blocked} payment${rep.blocked > 1 ? "s" : ""} blocked: bank or sender doesn't match the vendor master`} />
      )}

      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="lg" mb="lg">
        <Stat label="Needs your sign-off" value={mine.length} color="brand.7" onClick={() => go("bills/approval")}
          sub={fraud ? <Text span c="red.7" fz="sm" fw={500}>{fraud} possible fraud</Text> : usdShort(sumMoney(mine.map((b) => b.amount_usd)))} />
        <Stat label="Due in 7 days" value={usdShort(rep?.due_7d_usd)} sub={`${due7} bill${due7 === 1 ? "" : "s"}`} onClick={() => go("bills/payment")} />
        <Stat label="Ready to pay" value={usdShort(sumMoney(ready.map((b) => b.payable_usd ?? b.amount_usd)))} sub={`${ready.length} bills`} onClick={() => go("bills/payment")} />
        <Stat label="Caught before payment" value={usdShort(rep?.caught_usd)} onClick={() => go("reports")}
          sub={rep?.touchless_rate == null ? undefined : `${Math.round(rep.touchless_rate * 100)}% cleared without a person`} />
      </SimpleGrid>

      <Box style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0, 7fr) minmax(0, 5fr)", gap: "var(--mantine-spacing-lg)" }}>
          <Card withBorder padding="lg" style={{ minHeight: 0, overflow: "hidden" }}>
            <CardHead title="Needs attention" mb={0} right={<Anchor fz="sm" onClick={() => go("bills/approval")}>View all {attention.length}</Anchor>} />
            <Stack gap={0}>
              {attention.slice(0, short ? 5 : 6).map((b, i) => (
                <Group key={b.case_id} justify="space-between" py={short ? 10 : 14} wrap="nowrap" style={{ borderTop: i ? "1px solid var(--mantine-color-gray-2)" : undefined, cursor: "pointer" }} onClick={() => go(`bill/${b.case_id}`)}>
                  <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 8, flexShrink: 0, background: `var(--mantine-color-${b.risk === "high" || b.stage === "blocked" ? "red-7" : "brand-6"})` }} />
                    <div style={{ minWidth: 0 }}>
                      <Text fw={500}>{shortName(b.vendor_name)}</Text>
                      <Text fz="sm" c="dimmed" lineClamp={1}>{b.payment_block ?? b.signals[0]?.title ?? b.warning ?? "Above the agents' approval limit"}</Text>
                    </div>
                  </Group>
                  <Text fw={500} style={{ whiteSpace: "nowrap" }}>{b.amount ? amount(b.amount, b.currency) : "—"}</Text>
                </Group>
              ))}
              {!attention.length && <Text c="dimmed" pt="md">Nothing needs attention.</Text>}
            </Stack>
          </Card>
          <Stack gap="lg" style={{ minHeight: 0 }}>
            <Card withBorder padding="lg" style={{ flex: "1 0 auto" }}>
              <CardHead title="Cash out" mb="sm" right={
                <Group gap="md" wrap="nowrap">
                  <Group gap={6} wrap="nowrap"><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--mantine-color-brand-7)" }} /><Text fz="sm" c="dimmed">Approved</Text></Group>
                  <Group gap={6} wrap="nowrap"><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--mantine-color-brand-2)" }} /><Text fz="sm" c="dimmed">Pending</Text></Group>
                </Group>} />
              {peak && <Text fz="sm" c="dimmed" mb="sm">Peak {week(peak.week_start)} · {usdShort(sumMoney([peak.approved_usd, peak.pending_usd]))} · {usdShort(peak.pending_usd)} unapproved</Text>}
              {rep && <BarChart h={short ? 72 : 120} data={rep.forecast.map((w) => ({ week: week(w.week_start), Approved: Number(w.approved_usd), Pending: Number(w.pending_usd) }))}
                dataKey="week" type="stacked" valueFormatter={(v) => usdShort(v)} withYAxis={false} gridAxis="none" barProps={{ radius: 3 }}
                series={[{ name: "Approved", color: "brand.7" }, { name: "Pending", color: "brand.2" }]} />}
            </Card>
            <Box style={{ flex: "0 1 auto", minHeight: 0, overflowY: "auto" }}><DiscountCard rows={short ? 1 : 2} /></Box>
          </Stack>
      </Box>
    </Box>
  );
}
