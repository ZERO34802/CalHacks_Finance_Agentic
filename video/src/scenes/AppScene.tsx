import type { FC, ReactNode } from "react";
import { AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Cursor, Icon, type IconName, LogoTile } from "../components";
import { C, clamp, clickPress, cursorPath, easeInOut, glass, prog, ui } from "../theme";

// Scene 4, the main product shot: the ReconAI app in dark glass.
//  A. Home: KPI cards count up, sparklines draw, a glowing chart draws; the cursor scrubs it and the tooltip snaps to
//     two real catches (INV-2291-A duplicate, PPT-6620 bank change).
//  B. Bills: the cursor opens the status filter, picks "Needs you", rows refresh, and it opens the Penang bill.
// Nav, statuses and every bill row match ui/ and data/answer_key.json. Chart shape is illustrative (no axis values).
export const APP_FRAMES = 480;

const WIN = { x: 120, y: 50, w: 1680, h: 800 };
const SIDE = 110;
const HEAD = 84;
const L = SIDE + 40;            // content left, window coords
const T = HEAD + 30;            // content top
const CW = WIN.w - SIDE - 80;   // content width
const abs = (x: number, y: number) => ({ x: WIN.x + x, y: WIN.y + y });

// --- timeline -------------------------------------------------------------------------------------------------------
const SCRUB = [178, 196, 214, 238, 256];   // scrub keyframes: start, at dot 1, hold, at dot 2, hold
const NAV_CLICK = 286;
const SWITCH = 290;                         // Home -> Bills
const FILTER_CLICK = 344;
const OPTION_CLICK = 392;
const ROW_CLICK = 464;

// --- Home: KPI cards ------------------------------------------------------------------------------------------------
const KPI_W = (CW - 2 * 30) / 3;
const KPIS = [
  { label: "Caught before payment", to: 857, fmt: (v: number) => `$${Math.round(v)}k`, color: C.cyan, spark: [3, 4, 3.5, 5, 4.6, 6, 7, 6.4, 8, 9] },
  { label: "Test cases passed", to: 48, fmt: (v: number) => `${Math.round(v)}/48`, color: C.green, spark: [] },
  { label: "Hours saved (est.)", to: 23, fmt: (v: number) => `${Math.round(v)}h`, color: C.violet, spark: [2, 3, 2.6, 4, 3.4, 5, 4.6, 6, 5.5, 7] },
];

