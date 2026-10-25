import type { CSSProperties, FC, ReactNode } from "react";
import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Cursor, Icon, type IconName, LogoTile, Mark } from "../components";
import { C, clamp, clickPress, cursorPath, easeInOut, glass, prog, ui } from "../theme";
import { BILL_AT, BillTile } from "./OldWay";
import { AppTag, Av, BotAv, Chip, SL } from "./slackParts";

// Scenes 3-10: AP that starts at the first quote. One continuous component so the Slack channel and the Expected card
// stay put across beats (no crossfade flicker).
//   3 rewind to the first quote      4 the whisper          5 signed and vetted (Price, Bank, PO fill)
//   6 a claim isn't a receipt         7 the bill arrives     8 paid, by a person, from a DM
//   9 one Expected card per supplier 10 the wrong account: Penang, then the real app's bill page
// The Slack window mirrors the product's real messages (backend/slack/*), trimmed to a few words, in Slack's light
// theme. Kestrel is case_01: PO-7001, 50 x HBM3E-12H-24G at the MSA price $1,450 = KM-INV-30118, $72,500, terms
// 2/15 net 30, so releasing in time pays $71,050 (the app shows "Early-payment discount captured: $1,450").
// Whisper numbers are the product's coach math for that SKU (market.py analyze): counter $1,180 (p25), aim $1,300
// (median), walk away above $1,460 (p75); a $1,520 opening quote (illustrative) saves $11,000 at the aim.
// Penang is case_04: PPT-6620, $3.3M, PO-6100, 2,000 x $1,650, bank ••9902 vs ••4418 on file, from penang-packtest.com.
export const S = { s3: 0, s4: 90, s5: 255, s6: 390, s7: 495, s8: 630, s9: 765, s10: 855 };
export const STORY_FRAMES = 1065;

// --- layout ------------------------------------------------------------------------------------------------------------
const WIN = { x: 70, y: 56, w: 1270, h: 790 };
const TITLE = 40;
const SIDE = 230;
const HEAD = 64;
const AV_X = SIDE + 26;
const BODY_X = SIDE + 90;

const EXP = { x: 1390, y: 150, w: 450, head: 96, rowH: 92 };
const ROWS = ["Price", "PO", "Bank", "Received"];
const rowY = (i: number) => EXP.y + EXP.head + i * EXP.rowH + EXP.rowH / 2;
const valueAt = (i: number) => ({ x: EXP.x + EXP.w - 130, y: rowY(i) });
const BILL = { x: 860, y: 150, w: 420 };

// --- the thread ----------------------------------------------------------------------------------------------------------
const ITEMS = [
  { key: "quote", at: S.s4 + 32, h: 92 },
  { key: "whisper", at: S.s4 + 62, h: 262 },
  { key: "agreed", at: S.s5 + 6, h: 84 },
  { key: "contract", at: S.s5 + 22, h: 150 },
  { key: "onboard", at: S.s5 + 70, h: 156 },
  { key: "po", at: S.s5 + 104, h: 84 },
  { key: "shipped", at: S.s6 + 8, h: 92 },
  { key: "receipt", at: S.s6 + 52, h: 84 },
  { key: "invoice", at: S.s7 + 6, h: 120 },
] as const;
type Key = (typeof ITEMS)[number]["key"];
const idx = (k: Key) => ITEMS.findIndex((it) => it.key === k);
const GAP = 12;
const PAD = 16;
const grow = (i: number, f: number) => prog(f, ITEMS[i].at, ITEMS[i].at + 14, easeInOut);
const topOf = (i: number, f: number) => PAD + ITEMS.slice(0, i).reduce((y, it, j) => y + (it.h + GAP) * grow(j, f), 0);
const scrollAt = (f: number) => Math.max(0, topOf(ITEMS.length, f) + PAD - (WIN.h - TITLE - HEAD));
const absAt = (k: Key, f: number, x: number, y: number) => ({ x: WIN.x + x, y: WIN.y + TITLE + HEAD + topOf(idx(k), f) - scrollAt(f) + y });

// --- timeline: values flying into the Expected card ------------------------------------------------------------------
const ACCEPT_CLICK = S.s5 + 50;
const ACCEPT_ABS = absAt("contract", ACCEPT_CLICK, BODY_X + 150, 30 + 56 + 23);   // the Accept button, on screen
const FLY = 24;
// [row, value, start frame, source point (message-local)]
const FLIGHTS: { row: number; value: string; at: number; from: [Key, number, number] }[] = [
  { row: 0, value: "$1,450", at: ACCEPT_CLICK + 6, from: ["contract", BODY_X + 534, 50] },
  { row: 2, value: "••••", at: S.s5 + 102, from: ["onboard", BODY_X + 237, 105] },
  { row: 1, value: "PO-7001", at: S.s5 + 114, from: ["po", BODY_X + 110, 45] },
  { row: 3, value: "50", at: S.s6 + 62, from: ["receipt", BODY_X + 317, 50] },
];
const filledAt = (row: number) => FLIGHTS.find((f) => f.row === row)!.at + FLY;
const KESTREL_VALUES = ["$1,450", "PO-7001", "••••", "50"];
const PENANG_VALUES = ["$1,650", "PO-6100", "••4418", "2,000"];

// --- small pieces -----------------------------------------------------------------------------------------------------
const KAv: FC<{ size?: number; dim?: number }> = ({ size, dim }) => <Av bg="#5b6cff" size={size} dim={dim}>K</Av>;
const HAv: FC<{ size?: number }> = ({ size }) => <Av bg={C.teal} size={size}>H</Av>;
const AAv = () => <Av bg="#1f9d74">AL</Av>;


