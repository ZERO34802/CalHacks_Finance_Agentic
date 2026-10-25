// Agent trace as a flow chart: the raw steps (often 20+) are grouped into the pipeline's phases, one node each.
// Click a phase to see its sub-steps (agent, skill version, timing, errors, raw detail). A controller rejection
// that sent the case back to the Investigator shows as a dashed loop from Sign-off back to Investigate.
import { Anchor, Badge, Box, Group, ScrollArea, Stack, Text } from "@mantine/core";
import { IconAlertOctagon, IconAlertTriangle } from "@tabler/icons-react";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo, useState } from "react";
import type { ReviewPacket, Step } from "../types/contracts";
import { findingColor, stage, stepColor } from "./format";
import { HEAD_BG, HEAD_BORDER, symbols } from "./parts";

export const stepName = (st: string) => {
  const l = stage(st);
  return l !== st ? l : (st.split(".").pop() ?? st).replace(/^a_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
};

// phase -> which step stages and which finding agents belong to it
const PHASES: { key: string; title: string; stages: string[]; agents: string[] }[] = [
  { key: "read", title: "Receive & read", stages: ["intake", "reader"], agents: ["Reader"] },
  { key: "dedup", title: "Duplicate check", stages: ["doc_dedup", "registry"], agents: ["Dedup", "Case registry"] },
  { key: "match", title: "3-way match", stages: ["matcher"], agents: ["Matcher"] },
  { key: "investigate", title: "Investigate", stages: ["router", "investigator"], agents: ["Router", "Investigator"] },
  { key: "vendor", title: "Vendor & bank", stages: ["vendor_guard"], agents: ["Vendor Guard"] },
  { key: "validate", title: "Controls re-check", stages: ["validators"], agents: ["Validators"] },
  { key: "approve", title: "Sign-off", stages: ["approver", "supplier"], agents: ["Approver"] },
  { key: "post", title: "Ledger", stages: ["poster"], agents: ["Poster"] },
  { key: "after", title: "After the case", stages: ["after_case", "memory"], agents: [] },
];
const phaseOf = (st: string) => PHASES.find((p) => p.stages.includes(st.split(".")[0]))?.key ?? "after";

type Phase = { key: string; title: string; steps: Step[]; findings: ReviewPacket["findings"]; status: string; ms: number };
const RANK = ["failed", "blocked", "flag", "escalated", "running", "retried", "ok", "skipped"];
const rank = (s: string) => (RANK.includes(s) ? RANK.indexOf(s) : RANK.length);
const worst = (xs: string[]) => [...xs].sort((a, b) => rank(a) - rank(b))[0] ?? "skipped";
const tone = (s: string) => (s === "flag" ? findingColor(s) : stepColor(s));   // amber = needs review, red = danger
// status mark: warning triangle (amber), danger octagon (red), else a dot
const Mark = ({ c, size, dim }: { c: string; size: number; dim?: boolean }) =>
  c === "amber" ? <IconAlertTriangle size={size + 6} color="var(--mantine-color-amber-7)" style={{ flexShrink: 0 }} />
    : c === "red" ? <IconAlertOctagon size={size + 6} color="var(--mantine-color-red-7)" style={{ flexShrink: 0 }} />
      : <span style={{ width: size, height: size, margin: 3, borderRadius: size, flexShrink: 0, background: `var(--mantine-color-${dim ? "gray-4" : "brand-6"})` }} />;

function phases(packet: ReviewPacket): Phase[] {
  const out = PHASES.map((p) => ({ key: p.key, title: p.title, steps: [] as Step[], findings: [] as Phase["findings"], status: "skipped", ms: 0 }));
  const at = (k: string) => out.find((p) => p.key === k)!;
  [...packet.trace].sort((a, b) => a.seq - b.seq).forEach((s) => at(phaseOf(s.stage)).steps.push(s));
  packet.findings.forEach((f) => at(PHASES.find((p) => p.agents.includes(f.agent))?.key ?? "after").findings.push(f));
  out.forEach((p) => {
    const ran = p.steps.filter((s) => s.status !== "skipped");
    p.status = worst([...ran.map((s) => s.status), ...p.findings.filter((f) => f.status === "flag").map(() => "flag")]);
    p.ms = p.steps.reduce((n, s) => n + (s.duration_ms ?? 0), 0);
  });
  return out.filter((p) => p.steps.length || p.findings.length);
}

const W = 196, H = 58, GAP = 22;
type PhaseData = { p: Phase; on: boolean };

function PhaseNode({ data }: NodeProps<Node<PhaseData>>) {
  const { p, on } = data;
  const c = tone(p.status), skipped = p.status === "skipped";
  // the outcome in a few words (the finding), not the phase name again
  const gist = p.findings[0] ? symbols(p.findings[0].detail) : `${p.steps.length} step${p.steps.length === 1 ? "" : "s"}`;
  return (
    <Box w={W} h={H} px={10} py={8} style={{
      borderRadius: 8, cursor: "pointer", background: on ? "var(--mantine-color-brand-0)" : "var(--mantine-color-body)",
      border: `1px ${skipped ? "dashed" : "solid"} var(--mantine-color-${on ? "brand-6" : skipped ? "gray-4" : c === "red" ? "red-4" : c === "amber" ? "amber-4" : "brand-3"})`,
      boxShadow: on ? "0 0 0 3px var(--mantine-color-brand-1)" : undefined, opacity: skipped ? 0.65 : 1,
    }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle id="r-out" type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle id="r-in" type="target" position={Position.Right} style={{ opacity: 0 }} />
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Mark c={skipped ? "gray" : c} size={8} dim={skipped} />
          <Text fz="sm" fw={600} truncate>{p.title}</Text>
        </Group>
        <Text fz={10} c="dimmed" style={{ flexShrink: 0 }}>{skipped ? "skipped" : `${p.ms} ms`}</Text>
      </Group>
      <Text fz="xs" c={c === "red" ? "red.7" : c === "amber" ? "amber.8" : "dimmed"} truncate mt={2} pl={20}>{gist}</Text>
    </Box>
  );
}
const nodeTypes = { phase: PhaseNode };

export function TraceFlow({ packet }: { packet: ReviewPacket }) {
  const ps = useMemo(() => phases(packet), [packet]);
  const [sel, setSel] = useState<string | null>(null);
  const cur = ps.find((p) => p.key === sel) ?? ps.find((p) => ["failed", "blocked", "flag"].includes(p.status)) ?? ps[0];
  const replan = packet.trace.some((s) => s.stage.endsWith("replan"));

  const nodes: Node<PhaseData>[] = ps.map((p, i) => ({ id: p.key, type: "phase", position: { x: 0, y: i * (H + GAP) }, data: { p, on: p.key === cur?.key } }));
  const edges: Edge[] = ps.slice(1).map((p, i) => ({ id: `${ps[i].key}-${p.key}`, source: ps[i].key, target: p.key, type: "smoothstep",
    style: { stroke: `var(--mantine-color-${p.status === "skipped" ? "gray-4" : "brand-4"})`, strokeWidth: 1.5 } }));
  if (replan && ps.some((p) => p.key === "approve") && ps.some((p) => p.key === "investigate")) edges.push({
    id: "replan", source: "approve", sourceHandle: "r-out", target: "investigate", targetHandle: "r-in", type: "smoothstep", animated: true,
    label: "re-plan", labelStyle: { fontSize: 10, fill: "var(--mantine-color-brand-8)" }, labelBgStyle: { fill: "var(--mantine-color-body)" },
    style: { stroke: "var(--mantine-color-brand-6)", strokeDasharray: "4 3", strokeWidth: 1.5 },
  });

  return (
    <Box style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "290px minmax(0, 1fr)" }}>
      <Box style={{ minHeight: 0, borderRight: "1px solid var(--mantine-color-gray-3)" }}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={(_, n) => setSel(n.id)} fitView fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} zoomOnScroll={false} zoomOnDoubleClick={false} panOnScroll
          proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} color="var(--mantine-color-gray-3)" />
        </ReactFlow>
      </Box>
      {cur && <PhaseDetail p={cur} />}
    </Box>
  );
}

