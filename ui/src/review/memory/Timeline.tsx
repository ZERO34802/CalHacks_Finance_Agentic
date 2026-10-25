// Memory timeline: x = date, one row per memory line, a mark per version (color + shape = source family),
// hollow + struck = forgotten. Top lane: decisions that read memory. Vertical hairlines: skill changes.
import { Box, Group, Text } from "@mantine/core";
import { useElementSize } from "@mantine/hooks";
import { useState, type ReactNode } from "react";
import type { MemoryVersion, VendorMemoryTimeline } from "../../types/contracts";
import { FAMILY, familyOf, fmtDay, sourceOf, ts, type Shape } from "./model";

const INK = "#0b0b0b", INK2 = "#52514e", MUTED = "#898781", GRID = "#e1e0d9", BASE = "#c3c2b7", SURFACE = "#ffffff";
const LEFT = 236, RIGHT = 20, AXIS = 24, LANE = 30, ROW = 32, DAY = 86_400_000;

export function Mark({ shape, cx, cy, r, color, hollow, ring = SURFACE }: { shape: Shape; cx: number; cy: number; r: number; color: string; hollow?: boolean; ring?: string }) {
  const fill = hollow ? SURFACE : color;
  const stroke = hollow ? color : ring;
  const p = { fill, stroke, strokeWidth: 2 };
  if (shape === "square") { const s = r * 1.8; return <rect x={cx - s / 2} y={cy - s / 2} width={s} height={s} rx={1.5} {...p} />; }
  if (shape === "diamond") { const d = r * 1.3; return <polygon points={`${cx},${cy - d} ${cx + d},${cy} ${cx},${cy + d} ${cx - d},${cy}`} {...p} />; }
  if (shape === "triangle") { const d = r * 1.25; return <polygon points={`${cx},${cy - d} ${cx + d},${cy + d * 0.8} ${cx - d},${cy + d * 0.8}`} {...p} />; }
  return <circle cx={cx} cy={cy} r={r} {...p} />;
}

/** Small legend swatch that mirrors the mark. */
export function Swatch({ shape, color, hollow, size = 14 }: { shape: Shape; color: string; hollow?: boolean; size?: number }) {
  return <svg width={size} height={size} style={{ flexShrink: 0 }} aria-hidden><Mark shape={shape} cx={size / 2} cy={size / 2} r={size / 2 - 2.5} color={color} hollow={hollow} /></svg>;
}

type Tip = { x: number; y: number; body: ReactNode };