const Msg: FC<{ k: Key; avatar: ReactNode; name: ReactNode; time: string; eph?: boolean; children: ReactNode }> = ({ k, avatar, name, time, eph, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const i = idx(k);
  const s = spring({ frame: frame - ITEMS[i].at, fps, config: { damping: 15, stiffness: 120 } });
  if (frame < ITEMS[i].at) return null;
  return (
    <div style={{ position: "absolute", left: SIDE, right: 0, top: topOf(i, frame), height: ITEMS[i].h, background: eph ? SL.eph : undefined,
      opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 30}px)` }}>
      {eph && <div style={{ position: "absolute", left: 90, top: 6, fontSize: 16, color: SL.muted, display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="eyeOff" size={18} color={SL.muted} width={3} /> Only visible to you</div>}
      <div style={{ position: "absolute", left: 26, top: eph ? 32 : 8 }}>{avatar}</div>
      <div style={{ position: "absolute", left: 90, top: eph ? 30 : 6, right: 24 }}>
        <div style={{ fontSize: 21, fontWeight: 800, color: SL.text, height: 28 }}>{name}<span style={{ fontSize: 15, fontWeight: 400, color: SL.muted, marginLeft: 10 }}>{time}</span></div>
        <div style={{ fontSize: 22, color: SL.text, marginTop: 2 }}>{children}</div>
      </div>
    </div>
  );
};

// --- message bodies ------------------------------------------------------------------------------------------------------
const Typing: FC = () => {
  const frame = useCurrentFrame();
  return <div style={{ display: "flex", gap: 8, paddingTop: 10 }}>{[0, 1, 2].map((i) => (
    <div key={i} style={{ width: 12, height: 12, borderRadius: 6, background: "#999", transform: `translateY(${Math.sin(frame * 0.35 - i * 0.9) * -5}px)` }} />))}</div>;
};
const QUOTE_AT = S.s4 + 32;
const Quote: FC = () => {
  const frame = useCurrentFrame();
  if (frame < QUOTE_AT + 18) return <Typing />;
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}><Icon name="tag" size={30} color={SL.text} />We can do <b>$1,520</b> per stack for 50.</span>;
};

const G = { w: 700, lo: 1150, hi: 1560 };
const gx = (v: number) => ((v - G.lo) / (G.hi - G.lo)) * G.w;
const W0 = ITEMS[idx("whisper")].at;
const PINS = [
  { v: 1520, label: "their quote", color: C.red, at: W0 + 16 },
  { v: 1460, label: "walk away", color: "#d97706", at: W0 + 28 },
  { v: 1300, label: "aim", color: SL.green, at: W0 + 40 },
  { v: 1180, label: "counter", color: "#0891b2", at: W0 + 52 },
];
const SAVE_AT = W0 + 64;
const Whisper: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zone = prog(frame, PINS[1].at, PINS[1].at + 24);
  const save = interpolate(frame, [SAVE_AT, SAVE_AT + 30], [0, 11000], { ...clamp, easing: easeInOut });
  return (
    <div>
      <b>Negotiation notes</b> <span style={{ color: SL.muted }}>· HBM3E stacks</span>
      <div style={{ display: "flex", alignItems: "center", gap: 28, marginTop: 8 }}>
        <div style={{ position: "relative", width: G.w, height: 118 }}>
          <div style={{ position: "absolute", top: 53, left: 0, width: G.w, height: 10, borderRadius: 5, background: "#e2e2e2" }} />
          <div style={{ position: "absolute", top: 53, left: 0, width: gx(1460) * zone, height: 10, borderRadius: 5, background: "#2bac76" }} />
          {PINS.map((p) => {
            const s = spring({ frame: frame - p.at, fps, config: { damping: 10, stiffness: 150 } });
            return (
              <div key={p.v} style={{ position: "absolute", left: gx(p.v), top: 0, transform: `translateX(-50%) translateY(${(1 - s) * -34}px)`,
                opacity: Math.min(1, s * 2), display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ fontSize: 25, fontWeight: 800 }}>${p.v.toLocaleString("en-US")}</div>
                <div style={{ width: 22, height: 22, borderRadius: 11, background: p.color, border: "4px solid #fff", marginTop: 12, boxShadow: "0 1px 4px rgba(0,0,0,0.35)" }} />
                <div style={{ fontSize: 17, color: SL.muted, marginTop: 6, whiteSpace: "nowrap" }}>{p.label}</div>
              </div>
            );
          })}
        </div>
        <div style={{ padding: "12px 22px", borderRadius: 14, background: "#e8f5ee", color: SL.green, textAlign: "center", border: "2px solid #2bac76",
          opacity: prog(frame, SAVE_AT, SAVE_AT + 10), transform: `scale(${0.7 + 0.3 * spring({ frame: frame - SAVE_AT, fps, config: { damping: 9, stiffness: 160 } })})` }}>
          <div style={{ fontSize: 34, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>+${Math.round(save).toLocaleString("en-US")}</div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>at the aim</div>
        </div>
      </div>
    </div>
  );
};

const Contract: FC = () => {
  const frame = useCurrentFrame();
  const hover = prog(frame, ACCEPT_CLICK - 12, ACCEPT_CLICK - 4);
  const press = clickPress(frame, [ACCEPT_CLICK]);
  const done = frame >= ACCEPT_CLICK + 4;
  return (
    <div>
      <div style={{ display: "flex", gap: 12 }}>
        <Chip w={260}><span style={{ width: 26, height: 30, borderRadius: 4, background: "#e01e5a", color: "#fff", fontSize: 10, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>PDF</span>Supply Agreement</Chip>
        <Chip w={160}>HBM3E × 50</Chip>
        <Chip w={180} bg="#e8f5ee" color={SL.green}>$1,450 / stack</Chip>
        <Chip w={170}>2/15 net 30</Chip>
      </div>
      <div style={{ marginTop: 16, width: 300, height: 46, borderRadius: 8, background: SL.green, color: "#fff", fontSize: 20, fontWeight: 800,
        display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${1 + 0.04 * hover * (done ? 0 : 1) - 0.07 * press})`,
        boxShadow: `0 0 ${18 * hover}px rgba(0,122,90,0.55)` }}>{done ? "✓ Accepted" : "Accept & start onboarding"}</div>
    </div>
  );
};

