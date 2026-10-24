// Settings: the rules the system enforces in code (read-only here; they live in config/policy.yaml), people,
// and integrations, labelled connected / simulated / not connected.
import { Badge, Card, Grid, Table, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import type { ApSettings } from "../../types/contracts";
import { ap } from "../api";
import { PEOPLE, usd } from "../format";
import { PageHead } from "../parts";

const STATUS: Record<string, string> = { connected: "green", simulated: "yellow", not_connected: "gray" };

export default function Settings() {
  const [s, setS] = useState<ApSettings | null>(null);
  useEffect(() => { ap.settings().then(setS).catch(() => {}); }, []);
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
              {row("Payment run released by", "Someone other than who prepared it")}
              {row("Bank details", "Agents can never change them; payments go to the vendor master only")}
            </Table.Tbody></Table>
          </Card>
          <Card withBorder padding="lg" mt="lg"><Text fw={600} mb="sm">People</Text>
            <Table fz="sm"><Table.Tbody>{Object.values(PEOPLE).map((p) => row(p.title, `${p.name} · ${p.email}`))}</Table.Tbody></Table>
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
            <Table fz="sm"><Table.Tbody>{s.integrations.map((i) => (
              <Table.Tr key={i.name}><Table.Td><Text fz="sm" fw={500}>{i.name}</Text><Text fz="xs" c="dimmed">{i.note}</Text></Table.Td>
                <Table.Td ta="right"><Badge variant="light" color={STATUS[i.status]}>{i.status.replace("_", " ")}</Badge></Table.Td></Table.Tr>
            ))}</Table.Tbody></Table>
          </Card>
        </Grid.Col>
      </Grid>
    </>
  );
}