export default function Timeline({ data, asOf, selected, onSelect, onCase }: {
  data: VendorMemoryTimeline; asOf: number; selected: { entry_id: string; version: number } | null;
  onSelect: (entry_id: string, version: number) => void; onCase: (case_id: string) => void;
}) {
  const { ref, width } = useElementSize();
  const [tip, setTip] = useState<Tip | null>(null);
  const W = Math.max(width, 560);
  const skills = data.events.filter((e) => e.kind === "skill_change");
  const all = [
    ...data.slots.flatMap((s) => s.versions.map((v) => ts(v.valid_from))),
    ...data.uses.map((u) => ts(u.at)), ...skills.map((e) => ts(e.at)), Date.now(),
  ].filter((t) => !Number.isNaN(t));
  let t0 = Math.min(...all), t1 = Math.max(...all);
  const pad = Math.max((t1 - t0) * 0.03, 3 * DAY);
  t0 -= pad; t1 += pad;
  const x = (t: number) => LEFT + ((t - t0) / (t1 - t0)) * (W - LEFT - RIGHT);
  const top = AXIS + LANE;
  const H = top + data.slots.length * ROW + 10;

  // Month ticks, thinned so labels never collide.
  const months: number[] = [];
  for (let d = new Date(new Date(t0).getFullYear(), new Date(t0).getMonth() + 1, 1); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) months.push(d.getTime());
  const every = Math.max(1, Math.ceil(52 / Math.max(1, (W - LEFT - RIGHT) / Math.max(1, months.length))));
  const ticks = months.filter((_, i) => i % every === 0);

  const show = (cx: number, cy: number, body: ReactNode) => setTip({ x: cx, y: cy, body });
  const hide = () => setTip(null);

  const versionTip = (v: MemoryVersion, label: string) => {
    const f = familyOf(v.source);
    return (
      <>
        <Text fz="sm" fw={600} td={v.change === "forgotten" ? "line-through" : undefined} lh={1.35}>{v.text}</Text>
        <Group gap={6} mt={6} wrap="nowrap"><span style={{ width: 14, height: 2, background: f.color, borderRadius: 1, flexShrink: 0 }} />
          <Text fz="xs" c="dimmed">{sourceOf(v.source).label} · {v.provenance}</Text></Group>
        <Text fz="xs" c="dimmed" mt={2}>v{v.version} · {v.change} · valid from {fmtDay(ts(v.valid_from))}</Text>
        {v.cases.length > 0 && <Text fz="xs" c="dimmed" mt={2}>Cases: {v.cases.join(", ")}</Text>}
        {v.people.length > 0 && <Text fz="xs" c="dimmed" mt={2}>By: {v.people.join(", ")}</Text>}
        <Text fz={10} c="dimmed" mt={4}>{label} · click for history</Text>
      </>
    );
  };

  return (
    <Box ref={ref} pos="relative" onMouseLeave={hide}>
      <div style={{ overflowX: "auto" }}>
      <svg width={W} height={H} role="img" aria-label={`Memory timeline for ${data.vendor_name}`} style={{ display: "block", fontFamily: "inherit" }}>
        {/* axis + recessive month grid */}
        {ticks.map((t, i) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={AXIS - 4} y2={H - 6} stroke={GRID} strokeWidth={1} />
            <text x={x(t) + 4} y={AXIS - 10} fontSize={11} fill={MUTED} style={{ fontVariantNumeric: "tabular-nums" }}>
              {new Date(t).toLocaleDateString("en-US", { month: "short" })}{i === 0 || new Date(t).getMonth() === 0 ? ` ${new Date(t).getFullYear()}` : ""}
            </text>
          </g>
        ))}
        <line x1={LEFT} x2={W - RIGHT} y1={AXIS - 4} y2={AXIS - 4} stroke={BASE} strokeWidth={1} />

        {/* decisions lane */}
        <text x={0} y={AXIS + LANE / 2 + 4} fontSize={12} fill={INK2} fontWeight={600}>Decisions that read memory</text>
        {data.uses.length === 0 && <text x={LEFT + 6} y={AXIS + LANE / 2 + 4} fontSize={11} fill={MUTED}>none yet</text>}
        <line x1={0} x2={W - RIGHT} y1={top - 1} y2={top - 1} stroke={GRID} strokeWidth={1} />

        {/* rows */}
        {data.slots.map((s, i) => {
          const cy = top + i * ROW + ROW / 2;
          const isSel = selected?.entry_id === s.entry_id;
          const pts: { v: MemoryVersion; cx: number }[] = [];
          for (const v of s.versions) {
            let cx = x(ts(v.valid_from));
            const prev = pts[pts.length - 1];
            if (prev && cx - prev.cx < 13) cx = prev.cx + 13;   // same-day versions sit side by side
            pts.push({ v, cx });
          }
          const last = pts[pts.length - 1];
          const live = last && last.v.change !== "forgotten";
          const label = s.label.length > 34 ? `${s.label.slice(0, 33).trimEnd()}…` : s.label;
          return (
            <g key={s.entry_id}>
              <rect x={0} y={cy - ROW / 2} width={W - RIGHT} height={ROW} fill={isSel ? "#e6f4f5" : "transparent"} />
              {i > 0 && <line x1={0} x2={W - RIGHT} y1={cy - ROW / 2} y2={cy - ROW / 2} stroke="#f1f0ec" strokeWidth={1} />}
              <text x={0} y={cy + 4} fontSize={12} fill={s.current?.change === "forgotten" || !s.current ? MUTED : INK} style={{ cursor: "pointer" }}
                textDecoration={s.current?.change === "forgotten" ? "line-through" : undefined}
                onClick={() => last && onSelect(s.entry_id, last.v.version)}>
                <title>{s.label}</title>{label}
              </text>
              {/* lifetime: solid between versions, faint after the latest one while it is still believed */}
              {pts.slice(1).map((p, k) => <line key={k} x1={pts[k].cx} x2={p.cx} y1={cy} y2={cy} stroke={BASE} strokeWidth={2} strokeLinecap="round" />)}
              {live && <line x1={last.cx} x2={W - RIGHT} y1={cy} y2={cy} stroke={GRID} strokeWidth={2} strokeLinecap="round" />}
              {pts.map(({ v, cx }) => {
                const f = familyOf(v.source);
                const gone = v.change === "forgotten";
                const future = ts(v.valid_from) > asOf;
                const sel = isSel && selected?.version === v.version;
                return (
                  <g key={v.version} tabIndex={0} role="button" aria-label={`${s.label}, version ${v.version}, ${v.change}`}
                    style={{ cursor: "pointer", outline: "none", opacity: future ? 0.3 : 1 }}
                    onPointerEnter={() => show(cx, cy, versionTip(v, s.label))} onFocus={() => show(cx, cy, versionTip(v, s.label))} onBlur={hide}
                    onClick={() => onSelect(s.entry_id, v.version)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s.entry_id, v.version); } }}>
                    <circle cx={cx} cy={cy} r={12} fill="transparent" />
                    {sel && <circle cx={cx} cy={cy} r={10} fill="none" stroke={INK} strokeWidth={1.5} />}
                    <Mark shape={f.shape} cx={cx} cy={cy} r={5.5} color={f.color} hollow={gone} />
                    {gone && <line x1={cx - 6} y1={cy + 6} x2={cx + 6} y2={cy - 6} stroke={f.color} strokeWidth={2} strokeLinecap="round" />}
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* skill changes: full-height hairlines with a cap in the lane */}
        {skills.map((e, k) => {
          const cx = x(ts(e.at));
          const body = (<><Text fz="sm" fw={600}>{e.label}</Text><Text fz="xs" c="dimmed" mt={4}>Skill change · {fmtDay(ts(e.at))}</Text>
            {e.case_ids.length > 0 && <Text fz="xs" c="dimmed">Driven by cases: {e.case_ids.join(", ")}</Text>}</>);
          return (
            <g key={`sk${k}`} onPointerEnter={() => show(cx, AXIS + 8, body)} tabIndex={0} onFocus={() => show(cx, AXIS + 8, body)} onBlur={hide} style={{ outline: "none" }}>
              <line x1={cx} x2={cx} y1={AXIS + 2} y2={H - 6} stroke={INK2} strokeWidth={1} />
              <rect x={cx - 4} y={AXIS + 2} width={8} height={8} rx={1.5} fill={INK2} stroke={SURFACE} strokeWidth={2} />
              <rect x={cx - 7} y={AXIS} width={14} height={H - AXIS} fill="transparent" />
            </g>
          );
        })}

        {/* decision ticks (memory_use) */}
        {data.uses.map((u, k) => {
          const cx = x(ts(u.at)), cy = AXIS + LANE / 2;
          const body = (<><Text fz="sm" fw={600}>{u.decision ?? "decision pending"}</Text>
            <Text fz="xs" c="dimmed" mt={4}>Case {u.case_id} read {u.memory_version}</Text><Text fz="xs" c="dimmed">{fmtDay(ts(u.at))} · click to open the bill</Text></>);
          return (
            <g key={`u${k}`} style={{ cursor: "pointer", outline: "none" }} tabIndex={0} role="button" aria-label={`Case ${u.case_id} read memory`}
              onPointerEnter={() => show(cx, cy, body)} onFocus={() => show(cx, cy, body)} onBlur={hide} onClick={() => onCase(u.case_id)}
              onKeyDown={(e) => { if (e.key === "Enter") onCase(u.case_id); }}>
              <rect x={cx - 7} y={cy - 12} width={14} height={24} fill="transparent" />
              <line x1={cx} x2={cx} y1={cy - 6} y2={cy + 6} stroke={INK2} strokeWidth={2} strokeLinecap="round" />
            </g>
          );
        })}

        {/* as-of cursor */}
        <line x1={x(asOf)} x2={x(asOf)} y1={AXIS - 4} y2={H - 6} stroke="#0e6e76" strokeWidth={1.5} />
        <circle cx={x(asOf)} cy={AXIS - 4} r={3.5} fill="#0e6e76" stroke={SURFACE} strokeWidth={2} />
      </svg>
      </div>
      {tip && (
        <Box pos="absolute" p="xs" bg="white" style={{
          left: tip.x > W - 300 ? undefined : tip.x + 14, right: tip.x > W - 300 ? W - tip.x + 14 : undefined,
          top: tip.y < H / 2 ? Math.max(0, tip.y - 12) : undefined, bottom: tip.y < H / 2 ? undefined : H - tip.y - 12, width: 280, pointerEvents: "none", zIndex: 5, borderRadius: 8,
          border: "1px solid rgba(11,11,11,0.10)", boxShadow: "0 6px 20px rgba(0,0,0,0.10)",
        }}>{tip.body}</Box>
      )}
    </Box>
  );
}

export function TimelineLegend({ hasUses, hasSkills }: { hasUses: boolean; hasSkills: boolean }) {
  const item = (k: string, sw: ReactNode, label: string) => <Group key={k} gap={6} wrap="nowrap">{sw}<Text fz="xs" c="dimmed">{label}</Text></Group>;
  return (
    <Group gap="lg" style={{ rowGap: 6 }}>
      {(Object.keys(FAMILY) as (keyof typeof FAMILY)[]).map((k) => item(k, <Swatch shape={FAMILY[k].shape} color={FAMILY[k].color} />, FAMILY[k].label))}
      {item("forgot", <svg width={14} height={14} aria-hidden><Mark shape="circle" cx={7} cy={7} r={4.5} color={INK2} hollow /><line x1={2} y1={12} x2={12} y2={2} stroke={INK2} strokeWidth={2} /></svg>, "Forgotten")}
      {item("use", <svg width={14} height={14} aria-hidden><line x1={7} x2={7} y1={1} y2={13} stroke={INK2} strokeWidth={2} strokeLinecap="round" /></svg>, hasUses ? "Decision read memory" : "Decision read memory (none yet)")}
      {item("skill", <svg width={14} height={14} aria-hidden><line x1={7} x2={7} y1={0} y2={14} stroke={INK2} strokeWidth={1} /><rect x={3} y={0} width={8} height={8} rx={1.5} fill={INK2} /></svg>, hasSkills ? "Skill change" : "Skill change (none yet)")}
      {item("asof", <svg width={14} height={14} aria-hidden><line x1={7} x2={7} y1={0} y2={14} stroke="#0e6e76" strokeWidth={1.5} /></svg>, "As-of date")}
    </Group>
  );
}