const CHECKS: { icon: IconName; label: string }[] = [
  { icon: "shield", label: "Sanctions" }, { icon: "bank", label: "Bank" }, { icon: "globe", label: "Domain" }, { icon: "doc", label: "Tax form" },
];
const Onboard: FC = () => {
  const frame = useCurrentFrame();
  const t0 = ITEMS[idx("onboard")].at;
  return (
    <div>
      <span>✅ <b>Kestrel Memory</b> is onboarded · 90-day probation</span>
      <div style={{ display: "flex", gap: 12, marginTop: 10 }}>
        {CHECKS.map((c, i) => {
          const t = t0 + 8 + i * 6;
          return (
            <div key={c.label} style={{ width: 150, height: 70, borderRadius: 10, border: "1px solid #ddd", background: "#fafafa", display: "flex", alignItems: "center",
              gap: 10, padding: "0 12px", boxSizing: "border-box", opacity: prog(frame, t - 4, t + 4) }}>
              <Icon name={c.icon} size={30} color={SL.text} width={2.8} />
              <span style={{ fontSize: 17, flex: 1 }}>{c.label}</span>
              <Mark ok p={prog(frame, t + 2, t + 12)} size={26} color={SL.green} />
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Shipped: FC = () => {
  const frame = useCurrentFrame();
  const t = ITEMS[idx("shipped")].at;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
      🚚 Kestrel says <b>PO-7001 shipped · 50</b>
      <Chip bg="#fff4e0" color="#b45309" style={{ opacity: prog(frame, t + 12, t + 22) }}>claim, not a receipt</Chip>
    </span>
  );
};

const Receipt: FC = () => (
  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
    <Chip w={230}>✅ GRN-PO-7001-1</Chip>
    <Chip w={150} bg="#e8f5ee" color={SL.green}>50 received</Chip>
    <span style={{ color: SL.muted, fontSize: 20 }}>counted by Ana Lee, Helix</span>
  </div>
);

const INV_AT = ITEMS[idx("invoice")].at;
const Invoice: FC = () => {
  const frame = useCurrentFrame();
  const reading = frame >= INV_AT + 10 && frame < INV_AT + 46;
  const scan = prog(frame, INV_AT + 12, INV_AT + 42, easeInOut);
  return (
    <div style={{ position: "relative", width: 420, height: 70, borderRadius: 10, border: `2px solid ${reading ? "#06b6d4" : "#ddd"}`, overflow: "hidden",
      display: "flex", alignItems: "center", gap: 14, padding: "0 16px", boxSizing: "border-box", background: "#fff",
      boxShadow: reading ? `0 0 ${18 + 10 * Math.sin(frame * 0.5)}px rgba(6,182,212,0.6)` : undefined }}>
      <span style={{ width: 36, height: 44, borderRadius: 6, background: "#e01e5a", color: "#fff", fontSize: 12, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>PDF</span>
      <b>KM-INV-30118.pdf</b>
      {reading && <div style={{ position: "absolute", left: 0, right: 0, top: scan * 70 - 3, height: 6, background: "#06b6d4", boxShadow: "0 0 14px #06b6d4" }} />}
    </div>
  );
};

const BODIES: Record<Key, { avatar: ReactNode; name: ReactNode; time: string; eph?: boolean; body: ReactNode }> = {
  quote: { avatar: <KAv />, name: "Kestrel Memory", time: "10:02", body: <Quote /> },
  whisper: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "10:02", eph: true, body: <Whisper /> },
  agreed: { avatar: <AAv />, name: "Ana Lee", time: "10:09", body: <>Agreed: 50 at <b>$1,450</b>, 2/15 net 30.</> },
  contract: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "10:10", body: <Contract /> },
  onboard: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "10:12", body: <Onboard /> },
  po: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "10:12", body: <>📦 <b>PO-7001</b> created in Helix ERP from the contract.</> },
  shipped: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "Oct 10", body: <Shipped /> },
  receipt: { avatar: <BotAv />, name: <>ReconAI<AppTag /></>, time: "Oct 11", body: <Receipt /> },
  invoice: { avatar: <KAv />, name: "Kestrel Memory", time: "Oct 12", body: <Invoice /> },
};

// --- the Slack window ----------------------------------------------------------------------------------------------------
const SlackWindow: FC<{ kDim: number }> = ({ kDim }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", inset: 0, borderRadius: 18, overflow: "hidden", background: "#fff", fontFamily: ui }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: TITLE, background: SL.top, display: "flex", alignItems: "center", gap: 8, paddingLeft: 16 }}>
        {["#ff5f57", "#febc2e", "#28c840"].map((d) => <div key={d} style={{ width: 12, height: 12, borderRadius: 6, background: d }} />)}
        <div style={{ marginLeft: 260, width: 520, height: 26, borderRadius: 6, background: "rgba(255,255,255,0.18)" }} />
      </div>
      <div style={{ position: "absolute", left: 0, top: TITLE, bottom: 0, width: SIDE, background: SL.side, padding: "18px 14px", boxSizing: "border-box", color: SL.sideText }}>
        <div style={{ color: "#fff", fontWeight: 800, fontSize: 23, padding: "0 8px 18px" }}>Helix Silicon</div>
        {[0.7, 0.55].map((w, i) => <div key={i} style={{ height: 12, width: `${w * 100}%`, borderRadius: 6, background: "rgba(255,255,255,0.16)", margin: "12px 8px" }} />)}
        <div style={{ marginTop: 14, padding: "8px 10px", borderRadius: 8, background: SL.active, color: SL.side, fontWeight: 800, fontSize: 19, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="lock" size={18} color={SL.side} width={3.4} /> helix-kestrel
        </div>
        {[0.6, 0.45, 0.65].map((w, i) => <div key={i} style={{ height: 12, width: `${w * 100}%`, borderRadius: 6, background: "rgba(255,255,255,0.16)", margin: "18px 8px" }} />)}
      </div>
      <div style={{ position: "absolute", left: SIDE, right: 0, top: TITLE, height: HEAD, borderBottom: `1px solid ${SL.line}`, display: "flex", alignItems: "center", gap: 10,
        padding: "0 26px", background: "#fff", zIndex: 2 }}>
        <Icon name="lock" size={22} color={SL.text} width={3} />
        <span style={{ fontSize: 25, fontWeight: 800, color: SL.text }}>helix-kestrel</span>
        <div style={{ flex: 1 }} />
        <HAv size={40} />
        <div style={{ position: "relative" }}>
          <KAv size={40} dim={kDim} />
          <div style={{ position: "absolute", right: -9, bottom: -9, width: 26, height: 26, borderRadius: 13, background: "#fff", display: "flex", alignItems: "center",
            justifyContent: "center", opacity: kDim, boxShadow: "0 1px 4px rgba(0,0,0,0.3)" }}><Icon name="eyeOff" size={18} color="#7c3aed" width={3.4} /></div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: TITLE + HEAD, bottom: 0, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 3000, transform: `translateY(${-scrollAt(frame)}px)` }}>
          {ITEMS.map((it) => <Msg key={it.key} k={it.key} {...BODIES[it.key]}>{BODIES[it.key].body}</Msg>)}
        </div>
      </div>
    </div>
  );
};

// --- the Expected card (key visual) --------------------------------------------------------------------------------------
type CardProps = { vendor: string; initials: string; color: string; values: string[]; filled: number[]; title?: string;
  bad?: number[]; glow?: number; marks?: boolean };
export const ExpectedCard: FC<CardProps> = ({ vendor, initials, color, values, filled, title = "Expected", bad = [], glow = 0, marks = true }) => (
  <div style={{ ...glass, width: EXP.w, height: EXP.head + 4 * EXP.rowH + 24, borderRadius: 26, background: "rgba(16,18,26,0.82)", boxSizing: "border-box",
    fontFamily: ui, color: C.text, boxShadow: `0 30px 80px rgba(0,0,0,0.5), 0 0 ${60 * glow}px rgba(62,224,143,${0.55 * glow})`,
    borderColor: glow ? `rgba(62,224,143,${0.3 + 0.6 * glow})` : undefined }}>
    <div style={{ height: EXP.head, display: "flex", alignItems: "center", gap: 14, padding: "0 28px", borderBottom: `1px solid ${C.line}` }}>
      <Av bg={color} size={46}>{initials}</Av>
      <div>
        <div style={{ fontSize: 27, fontWeight: 800 }}>{title}</div>
        <div style={{ fontSize: 17, color: C.muted }}>{vendor}</div>
      </div>
    </div>
    {ROWS.map((r, i) => {
      const f = filled[i];
      const isBad = bad.includes(i);
      return (
        <div key={r} style={{ height: EXP.rowH, display: "flex", alignItems: "center", padding: "0 28px", borderBottom: i < 3 ? `1px solid ${C.line}` : undefined }}>
          <span style={{ fontSize: 22, color: C.muted, width: 130 }}>{r}</span>
          <div style={{ flex: 1, height: 44, borderRadius: 12, border: `2px dashed rgba(255,255,255,${0.18 * (1 - f)})`, display: "flex", alignItems: "center",
            justifyContent: "flex-end", padding: "0 14px", gap: 12, background: `rgba(255,255,255,${0.04 * f})` }}>
            <span style={{ fontSize: 26, fontWeight: 800, opacity: f, color: isBad ? C.red : C.text, fontVariantNumeric: "tabular-nums" }}>{values[i]}</span>
            {marks && <div style={{ opacity: f > 0 ? 1 : 0 }}><Mark ok={!isBad} p={f} size={32} /></div>}
          </div>
        </div>
      );
    })}
  </div>
);

// a value flying from a chat message into its row, on an arc
const Flight: FC<{ value: string; from: { x: number; y: number }; to: { x: number; y: number }; t: number }> = ({ value, from, to, t }) => {
  if (t <= 0 || t >= 1) return null;
  const x = from.x + (to.x - from.x) * t;
  const y = from.y + (to.y - from.y) * t - Math.sin(t * Math.PI) * 140;
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${1 + Math.sin(t * Math.PI) * 0.25})`, padding: "8px 16px", borderRadius: 12,
      background: C.cyan, color: "#04212a", fontFamily: ui, fontWeight: 800, fontSize: 24, boxShadow: `0 0 26px ${C.cyan}`, zIndex: 40, whiteSpace: "nowrap" }}>{value}</div>
  );
};

// the parsed bill, docked beside the Expected card; lines tie matching rows
const BillCard: FC<{ title: string; amount: string; values: string[]; shown: number[]; bad?: number[]; red?: number }> = ({ title, amount, values, shown, bad = [], red = 0 }) => (
  <div style={{ ...glass, width: BILL.w, height: EXP.head + 4 * EXP.rowH + 24, borderRadius: 26, background: "rgba(16,18,26,0.85)", boxSizing: "border-box",
    fontFamily: ui, color: C.text, boxShadow: `0 0 0 ${6 * red}px ${C.red}, 0 0 ${80 * red}px rgba(255,84,112,0.55), 0 30px 80px rgba(0,0,0,0.5)` }}>
    <div style={{ height: EXP.head, display: "flex", alignItems: "center", gap: 14, padding: "0 26px", borderBottom: `1px solid ${C.line}` }}>
      <Icon name="doc" size={40} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 25, fontWeight: 800 }}>Bill</div>
        <div style={{ fontSize: 17, color: C.muted }}>{title}</div>
      </div>
      <span style={{ fontSize: 30, fontWeight: 800 }}>{amount}</span>
    </div>
    {ROWS.map((r, i) => (
      <div key={r} style={{ height: EXP.rowH, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", borderBottom: i < 3 ? `1px solid ${C.line}` : undefined }}>
        <span style={{ fontSize: 22, color: C.muted }}>{r === "Received" ? "Qty" : r}</span>
        <span style={{ fontSize: 26, fontWeight: 800, opacity: shown[i], color: bad.includes(i) ? C.red : C.text, fontVariantNumeric: "tabular-nums" }}>{values[i]}</span>
      </div>
    ))}
  </div>
);

// lines between the bill's rows and the Expected card's rows; `snap` breaks a row's line in red
const MatchLines: FC<{ draw: number[]; okAt: number[]; badRow?: number; snap?: number }> = ({ draw, okAt, badRow = -1, snap = 0 }) => {
  const frame = useCurrentFrame();
  const x1 = BILL.x + BILL.w, x2 = EXP.x, mid = (x1 + x2) / 2;
  return (
    <>
      <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0, zIndex: 30, overflow: "visible" }}>
        {ROWS.map((_, i) => {
          const y = rowY(i), d = draw[i], isBad = i === badRow;
          if (isBad && snap > 0) {
            const gap = 26 * snap;
            return (
              <g key={i} stroke={C.red} strokeWidth={4} strokeLinecap="round">
                <line x1={x1} y1={y} x2={mid - gap} y2={y + 10 * snap} />
                <line x1={mid + gap} y1={y - 10 * snap} x2={x2} y2={y} />
              </g>
            );
          }
          return <line key={i} x1={x1} y1={y} x2={x1 + (x2 - x1) * d} y2={y} stroke={isBad ? C.red : C.green} strokeWidth={4} strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${isBad ? C.red : C.green})` }} />;
        })}
      </svg>
      {ROWS.map((_, i) => okAt[i] >= 0 && frame >= okAt[i] && (
        <div key={i} style={{ position: "absolute", left: mid - 20, top: rowY(i) - 20, zIndex: 31, background: C.bg, borderRadius: 20 }}>
          <Mark ok={i !== badRow} p={prog(frame, okAt[i], okAt[i] + 10)} size={40} />
        </div>
      ))}
    </>
  );
};

