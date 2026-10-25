// Memory: per-vendor, self-evolving agentic memory. Every line has provenance and a version history;
// the Investigator reads it per case (trace records the version); skill changes are driven by cases.
import { Alert, Anchor, Badge, Button, Card, Grid, Group, Paper, Select, SimpleGrid, Slider, Stack, Text, ThemeIcon, Timeline as MTimeline } from "@mantine/core";
import { IconBrain } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import type { MemorySlot, MemoryVersion, VendorMemoryTimeline } from "../../types/contracts";
import { ap } from "../api";
import { useApp } from "../context";
import { shortName } from "../format";
import { changeDays, dayStart, familyOf, fmtDay, sourceOf, ts, versionAt, wordDiff } from "../memory/model";
import Timeline, { Swatch, TimelineLegend } from "../memory/Timeline";
import { Avatarish, PageHead, Stat } from "../parts";

const DAY = 86_400_000;

export default function Memory({ vendorId }: { vendorId?: string }) {
  const { vendors, bills, go } = useApp();
  const list = Object.values(vendors);
  const id = vendorId ?? list[0]?.id;
  const [data, setData] = useState<VendorMemoryTimeline | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState<{ entry_id: string; version: number } | null>(null);
  const [step, setStep] = useState<number | null>(null);

  useEffect(() => { setData(null); setSel(null); setStep(null); }, [id]);
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    ap.memoryTimeline(id).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, [id, bills]);

  const steps = useMemo(() => {
    if (!data) return [];
    const today = dayStart(Date.now());
    return [...new Set([...changeDays(data.slots), today])].sort((a, b) => a - b);
  }, [data]);
  const idx = step == null || step >= steps.length ? steps.length - 1 : step;
  const asOf = steps.length ? steps[idx] + DAY - 1 : Date.now();

  const picker = (
    <Select w={300} value={id ?? null} allowDeselect={false} placeholder="Pick a vendor" aria-label="Vendor"
      data={list.map((v) => ({ value: v.id, label: v.name }))} onChange={(v) => v && go(`memory/${v}`)} />
  );
  if (!id) return <><PageHead title="Memory" sub="What ReconAI remembers about each supplier" /><Text c="dimmed">No vendors loaded yet.</Text></>;
  if (err && !data) return <><PageHead title="Memory" right={picker} /><Alert color="red" title="Could not load memory">{err}</Alert></>;
  if (!data) return <><PageHead title="Memory" right={picker} /><Text c="dimmed" fz="sm">Loading memory…</Text></>;

  const skills = data.events.filter((e) => e.kind === "skill_change");
  const liveLines = data.slots.filter((s) => s.current && s.current.change !== "forgotten").length;
  const versions = data.slots.reduce((n, s) => n + s.versions.length, 0);
  const slot = sel ? data.slots.find((s) => s.entry_id === sel.entry_id) ?? null : null;

  return (
    <div style={{ opacity: loading ? 0.6 : 1, transition: "opacity 120ms" }}>
      <PageHead title="Memory" right={picker} sub={<>
        What ReconAI remembers about <b>{shortName(data.vendor_name)}</b>
        {data.memory_version && <> · <Badge variant="light" color="gray" ff="monospace" tt="none">{data.memory_version}</Badge></>}
      </>} />

      {data.slots.length === 0 ? (
        <Paper withBorder radius="md" p={48}>
          <Stack align="center" gap="xs">
            <ThemeIcon size={48} radius="xl" variant="light"><IconBrain size={26} /></ThemeIcon>
            <Text fw={600} fz="lg">Memory starts after the first case closes</Text>
            <Text c="dimmed" fz="sm" ta="center" maw={520}>
              When a {shortName(data.vendor_name)} case is resolved, the Memory Writer records facts from the system of record,
              patterns computed from case history, and controller decisions, each with provenance and a version.
            </Text>
          </Stack>
        </Paper>
      ) : (
        <>
          <Grid gutter="lg" mb="lg">
            <Grid.Col span={{ base: 12, md: 7 }}>
              <SimpleGrid cols={{ base: 2, sm: 4 }}>
                <Stat label="Lines" value={liveLines} sub={`${data.slots.length - liveLines} forgotten`} />
                <Stat label="Versions" value={versions} sub="history kept" />
                <Stat label="Decisions used it" value={data.uses.length} sub="cases that read memory" />
                <Stat label="Skill changes" value={skills.length} sub="driven by cases" />
              </SimpleGrid>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 5 }}><SourceBreakdown sources={data.sources} /></Grid.Col>
          </Grid>

          <Card withBorder padding="lg" mb="lg">
            <Group justify="space-between" align="flex-start" mb="sm">
              <div><Text fw={600}>How this memory evolved</Text>
                <Text fz="xs" c="dimmed">Written only from trusted signals (system of record, case outcomes, human decisions), never from incoming documents · hover a mark for provenance, click for its history</Text></div>
            </Group>
            <TimelineLegend hasUses={data.uses.length > 0} hasSkills={skills.length > 0} />
            <div style={{ marginTop: 12 }}>
              <Timeline data={data} asOf={asOf} selected={sel} onSelect={(entry_id, version) => setSel({ entry_id, version })} onCase={(c) => go(`bill/${c}`)} />
            </div>
          </Card>

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, md: 7 }}>
              <AsOf data={data} steps={steps} idx={idx} setStep={setStep} asOf={asOf} onSelect={(s) => s.current && setSel({ entry_id: s.entry_id, version: (versionAt(s, asOf) ?? s.current).version })} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 5 }}>
              {slot ? <Detail slot={slot} version={sel!.version} onCase={(c) => go(`bill/${c}`)} onClose={() => setSel(null)} />
                : <Card withBorder padding="lg"><Text fw={600}>Line history</Text><Text fz="sm" c="dimmed" mt={4}>Click a mark on the timeline, or a line on the left, to see every version with diffs, provenance, cases and people.</Text></Card>}
            </Grid.Col>
          </Grid>
        </>
      )}
    </div>
  );
}

