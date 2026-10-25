// Small shared pieces: badges, signal list, stat card, bills table.
import { Alert, Avatar, Badge, Card, Checkbox, Group, Loader, Paper, Stack, Table, Text, Tooltip, type MantineSpacing } from "@mantine/core";
import { IconAlertTriangle, IconChevronRight } from "@tabler/icons-react";
import type { ReactNode } from "react";
import type { Bill, Signal } from "../types/contracts";
import { useApp } from "./context";
import { amount, currencySymbol, day, due, REC, RISK, shortName, STAGES, sumMoney, usd } from "./format";

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
    <Paper withBorder p="lg" radius="md" onClick={onClick} style={{ cursor: onClick ? "pointer" : undefined }}>
      <Text fz="sm" c="dimmed" fw={500}>{label}</Text>
      <Text fz={32} fw={600} c={color} mt={6} lh={1.1}>{value}</Text>
      {sub && <Text fz="sm" c="dimmed" mt={6} component="div">{sub}</Text>}
    </Paper>
  );
}

/* Bills lifecycle: the four Bills tabs, the order every bill list uses, and the queue the bill page walks with K / J. */
export const BILL_TABS: Record<string, { label: string; stages: string[] }> = {
  overview: { label: "Overview", stages: ["processing", "needs_review", "on_hold", "ready_to_pay", "blocked", "scheduled", "paid", "rejected"] },
  approval: { label: "For approval", stages: ["needs_review", "on_hold"] },
  payment: { label: "For payment", stages: ["ready_to_pay", "blocked", "scheduled"] },
  history: { label: "History", stages: ["paid", "rejected"] },
};
const ORDER = ["processing", "needs_review", "on_hold", "blocked", "ready_to_pay", "scheduled", "failed", "partially_paid", "paid", "rejected"];
/** Highest priority first: stage, then fraud risk, then the nearest due date. Same order on the Bills table and the bill page list. */
export const sortBills = (bs: Bill[]) => [...bs].sort((a, b) =>
  ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage) || (a.risk === "high" ? 0 : 1) - (b.risk === "high" ? 0 : 1) || (a.days_to_due ?? 9999) - (b.days_to_due ?? 9999));
export const tabOf = (stage: string) => Object.keys(BILL_TABS).find((k) => k !== "overview" && BILL_TABS[k].stages.includes(stage)) ?? "overview";
/** The list a bill was opened from (tab + ids in table order). Module state: survives the bill page remounting per bill. */
export const billQueue: { tab: string; ids: string[] } = { tab: "", ids: [] };

/** Backend prose says "USD 15,200.00"; show "$15,200.00" like every other amount. */
const CODES = /\b(USD|TWD|MYR|KRW|EUR|GBP|JPY|CNY) (-?)(\d[\d,]*(?:\.\d+)?)/g;
export const symbols = (s: string | null | undefined) => (s ?? "").replace(CODES, (_, c: string, neg: string, n: string) => `${neg}${currencySymbol(c)}${n}`);

/** Why a bill is flagged, in one line (empty when clean). */
export const billReason = (b: Bill) => symbols(b.payment_block ?? b.warning ?? b.signals[0]?.title ?? "");
export const reasonColor = (b: Bill) => (b.risk === "high" || b.stage === "blocked" ? "red.7" : "orange.8");