// --- scene 8: the approver DM --------------------------------------------------------------------------------------------
const DM = { x: 330, y: 200, w: 980, h: 470 };
const DM_IN = S.s8 + 6;
const APPROVE_CLICK = S.s8 + 82;
const BTN = { x: 150, y: 300, w: 420, h: 54 };   // DM-relative
const BTN_ABS = { x: DM.x + BTN.x + BTN.w / 2, y: DM.y + BTN.y + BTN.h / 2 };
const TOAST = { right: 70, top: 28 };

const DmWindow: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - DM_IN, fps, config: { damping: 15, stiffness: 110 } });
  const away = prog(frame, S.s9, S.s9 + 16, easeInOut);
  const hover = prog(frame, APPROVE_CLICK - 14, APPROVE_CLICK - 5);
  const press = clickPress(frame, [APPROVE_CLICK]);
  const done = frame >= APPROVE_CLICK + 4;
  const arrow = prog(frame, DM_IN + 30, DM_IN + 46);
  if (frame < DM_IN || away >= 1) return null;
  return (
    <div style={{ position: "absolute", left: DM.x, top: DM.y, width: DM.w, height: DM.h, borderRadius: 18, overflow: "hidden", background: "#fff", fontFamily: ui, color: SL.text,
      boxShadow: "0 50px 140px rgba(0,0,0,0.75), 0 0 0 1px rgba(0,0,0,0.1)", opacity: Math.min(1, s * 1.5) * (1 - away),
      transform: `translateY(${(1 - s) * 140 + away * 260}px) scale(${0.92 + 0.08 * s})`, zIndex: 20 }}>
      <div style={{ height: 70, borderBottom: `1px solid ${SL.line}`, display: "flex", alignItems: "center", gap: 14, padding: "0 26px" }}>
        <Icon name="lock" size={24} color="#7c3aed" width={3} />
        <BotAv />
        <span style={{ fontSize: 24, fontWeight: 800 }}>ReconAI</span><AppTag />
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 19, color: SL.muted }}>to</span>
        <Av bg="#7c3aed" size={40}>MC</Av>
        <span style={{ fontSize: 21, fontWeight: 700 }}>M. Chen</span>
        <span style={{ fontSize: 17, color: SL.muted }}>Controller</span>
      </div>
      <div style={{ position: "absolute", left: 40, top: 100, display: "flex", alignItems: "center", gap: 20 }}>
        <Icon name="doc" size={70} color={SL.text} width={2.4} />
        <div>
          <div style={{ fontSize: 46, fontWeight: 800, letterSpacing: -1 }}>$72,500 <span style={{ fontSize: 22, color: SL.muted, fontWeight: 600 }}>KM-INV-30118</span></div>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            {ROWS.map((r, i) => (
              <span key={r} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 16, background: "#e8f5ee", color: SL.green, fontSize: 18, fontWeight: 700,
                opacity: prog(frame, DM_IN + 14 + i * 5, DM_IN + 22 + i * 5) }}>✓ {r}</span>
            ))}
          </div>
        </div>
      </div>
      {/* the agent prepared it; a person releases it */}
      <div style={{ position: "absolute", left: 640, top: 210, display: "flex", alignItems: "center", gap: 12 }}>
        <Av bg="#e6f7fb" size={54}><Icon name="bot" size={38} color="#0891b2" /></Av>
        <div style={{ width: 90, overflow: "hidden", opacity: arrow }}><div style={{ transform: `translateX(${(arrow - 1) * 70}px)` }}><Icon name="arrow" size={60} color="#999" width={3} /></div></div>
        <Av bg={done ? SL.green : "#f0e9fb"} size={54}><Icon name="user" size={38} color={done ? "#fff" : "#7c3aed"} /></Av>
      </div>
      <div style={{ position: "absolute", left: BTN.x, top: BTN.y, display: "flex", gap: 12 }}>
        <div style={{ width: BTN.w, height: BTN.h, borderRadius: 8, background: SL.green, color: "#fff", fontSize: 21, fontWeight: 800, display: "flex", alignItems: "center",
          justifyContent: "center", transform: `scale(${1 + 0.04 * hover * (done ? 0 : 1) - 0.07 * press})`, boxShadow: `0 0 ${20 * hover}px rgba(0,122,90,0.6)` }}>
          {done ? "✓ Approved · released" : "Approve & release via Coinbase"}</div>
        <div style={{ width: 100, height: BTN.h, borderRadius: 8, border: "1px solid #bbb", fontSize: 21, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", opacity: done ? 0.35 : 1 }}>Hold</div>
      </div>
    </div>
  );
};