function PhaseDetail({ p }: { p: Phase }) {
  const [open, setOpen] = useState<string[]>([]);
  const tech = (s: Step) => Object.entries(s.detail).filter(([k]) => k !== "stub").map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ").slice(0, 900);
  return (
    <Box style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Group justify="space-between" px="md" py={10} bg={HEAD_BG} style={{ borderBottom: HEAD_BORDER, flexShrink: 0 }} wrap="nowrap">
        <Text fw={600}>{p.title}</Text>
        <Text fz="xs" c="dimmed">{p.steps.length} step{p.steps.length === 1 ? "" : "s"} · {p.ms} ms</Text>
      </Group>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack gap={0} px="md" pb="md">
          {p.findings.map((f, i) => (
            <Box key={i} py="sm" style={{ borderBottom: "1px solid var(--mantine-color-gray-2)" }}>
              {(f.check !== p.title || f.status !== "ok") && <Group gap={6} mb={2}>{f.check !== p.title && <Text fz="sm" fw={600}>{f.check}</Text>}
                {f.status !== "ok" && <Badge size="xs" variant="light" color={findingColor(f.status)}>{f.status === "unchecked" ? "not checked" : f.status}</Badge>}</Group>}
              <Text fz="sm" c={f.status === "flag" ? "amber.9" : f.status === "blocked" ? "red.8" : undefined}>{symbols(f.detail)}</Text>
            </Box>
          ))}
          {p.steps.map((s) => {
            const t = tech(s);
            return (
              <Box key={s.id} py={10} pl={s.parent_id ? "md" : 0} style={{ borderBottom: "1px solid var(--mantine-color-gray-2)" }}>
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                    <Mark c={s.status === "skipped" ? "gray" : stepColor(s.status)} size={6} dim={s.status === "skipped"} />
                    <Text fz="sm" fw={500} truncate>{s.parent_id ? "↳ " : ""}{stepName(s.stage)}</Text>
                    {s.status !== "ok" && <Badge size="xs" variant="light" color={stepColor(s.status)}>{s.status}</Badge>}
                    {s.detail.stub === true && <Badge size="xs" variant="outline" color="gray">placeholder</Badge>}
                  </Group>
                  <Text fz="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{s.duration_ms ?? "…"} ms</Text>
                </Group>
                <Text fz="xs" c="dimmed" pl={12}>{[s.role, s.skill && `${s.skill}@${s.skill_version}`, s.tool].filter(Boolean).join(" · ")}</Text>
                {s.error && <Text fz="xs" c="red.7" pl={12}>{s.error}</Text>}
                {t && <Anchor fz="xs" pl={12} onClick={() => setOpen((o) => (o.includes(s.id) ? o.filter((x) => x !== s.id) : [...o, s.id]))}>{open.includes(s.id) ? "Hide details" : "Details"}</Anchor>}
                {open.includes(s.id) && <Text fz="xs" ff="monospace" c="dimmed" pl={12} style={{ wordBreak: "break-word" }}>{t}</Text>}
              </Box>
            );
          })}
        </Stack>
      </ScrollArea>
    </Box>
  );
}