function SourceBreakdown({ sources }: { sources: Record<string, number> }) {
  const rows = Object.entries(sources).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <Card withBorder padding="md" h="100%">
      <Text fz="xs" c="dimmed" tt="uppercase" fw={600} mb={8}>Where it came from</Text>
      <Stack gap={6}>
        {rows.map(([src, n]) => {
          const f = familyOf(src);
          return (
            <Group key={src} gap="sm" wrap="nowrap" title={sourceOf(src).hint}>
              <Swatch shape={f.shape} color={f.color} size={14} />
              <Text fz="xs" w={150} style={{ flexShrink: 0 }}>{sourceOf(src).label}</Text>
              <div style={{ flex: 1, height: 8 }}>
                <div style={{ width: `${(n / max) * 100}%`, height: 8, background: f.color, borderRadius: "0 4px 4px 0", minWidth: 4 }} />
              </div>
              <Text fz="xs" fw={600} w={22} ta="right" style={{ fontVariantNumeric: "tabular-nums" }}>{n}</Text>
            </Group>
          );
        })}
        {rows.length === 0 && <Text fz="xs" c="dimmed">No lines yet.</Text>}
      </Stack>
    </Card>
  );
}

function DiffText({ from, to }: { from: string; to: string }) {
  return (
    <Text fz="sm" lh={1.45}>
      {wordDiff(from, to).map((p, i) => p.op === "same" ? <span key={i}>{p.t}</span>
        : p.op === "add" ? <span key={i} style={{ background: "var(--mantine-color-green-1)", color: "var(--mantine-color-green-9)", borderRadius: 3 }}>{p.t}</span>
          : <span key={i} style={{ background: "var(--mantine-color-red-0)", color: "var(--mantine-color-red-8)", textDecoration: "line-through", borderRadius: 3, marginRight: 2 }}>{p.t}</span>)}
    </Text>
  );
}