const Payout: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const coinT = interpolate(frame, [APPROVE_CLICK + 8, APPROVE_CLICK + 38], [0, 1], { ...clamp, easing: easeInOut });
  const toastAt = { x: 1920 - TOAST.right - 420, y: TOAST.top + 50 };
  const toast = spring({ frame: frame - (APPROVE_CLICK + 34), fps, config: { damping: 11, stiffness: 120 } });
  const away = prog(frame, S.s9 + 20, S.s9 + 36);
  return (
    <>
      {coinT > 0 && coinT < 1 && [0.12, 0.06, 0].map((lag, j) => {
        const t = Math.max(0, coinT - lag);
        const x = BTN_ABS.x + (toastAt.x - BTN_ABS.x) * t, y = BTN_ABS.y + (toastAt.y - BTN_ABS.y) * t - Math.sin(t * Math.PI) * 200;
        return <div key={j} style={{ position: "absolute", left: x - 32, top: y - 32, width: 64, height: 64, borderRadius: 32, background: "#2775ca", border: "5px solid #fff",
          color: "#fff", fontFamily: ui, fontWeight: 800, fontSize: 34, display: "flex", alignItems: "center", justifyContent: "center", opacity: j === 2 ? 1 : 0.25 + j * 0.15,
          transform: `scale(${(1 + Math.sin(t * Math.PI) * 0.4) * (j === 2 ? 1 : 0.8)})`, boxShadow: "0 0 30px rgba(39,117,202,0.7)", zIndex: 45 }}>$</div>;
      })}
      <div style={{ ...glass, position: "absolute", right: TOAST.right, top: TOAST.top, display: "flex", alignItems: "center", gap: 18, padding: "18px 30px", zIndex: 44,
        background: "rgba(24,27,36,0.92)", borderRadius: 22, borderColor: "rgba(62,224,143,0.5)", fontFamily: ui, color: C.text,
        transform: `translate(${(1 - toast) * 300}px, ${(1 - toast) * -100}px)`, opacity: frame < APPROVE_CLICK + 34 ? 0 : Math.min(1, toast * 1.5) * (1 - away) }}>
        <Mark ok p={prog(frame, APPROVE_CLICK + 42, APPROVE_CLICK + 56)} size={58} />
        <div>
          <div style={{ fontSize: 32, fontWeight: 800 }}>Paid · USDC</div>
          <div style={{ fontSize: 19, color: C.muted }}>$71,050 · 2% early-pay kept · testnet</div>
        </div>
      </div>
    </>
  );
};

