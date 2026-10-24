// Small shared pieces: badges, signal list, stat card, bills table.
import { Alert, Avatar, Badge, Button, Checkbox, Group, Loader, Paper, Stack, Table, Text, Tooltip } from "@mantine/core";
import { Fragment, type ReactNode } from "react";
import type { Bill, Signal } from "../types/contracts";
import { useApp } from "./context";
import { amount, day, due, REC, RISK, shortName, STAGES, sumMoney, usd } from "./format";

export const StageBadge = ({ stage }: { stage: string }) =>
  stage === "processing"
    ? <Badge variant="light" color="gray" leftSection={<Loader size={10} color="gray" />}>Processing</Badge>
    : <Badge variant="light" color={STAGES[stage]?.color ?? "gray"} maw="none" style={{ flexShrink: 0 }}>{STAGES[stage]?.label ?? stage}</Badge>;

export const RecBadge = ({ rec }: { rec: string | null | undefined }) =>
  rec ? <Badge variant="outline" size="sm" color={REC[rec]?.color}>{REC[rec]?.label}</Badge> : <Text fz="xs" c="dimmed">—</Text>;

export function RiskDots({ bill }: { bill: Bill }) {
  if (!bill.signals.length) return <Text fz="xs" c="dimmed">None</Text>;
  return (
    <Tooltip multiline w={300} label={bill.signals.map((s) => `• ${s.title}`).join("\n")} style={{ whiteSpace: "pre-line" }}>
      <Badge variant="light" color={RISK[bill.risk]} style={{ flexShrink: 0 }}>{bill.risk === "high" ? "High risk" : `${bill.signals.length} flag${bill.signals.length > 1 ? "s" : ""}`}</Badge>
    </Tooltip>
  );
}