function AsOf({ data, steps, idx, setStep, asOf, onSelect }: {
  data: VendorMemoryTimeline; steps: number[]; idx: number; setStep: (i: number) => void; asOf: number; onSelect: (s: MemorySlot) => void;
}) {
  const prevT = idx > 0 ? steps[idx - 1] + DAY - 1 : -Infinity;
  const rows = data.slots.map((s) => ({ s, now: versionAt(s, asOf), before: idx > 0 ? versionAt(s, prevT) : null }));
  const known = rows.filter((r) => r.now);
  const dropped = rows.filter((r) => !r.now && r.before);
  const uses = data.uses.filter((u) => ts(u.at) <= asOf).length;
  const marks = steps.length <= 12 ? steps.map((_, i) => ({ value: i })) : [];
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" align="flex-end">
        <div><Text fz="xs" c="dimmed">Audit replay</Text><Text fw={600}>What ReconAI knew on {fmtDay(steps[idx])}</Text></div>
        <Text fz="xs" c="dimmed">{known.length} line{known.length === 1 ? "" : "s"} · {uses} decision{uses === 1 ? "" : "s"} had read memory by then</Text>
      </Group>
      <Slider mt="md" mb="xl" min={0} max={Math.max(0, steps.length - 1)} step={1} value={idx} onChange={setStep} marks={marks}
        label={(i) => fmtDay(steps[i] ?? Date.now())} disabled={steps.length < 2} aria-label="As of date" />
      <Group justify="space-between" mt={-12} mb="sm">
        <Text fz="xs" c="dimmed">{fmtDay(steps[0])}</Text>
        <Group gap={6}>
          <Button size="compact-xs" variant="default" disabled={idx === 0} onClick={() => setStep(idx - 1)}>Previous change</Button>
          <Button size="compact-xs" variant="default" disabled={idx >= steps.length - 1} onClick={() => setStep(idx + 1)}>Next change</Button>
        </Group>
        <Text fz="xs" c="dimmed">today</Text>
      </Group>
      <Stack gap={6}>
        {known.length === 0 && <Text fz="sm" c="dimmed">Nothing was known yet.</Text>}
        {known.map(({ s, now, before }) => {
          const v = now!;
          const isNew = idx > 0 && !before;
          const changed = !!before && before.version !== v.version;
          const f = familyOf(v.source);
          return (
            <Paper key={s.entry_id} withBorder={false} p="xs" radius="sm" style={{ cursor: "pointer", background: isNew || changed ? "var(--mantine-color-green-0)" : "var(--mantine-color-gray-0)" }} onClick={() => onSelect(s)}>
              <Group gap="sm" wrap="nowrap" align="flex-start">
                <div style={{ paddingTop: 4 }}><Swatch shape={f.shape} color={f.color} size={14} /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {changed ? <DiffText from={before!.text} to={v.text} /> : <Text fz="sm" lh={1.45}>{v.text}</Text>}
                  <Text fz="xs" c="dimmed">[{v.provenance}] · v{v.version} · from {fmtDay(ts(v.valid_from))}</Text>
                </div>
                {isNew && <Badge size="xs" color="green" variant="light">New</Badge>}
                {changed && <Badge size="xs" color="green" variant="light">Changed</Badge>}
              </Group>
            </Paper>
          );
        })}
        {dropped.map(({ s, before }) => (
          <Paper key={s.entry_id} p="xs" radius="sm" bg="red.0" style={{ cursor: "pointer" }} onClick={() => onSelect(s)}>
            <Group gap="sm" wrap="nowrap">
              <Text fz="sm" td="line-through" c="red.8" style={{ flex: 1 }}>{before!.text}</Text>
              <Badge size="xs" color="red" variant="light">Forgotten</Badge>
            </Group>
          </Paper>
        ))}
      </Stack>
      <Text fz="xs" c="dimmed" mt="sm">Memory is context, not evidence: decisions still cite current documents. Highlighted lines changed since the previous step.</Text>
    </Card>
  );
}

function Detail({ slot, version, onCase, onClose }: { slot: MemorySlot; version: number; onCase: (c: string) => void; onClose: () => void }) {
  const vs = slot.versions;
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div style={{ minWidth: 0 }}><Text fz="xs" c="dimmed">Line history · {vs.length} version{vs.length === 1 ? "" : "s"}</Text>
          <Text fw={600} lh={1.3}>{slot.current?.text ?? slot.label}</Text></div>
        <Anchor fz="xs" onClick={onClose}>Close</Anchor>
      </Group>
      <MTimeline mt="md" bulletSize={18} lineWidth={2} active={vs.length - 1} color="brand">
        {vs.map((v, i) => <MTimeline.Item key={v.version} bullet={<Swatch shape={familyOf(v.source).shape} color={familyOf(v.source).color} hollow={v.change === "forgotten"} size={12} />}
          title={<Group gap={6}><Text fz="sm" fw={600}>v{v.version}</Text><ChangeBadge change={v.change} /><Text fz="xs" c="dimmed">from {fmtDay(ts(v.valid_from))}</Text></Group>}>
          <VersionBody v={v} prev={i > 0 ? vs[i - 1] : null} onCase={onCase} highlight={v.version === version} />
        </MTimeline.Item>)}
      </MTimeline>
    </Card>
  );
}

const ChangeBadge = ({ change }: { change: string }) =>
  <Badge size="xs" variant="light" color={change === "added" ? "brand" : change === "forgotten" ? "red" : "blue"}>{change}</Badge>;

function VersionBody({ v, prev, onCase, highlight }: { v: MemoryVersion; prev: MemoryVersion | null; onCase: (c: string) => void; highlight: boolean }) {
  const src = sourceOf(v.source);
  return (
    <Paper p={highlight ? "xs" : 0} mt={4} radius="sm" bg={highlight ? "brand.0" : undefined}>
      {v.change === "forgotten" ? <Text fz="sm" td="line-through" c="dimmed">{prev?.text ?? v.text}</Text>
        : prev ? <DiffText from={prev.text} to={v.text} /> : <Text fz="sm">{v.text}</Text>}
      <Text fz="xs" c="dimmed" mt={4}>{src.label} · [{v.provenance}]</Text>
      {(v.cases.length > 0 || v.people.length > 0) && (
        <Group gap={6} mt={6}>
          {v.cases.map((c) => <Badge key={c} size="sm" variant="outline" color="gray" tt="none" style={{ cursor: "pointer" }} onClick={() => onCase(c)}>{c}</Badge>)}
          {v.people.map((p) => <Group key={p} gap={4} wrap="nowrap"><Avatarish name={p} size={18} /><Text fz="xs">{p}</Text></Group>)}
        </Group>
      )}
    </Paper>
  );
}