// --- scene 9: one card per supplier --------------------------------------------------------------------------------------
const FAN = [
  { vendor: "Formosa Wafer Works", initials: "FW", color: "#22b8cf", x: 520, y: 470, rot: -8 },
  { vendor: "Kestrel Memory", initials: "KM", color: "#5b6cff", x: 800, y: 450, rot: -3 },
  { vendor: "Penang Pack & Test", initials: "PP", color: "#e0559b", x: 1100, y: 450, rot: 3 },
  { vendor: "Aerolane Freight", initials: "AF", color: "#f08c00", x: 1380, y: 470, rot: 8 },
];
const FAN_SCALE = 0.62;
const EXP_CENTER = { x: EXP.x + EXP.w / 2, y: EXP.y + (EXP.head + 4 * EXP.rowH + 24) / 2 };

// --- scene 10: Penang, then the real app ---------------------------------------------------------------------------------
const P = S.s10;
const EMAIL = { x: 110, y: 170, w: 640 };
const P_LINES = [P + 52, P + 60, P + 80, P + 68];   // draw frames per row (bank last)
const P_OK = [P + 58, P + 66, -1, P + 74];
const P_SNAP = P + 96;
const P_HOLD = P + 104;
const APP_CUT = P + 126;
// the captured bill page (video/public/ui/penang-bill.png, 1920x1080 CSS px at 2x): where to look, in page px
const PAGE = { full: { x: 960, y: 540, z: 0.8 }, fraud: { x: 724, y: 300, z: 1.75 }, pay: { x: 930, y: 700, z: 1.9 } };
const HIGHLIGHTS = [
  { x: 292, y: 247, w: 866, h: 76, at: APP_CUT + 46 },   // ✗ Bank account matches the vendor master (••9902 vs ••4418)
  { x: 708, y: 693, w: 444, h: 70, at: APP_CUT + 68 },   // To (vendor master) ••4418
];

const AppCut: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - APP_CUT, fps, config: { damping: 16, stiffness: 100 } });
  const a = prog(frame, APP_CUT + 22, APP_CUT + 44, easeInOut);
  const b = prog(frame, APP_CUT + 58, APP_CUT + 76, easeInOut);
  const lerp = (k: "x" | "y" | "z") => PAGE.full[k] + (PAGE.fraud[k] - PAGE.full[k]) * a + (PAGE.pay[k] - PAGE.fraud[k]) * b;
  const fx = lerp("x"), fy = lerp("y"), z = lerp("z") * (0.9 + 0.1 * s);
  const cx = 960, cy = 470;
  if (frame < APP_CUT) return null;
  return (
    <AbsoluteFill style={{ opacity: Math.min(1, s * 1.4), overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, transformOrigin: "0 0",
        transform: `translate(${cx - fx * z}px, ${cy - fy * z}px) scale(${z})` }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 16, overflow: "hidden", boxShadow: "0 40px 120px rgba(0,0,0,0.6)" }}>
          <Img src={staticFile("ui/penang-bill.png")} style={{ width: 1920, height: 1080 }} />
        </div>
        {HIGHLIGHTS.map((h, i) => {
          const p = prog(frame, h.at, h.at + 10);
          return <div key={i} style={{ position: "absolute", left: h.x, top: h.y, width: h.w, height: h.h, borderRadius: 10, border: `3px solid ${C.red}`,
            boxShadow: `0 0 ${24 * p}px rgba(255,84,112,0.7)`, opacity: p, transform: `scale(${1.06 - 0.06 * p})` }} />;
        })}
      </div>
    </AbsoluteFill>
  );
};

