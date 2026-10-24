// "Pay early, save X": ReconAI looks at bills ready to pay, finds vendors whose contract terms give an
// early-payment discount, and suggests paying on the discount deadline. Amounts come from the backend (code).
import { Badge, Button, Card, Group, Stack, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDiscount2, IconSparkles } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type { EarlyPayOffer } from "../types/contracts";
import { ap } from "./api";
import { me, useApp } from "./context";
import { amount, day, shortName, sumMoney, usd } from "./format";
import { Avatarish } from "./parts";

export function DiscountCard() {
  const { bills, seat, go, refresh, lastEvent } = useApp();
  const [offers, setOffers] = useState<EarlyPayOffer[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { ap.discounts().then(setOffers).catch(() => setOffers([])); }, [bills, lastEvent]);
  const open = offers.filter((o) => ["available", "needs_approval", "blocked"].includes(o.status));
  const ready = open.filter((o) => o.status === "available");
  const captured = offers.filter((o) => o.status === "captured"), missed = offers.filter((o) => o.status === "missed");
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

  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb={4}>
        <Group gap={8}><IconDiscount2 size={20} color="var(--mantine-color-brand-7)" /><Text fw={600}>Early-payment discounts</Text>
          <Badge size="sm" variant="light" leftSection={<IconSparkles size={10} />}>Suggested by ReconAI</Badge></Group>
        {ready.length > 1 && <Button size="xs" loading={busy === "all"} onClick={() => schedule(ready, "all")}>Schedule all · save {usd(sumMoney(ready.map((o) => o.discount_usd)))}</Button>}
      </Group>
      <Text fz="xs" c="dimmed" mb="sm">From each vendor's contract terms (not the invoice). Paying on the deadline keeps the cash longest.
        {captured.length > 0 && ` Captured so far: ${usd(sumMoney(captured.map((o) => o.discount_usd)))}.`}
        {missed.length > 0 && ` Missed: ${usd(sumMoney(missed.map((o) => o.discount_usd)))}.`}</Text>
      <Stack gap={0}>
        {open.map((o) => (
          <Group key={o.case_id} justify="space-between" py="sm" wrap="nowrap" style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }}>
            <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
              <Avatarish name={o.vendor_name} size={30} />
              <div style={{ minWidth: 0 }}>
                <Group gap={6}><Text fz="sm" fw={500}>{shortName(o.vendor_name)}</Text><Text fz="xs" c="dimmed" ff="monospace">{o.invoice_no}</Text>
                  <Badge size="xs" variant="default" tt="none">{o.terms}</Badge></Group>
                <Text fz="xs" c={o.days_left <= 3 ? "orange.8" : "dimmed"}>Pay by {day(o.pay_by)} ({o.days_left === 0 ? "today" : `${o.days_left}d left`}) · ≈{o.annualized_return_pct}% annualized</Text>
              </div>
            </Group>
            <Group gap="sm" wrap="nowrap">
              <div style={{ textAlign: "right" }}><Text fz="sm" fw={600} c="green.8">Save {amount(o.discount_amount, o.currency)}</Text>
                {o.currency !== "USD" && <Text fz="xs" c="dimmed">≈ {usd(o.discount_usd)}</Text>}</div>
              {o.status === "available" ? <Button size="xs" variant="light" loading={busy === o.case_id} onClick={() => schedule([o], o.case_id)}>Schedule {day(o.pay_by).replace(/, \d{4}$/, "")}</Button>
                : o.status === "needs_approval" ? <Button size="xs" variant="default" onClick={() => go(`bill/${o.case_id}`)}>Approve first</Button>
                  : <Tooltip label={o.note}><Badge color="red" variant="light">blocked</Badge></Tooltip>}
            </Group>
          </Group>
        ))}
        {!open.length && <Text fz="sm" c="dimmed">No discounts open right now.</Text>}
      </Stack>
    </Card>
  );
}