export function BillsTable({ bills, select, extra, footer = true, compact, highlight, onOpen }: {
  bills: Bill[]; select?: { selected: string[]; toggle: (id: string) => void; all?: (ids: string[]) => void; can?: (b: Bill) => boolean };
  extra?: { head: string; cell: (b: Bill) => ReactNode }; footer?: boolean;
  /** narrow layout (next to the payment panel): no Status / Invoice # columns, the invoice # moves under the vendor */
  compact?: boolean; highlight?: string[]; onOpen?: (id: string) => void;
}) {
  const { go } = useApp();
  if (!bills.length) return <Text c="dimmed" fz="sm" py="xl" ta="center">Nothing here.</Text>;
  const open = (id: string) => (onOpen ? onOpen(id) : go(`bill/${id}`));
  const selectable = select ? bills.filter((b) => (select.can ? select.can(b) : true)) : [];
  const allOn = !!select && selectable.length > 0 && selectable.every((b) => select.selected.includes(b.case_id));
  const th = { fz: "xs", fw: 600, c: "dimmed", tt: "uppercase" } as const;
  return (
    <>
      <Table stickyHeader verticalSpacing={8} highlightOnHover style={{ whiteSpace: "nowrap" }}>
        <Table.Thead style={{ zIndex: 1 }}>
          <Table.Tr>
            {select && <Table.Th w={40}><Checkbox size="xs" checked={allOn} disabled={!selectable.length} onChange={() => select.all?.(allOn ? [] : selectable.map((b) => b.case_id))} aria-label="Select all" /></Table.Th>}
            <Table.Th><Text {...th}>Vendor</Text></Table.Th>
            {!compact && <Table.Th><Text {...th}>Status</Text></Table.Th>}
            <Table.Th ta="right"><Text {...th}>Amount</Text></Table.Th>
            {!compact && <Table.Th><Text {...th}>Invoice #</Text></Table.Th>}
            <Table.Th><Text {...th}>Due</Text></Table.Th>
            {extra && <Table.Th><Text {...th}>{extra.head}</Text></Table.Th>}
            {!compact && <Table.Th w={28} />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {bills.map((b) => {
            const why = billReason(b);
            const split = b.payable && b.payable !== b.amount;
            const offer = b.discount && ["available", "needs_approval"].includes(b.discount.status) ? b.discount : null;
            return (
              <Table.Tr key={b.case_id} style={{ cursor: "pointer" }} bg={highlight?.includes(b.case_id) ? "brand.0" : undefined} onClick={() => open(b.case_id)}>
                {select && (
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    <Checkbox size="xs" checked={select.selected.includes(b.case_id)} disabled={select.can ? !select.can(b) : false}
                      onChange={() => select.toggle(b.case_id)} aria-label={`Select ${b.invoice_no ?? b.case_id}`} />
                  </Table.Td>
                )}
                <Table.Td>
                  <Group gap="sm" wrap="nowrap">
                    <Avatarish name={b.vendor_name} size={28} />
                    <div style={{ minWidth: 0, maxWidth: compact ? 140 : 320 }}>
                      <Group gap={6} wrap="nowrap"><Text fz="sm" fw={500} truncate>{shortName(b.vendor_name)}</Text>
                        {b.risk === "high" && <IconAlertTriangle size={14} color="var(--mantine-color-red-7)" style={{ flexShrink: 0 }} />}</Group>
                      <Text fz="xs" truncate c={why ? reasonColor(b) : "dimmed"}>{why || (compact ? b.invoice_no ?? b.case_id : `Invoiced ${day(b.invoice_date)}`)}</Text>
                    </div>
                  </Group>
                </Table.Td>
                {!compact && <Table.Td><StageBadge stage={b.stage} /></Table.Td>}
                <Table.Td ta="right">
                  <Text fz="sm" ff="monospace">{b.amount ? amount(b.amount, b.currency) : "—"}</Text>
                  {split ? <Text fz="xs" c="dimmed">pay {amount(b.payable, b.currency)}</Text>
                    : offer ? <Text fz="xs" c="brand.7">save {amount(offer.discount_amount, b.currency)}</Text>
                      : b.currency && b.currency !== "USD" ? <Text fz="xs" c="dimmed">≈ {usd(b.amount_usd)}</Text> : null}
                </Table.Td>
                {!compact && <Table.Td><Text fz="sm" ff="monospace">{b.invoice_no ?? "not read"}</Text></Table.Td>}
                <Table.Td><Text fz="sm">{day(b.due_date).replace(/, \d{4}$/, "")}</Text>
                  <Text fz="xs" c={b.days_to_due != null && b.days_to_due < 7 ? "orange.8" : "dimmed"}>{due(b.days_to_due)}</Text></Table.Td>
                {extra && <Table.Td>{extra.cell(b)}</Table.Td>}
                {!compact && <Table.Td><IconChevronRight size={16} color="var(--mantine-color-gray-5)" /></Table.Td>}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {footer && <BillsFooter bills={bills} />}
    </>
  );
}

export function BillsFooter({ bills, children }: { bills: Bill[]; children?: ReactNode }) {
  return (
    <Group justify="space-between" px="md" py={8} style={{ borderTop: "1px solid var(--mantine-color-gray-2)", flexShrink: 0 }}>
      <div>{children}</div>
      <Text fz="sm" c="dimmed">{bills.length} bill{bills.length === 1 ? "" : "s"} · <b>{usd(sumMoney(bills.map((b) => b.amount_usd)))}</b></Text>
    </Group>
  );
}

/** One header tint for every card title bar and pane header in the app: light logo teal (#e6f4f5), dark title text. */
export const HEAD_BG = "brand.0";
export const HEAD_BORDER = "1px solid var(--mantine-color-brand-2)";

/** Card title bar: a tinted strip with a bottom border, so the title never runs into the rows below it.
 *  Must be the Card's first child (Card.Section pulls itself to the card's top edge). `px` for padding={0} cards. */
export function CardHead({ title, pre, sub, right, mb = "md", px }: {
  title: ReactNode; pre?: ReactNode; sub?: ReactNode; right?: ReactNode; mb?: MantineSpacing | number; px?: MantineSpacing;
}) {
  return (
    <Card.Section inheritPadding={!px} px={px} py="sm" mb={mb} bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER }}>
      <Group justify="space-between" wrap="nowrap" gap="sm">
        <div style={{ minWidth: 0 }}>
          {pre && <Text fz="xs" c="dimmed">{pre}</Text>}
          <Text fw={600} fz={17} lh={1.3} component="div">{title}</Text>
          {sub && <Text fz="xs" c="dimmed">{sub}</Text>}
        </div>
        {right}
      </Group>
    </Card.Section>
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
