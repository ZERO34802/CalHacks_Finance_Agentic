// Settings: the rules the system enforces in code (read-only here; they live in config/policy.yaml), people,
// and integrations, labelled connected / simulated / not connected.
import { Anchor, Badge, Card, Grid, Group, Stack, Table, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import type { ApSettings, ErpStatus, Role, SlackRoleHolder } from "../../types/contracts";
import { ap } from "../api";
import { PEOPLE, RELEASE_RULE, usd } from "../format";
import { PageHead } from "../parts";

const STATUS: Record<string, string> = { connected: "green", simulated: "yellow", not_connected: "gray" };
const SLACK_ROLES: { role: Role; label: string }[] = [
  { role: "approver", label: "AP lead" }, { role: "controller", label: "Controller" }, { role: "cfo", label: "CFO" }, { role: "cto", label: "CTO" },
];

export default function Settings() {
  const [s, setS] = useState<ApSettings | null>(null);
  const [slack, setSlack] = useState<SlackRoleHolder[] | null>(null);
  const [erp, setErp] = useState<ErpStatus | null>(null);
  useEffect(() => {
    ap.settings().then(setS).catch(() => {});
    ap.slackRoles().then(setSlack).catch(() => setSlack([]));
    ap.erpStatus().then(setErp).catch(() => setErp(null));   // endpoint may be missing: show nothing
  }, []);
  if (!s) return null;
  const row = (k: string, v: React.ReactNode) => <Table.Tr key={k}><Table.Td c="dimmed" w="45%">{k}</Table.Td><Table.Td>{v}</Table.Td></Table.Tr>;
  return (
    <>
      <PageHead title="Settings" sub="Enforced in code by validators and the Poster. Change them in config/policy.yaml (loosening needs a second sign-off)." />
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="lg"><Text fw={600} mb="sm">Approval workflow</Text>
            <Table fz="sm"><Table.Tbody>
              {Object.entries(s.approval_limits).map(([role, lim]) => row(`${PEOPLE[role as keyof typeof PEOPLE]?.title ?? role} may approve up to`, usd(lim)))}
              {row("Approval SLA", `${s.sla_hours} hours, then escalate to backup approver`)}
              {row("Requester can approve own purchase", "Never")}
              {row("Payment run released by", "A controller, CFO or CTO (AP leads approve but never release)")}
              {row("Bank details", "Agents can never change them; payments go to the vendor master only")}
            </Table.Tbody></Table>
          </Card>
          <Card withBorder padding="lg" mt="lg"><Text fw={600} mb="sm">People</Text>
            <Table fz="sm"><Table.Tbody>{Object.values(PEOPLE).map((p) => row(p.title, `${p.name} · ${p.email}`))}</Table.Tbody></Table>
          </Card>
          <Card withBorder padding="lg" mt="lg"><Text fw={600} mb={4}>Who's who (Slack)</Text>
            <Text fz="xs" c="dimmed" mb="sm">{RELEASE_RULE}; a controller, CFO or CTO who approved a bill can release it directly.</Text>
            <Stack gap="xs">
              {SLACK_ROLES.map(({ role, label }) => {
                const ps = (slack ?? []).filter((p) => p.role === role);
                return (
                  <Group key={role} justify="space-between" align="flex-start" wrap="nowrap">
                    <Text fz="sm" c="dimmed" w={90}>{label}</Text>
                    <Stack gap={0} style={{ flex: 1 }} align="flex-end">
                      {ps.length ? ps.map((p) => <Text key={p.slack_user} fz="sm">{p.name} · <Text span fz="xs" c="dimmed">{p.email || p.slack_user}</Text></Text>)
                        : <Text fz="xs" c="dimmed">{slack ? "Nobody registered" : "…"}</Text>}
                    </Stack>
                  </Group>
                );
              })}
            </Stack>
            <Text fz="xs" c="dimmed" mt="sm">Register in Slack: <Text span ff="monospace" fz="xs">/reconai role controller</Text> (ap_lead, controller, cfo or cto)</Text>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="lg"><Text fw={600} mb="sm">Matching & controls</Text>
            <Table fz="sm"><Table.Tbody>
              {row("Materiality (auto-accept below)", `${usd(s.materiality_abs)} or ${(Number(s.materiality_pct) * 100).toFixed(1)}% of total`)}
              {row("Quantity tolerance", `${(Number(s.qty_tolerance_pct) * 100).toFixed(1)}%`)}
              {row("Price tolerance", `${(Number(s.price_tolerance_pct) * 100).toFixed(1)}%`)}
              {row("Locked periods (nothing posts)", s.locked_periods.join(", "))}
              {Object.entries(s.accounts).map(([k, v]) => row(`GL: ${k.replace("_", " ")}`, <Text ff="monospace" fz="sm">{v}</Text>))}
              {row("FX to USD (simulated)", Object.entries(s.fx_rates).map(([c, r]) => `${c} ${r}`).join(" · "))}
            </Table.Tbody></Table>
          </Card>
          <Card withBorder padding="lg" mt="lg"><Text fw={600} mb="sm">Integrations</Text>
            <Table fz="sm"><Table.Tbody>
              {erp && <Table.Tr><Table.Td><Text fz="sm" fw={500}>ERP · {erp.mode === "odoo" ? "Odoo" : "Simulated"}</Text>
                <Text fz="xs" c="dimmed">{erp.mode === "odoo" && erp.url ? <><Anchor href={erp.url} target="_blank" fz="xs">{erp.url}</Anchor>{erp.database && ` · db ${erp.database}`}{erp.note && ` · ${erp.note}`}</> : erp.note}</Text></Table.Td>
                <Table.Td ta="right"><Badge variant="light" color={erp.mode === "odoo" ? (erp.connected ? "green" : "red") : "yellow"}>
                  {erp.mode === "odoo" ? (erp.connected ? "connected" : "not reachable") : "simulated"}</Badge></Table.Td></Table.Tr>}
              {s.integrations.map((i) => (
              <Table.Tr key={i.name}><Table.Td><Text fz="sm" fw={500}>{i.name}</Text><Text fz="xs" c="dimmed">{i.note}</Text></Table.Td>
                <Table.Td ta="right"><Badge variant="light" color={STATUS[i.status]}>{i.status.replace("_", " ")}</Badge></Table.Td></Table.Tr>
            ))}</Table.Tbody></Table>
          </Card>
        </Grid.Col>
      </Grid>
    </>
  );
}