// --- the story -----------------------------------------------------------------------------------------------------------
export const Story: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // scene 3: the bill rewinds out, the channel and the empty card arrive
  const rewind = prog(frame, 0, 26, easeInOut);
  const win = spring({ frame: frame - 30, fps, config: { damping: 16, stiffness: 100 } });
  const dock = spring({ frame: frame - 52, fps, config: { damping: 15, stiffness: 100 } });
  // scene 8 backdrop; scene 9 the channel leaves
  const backdrop = prog(frame, S.s8, S.s8 + 16) * (1 - prog(frame, S.s9, S.s9 + 10));
  const leave = prog(frame, S.s9, S.s9 + 24, easeInOut);
  const kDim = prog(frame, ITEMS[idx("whisper")].at, ITEMS[idx("whisper")].at + 14) * (1 - prog(frame, S.s5, S.s5 + 14));

  // Expected card (Kestrel): rows fill as values land; glows when complete
  const filled = ROWS.map((_, i) => prog(frame, filledAt(i), filledAt(i) + 8));
  const cardGlow = interpolate(frame, [filledAt(3) + 4, filledAt(3) + 14, filledAt(3) + 34], [0, 1, 0], clamp)
    + interpolate(frame, [S.s7 + 118, S.s7 + 126, S.s7 + 140], [0, 1, 0], clamp);

  // scene 7: the bill docks beside the card
  const billIn = spring({ frame: frame - (INV_AT + 46), fps, config: { damping: 15, stiffness: 110 } });
  const kLines = [0, 1, 2, 3].map((i) => prog(frame, INV_AT + 66 + i * 9, INV_AT + 80 + i * 9));
  const kOk = [0, 1, 2, 3].map((i) => INV_AT + 76 + i * 9);

  // scene 9: fan out, Penang to the front, then docks
  const fan = prog(frame, S.s9 + 6, S.s9 + 34, easeInOut);
  const lift = prog(frame, S.s9 + 46, S.s9 + 66, easeInOut);
  const redock = prog(frame, S.s9 + 72, S.s10 + 4, easeInOut);

  // scene 10
  const email = spring({ frame: frame - P, fps, config: { damping: 15, stiffness: 110 } });
  const pBill = spring({ frame: frame - (P + 30), fps, config: { damping: 15, stiffness: 110 } });
  const pLines = P_LINES.map((t) => prog(frame, t, t + 12));
  const snap = prog(frame, P_SNAP, P_SNAP + 8);
  const red = prog(frame, P_HOLD - 6, P_HOLD + 4);
  const shake = frame >= P_HOLD - 6 && frame < P_HOLD + 6 ? Math.sin((frame - P_HOLD) * 2.4) * (P_HOLD + 6 - frame) * 1.1 : 0;
  const lock = spring({ frame: frame - P_HOLD, fps, config: { damping: 10, stiffness: 170, mass: 0.8 } });
  const stamp = spring({ frame: frame - (P_HOLD + 8), fps, config: { damping: 9, stiffness: 160, mass: 0.7 } });
  const toApp = prog(frame, APP_CUT - 6, APP_CUT + 10);

  const kCursor = cursorPath(frame, [[S.s5 + 20, 1840, 1060], [ACCEPT_CLICK - 14, ACCEPT_ABS.x - 20, ACCEPT_ABS.y - 6],
    [ACCEPT_CLICK, ACCEPT_ABS.x - 30, ACCEPT_ABS.y - 4], [S.s5 + 90, ACCEPT_ABS.x + 620, ACCEPT_ABS.y + 60]]);
  const mCursor = cursorPath(frame, [[S.s8 + 36, 1840, 1060], [APPROVE_CLICK - 16, BTN_ABS.x - 20, BTN_ABS.y - 6], [APPROVE_CLICK, BTN_ABS.x - 30, BTN_ABS.y - 2], [S.s9, BTN_ABS.x + 60, BTN_ABS.y + 120]]);

  const fanCard = (i: number) => {
    const f = FAN[i];
    const isK = i === 1, isP = i === 2;
    // Kestrel's card travels from the dock into the fan; the others spread out from behind it
    const start = isK ? EXP_CENTER : { x: FAN[1].x, y: FAN[1].y };
    let x = start.x + (f.x - start.x) * fan, y = start.y + (f.y - start.y) * fan;
    let sc = isK ? 1 + (FAN_SCALE - 1) * fan : FAN_SCALE * (0.7 + 0.3 * fan);
    let rot = f.rot * fan;
    if (isP) {   // lifts to the front, then docks where the Kestrel card was
      y -= 60 * lift; sc += 0.12 * lift; rot *= 1 - lift;
      x += (EXP_CENTER.x - x) * redock; y += (EXP_CENTER.y - y) * redock; sc += (1 - sc) * redock;
    }
    const others = isP ? 1 : 1 - redock;
    return { x, y, sc, rot, op: (isK ? 1 : prog(frame, S.s9 + 8, S.s9 + 22)) * others * (isP ? 1 - toApp : 1 - 0.35 * lift) };
  };

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      {/* scene 3: rewind */}
      {frame < 60 && (
        <>
          <div style={{ position: "absolute", left: BILL_AT.x, top: BILL_AT.y + 20, transform: `translate(-50%, -50%) translateY(${-rewind * 700}px) scaleY(${1 + 0.6 * Math.sin(rewind * Math.PI)})`,
            filter: `blur(${10 * Math.sin(rewind * Math.PI)}px)`, opacity: 1 - rewind }}><BillTile size={0.95} /></div>
          <div style={{ position: "absolute", left: 960, top: 450, transform: "translate(-50%, -50%)", opacity: interpolate(frame, [4, 12, 30, 44], [0, 1, 1, 0], clamp), display: "flex", gap: 0 }}>
            {[0, 1].map((k) => <svg key={k} viewBox="0 0 60 60" width={130} height={130} style={{ marginLeft: k ? -40 : 0, filter: `drop-shadow(0 0 20px ${C.violet})` }}>
              <polygon points="56,6 56,54 8,30" fill={C.violet} opacity={0.6 + 0.4 * Math.sin(frame * 0.6 + k)} /></svg>)}
          </div>
          <svg width={1920} height={1080} style={{ position: "absolute", opacity: interpolate(frame, [2, 10, 30, 44], [0, 0.7, 0.7, 0], clamp) }}>
            {Array.from({ length: 14 }, (_, i) => {
              const y = 140 + i * 58, x = ((frame * 90 + i * 377) % 2400) - 240;
              return <line key={i} x1={1920 - x} y1={y} x2={1920 - x + 260} y2={y} stroke={i % 2 ? C.cyan : C.violet} strokeWidth={3} strokeLinecap="round" opacity={0.6} />;
            })}
          </svg>
        </>
      )}

      {/* the Slack channel */}
      {frame < S.s9 + 30 && (
        <div style={{ position: "absolute", left: WIN.x, top: WIN.y, width: WIN.w, height: WIN.h, opacity: Math.min(1, win * 1.5) * (1 - leave),
          transform: `translateX(${-leave * 300}px) translateY(${(1 - win) * 80}px) scale(${0.9 + 0.1 * win})`, boxShadow: "0 40px 120px rgba(0,0,0,0.6)", borderRadius: 18,
          filter: backdrop ? `blur(${7 * backdrop}px) brightness(${1 - 0.4 * backdrop})` : frame >= INV_AT + 46 ? `brightness(${1 - 0.25 * billIn})` : undefined }}>
          <SlackWindow kDim={kDim} />
        </div>
      )}

      {/* the Expected card: docked for Kestrel through scene 8 */}
      {frame < S.s9 + 6 && (
        <div style={{ position: "absolute", left: EXP.x, top: EXP.y, opacity: Math.min(1, dock * 1.5), transform: `translateX(${(1 - dock) * 520}px)`, zIndex: 10,
          filter: backdrop ? `brightness(${1 - 0.4 * backdrop})` : undefined }}>
          <ExpectedCard vendor="Kestrel Memory" initials="KM" color="#5b6cff" values={KESTREL_VALUES} filled={filled} glow={Math.min(1, cardGlow)} />
        </div>
      )}
      {FLIGHTS.map((fl, i) => {
        const t = prog(frame, fl.at, fl.at + FLY, easeInOut);
        const from = absAt(fl.from[0], fl.at, fl.from[1], fl.from[2]);
        return <Flight key={i} value={fl.value} from={from} to={valueAt(fl.row)} t={t} />;
      })}

      {/* scene 7: the bill beside the card */}
      {frame >= INV_AT + 46 && frame < S.s8 + 20 && (
        <>
          <div style={{ position: "absolute", left: BILL.x, top: BILL.y, zIndex: 9, opacity: Math.min(1, billIn * 1.5) * (1 - prog(frame, S.s8, S.s8 + 16)),
            transform: `translateX(${(1 - billIn) * -260}px) scale(${0.85 + 0.15 * billIn})` }}>
            <BillCard title="KM-INV-30118" amount="$72,500" values={KESTREL_VALUES} shown={[1, 1, 1, 1].map((_, i) => prog(frame, INV_AT + 56 + i * 4, INV_AT + 66 + i * 4))} />
          </div>
          <div style={{ opacity: 1 - prog(frame, S.s8, S.s8 + 12) }}><MatchLines draw={kLines} okAt={kOk} /></div>
        </>
      )}

      {/* scene 8 */}
      <DmWindow />
      <Payout />

      {/* scene 9: one Expected card per supplier */}
      {frame >= S.s9 && frame < APP_CUT + 12 && (
        [0, 3, 1, 2].map((i) => {
          const c = fanCard(i), f = FAN[i];
          if (c.op <= 0.01) return null;
          return (
            <div key={f.vendor} style={{ position: "absolute", left: c.x, top: c.y, transform: `translate(-50%, -50%) rotate(${c.rot}deg) scale(${c.sc})`, opacity: c.op, zIndex: i === 2 ? 12 : 11 }}>
              <ExpectedCard vendor={f.vendor} initials={f.initials} color={f.color} values={i === 2 ? PENANG_VALUES : i === 1 ? KESTREL_VALUES : ["", "", "", ""]}
                filled={[1, 1, 1, 1]} glow={i === 2 ? lift * (1 - redock) * 0.6 : 0} />
            </div>
          );
        })
      )}

      {/* scene 10: Penang's bill arrives by email from a look-alike domain */}
      {frame >= P && frame < APP_CUT + 12 && (
        <div style={{ position: "absolute", inset: 0, opacity: 1 - toApp }}>
          <div style={{ position: "absolute", left: EMAIL.x, top: EMAIL.y, width: EMAIL.w, padding: "22px 28px", borderRadius: 18, background: "#fff", color: SL.text, fontFamily: ui,
            boxShadow: "0 30px 80px rgba(0,0,0,0.55)", opacity: Math.min(1, email * 1.5), transform: `translateY(${(1 - email) * 60}px)` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 22 }}>
              <span style={{ fontSize: 30 }}>📧</span>
              <span style={{ color: SL.muted }}>From</span>
              <span>accounts@<span style={{ background: `rgba(255,84,112,${0.25 * prog(frame, P + 18, P + 28)})`, color: frame >= P + 18 ? "#c81e45" : SL.text, borderRadius: 4, padding: "0 2px", fontWeight: 700 }}>penang-packtest.com</span></span>
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 10 }}>PPT-6620 · new bank details</div>
            <div style={{ marginTop: 12, display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 14px", borderRadius: 14, background: "#fde8ec", color: "#c81e45",
              fontSize: 18, fontWeight: 700, opacity: prog(frame, P + 22, P + 32) }}>look-alike · on file: penangpacktest.com.my</div>
          </div>
          <div style={{ position: "absolute", left: BILL.x, top: BILL.y, zIndex: 9, opacity: Math.min(1, pBill * 1.5),
            transform: `translateX(${(1 - pBill) * -260 + shake}px) scale(${0.85 + 0.15 * pBill})` }}>
            <BillCard title="PPT-6620" amount="$3.3M" values={["$1,650", "PO-6100", "••9902", "2,000"]} bad={[2]} red={red}
              shown={[0, 1, 2, 3].map((i) => prog(frame, P + 38 + i * 4, P + 48 + i * 4))} />
            {/* lock + HELD */}
            <div style={{ position: "absolute", left: -46, top: -46, width: 110, height: 110, borderRadius: 55, background: C.red, display: "flex", alignItems: "center",
              justifyContent: "center", opacity: frame < P_HOLD ? 0 : 1, transform: `translateY(${(1 - lock) * -260}px) scale(${0.6 + 0.4 * lock})`, boxShadow: `0 0 40px ${C.red}` }}>
              <Icon name="lock" size={64} width={3.2} /></div>
            <div style={{ position: "absolute", left: BILL.w / 2 - 100, top: 300, width: 200, padding: "12px 0", textAlign: "center", borderRadius: 14, background: C.red, color: "#fff",
              fontSize: 44, fontWeight: 800, letterSpacing: 4, opacity: frame < P_HOLD + 8 ? 0 : 1, transform: `rotate(${-6 * stamp}deg) scale(${1.6 - 0.6 * stamp})` }}>HELD</div>
          </div>
          <MatchLines draw={pLines} okAt={P_OK.map((t, i) => (i === 2 ? (frame >= P_SNAP ? P_SNAP : -1) : t))} badRow={2} snap={snap} />
        </div>
      )}

      {/* scene 10b: the real app's bill page */}
      <AppCut />

      <Cursor x={kCursor.x} y={kCursor.y} press={clickPress(frame, [ACCEPT_CLICK])} label="Kestrel" color="#5b6cff"
        opacity={interpolate(frame, [S.s5 + 20, S.s5 + 28, S.s5 + 74, S.s5 + 86], [0, 1, 1, 0], clamp)} />
      <Cursor x={mCursor.x} y={mCursor.y} press={clickPress(frame, [APPROVE_CLICK])} label="M. Chen" color="#7c3aed"
        opacity={interpolate(frame, [S.s8 + 36, S.s8 + 44, S.s9 - 6, S.s9 + 4], [0, 1, 1, 0], clamp)} />

      <Sequence durationInFrames={S.s4}><Caption text="ReconAI starts at the first quote." duration={S.s4} start={24} /></Sequence>
      <Sequence from={S.s4} durationInFrames={S.s5 - S.s4}><Caption text="Only your side sees this." duration={S.s5 - S.s4} start={60} /></Sequence>
      <Sequence from={S.s5} durationInFrames={S.s6 - S.s5}><Caption text="Signed and vetted." duration={S.s6 - S.s5} start={10} /></Sequence>
      <Sequence from={S.s6} durationInFrames={S.s7 - S.s6}><Caption text="A claim isn't a receipt." duration={S.s7 - S.s6} start={8} /></Sequence>
      <Sequence from={S.s7} durationInFrames={S.s8 - S.s7}><Caption text="It already knows what you owe." duration={S.s8 - S.s7} start={30} /></Sequence>
      <Sequence from={S.s8} durationInFrames={S.s9 - S.s8}><Caption text="One click to pay. Never the agent's." duration={S.s9 - S.s8} start={12} /></Sequence>
      <Sequence from={S.s9} durationInFrames={S.s10 - S.s9}><Caption text="One for every supplier." duration={S.s10 - S.s9} start={10} /></Sequence>
      <Sequence from={S.s10} durationInFrames={APP_CUT - S.s10}><Caption text="The wrong account never gets paid." duration={APP_CUT - S.s10} start={12} /></Sequence>
      <Sequence from={APP_CUT}><Caption text="Every reason, on the record." duration={STORY_FRAMES - APP_CUT} start={10} /></Sequence>
    </AbsoluteFill>
  );
};