export function Signals({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <Alert color="brand" variant="light" title="All pre-payment checks passed">Bank, sender, duplicates and the 3-way match look clean.</Alert>;
  return (
    <Stack gap="xs">
      {signals.map((s) => (
        <Alert key={s.code + s.title} color={RISK[s.severity]} variant="light" title={s.title}>{s.detail}</Alert>
      ))}
    </Stack>
  );
}

export function Stat({ label, value, sub, color, onClick }: { label: string; value: ReactNode; sub?: ReactNode; color?: string; onClick?: () => void }) {
  return (
    <Paper withBorder p="md" radius="md" onClick={onClick} style={{ cursor: onClick ? "pointer" : undefined }}>
      <Text fz="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text fz={28} fw={600} c={color} mt={4} lh={1.2}>{value}</Text>
      {sub && <Text fz="xs" c="dimmed" mt={4}>{sub}</Text>}
    </Paper>
  );
}

export function BillsTable({ bills, select, extra, footer = true }: {
  bills: Bill[]; select?: { selected: string[]; toggle: (id: string) => void; all?: (ids: string[]) => void; can?: (b: Bill) => boolean };
  extra?: { head: string; cell: (b: Bill) => ReactNode }; footer?: boolean;
}) {
  const { go } = useApp();
  if (!bills.length) return <Text c="dimmed" fz="sm" py="xl" ta="center">Nothing here.</Text>;
  const cols = 7 + (select ? 1 : 0) + (extra ? 1 : 0);
  const selectable = select ? bills.filter((b) => (select.can ? select.can(b) : true)) : [];
  const allOn = !!select && selectable.length > 0 && selectable.every((b) => select.selected.includes(b.case_id));
  return (
    <>
      <Table.ScrollContainer minWidth={extra || select ? 1120 : 960}>
        <Table verticalSpacing="sm" highlightOnHover style={{ whiteSpace: "nowrap" }}>
          <Table.Thead bg="gray.0">
            <Table.Tr>
              {select && <Table.Th w={40}><Checkbox size="xs" checked={allOn} onChange={() => select.all?.(allOn ? [] : selectable.map((b) => b.case_id))} aria-label="Select all" /></Table.Th>}
              <Table.Th>Vendor / source</Table.Th><Table.Th>Status</Table.Th><Table.Th ta="right">Amount</Table.Th>
              <Table.Th>Invoice #</Table.Th><Table.Th>Due date</Table.Th><Table.Th>Checks</Table.Th>
              {extra && <Table.Th>{extra.head}</Table.Th>}<Table.Th>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {bills.map((b) => (
              <Fragment key={b.case_id}>
                <Table.Tr style={{ cursor: "pointer" }} onClick={() => go(`bill/${b.case_id}`)}>
                  {select && (
                    <Table.Td onClick={(e) => e.stopPropagation()}>
                      <Checkbox size="xs" checked={select.selected.includes(b.case_id)} disabled={select.can ? !select.can(b) : false}
                        onChange={() => select.toggle(b.case_id)} aria-label={`Select ${b.invoice_no}`} />
                    </Table.Td>
                  )}
                  <Table.Td><Group gap="sm" wrap="nowrap"><Avatarish name={b.vendor_name} />
                    <div><Text fz="sm" fw={500}>{shortName(b.vendor_name)}</Text><Text fz="xs" c="dimmed">ReconAI · {day(b.invoice_date)}</Text></div></Group></Table.Td>
                  <Table.Td><StageBadge stage={b.stage} /></Table.Td>
                  <Table.Td ta="right"><Text fz="sm" ff="monospace">{amount(b.amount, b.currency)}</Text>
                    {b.payable && b.payable !== b.amount && <Text fz="xs" c="dimmed">pay {amount(b.payable, b.currency)} · {amount(b.disputed, b.currency)} held</Text>}
                    {b.currency !== "USD" && <Text fz="xs" c="dimmed">≈ {usd(b.amount_usd)}</Text>}
                    {b.discount && ["available", "needs_approval"].includes(b.discount.status) &&
                      <Text fz="xs" c="green.8">save {amount(b.discount.discount_amount, b.currency)} by {day(b.discount.pay_by).replace(/, \d{4}$/, "")}</Text>}</Table.Td>
                  <Table.Td><Text fz="sm" ff="monospace">{b.invoice_no ?? "not read"}</Text>
                    {b.overbilled && <Text fz="xs" c="red.7">{amount(b.overbilled, b.currency)} overbilled</Text>}</Table.Td>
                  <Table.Td><Text fz="sm">{day(b.due_date)}</Text><Text fz="xs" c={b.days_to_due != null && b.days_to_due < 7 ? "orange" : "dimmed"}>{due(b.days_to_due)}</Text></Table.Td>
                  <Table.Td><RiskDots bill={b} /></Table.Td>
                  {extra && <Table.Td>{extra.cell(b)}</Table.Td>}
                  <Table.Td onClick={(e) => e.stopPropagation()}><Button size="xs" variant="default" w={90} onClick={() => go(`bill/${b.case_id}`)}>Review</Button></Table.Td>
                </Table.Tr>
                {b.warning && (
                  <Table.Tr bg={b.risk === "high" ? "red.0" : "orange.0"} style={{ cursor: "pointer" }} onClick={() => go(`bill/${b.case_id}`)}>
                    <Table.Td colSpan={cols} py={6}><Text fz="sm" c={b.risk === "high" ? "red.8" : "orange.9"} pl={select ? 40 : 0}>↳ {b.warning}</Text></Table.Td>
                  </Table.Tr>
                )}
              </Fragment>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {footer && <Group justify="flex-end" px="md" py="sm" style={{ borderTop: "1px solid var(--mantine-color-gray-2)" }}>
        <Text fz="sm" c="dimmed">1–{bills.length} of {bills.length} · <b>{usd(sumMoney(bills.map((b) => b.amount_usd)))}</b> total (USD)</Text></Group>}
    </>
  );
}

export function PageHead({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg">
      <div><Text fz={26} fw={650}>{title}</Text>{sub && <Text c="dimmed" fz="sm">{sub}</Text>}</div>
      {right}
    </Group>
  );
}

export function Avatarish({ name, size = 30 }: { name: string; size?: number }) {
  const colors = ["teal", "violet", "orange", "blue", "pink", "grape", "cyan"];
  const c = colors[[...name].reduce((n, ch) => n + ch.charCodeAt(0), 0) % colors.length];
  return <Avatar size={size} color={c} radius="xl">{shortName(name).split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}</Avatar>;
}