const Sparkline: FC<{ data: number[]; color: string; p: number }> = ({ data, color, p }) => {
  const w = 170, h = 64, max = Math.max(...data);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h * 0.9}`).join(" ");
  return (
    <svg width={w} height={h} style={{ overflow: "visible", filter: `drop-shadow(0 0 6px ${color})` }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />
    </svg>
  );
};

const Kpi: FC<{ i: number }> = ({ i }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = KPIS[i];
  const t0 = 24 + i * 12;
  const s = spring({ frame: frame - t0, fps, config: { damping: 14, stiffness: 110 } });
  const v = interpolate(frame, [t0 + 6, t0 + 70], [0, k.to], { ...clamp, easing: easeInOut });
  const sp = prog(frame, t0 + 14, t0 + 70, easeInOut);
  return (
    <div style={{
      ...glass, position: "absolute", left: L + i * (KPI_W + 30), top: T, width: KPI_W, height: 180, borderRadius: 24,
      padding: "26px 30px", boxSizing: "border-box", opacity: Math.min(1, s * 1.4), transform: `translateY(${(1 - s) * 50}px)`,
    }}>
      <div style={{ fontSize: 22, color: C.muted, fontWeight: 500 }}>{k.label}</div>
      <div style={{ fontSize: 68, fontWeight: 800, letterSpacing: -2, marginTop: 10, fontVariantNumeric: "tabular-nums" }}>{k.fmt(v)}</div>
      <div style={{ position: "absolute", right: 30, bottom: 34 }}>
        {k.spark.length ? <Sparkline data={k.spark} color={k.color} p={sp} /> : (
          // test cases: a ring that fills as the count goes up
          <svg width={84} height={84} viewBox="0 0 84 84" style={{ filter: `drop-shadow(0 0 6px ${k.color})` }}>
            <circle cx={42} cy={42} r={34} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth={9} />
            <circle cx={42} cy={42} r={34} fill="none" stroke={k.color} strokeWidth={9} strokeLinecap="round" pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - v / 48} transform="rotate(-90 42 42)" />
          </svg>
        )}
      </div>
    </div>
  );
};

// --- Home: chart ----------------------------------------------------------------------------------------------------
const CH = { x: L, y: T + 210, w: CW, h: WIN.h - (T + 210) - 30 };
const PLOT = { x: 50, y: 110, w: CW - 100, h: CH.h - 170 };
const SERIES = [0.32, 0.4, 0.36, 0.52, 0.47, 0.6, 0.55, 0.68, 0.63, 0.8, 0.73, 0.86];
const DOTS: Record<number, { bill: string; what: string; amount: string }> = {
  3: { bill: "INV-2291-A", what: "Duplicate of a paid bill", amount: "$21,600" },
  9: { bill: "PPT-6620", what: "Bank details changed", amount: "$3.3M" },
};
const px = (i: number) => PLOT.x + (i / (SERIES.length - 1)) * PLOT.w;
const py = (v: number) => PLOT.y + PLOT.h - v * PLOT.h;
const LINE = SERIES.map((v, i) => {
  if (i === 0) return `M ${px(0)} ${py(v)}`;
  const mx = (px(i - 1) + px(i)) / 2;
  return `C ${mx} ${py(SERIES[i - 1])} ${mx} ${py(v)} ${px(i)} ${py(v)}`;
}).join(" ");
const AREA = `${LINE} L ${px(SERIES.length - 1)} ${PLOT.y + PLOT.h} L ${px(0)} ${PLOT.y + PLOT.h} Z`;
const SCRUB_Y = abs(CH.x, CH.y).y + PLOT.y + PLOT.h * 0.62;
const scrubX = (f: number) => abs(CH.x, 0).x + interpolate(f, SCRUB, [px(1), px(3), px(3), px(9), px(9)], { ...clamp, easing: easeInOut });

const Chart: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - 70, fps, config: { damping: 16, stiffness: 100 } });
  const draw = prog(frame, 92, 160, easeInOut);
  const scrubbing = frame >= SCRUB[0] && frame < SCRUB[4] + 18;
  const cx = scrubX(frame) - WIN.x - CH.x;
  const lagX = scrubX(frame - 4) - WIN.x - CH.x;   // tooltip follows a beat behind: fluid follow
  const idx = Math.round(((cx - PLOT.x) / PLOT.w) * (SERIES.length - 1));
  const snap = Math.max(0, Math.min(SERIES.length - 1, idx));
  const near = Math.max(0, ...Object.keys(DOTS).map((k) => 1 - Math.abs(cx - px(+k)) / 60));
  const dot = DOTS[snap];
  const show = interpolate(frame, [SCRUB[0], SCRUB[0] + 8, SCRUB[4] + 10, SCRUB[4] + 18], [0, 1, 1, 0], clamp);
  const flip = lagX > PLOT.x + PLOT.w * 0.6;   // near the right edge the tooltip opens to the left
  return (
    <div style={{ ...glass, position: "absolute", left: CH.x, top: CH.y, width: CH.w, height: CH.h, borderRadius: 24,
      opacity: Math.min(1, s * 1.4), transform: `translateY(${(1 - s) * 50}px)` }}>
      <div style={{ position: "absolute", left: 32, top: 26, display: "flex", alignItems: "center", gap: 26 }}>
        <span style={{ fontSize: 26, fontWeight: 700 }}>Bills this quarter</span>
        <span style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 20, color: C.muted }}>
          <span style={{ width: 12, height: 12, borderRadius: 6, background: C.red, boxShadow: `0 0 10px ${C.red}` }} /> caught
        </span>
      </div>
      <svg width={CH.w} height={CH.h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs>
          <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.cyan} stopOpacity={0.35} />
            <stop offset="100%" stopColor={C.cyan} stopOpacity={0} />
          </linearGradient>
          <clipPath id="reveal"><rect x={0} y={0} width={PLOT.x + PLOT.w * draw + 4} height={CH.h} /></clipPath>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((g) => (
          <line key={g} x1={PLOT.x} x2={PLOT.x + PLOT.w} y1={PLOT.y + PLOT.h * (1 - g)} y2={PLOT.y + PLOT.h * (1 - g)} stroke="rgba(255,255,255,0.06)" />
        ))}
        {SERIES.map((_, i) => (
          <text key={i} x={px(i)} y={PLOT.y + PLOT.h + 40} fill={C.muted} fontSize={18} textAnchor="middle" fontFamily={ui}
            opacity={prog(frame, 92 + i * 3, 104 + i * 3)}>W{i + 1}</text>
        ))}
        <path d={AREA} fill="url(#fill)" clipPath="url(#reveal)" opacity={prog(frame, 110, 170)} />
        <path d={LINE} fill="none" stroke={C.cyan} strokeWidth={4.5} strokeLinecap="round" pathLength={1} strokeDasharray={1}
          strokeDashoffset={1 - draw} style={{ filter: `drop-shadow(0 0 10px ${C.cyan})` }} />
        {Object.keys(DOTS).map((k) => {
          const i = +k;
          const pop = spring({ frame: frame - (92 + 68 * (i / (SERIES.length - 1)) + 6), fps, config: { damping: 9, stiffness: 180 } });
          const hit = snap === i && scrubbing ? 1 : 0;
          return (
            <g key={k}>
              <circle cx={px(i)} cy={py(SERIES[i])} r={(18 + 10 * hit) * pop} fill={C.red} opacity={0.18 + 0.2 * hit} />
              <circle cx={px(i)} cy={py(SERIES[i])} r={9 * pop} fill={C.red} stroke="#fff" strokeWidth={3} />
            </g>
          );
        })}
        {/* scrubber: dashed guide locks to the nearest point */}
        <g opacity={show}>
          <line x1={px(snap)} x2={px(snap)} y1={PLOT.y - 10} y2={PLOT.y + PLOT.h} stroke="#fff" strokeOpacity={0.5} strokeWidth={2} strokeDasharray="6 8" />
          {!dot && <circle cx={px(snap)} cy={py(SERIES[snap])} r={9} fill={C.bg} stroke={C.cyan} strokeWidth={4} />}
        </g>
      </svg>
      {/* floating tooltip: week label between points, the caught bill on a red dot */}
      <div style={{
        position: "absolute", left: flip ? lagX - 26 : lagX + 26, top: py(SERIES[snap]) - 150, opacity: show, padding: "16px 22px", borderRadius: 18, whiteSpace: "nowrap",
        background: "rgba(20,22,30,0.85)", border: `1px solid ${dot ? C.red : C.line}`, backdropFilter: "blur(16px)",
        boxShadow: dot ? `0 0 30px rgba(255,84,112,0.35)` : "0 10px 30px rgba(0,0,0,0.4)", minWidth: 120,
        transform: `translateX(${flip ? -100 : 0}%) scale(${0.9 + 0.1 * Math.max(near, 0.001)})`, transformOrigin: flip ? "100% 100%" : "0 100%",
      }}>
        <div style={{ fontSize: 18, color: C.muted }}>Week {snap + 1}</div>
        {dot && (
          <div style={{ opacity: near, marginTop: 6 }}>
            <div style={{ fontSize: 26, fontWeight: 800 }}>{dot.bill} · {dot.amount}</div>
            <div style={{ fontSize: 20, color: C.red, marginTop: 4 }}>{dot.what}</div>
          </div>
        )}
      </div>
    </div>
  );
};

// --- Bills table ----------------------------------------------------------------------------------------------------
type Status = "Cleared" | "Needs you" | "Held" | "Rejected";
const STATUS_COLOR: Record<Status, string> = { Cleared: C.green, "Needs you": C.violet, Held: C.amber, Rejected: C.red };
type Row = [bill: string, vendor: string, reason: string, amount: string, status: Status];
const ALL: Row[] = [
  ["KM-INV-30118", "Kestrel Memory", "", "$72,500.00", "Cleared"],
  ["PPT-6620", "Penang Pack & Test", "Bank changed", "$3,300,000.00", "Needs you"],
  ["INV-881", "Formosa Wafer Works", "Short delivery", "NT$18,600,000", "Held"],
  ["INV-2291-A", "Aerolane Freight", "Duplicate", "$21,600.00", "Rejected"],
  ["KM-INV-30152", "Kestrel Memory", "Price over PO", "$49,600.00", "Held"],
  ["INV-2336", "Aerolane Freight", "", "$18,412.50", "Cleared"],
];
const NEEDS: Row[] = [
  ["PPT-6620", "Penang Pack & Test", "Bank changed", "$3,300,000.00", "Needs you"],
  ["INV-374", "Formosa Wafer Works", "Unknown PO", "NT$4,650,000", "Needs you"],
  ["KM-INV-30333", "Kestrel Memory", "Hidden instructions", "$43,500.00", "Needs you"],
];
const VENDOR_COLOR: Record<string, string> = { K: "#5b6cff", P: "#e0559b", F: "#22b8cf", A: "#f08c00" };
const ROW_H = 76;
const TABLE_Y = T + 100;
const COLS = [30, 330, 720, 1030, 1260];
const FILTER = { x: L + CW - 270, y: T - 6, w: 270, h: 62 };
const OPTIONS: (Status | "All bills")[] = ["All bills", "Needs you", "Held", "Cleared", "Rejected"];
const OPT_H = 60;
const MENU = { x: FILTER.x - 30, y: FILTER.y + FILTER.h + 12, w: FILTER.w + 30 };

const TableRow: FC<{ r: Row; i: number; at: number; dim?: number; hover?: number }> = ({ r, i, at, dim = 0, hover = 0 }) => {
  const frame = useCurrentFrame();
  const p = prog(frame, at + i * 5, at + i * 5 + 18);
  const [bill, vendor, reason, amount, status] = r;
  return (
    <div style={{
      position: "absolute", left: L, top: TABLE_Y + 56 + i * ROW_H, width: CW, height: ROW_H - 8, borderRadius: 16,
      display: "flex", alignItems: "center", fontSize: 24, opacity: p * (1 - dim * 0.8), filter: `blur(${dim * 4}px)`,
      transform: `translateX(${(1 - p) * 120}px)`, background: `rgba(255,255,255,${0.035 + hover * 0.07})`,
      border: `1px solid rgba(167,139,250,${hover * 0.8})`, boxShadow: hover ? `0 0 ${24 * hover}px rgba(167,139,250,0.35)` : undefined,
    }}>
      <span style={{ position: "absolute", left: COLS[0], fontWeight: 700 }}>{bill}</span>
      <span style={{ position: "absolute", left: COLS[1], display: "flex", alignItems: "center", gap: 14, color: "#d7d9e0" }}>
        <span style={{ width: 36, height: 36, borderRadius: 10, background: VENDOR_COLOR[vendor[0]], display: "flex", alignItems: "center",
          justifyContent: "center", fontWeight: 800, fontSize: 18, color: "#fff" }}>{vendor[0]}</span>
        {vendor}
      </span>
      <span style={{ position: "absolute", left: COLS[2], color: reason ? "#fff" : C.muted }}>{reason || "—"}</span>
      <span style={{ position: "absolute", left: COLS[3], width: 200, textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>{amount}</span>
      <span style={{ position: "absolute", left: COLS[4], display: "flex", alignItems: "center", gap: 10, padding: "6px 16px", borderRadius: 20,
        background: `${STATUS_COLOR[status]}22`, color: STATUS_COLOR[status], fontSize: 20, fontWeight: 700 }}>
        <span style={{ width: 9, height: 9, borderRadius: 5, background: STATUS_COLOR[status], boxShadow: `0 0 8px ${STATUS_COLOR[status]}` }} />
        {status}
      </span>
    </div>
  );
};

const Bills: FC<{ cursor: { x: number; y: number } }> = ({ cursor }) => {
  const frame = useCurrentFrame();
  const local = { x: cursor.x - WIN.x, y: cursor.y - WIN.y };
  const filtered = frame >= OPTION_CLICK + 4;
  const open = prog(frame, FILTER_CLICK + 2, FILTER_CLICK + 16) * (1 - prog(frame, OPTION_CLICK + 2, OPTION_CLICK + 14));
  const overBtn = local.x > FILTER.x && local.x < FILTER.x + FILTER.w && local.y > FILTER.y && local.y < FILTER.y + FILTER.h;
  const btnHover = overBtn ? 1 : 0;
  const hoverOpt = open > 0.5 ? Math.floor((local.y - MENU.y - 10) / OPT_H) : -1;
  const dimOld = prog(frame, OPTION_CLICK + 4, OPTION_CLICK + 14);
  const overRow0 = filtered && local.y > TABLE_Y + 56 && local.y < TABLE_Y + 56 + ROW_H && local.x > L ? 1 : 0;
  const rowFlash = interpolate(frame, [ROW_CLICK, ROW_CLICK + 6, ROW_CLICK + 16], [0, 1, 0.6], clamp);
  return (
    <>
      <div style={{ position: "absolute", left: L, top: T, fontSize: 40, fontWeight: 800, letterSpacing: -1 }}>Bills</div>
      {/* column headers */}
      <div style={{ position: "absolute", left: L, top: TABLE_Y + 10, width: CW, fontSize: 19, color: C.muted, fontWeight: 600, letterSpacing: 1 }}>
        {["BILL", "VENDOR", "WHY", "AMOUNT", "STATUS"].map((h, i) => (
          <span key={h} style={{ position: "absolute", left: COLS[i], width: i === 3 ? 200 : undefined, textAlign: i === 3 ? "right" : undefined }}>{h}</span>
        ))}
      </div>
      {frame < OPTION_CLICK + 14 && ALL.map((r, i) => <TableRow key={`a${i}`} r={r} i={i} at={SWITCH + 6} dim={dimOld} />)}
      {filtered && NEEDS.map((r, i) => <TableRow key={`n${i}`} r={r} i={i} at={OPTION_CLICK + 14} hover={i === 0 ? Math.max(overRow0 * 0.6, rowFlash) : 0} />)}

      {/* filter button */}
      <div style={{
        ...glass, position: "absolute", left: FILTER.x, top: FILTER.y, width: FILTER.w, height: FILTER.h, borderRadius: 16,
        display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 22px", boxSizing: "border-box", fontSize: 24, fontWeight: 600,
        background: `rgba(255,255,255,${0.055 + btnHover * 0.07})`, borderColor: btnHover || open > 0 ? C.cyan : "rgba(255,255,255,0.11)",
        boxShadow: btnHover || open > 0 ? `0 0 24px rgba(34,211,238,0.35)` : glass.boxShadow,
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {filtered && <span style={{ width: 10, height: 10, borderRadius: 5, background: C.violet }} />}
          {filtered ? "Needs you" : "All bills"}
        </span>
        <span style={{ transform: `rotate(${open * 180}deg)`, display: "flex" }}><Icon name="chevron" size={28} color="#fff" /></span>
      </div>

      {/* dropdown: expands downward like an accordion */}
      <div style={{
        position: "absolute", left: MENU.x, top: MENU.y, width: MENU.w, padding: 10, boxSizing: "border-box", borderRadius: 18,
        background: "rgba(22,24,34,0.82)", border: "1px solid rgba(255,255,255,0.14)", backdropFilter: "blur(24px)",
        boxShadow: "0 30px 70px rgba(0,0,0,0.55)", opacity: open, transformOrigin: "top", transform: `scaleY(${0.6 + 0.4 * open}) translateY(${(1 - open) * -14}px)`,
        clipPath: `inset(0 0 ${(1 - open) * 100}% 0 round 18px)`, zIndex: 20,
      }}>
        {OPTIONS.map((o, i) => (
          <div key={o} style={{
            height: OPT_H, display: "flex", alignItems: "center", gap: 14, padding: "0 18px", borderRadius: 12, fontSize: 23,
            background: hoverOpt === i ? "rgba(167,139,250,0.22)" : "transparent", color: hoverOpt === i ? "#fff" : "#cfd2da",
          }}>
            <span style={{ width: 11, height: 11, borderRadius: 6, background: o === "All bills" ? "#fff" : STATUS_COLOR[o] }} />
            {o}
          </div>
        ))}
      </div>
    </>
  );
};

// --- frame -----------------------------------------------------------------------------------------------------------
const NAV: IconName[] = ["home", "chart", "doc", "users", "cart", "gear"];
const NAV_Y = (i: number) => 130 + i * 78;
const BILLS_NAV = abs(SIDE / 2, NAV_Y(2) + 28);
const FILTER_ABS = abs(FILTER.x + FILTER.w / 2, FILTER.y + FILTER.h / 2);
const OPTION_ABS = abs(MENU.x + MENU.w / 2, MENU.y + 10 + OPT_H * 1.5);
const ROW0_ABS = abs(L + 420, TABLE_Y + 56 + ROW_H / 2);

const KEYS: [number, number, number][] = [
  [150, 1840, 1060],
  [SCRUB[0] - 4, scrubX(SCRUB[0]), SCRUB_Y],
  ...SCRUB.map((f) => [f, scrubX(f), SCRUB_Y] as [number, number, number]),
  [NAV_CLICK - 4, BILLS_NAV.x, BILLS_NAV.y],
  [NAV_CLICK + 14, BILLS_NAV.x + 40, BILLS_NAV.y + 30],
  [FILTER_CLICK - 6, FILTER_ABS.x, FILTER_ABS.y],
  [FILTER_CLICK + 18, FILTER_ABS.x - 10, FILTER_ABS.y + 30],
  [OPTION_CLICK - 20, OPTION_ABS.x - 30, OPTION_ABS.y + OPT_H * 2],   // drifts past Held / Cleared
  [OPTION_CLICK - 4, OPTION_ABS.x - 20, OPTION_ABS.y],
  [OPTION_CLICK + 30, OPTION_ABS.x - 200, OPTION_ABS.y + 160],
  [ROW_CLICK - 6, ROW0_ABS.x, ROW0_ABS.y],
  [APP_FRAMES, ROW0_ABS.x, ROW0_ABS.y],
];

export const AppScene: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const win = spring({ frame, fps, config: { damping: 18, stiffness: 90 } });
  const cursor = cursorPath(frame, KEYS);
  const dragging = frame >= SCRUB[0] && frame <= SCRUB[4] ? 0.6 : 0;
  const press = Math.max(dragging, clickPress(frame, [SCRUB[0] - 4, NAV_CLICK, FILTER_CLICK, OPTION_CLICK, ROW_CLICK]));
  const sw = prog(frame, SWITCH, SWITCH + 22, easeInOut);
  const navHover = prog(frame, NAV_CLICK - 14, NAV_CLICK - 4);
  const activeNav = frame >= NAV_CLICK + 2 ? 2 : 0;

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      <div style={{
        ...glass, position: "absolute", left: WIN.x, top: WIN.y, width: WIN.w, height: WIN.h, borderRadius: 30, overflow: "hidden",
        background: "rgba(14,15,22,0.72)", opacity: win, transform: `translateY(${(1 - win) * 90}px) scale(${0.92 + 0.08 * win})`,
      }}>
        {/* sidebar */}
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: SIDE, borderRight: `1px solid ${C.line}`, background: "rgba(255,255,255,0.02)" }}>
          <div style={{ position: "absolute", left: (SIDE - 58) / 2, top: 22 }}><LogoTile size={58} /></div>
          {NAV.map((n, i) => {
            const active = i === activeNav;
            const hover = i === 2 && activeNav !== 2 ? navHover : 0;
            return (
              <div key={n} style={{
                position: "absolute", left: (SIDE - 60) / 2, top: NAV_Y(i), width: 60, height: 60, borderRadius: 16,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: active ? "rgba(34,211,238,0.16)" : `rgba(255,255,255,${hover * 0.1})`,
                boxShadow: active ? `0 0 20px rgba(34,211,238,0.35), inset 0 0 0 1px ${C.cyan}` : hover ? `inset 0 0 0 1px rgba(34,211,238,${hover})` : undefined,
                opacity: prog(frame, 10 + i * 4, 24 + i * 4),
              }}>
                <Icon name={n} size={32} color={active ? C.cyan : "#9aa0ad"} width={2.8} />
              </div>
            );
          })}
        </div>
        {/* header: search + you */}
        <div style={{ position: "absolute", left: SIDE, right: 0, top: 0, height: HEAD, borderBottom: `1px solid ${C.line}`, display: "flex", alignItems: "center", padding: "0 40px", gap: 20 }}>
          <div style={{ flex: 1, maxWidth: 620, height: 50, borderRadius: 25, background: "rgba(255,255,255,0.05)", border: `1px solid ${C.line}`,
            display: "flex", alignItems: "center", gap: 14, padding: "0 20px", color: C.muted, fontSize: 21 }}>
            <Icon name="search" size={26} color={C.muted} /> Search bills, vendors, cases
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ width: 50, height: 50, borderRadius: 25, background: `linear-gradient(135deg, ${C.violet}, ${C.cyan})`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Icon name="user" size={30} color="#fff" />
          </div>
        </div>

        {/* view A: Home, slides out left */}
        <div style={{ position: "absolute", inset: 0, opacity: 1 - sw, transform: `translateX(${-sw * 120}px)` }}>
          {frame < SWITCH + 24 && <>{KPIS.map((_, i) => <Kpi key={i} i={i} />)}<Chart /></>}
        </div>
        {/* view B: Bills, slides in from the right */}
        <div style={{ position: "absolute", inset: 0, opacity: sw, transform: `translateX(${(1 - sw) * 120}px)` }}>
          {frame >= SWITCH && <Bills cursor={cursor} />}
        </div>
      </div>

      <Cursor x={cursor.x} y={cursor.y} press={press} opacity={interpolate(frame, [150, 160], [0, 1], clamp)} />
      <Sequence durationInFrames={SWITCH}><Caption text="Every catch, live." duration={SWITCH} start={20} /></Sequence>
      <Sequence from={SWITCH}><Caption text="What needs you, one click away." duration={APP_FRAMES - SWITCH} start={14} /></Sequence>
    </AbsoluteFill>
  );
};
