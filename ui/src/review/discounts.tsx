// "Pay early, save X": ReconAI looks at bills ready to pay, finds vendors whose contract terms give an
// early-payment discount, and suggests paying on the discount deadline. Amounts come from the backend (code).
import { Anchor, Button, Card, Group, Stack, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import type { EarlyPayOffer } from "../types/contracts";
import { ap } from "./api";
import { me, useApp } from "./context";
import { CardHead } from "./parts";
import { day, shortName, sumMoney, usd } from "./format";

export function DiscountCard({ rows = 3 }: { rows?: number }) {
  const { bills, seat, go, refresh, lastEvent } = useApp();
  const [offers, setOffers] = useState<EarlyPayOffer[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => { ap.discounts().then(setOffers).catch(() => setOffers([])); }, [bills, lastEvent]);
  const open = offers.filter((o) => ["available", "needs_approval", "blocked"].includes(o.status));
  const ready = open.filter((o) => o.status === "available");
  const captured = sumMoney(offers.filter((o) => o.status === "captured").map((o) => o.discount_usd));
  const who = me(seat);

  const schedule = async (list: EarlyPayOffer[], key: string) => {
    setBusy(key);
    try {
      const byDate = new Map<string, string[]>();
      list.forEach((o) => byDate.set(o.pay_by, [...(byDate.get(o.pay_by) ?? []), o.case_id]));
      const runs = await Promise.all([...byDate.entries()].map(([d, ids]) => ap.createRun(ids, d, who.email)));
      notifications.show({ color: "brand", title: `Scheduled to capture ${usd(sumMoney(list.map((o) => o.discount_usd)))}`,
        message: `${runs.length} payment run(s) on the discount deadline. Someone other than ${who.name} must release them.` });
      refresh();
    } catch (e) { notifications.show({ color: "red", title: "Couldn't schedule", message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(null); }
  };

  const sorted = [...open].sort((a, b) => a.days_left - b.days_left);
  const shown = all ? sorted : sorted.slice(0, rows);
  return (
    <Card withBorder padding="lg">
      <CardHead title="Early-pay savings" mb="xs"
        right={ready.length > 1 && <Button size="compact-sm" loading={busy === "all"} onClick={() => schedule(ready, "all")}>Schedule all</Button>} />
      <Group gap="sm" align="baseline" mb="xs"><Text fz={28} fw={600} c="brand.7" lh={1.2}>{usd(sumMoney(open.filter((o) => o.status !== "blocked").map((o) => o.discount_usd)))}</Text>
        {Number(captured) > 0 && <Text fz="sm" c="dimmed">{usd(captured)} captured</Text>}</Group>
      <Stack gap={0}>
        {shown.map((o) => (
          <Group key={o.case_id} justify="space-between" py={12} wrap="nowrap" style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }}>
            <div style={{ minWidth: 0 }}>
              <Text fw={500} truncate>{shortName(o.vendor_name)}</Text>
              <Text fz="sm" c={o.days_left <= 3 ? "brand.7" : "dimmed"}>by {day(o.pay_by).replace(/, \d{4}$/, "")} · save {usd(o.discount_usd)}</Text>
            </div>
            {o.status === "available" ? <Button size="xs" variant="default" loading={busy === o.case_id} onClick={() => schedule([o], o.case_id)}>Schedule</Button>
              : o.status === "needs_approval" ? <Button size="xs" variant="default" onClick={() => go(`bill/${o.case_id}`)}>Approve first</Button>
                : <Tooltip label={o.note}><Text fz="sm" c="red.7">Blocked</Text></Tooltip>}
          </Group>
        ))}
        {!open.length && <Text fz="sm" c="dimmed">No discounts open right now.</Text>}
        {open.length > rows && <Anchor fz="sm" pt="sm" style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }} onClick={() => setAll((x) => !x)}>{all ? "Show fewer" : `Show all ${open.length}`}</Anchor>}
      </Stack>
    </Card>
  );
}
