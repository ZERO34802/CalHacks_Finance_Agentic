// Outbound email (supplier discrepancy, onboarding confirmation): status, recipient, full body. Shared by BillPage and Vendors.
import { Badge, Group, Paper, Text, Tooltip } from "@mantine/core";
import type { OutboundEmail } from "../types/contracts";
import { when } from "./format";

export const emailStatus = (e: OutboundEmail) =>
  e.status === "sent" ? { label: e.provider === "resend" ? "Sent via Resend" : "Sent", color: "green" }
    : e.status === "failed" ? { label: "Failed", color: "red" } : { label: "In outbox", color: "yellow" };

export const emailGist = (e: OutboundEmail) => e.subject.match(/request for (.+)$/i)?.[1] ?? e.subject.replace(/^\[REC [^\]]+\]\s*/, "");

export function EmailStatusBadge({ e }: { e: OutboundEmail }) {
  const s = emailStatus(e);
  return <Tooltip label={e.error ?? ""} disabled={!e.error}><Badge size="sm" variant="light" color={s.color}>{s.label}</Badge></Tooltip>;
}

export function EmailCard({ e, body = true }: { e: OutboundEmail; body?: boolean }) {
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap" mb={6}>
        <div style={{ minWidth: 0 }}>
          <Text fz="sm" fw={600}>{e.subject}</Text>
          <Text fz="xs" c="dimmed">To {e.to} (contact on file){e.delivered_to && e.delivered_to !== e.to ? ` · delivered to ${e.delivered_to} (demo inbox)` : ""} · {when(e.created_at)}</Text>
        </div>
        <EmailStatusBadge e={e} />
      </Group>
      {e.status === "failed" && e.error && <Text fz="xs" c="red.7" mb={6}>{e.error}</Text>}
      {body && <Paper bg="gray.0" p="sm"><Text ff="monospace" fz="xs" style={{ whiteSpace: "pre-wrap" }}>{e.body}</Text></Paper>}
      {e.provider_id && <Text fz={10} c="dimmed" ff="monospace" mt={4}>{e.provider} id {e.provider_id}</Text>}
    </Paper>
  );
}
