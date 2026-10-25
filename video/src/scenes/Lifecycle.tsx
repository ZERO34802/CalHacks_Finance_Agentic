import { Fragment, type FC, type ReactNode } from "react";
import { AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Chevrons, Cursor, Decrypt, GlowSweep, Icon, type IconName, Mark, RotatingText, Shiny, SplitFlap } from "../components";
import { clamp, clickPress, cursorPath, easeInOut, glassW as glass, prog, ui, W as C } from "../theme";
import { AppTag, Av, Chip, SL } from "./slackParts";

// Scenes 3-11: the whole bill lifecycle in one vendor channel, as one continuous shot.
//   3 fast-forward into Slack     4 the private coach (price + cash flow)     5 contract, auto-onboarding
//   6 document 1: PO in the ERP   7 vendor reports the shipment               8 CTO confirms the count: document 2
//   9 document 3: invoice, 3-way match, mismatch tags the vendor            10 corrected invoice, all three agree
//  11 all-clear DM, one click releases payment, the channel updates
// Messages follow the product's real Slack flow (backend/slack/cycle.py, bot.py, onboard.py), cut to a few words.
// Numbers are case_01: PO-7001, 50 x HBM3E-12H-24G at the MSA price $1,450 = $72,500, terms 2/15 net 30, so a
// timely release pays $71,050. Payment is shown generically (the product releases via Coinbase on testnet today).
// Coach numbers come from market.py analyze() for that SKU with a $1,520 quote at net 30:
// counter $1,180, aim $1,300, walk away $1,460, +$11,000 at the aim, 2/15 net 30 worth $1,520. The first invoice
// billing the $1,520 quote, and the message clock (10:02 -> 10:33), are illustrative.
export const L = { s3: 0, s4: 90, s5: 300, s6: 480, s7: 615, s8: 765, s9: 945, s10: 1185, s11: 1350 };
export const LIFECYCLE_FRAMES = 1590;

// --- layout ------------------------------------------------------------------------------------------------------------
const WIN = { x: 50, y: 50, w: 1230, h: 800 };
const TITLE = 40;
const SIDE = 210;
const HEAD = 64;
const COMPOSER = 74;
const VIEW_H = WIN.h - TITLE - HEAD - COMPOSER;
const BODY = 90;   // message body x, relative to the message pane
const RX = 1320;
const RW = 560;
const DOC_Y = (i: number) => 172 + i * 148;
const DOC_H = 134;

// --- the thread ----------------------------------------------------------------------------------------------------------
const ITEMS = [
  { key: "quote", at: L.s4 + 10, h: 92 },
  { key: "whisper", at: L.s4 + 50, h: 300 },
  { key: "agreed", at: L.s5 + 6, h: 84 },
  { key: "contract", at: L.s5 + 22, h: 150 },
  { key: "onboard", at: L.s5 + 86, h: 160 },
  { key: "po", at: L.s6 + 8, h: 90 },
  { key: "shipped", at: L.s7 + 66, h: 92 },
  { key: "receipt", at: L.s8 + 130, h: 84 },
  { key: "invoice", at: L.s9 + 10, h: 132 },
  { key: "reconciling", at: L.s9 + 42, h: 84 },
  { key: "diff", at: L.s9 + 130, h: 92 },
  { key: "corrected", at: L.s10 + 10, h: 120 },
  { key: "paid", at: L.s11 + 180, h: 84 },
] as const;
type Key = (typeof ITEMS)[number]["key"];
const idx = (k: Key) => ITEMS.findIndex((it) => it.key === k);
const at = (k: Key) => ITEMS[idx(k)].at;
const GAP = 12;
const PAD = 16;
const grow = (i: number, f: number) => prog(f, ITEMS[i].at, ITEMS[i].at + 14, easeInOut);
const topOf = (i: number, f: number) => PAD + ITEMS.slice(0, i).reduce((y, it, j) => y + (it.h + GAP) * grow(j, f), 0);
const scrollAt = (f: number) => Math.max(0, topOf(ITEMS.length, f) + PAD - VIEW_H);
// a point inside a message body -> frame coordinates
const absAt = (k: Key, f: number, x: number, y: number) => ({ x: WIN.x + SIDE + BODY + x, y: WIN.y + TITLE + HEAD + topOf(idx(k), f) - scrollAt(f) + 30 + y });

// --- the three documents ------------------------------------------------------------------------------------------------
const FLY = 24;
const DOCS = [
  { n: 1, title: "Purchase order", id: "PO-7001", value: "50 × $1,450", source: "Helix ERP · from the contract", icon: "window" as IconName, at: at("po") + 12, from: ["po", 120, 14] as const },
  { n: 2, title: "Goods receipt", id: "GRN-PO-7001-1", value: "50 received", source: "Counted by the CTO", icon: "box" as IconName, at: at("receipt") + 10, from: ["receipt", 120, 20] as const },
  { n: 3, title: "Invoice", id: "KM-INV-30118", value: "50 × $1,520", source: "XLSX · shared in the chat", icon: "doc" as IconName, at: at("invoice") + 20, from: ["invoice", 200, 34] as const },
];
const CORRECT_AT = at("corrected") + 16;   // the corrected invoice lands in card 3
const docFilled = (i: number, f: number) => prog(f, DOCS[i].at + FLY, DOCS[i].at + FLY + 8);

// 3-way match checks: [label, verdict frame, ok]
const MATCH_AT = at("reconciling") + 30;
const CHECKS: { label: string; at: number; ok: boolean }[] = [
  { label: "Qty 50 = 50 = 50", at: MATCH_AT, ok: true },
  { label: "Price", at: MATCH_AT + 12, ok: false },
  { label: "Bank", at: MATCH_AT + 20, ok: true },
  { label: "No duplicate", at: MATCH_AT + 28, ok: true },
];
const PRICE_FIXED = CORRECT_AT + 30;
const ALL_MATCHED = PRICE_FIXED + 10;

// the steps the agent does by itself, lit as they happen
const AUTO: { icon: IconName; label: string; at: number }[] = [
  { icon: "tag", label: "Coach", at: at("whisper") + 10 },
  { icon: "doc", label: "Contract", at: at("contract") + 2 },
  { icon: "shield", label: "Onboarding", at: at("onboard") + 40 },
  { icon: "window", label: "PO in ERP", at: at("po") + 4 },
  { icon: "box", label: "Receipt", at: at("receipt") + 4 },
  { icon: "search", label: "Invoice read", at: at("reconciling") },
  { icon: "docs", label: "3-way match", at: MATCH_AT },
  { icon: "bank", label: "Payment", at: L.s11 + 140 },
];

// invoice -> paid clock, in story minutes (message times 10:02 -> 10:33)
const CLOCK_F = [at("invoice"), at("diff"), at("corrected"), L.s11 + 140];
const CLOCK_M = [0, 0, 29, 31];

// --- small pieces -----------------------------------------------------------------------------------------------------
const VAv: FC<{ size?: number; dim?: number }> = ({ size, dim }) => <Av bg="#5b6cff" size={size} dim={dim}>V</Av>;
const CtoAv: FC<{ size?: number }> = ({ size }) => <Av bg={C.teal} size={size}>CTO</Av>;
const Mention: FC<{ children: ReactNode }> = ({ children }) => (
  <span style={{ background: "#e8f5fa", color: "#1264a3", borderRadius: 4, padding: "0 4px", fontWeight: 700 }}>{children}</span>
);

const Msg: FC<{ k: Key; avatar: ReactNode; name: ReactNode; time: string; eph?: boolean; bar?: string; children: ReactNode }> = ({ k, avatar, name, time, eph, bar, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const i = idx(k);
  const s = spring({ frame: frame - ITEMS[i].at, fps, config: { damping: 15, stiffness: 120 } });
  if (frame < ITEMS[i].at) return null;
  return (
    <div style={{ position: "absolute", left: SIDE, right: 0, top: topOf(i, frame), height: ITEMS[i].h, background: eph ? SL.eph : undefined,
      borderLeft: bar ? `5px solid ${bar}` : undefined, opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 30}px)` }}>
      {eph && <div style={{ position: "absolute", left: BODY, top: 6, fontSize: 16, color: SL.muted, display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="eyeOff" size={18} color={SL.muted} width={3} /> Only visible to you</div>}
      <div style={{ position: "absolute", left: 26, top: eph ? 32 : 8 }}>{avatar}</div>
      <div style={{ position: "absolute", left: BODY, top: eph ? 30 : 6, right: 24 }}>
        <div style={{ fontSize: 21, fontWeight: 800, color: SL.text, height: 28 }}>{name}<span style={{ fontSize: 15, fontWeight: 400, color: SL.muted, marginLeft: 10 }}>{time}</span></div>
        <div style={{ fontSize: 22, color: SL.text, marginTop: 2 }}>{children}</div>
      </div>
    </div>
  );
};
// the ReconAI app's avatar: brand-teal tile with the logo's chevrons
const BrandAv: FC<{ size?: number }> = ({ size = 52 }) => <Av bg={C.teal} size={size}><Chevrons width={size * 0.62} color="#fff" /></Av>;
const Bot = <>ReconAI<AppTag /></>;

const Typing: FC = () => {
  const frame = useCurrentFrame();
  return <div style={{ display: "flex", gap: 8, paddingTop: 10 }}>{[0, 1, 2].map((i) => (
    <div key={i} style={{ width: 12, height: 12, borderRadius: 6, background: "#999", transform: `translateY(${Math.sin(frame * 0.35 - i * 0.9) * -5}px)` }} />))}</div>;
};
const Quote: FC = () => {
  const frame = useCurrentFrame();
  if (frame < at("quote") + 22) return <Typing />;
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}><Icon name="tag" size={30} color={SL.text} />We can do <b>$1,520</b> per stack for 50, net 30.</span>;
};

// the coach: price gauge + cash-flow asks
const G = { w: 640, lo: 1150, hi: 1560 };
const gx = (v: number) => ((v - G.lo) / (G.hi - G.lo)) * G.w;
const W0 = at("whisper");
const PINS = [
  { v: 1520, label: "their quote", color: C.red, at: W0 + 16 },
  { v: 1460, label: "walk away", color: "#d97706", at: W0 + 30 },
  { v: 1300, label: "aim", color: SL.green, at: W0 + 44 },
  { v: 1180, label: "counter", color: "#0891b2", at: W0 + 58 },
];
const SAVE_AT = W0 + 72;
const CASH_AT = W0 + 96;
const Whisper: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zone = prog(frame, PINS[1].at, PINS[1].at + 24);
  const save = interpolate(frame, [SAVE_AT, SAVE_AT + 30], [0, 11000], { ...clamp, easing: easeInOut });
  const pop = (t: number) => ({ opacity: prog(frame, t, t + 10), transform: `scale(${0.7 + 0.3 * spring({ frame: frame - t, fps, config: { damping: 9, stiffness: 160 } })})` });
  return (
    <div>
      <b>Negotiation notes</b> <span style={{ color: SL.muted }}>· HBM3E stacks</span>
      <div style={{ display: "flex", alignItems: "center", gap: 24, marginTop: 6 }}>
        <div style={{ position: "relative", width: G.w, height: 112 }}>
          <div style={{ position: "absolute", top: 53, left: 0, width: G.w, height: 10, borderRadius: 5, background: "#e2e2e2" }} />
          <div style={{ position: "absolute", top: 53, left: 0, width: gx(1460) * zone, height: 10, borderRadius: 5, background: "#2bac76" }} />
          {PINS.map((p) => {
            const s = spring({ frame: frame - p.at, fps, config: { damping: 10, stiffness: 150 } });
            return (
              <div key={p.v} style={{ position: "absolute", left: gx(p.v), top: 0, transform: `translateX(-50%) translateY(${(1 - s) * -34}px)`,
                opacity: Math.min(1, s * 2), display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ fontSize: 24, fontWeight: 800 }}>${p.v.toLocaleString("en-US")}</div>
                <div style={{ width: 22, height: 22, borderRadius: 11, background: p.color, border: "4px solid #fff", marginTop: 12, boxShadow: "0 1px 4px rgba(0,0,0,0.35)" }} />
                <div style={{ fontSize: 16, color: SL.muted, marginTop: 6, whiteSpace: "nowrap" }}>{p.label}</div>
              </div>
            );
          })}
        </div>
        <div style={{ padding: "12px 20px", borderRadius: 14, background: "#e8f5ee", color: SL.green, textAlign: "center", border: "2px solid #2bac76", ...pop(SAVE_AT) }}>
          <div style={{ fontSize: 32, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>+${Math.round(save).toLocaleString("en-US")}</div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>at the aim</div>
        </div>
      </div>
      {/* cash flow: the terms to ask for before signing */}
      <div style={{ display: "flex", gap: 12, marginTop: 10 }}>
        <Chip bg="#eef6ff" color="#1d4ed8" style={pop(CASH_AT)}>💸 Ask 2/15 net 30 · worth $1,520</Chip>
        <Chip bg="#eef6ff" color="#1d4ed8" style={pop(CASH_AT + 12)}>or net 45 instead of net 30</Chip>
      </div>
    </div>
  );
};

const ACCEPT_CLICK = L.s5 + 66;
const ACCEPT_ABS = absAt("contract", ACCEPT_CLICK, 150, 56 + 23);
const Contract: FC = () => {
  const frame = useCurrentFrame();
  const hover = prog(frame, ACCEPT_CLICK - 12, ACCEPT_CLICK - 4);
  const press = clickPress(frame, [ACCEPT_CLICK]);
  const done = frame >= ACCEPT_CLICK + 4;
  return (
    <div>
      <div style={{ display: "flex", gap: 12 }}>
        <Chip w={250}><span style={{ width: 26, height: 30, borderRadius: 4, background: SL.code, color: "#fff", fontSize: 10, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>PDF</span>Supply Agreement</Chip>
        <Chip w={160}>HBM3E × 50</Chip>
        <Chip w={180} bg="#e8f5ee" color={SL.green}>$1,450 / stack</Chip>
        <Chip w={170} bg="#eef6ff" color="#1d4ed8">2/15 net 30</Chip>
      </div>
      <div style={{ marginTop: 16, width: 300, height: 46, borderRadius: 8, background: SL.green, color: "#fff", fontSize: 20, fontWeight: 800,
        display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${1 + 0.04 * hover * (done ? 0 : 1) - 0.07 * press})`,
        boxShadow: `0 0 ${18 * hover}px rgba(0,122,90,0.55)` }}>{done ? "✓ Accepted" : "Accept & start onboarding"}</div>
    </div>
  );
};

const ONBOARD_CHECKS: { icon: IconName; label: string }[] = [
  { icon: "shield", label: "Sanctions" }, { icon: "bank", label: "Bank" }, { icon: "globe", label: "Domain" }, { icon: "doc", label: "Tax form" },
];
const Onboard: FC = () => {
  const frame = useCurrentFrame();
  const t0 = at("onboard");
  return (
    <div>
      <span>✅ <b>Vendor</b> onboarded by policy: every check passed · 90-day probation</span>
      <div style={{ display: "flex", gap: 12, marginTop: 10 }}>
        {ONBOARD_CHECKS.map((c, i) => {
          const t = t0 + 8 + i * 7;
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

const FileCard: FC<{ name: string; ext: string; read: [number, number] }> = ({ name, ext, read }) => {
  const frame = useCurrentFrame();
  const reading = frame >= read[0] && frame < read[1];
  const scan = prog(frame, read[0], read[1], easeInOut);
  const color = ext === "PDF" ? SL.code : "#1d7044";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <div style={{ position: "relative", width: 430, height: 70, borderRadius: 10, border: `2px solid ${reading ? "#06b6d4" : "#ddd"}`, overflow: "hidden", display: "flex",
        alignItems: "center", gap: 14, padding: "0 16px", boxSizing: "border-box", background: "#fff",
        boxShadow: reading ? `0 0 ${18 + 10 * Math.sin(frame * 0.5)}px rgba(6,182,212,0.6)` : undefined }}>
        <span style={{ width: 44, height: 44, borderRadius: 6, background: color, color: "#fff", fontSize: 12, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>{ext}</span>
        <b>{name}</b>
        {reading && <div style={{ position: "absolute", left: 0, right: 0, top: scan * 70 - 3, height: 6, background: "#06b6d4", boxShadow: "0 0 14px #06b6d4" }} />}
      </div>
      {/* any of these formats works: the pill cycles, then lands on this file's */}
      <span style={{ fontSize: 18, color: SL.muted, display: "inline-flex", alignItems: "center", gap: 8 }}>accepted as
        <RotatingText words={ext === "PDF" ? ["XLSX", "CSV", "PDF"] : ["PDF", "CSV", "XLSX"]} at={read[0] - 8} every={10}
          style={{ background: color, color: "#fff", fontWeight: 800, fontSize: 18, minWidth: 52, justifyContent: "center" }} />
      </span>
    </div>
  );
};

const PaidMsg: FC = () => {
  const frame = useCurrentFrame();
  const glow = interpolate(frame, [at("paid"), at("paid") + 10, at("paid") + 40], [0, 1, 0.3], clamp);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10, background: `rgba(43,172,118,${0.12 * glow})`, borderRadius: 8, padding: "2px 8px", marginLeft: -8 }}>
      💸 Payment sent: <b>$71,050</b> for KM-INV-30118-R
    </span>
  );
};

const BODIES: Record<Key, { avatar: ReactNode; name: ReactNode; time: string; eph?: boolean; bar?: string; body: ReactNode }> = {
  quote: { avatar: <VAv />, name: "Vendor", time: "09:14", body: <Quote /> },
  whisper: { avatar: <BrandAv />, name: Bot, time: "09:14", eph: true, body: <Whisper /> },
  agreed: { avatar: <CtoAv />, name: "CTO · Helix", time: "09:40", body: <>Agreed: 50 at <b>$1,450</b>, 2/15 net 30.</> },
  contract: { avatar: <BrandAv />, name: Bot, time: "09:41", body: <Contract /> },
  onboard: { avatar: <BrandAv />, name: Bot, time: "09:43", body: <Onboard /> },
  po: { avatar: <BrandAv />, name: Bot, time: "09:43", body: <>📦 <b>PO-7001</b> created in Helix ERP from the contract · 50 × HBM3E-12H-24G</> },
  shipped: { avatar: <BrandAv />, name: Bot, time: "Oct 10", body: <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
    🚚 Shipment notice logged: <b>PO-7001 · 50 × HBM3E-12H-24G</b><Chip bg="#fff4e0" color="#b45309">claim · Helix counts it</Chip></span> },
  receipt: { avatar: <BrandAv />, name: Bot, time: "Oct 11", body: <>✅ Goods receipt <b>GRN-PO-7001-1</b> · 50 × HBM3E-12H-24G · counted by the CTO, Helix</> },
  invoice: { avatar: <VAv />, name: "Vendor", time: "Oct 12 · 10:02", body: <FileCard name="KM-INV-30118.xlsx" ext="XLSX" read={[at("invoice") + 14, at("invoice") + 44]} /> },
  reconciling: { avatar: <BrandAv />, name: Bot, time: "10:02", body: <>Received KM-INV-30118: reconciling against <b>PO-7001</b> and <b>GRN-PO-7001-1</b>.</> },
  diff: { avatar: <BrandAv />, name: Bot, time: "10:02", bar: C.red, body: <><Mention>@Vendor</Mention> We found a difference on <b>KM-INV-30118</b>; details emailed to your contact on file.</> },
  corrected: { avatar: <VAv />, name: "Vendor", time: "10:31", body: <FileCard name="KM-INV-30118-R.pdf" ext="PDF" read={[at("corrected") + 10, at("corrected") + 40]} /> },
  paid: { avatar: <BrandAv />, name: Bot, time: "10:33", body: <PaidMsg /> },
};

// --- composer: the vendor types the shipment command ------------------------------------------------------------------
const CMD = "/reconai shipped PO-7001 HBM3E-12H-24G=50";
const TYPE = [L.s7 + 10, L.s7 + 56];
const SEND = L.s7 + 62;
const Composer: FC = () => {
  const frame = useCurrentFrame();
  const n = Math.round(interpolate(frame, TYPE, [0, CMD.length], clamp));
  const text = frame < SEND ? CMD.slice(0, n) : "";
  const active = frame >= TYPE[0] - 6 && frame < SEND + 4;
  const send = clickPress(frame, [SEND]);
  return (
    <div style={{ position: "absolute", left: SIDE + 20, right: 20, bottom: 14, height: COMPOSER - 24, borderRadius: 10, border: `1px solid ${active ? "#1d9bd1" : "#ccc"}`,
      display: "flex", alignItems: "center", gap: 12, padding: "0 14px", background: "#fff", boxShadow: active ? "0 0 0 3px rgba(29,155,209,0.15)" : undefined }}>
      {active && <VAv size={30} />}
      <span style={{ fontSize: 21, fontFamily: "monospace", color: text ? SL.text : "#999", flex: 1, whiteSpace: "nowrap", overflow: "hidden" }}>
        {text ? <><span style={{ color: "#1264a3", fontWeight: 700 }}>{text.slice(0, 8)}</span>{text.slice(8)}<span style={{ opacity: Math.sin(frame * 0.4) > 0 ? 1 : 0 }}>|</span></>
          : <span style={{ fontFamily: ui }}>Message 🔒 vendor-deal</span>}
      </span>
      <div style={{ width: 36, height: 36, borderRadius: 8, background: active ? SL.green : "#ddd", display: "flex", alignItems: "center", justifyContent: "center",
        transform: `scale(${1 - 0.15 * send})` }}><Icon name="arrow" size={24} color="#fff" width={3.4} /></div>
    </div>
  );
};

const SlackWindow: FC<{ vDim: number; vPing: number }> = ({ vDim, vPing }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", inset: 0, borderRadius: 18, overflow: "hidden", background: "#fff", fontFamily: ui }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: TITLE, background: SL.top, display: "flex", alignItems: "center", gap: 8, paddingLeft: 16 }}>
        {["#ff5f57", "#febc2e", "#28c840"].map((d) => <div key={d} style={{ width: 12, height: 12, borderRadius: 6, background: d }} />)}
        <div style={{ marginLeft: 240, width: 480, height: 26, borderRadius: 6, background: "rgba(255,255,255,0.18)" }} />
      </div>
      <div style={{ position: "absolute", left: 0, top: TITLE, bottom: 0, width: SIDE, background: SL.side, padding: "18px 12px", boxSizing: "border-box", color: SL.sideText }}>
        <div style={{ color: "#fff", fontWeight: 800, fontSize: 22, padding: "0 8px 18px" }}>Helix Silicon</div>
        {[0.7, 0.55].map((w, i) => <div key={i} style={{ height: 12, width: `${w * 100}%`, borderRadius: 6, background: "rgba(255,255,255,0.16)", margin: "12px 8px" }} />)}
        <div style={{ marginTop: 14, padding: "8px 10px", borderRadius: 8, background: SL.active, color: SL.side, fontWeight: 800, fontSize: 19, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="lock" size={18} color={SL.side} width={3.4} /> vendor-deal
        </div>
        {[0.6, 0.45, 0.65].map((w, i) => <div key={i} style={{ height: 12, width: `${w * 100}%`, borderRadius: 6, background: "rgba(255,255,255,0.16)", margin: "18px 8px" }} />)}
      </div>
      <div style={{ position: "absolute", left: SIDE, right: 0, top: TITLE, height: HEAD, borderBottom: `1px solid ${SL.line}`, display: "flex", alignItems: "center", gap: 10,
        padding: "0 26px", background: "#fff", zIndex: 2 }}>
        <Icon name="lock" size={22} color={SL.text} width={3} />
        <span style={{ fontSize: 25, fontWeight: 800, color: SL.text }}>vendor-deal</span>
        <div style={{ flex: 1 }} />
        <Av bg={C.teal} size={40}>H</Av>
        <div style={{ position: "relative" }}>
          <VAv size={40} dim={vDim} />
          <div style={{ position: "absolute", right: -9, bottom: -9, width: 26, height: 26, borderRadius: 13, background: "#fff", display: "flex", alignItems: "center",
            justifyContent: "center", opacity: vDim, boxShadow: "0 1px 4px rgba(0,0,0,0.3)" }}><Icon name="eyeOff" size={18} color="#7c3aed" width={3.4} /></div>
          <div style={{ position: "absolute", right: -6, top: -6, width: 16, height: 16, borderRadius: 8, background: C.red, opacity: vPing, transform: `scale(${0.6 + 0.4 * vPing})` }} />
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: TITLE + HEAD, height: VIEW_H, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 4000, transform: `translateY(${-scrollAt(frame)}px)` }}>
          {ITEMS.map((it) => <Msg key={it.key} k={it.key} {...BODIES[it.key]}>{BODIES[it.key].body}</Msg>)}
        </div>
      </div>
      <Composer />
    </div>
  );
};

// --- right panel: the three documents, the match, the automation ---------------------------------------------------
const DocCard: FC<{ i: number }> = ({ i }) => {
  const frame = useCurrentFrame();
  const d = DOCS[i];
  const f = docFilled(i, frame);
  const isInv = i === 2;
  const corrected = isInv && frame >= CORRECT_AT + FLY;
  const flip = isInv ? prog(frame, CORRECT_AT + FLY, CORRECT_AT + FLY + 10) : 0;
  const priceBad = isInv && frame >= CHECKS[1].at && frame < PRICE_FIXED;
  const matched = prog(frame, ALL_MATCHED, ALL_MATCHED + 12);
  const value = corrected ? "50 × $1,450" : d.value;
  return (
    <div style={{ ...glass, position: "absolute", left: RX, top: DOC_Y(i), width: RW, height: DOC_H, borderRadius: 22, boxSizing: "border-box",
      background: `rgba(255,255,255,${0.5 + 0.42 * f})`, borderStyle: f < 1 ? "dashed" : "solid",
      borderColor: priceBad ? C.red : matched ? `rgba(22,163,74,${0.45 + 0.5 * matched})` : f > 0 ? "rgba(22,163,74,0.5)" : "rgba(10,31,33,0.16)",
      boxShadow: priceBad ? `0 0 36px rgba(194,74,64,0.28)` : matched ? `0 0 ${32 * matched}px rgba(22,163,74,0.28)` : glass.boxShadow, fontFamily: ui, color: C.text }}>
      {/* Border Glow sweeps: as the document is created, red on the mismatch, green when all three agree */}
      <GlowSweep at={d.at + FLY - 4} radius={22} colors={["#0e6e76", "#3aafa7", "#16a34a"]} />
      {isInv && <GlowSweep at={CHECKS[1].at} radius={22} colors={["#e6b5b0", "#c24a40", "#d68f00"]} />}
      <GlowSweep at={ALL_MATCHED + i * 6} radius={22} colors={["#16a34a", "#4ade80", "#3aafa7"]} />
      <div style={{ position: "absolute", left: 22, top: 20, width: 46, height: 46, borderRadius: 23, background: f > 0 ? (priceBad ? C.red : C.green) : "rgba(10,31,33,0.06)",
        color: f > 0 ? "#fff" : C.muted, fontSize: 25, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: f > 0 ? `0 6px ${18 * f}px rgba(22,163,74,0.35)` : undefined }}>{d.n}</div>
      <div style={{ position: "absolute", left: 88, top: 18 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color: f > 0 ? C.text : C.muted, display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name={d.icon} size={28} color={f > 0 ? C.text : C.muted} /> {d.title}</div>
        <div style={{ fontSize: 20, color: C.muted, marginTop: 4, opacity: f, fontFamily: "monospace" }}>
          <Decrypt key={corrected ? "r" : "o"} text={corrected ? "KM-INV-30118-R" : d.id} at={corrected ? CORRECT_AT + FLY : d.at + FLY} scramble={C.teal} /></div>
      </div>
      <div style={{ position: "absolute", right: 24, top: 22, fontSize: 30, fontWeight: 800, opacity: f, fontVariantNumeric: "tabular-nums",
        color: priceBad ? C.red : C.text, transform: `rotateX(${isInv ? Math.sin(flip * Math.PI) * 80 : 0}deg)` }}>{value}</div>
      <div style={{ position: "absolute", left: 88, bottom: 18, opacity: f, display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 14,
        background: "rgba(8,145,178,0.10)", color: C.cyan, fontSize: 17, fontWeight: 700 }}>
        {corrected ? "PDF · shared in the chat" : d.source}
      </div>
      {matched > 0 && <div style={{ position: "absolute", right: 22, bottom: 14 }}><Mark ok p={matched} size={34} color={C.green} /></div>}
    </div>
  );
};

const MatchStrip: FC = () => {
  const frame = useCurrentFrame();
  const show = prog(frame, MATCH_AT - 10, MATCH_AT);
  return (
    <div style={{ position: "absolute", left: RX, top: 622, width: RW, display: "flex", gap: 10, opacity: show }}>
      {CHECKS.map((c, i) => {
        const fixed = i === 1 && frame >= PRICE_FIXED;
        const ok = c.ok || fixed;
        const p = prog(frame, c.at, c.at + 10);
        const col = p === 0 ? C.muted : ok ? C.green : C.red;
        return (
          <div key={c.label} style={{ flex: [1.7, 1, 1, 1.35][i], height: 50, borderRadius: 14, border: `1px solid ${col}`, background: `${col}1f`, display: "flex",
            alignItems: "center", justifyContent: "center", gap: 6, color: col, fontFamily: ui, fontSize: 16, fontWeight: 800, whiteSpace: "nowrap" }}>
            {p > 0 && <Mark ok={ok} p={fixed ? prog(frame, PRICE_FIXED, PRICE_FIXED + 10) : p} size={24} color={col} />}{c.label}
          </div>
        );
      })}
    </div>
  );
};

const AutoGrid: FC = () => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: RX, top: 690, width: RW, fontFamily: ui }}>
      <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: 2, color: C.muted, marginBottom: 10 }}>AUTOMATED</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
        {AUTO.map((a) => {
          const on = prog(frame, a.at, a.at + 12);
          const pulse = interpolate(frame, [a.at, a.at + 6, a.at + 26], [0, 1, 0], clamp);
          const flagged = a.label === "3-way match" && frame >= CHECKS[1].at && frame < PRICE_FIXED;
          const col = flagged ? C.red : C.green;
          return (
            <div key={a.label} style={{ height: 66, borderRadius: 14, border: `1px solid ${on ? col : "rgba(15,18,34,0.10)"}`, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 4, background: on ? `${col}14` : "rgba(255,255,255,0.6)",
              boxShadow: `0 0 ${26 * pulse}px ${col}`, transform: `scale(${1 + 0.06 * pulse})` }}>
              <Icon name={a.icon} size={24} color={on ? col : "#a0a4b3"} width={2.8} />
              <span style={{ fontSize: 15, fontWeight: 700, color: on ? C.text : "#a0a4b3" }}>{a.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const minsAt = (f: number) => Math.round(interpolate(f, CLOCK_F, CLOCK_M, clamp));
// the clock is a split-flap board (React Bits "Split Flap Text")
const clockBoard = (f: number) => (f < CLOCK_F[0] ? "--" : String(minsAt(f)).padStart(2, " "));
const Clock: FC = () => {
  const frame = useCurrentFrame();
  const done = frame >= CLOCK_F[3];
  const glow = done ? interpolate(frame, [CLOCK_F[3], CLOCK_F[3] + 10, CLOCK_F[3] + 50], [0, 1, 0.4], clamp) : 0;
  return (
    <div style={{ ...glass, position: "absolute", left: RX, top: 30, width: RW, height: 70, borderRadius: 18, display: "flex", alignItems: "center", gap: 14, padding: "0 22px",
      boxSizing: "border-box", fontFamily: ui, color: C.text, borderColor: done ? C.green : undefined, boxShadow: `0 0 ${40 * glow}px rgba(22,163,74,0.35)` }}>
      <span style={{ fontSize: 26 }}>⏱</span>
      <span style={{ fontSize: 21, color: C.muted, flex: 1 }}>Invoice → paid</span>
      <SplitFlap value={clockBoard} size={34} tile={done ? "#065f46" : "#111827"} />
      <span style={{ fontSize: 24, fontWeight: 800, color: done ? C.green : C.text }}>min</span>
      <span style={{ fontSize: 17, color: C.muted, marginLeft: 6 }}>vs 17.4 days</span>
    </div>
  );
};

// PO -> Receipt -> Invoice (React Bits "Stepper"): a step is active while its document is on the way, complete (with a
// drawn check) once it lands, and the connector fills; the invoice step goes red on the mismatch.
const STEPS = ["PO", "Receipt", "Invoice"];
const STEP_DONE = [DOCS[0].at + FLY, DOCS[1].at + FLY, ALL_MATCHED];
const STEP_ACTIVE = [ACCEPT_CLICK + 4, STEP_DONE[0], STEP_DONE[1]];
const StepDot: FC<{ i: number }> = ({ i }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const done = frame >= STEP_DONE[i];
  const error = i === 2 && frame >= CHECKS[1].at && frame < PRICE_FIXED;
  const active = !done && frame >= STEP_ACTIVE[i];
  const since = done ? STEP_DONE[i] : error ? CHECKS[1].at : STEP_ACTIVE[i];
  const s = spring({ frame: frame - since, fps, config: { damping: 12, stiffness: 180 } });
  const on = done || error || active;
  return (
    <div style={{ width: 36, height: 36, borderRadius: 18, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
      background: error ? C.red : done ? C.green : active ? C.teal : "rgba(10,31,33,0.07)", color: on ? "#fff" : C.muted, fontSize: 17, fontWeight: 800,
      transform: `scale(${on ? 0.85 + 0.15 * s : 1})`, boxShadow: on ? `0 6px 16px ${error ? "rgba(194,74,64,0.35)" : done ? "rgba(22,163,74,0.35)" : "rgba(14,110,118,0.35)"}` : undefined }}>
      {error ? "!" : done ? (
        <svg viewBox="0 0 24 24" width={20} height={20}><polyline points="5,12.5 10,17 19,7.5" fill="none" stroke="#fff" strokeWidth={3.2} strokeLinecap="round"
          strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - prog(frame, STEP_DONE[i], STEP_DONE[i] + 10)} /></svg>
      ) : active ? <div style={{ width: 11, height: 11, borderRadius: 6, background: "#fff", transform: `scale(${0.8 + 0.2 * Math.sin(frame * 0.25)})` }} /> : i + 1}
    </div>
  );
};
const Stepper: FC = () => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: RX + 6, top: 116, width: RW - 12, height: 40, display: "flex", alignItems: "center", fontFamily: ui }}>
      {STEPS.map((label, i) => (
        <Fragment key={label}>
          <StepDot i={i} />
          <span style={{ marginLeft: 10, fontSize: 19, fontWeight: 800, color: frame >= STEP_ACTIVE[i] ? C.text : C.muted }}>{label}</span>
          {i < STEPS.length - 1 && (
            <div style={{ flex: 1, height: 3, margin: "0 14px", borderRadius: 2, background: "rgba(15,18,34,0.10)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${prog(frame, STEP_DONE[i], STEP_DONE[i] + 14) * 100}%`, background: C.green }} />
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
};

// a value flying from a message into a document card
const Flight: FC<{ label: string; from: { x: number; y: number }; to: { x: number; y: number }; t: number; color?: string }> = ({ label, from, to, t, color = C.teal }) => {
  if (t <= 0 || t >= 1) return null;
  const x = from.x + (to.x - from.x) * t;
  const y = from.y + (to.y - from.y) * t - Math.sin(t * Math.PI) * 140;
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${1 + Math.sin(t * Math.PI) * 0.25})`, padding: "8px 16px", borderRadius: 12,
      background: color, color: "#fff", fontFamily: ui, fontWeight: 800, fontSize: 24, boxShadow: `0 10px 30px rgba(14,110,118,0.35)`, zIndex: 40, whiteSpace: "nowrap" }}>{label}</div>
  );
};

// --- DMs ---------------------------------------------------------------------------------------------------------------
const DmShell: FC<{ x: number; y: number; w: number; h: number; inAt: number; outAt: number; children: ReactNode }> = ({ x, y, w, h, inAt, outAt, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - inAt, fps, config: { damping: 15, stiffness: 110 } });
  const away = prog(frame, outAt, outAt + 16, easeInOut);
  if (frame < inAt || away >= 1) return null;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: 18, overflow: "hidden", background: "#fff", fontFamily: ui, color: SL.text,
      boxShadow: "0 40px 120px rgba(15,18,34,0.30), 0 0 0 1px rgba(15,18,34,0.1)", opacity: Math.min(1, s * 1.5) * (1 - away),
      transform: `translateY(${(1 - s) * 140 + away * 260}px) scale(${0.92 + 0.08 * s})`, zIndex: 20 }}>
      <div style={{ height: 70, borderBottom: `1px solid ${SL.line}`, display: "flex", alignItems: "center", gap: 14, padding: "0 26px" }}>
        <Icon name="lock" size={24} color="#7c3aed" width={3} />
        <BrandAv />
        <span style={{ fontSize: 24, fontWeight: 800 }}>ReconAI</span><AppTag />
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 19, color: SL.muted }}>direct message to</span>
        <CtoAv size={40} />
        <span style={{ fontSize: 21, fontWeight: 700 }}>CTO</span>
      </div>
      {children}
    </div>
  );
};

const Btn: FC<{ w: number; label: string; done?: string; at: number; primary?: boolean }> = ({ w, label, done, at: clickAt, primary }) => {
  const frame = useCurrentFrame();
  const hover = primary ? prog(frame, clickAt - 14, clickAt - 5) : 0;
  const press = primary ? clickPress(frame, [clickAt]) : 0;
  const isDone = frame >= clickAt + 4;
  return (
    <div style={{ width: w, height: 54, borderRadius: 8, background: primary ? SL.green : "#fff", border: primary ? undefined : "1px solid #bbb", color: primary ? "#fff" : SL.text,
      fontSize: 21, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", opacity: !primary && isDone ? 0.35 : 1,
      transform: `scale(${1 + 0.04 * hover * (isDone ? 0 : 1) - 0.07 * press})`, boxShadow: primary ? `0 0 ${20 * hover}px rgba(0,122,90,0.6)` : undefined }}>
      {primary && isDone && done ? done : label}
    </div>
  );
};

// scene 8: confirm the count
const DM1 = { x: 300, y: 220, w: 920, h: 380 };
const COUNT_CLICK = L.s8 + 76;
const COUNT_BTN = { x: DM1.x + 40 + 130, y: DM1.y + 230 + 27 };
// scene 11: all clear
const DM2 = { x: 290, y: 190, w: 960, h: 480 };
const RELEASE_CLICK = L.s11 + 100;
const RELEASE_BTN = { x: DM2.x + 40 + 225, y: DM2.y + 380 + 27 };
const TOAST = { x: 520, y: 26 };
const ALL_CLEAR = ["3-way match", "Price", "Bank = vendor master", "No duplicate", "Sender verified"];

const Payout: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const coinT = interpolate(frame, [RELEASE_CLICK + 8, RELEASE_CLICK + 38], [0, 1], { ...clamp, easing: easeInOut });
  const to = { x: TOAST.x + 50, y: TOAST.y + 45 };
  const toast = spring({ frame: frame - (RELEASE_CLICK + 34), fps, config: { damping: 11, stiffness: 120 } });
  const away = prog(frame, L.s11 + 196, L.s11 + 212);
  return (
    <>
      {coinT > 0 && coinT < 1 && [0.12, 0.06, 0].map((lag, j) => {
        const t = Math.max(0, coinT - lag);
        const x = RELEASE_BTN.x + (to.x - RELEASE_BTN.x) * t, y = RELEASE_BTN.y + (to.y - RELEASE_BTN.y) * t - Math.sin(t * Math.PI) * 200;
        return <div key={j} style={{ position: "absolute", left: x - 32, top: y - 32, width: 64, height: 64, borderRadius: 32, background: C.green, border: "5px solid #fff",
          color: "#fff", fontFamily: ui, fontWeight: 800, fontSize: 34, display: "flex", alignItems: "center", justifyContent: "center", opacity: j === 2 ? 1 : 0.25 + j * 0.15,
          transform: `scale(${(1 + Math.sin(t * Math.PI) * 0.4) * (j === 2 ? 1 : 0.8)})`, boxShadow: "0 0 30px rgba(39,117,202,0.7)", zIndex: 45 }}>$</div>;
      })}
      <div style={{ ...glass, position: "absolute", left: TOAST.x, top: TOAST.y, display: "flex", alignItems: "center", gap: 18, padding: "16px 28px", zIndex: 44,
        background: "rgba(255,255,255,0.96)", borderRadius: 22, borderColor: "rgba(5,150,105,0.45)", fontFamily: ui, color: C.text,
        transform: `translateY(${(1 - toast) * -120}px)`, opacity: frame < RELEASE_CLICK + 34 ? 0 : Math.min(1, toast * 1.5) * (1 - away) }}>
        <Mark ok p={prog(frame, RELEASE_CLICK + 42, RELEASE_CLICK + 56)} size={54} color={C.green} />
        <div>
          <div style={{ fontSize: 30, fontWeight: 800 }}><Shiny at={RELEASE_CLICK + 40} every={80} color={C.text}>Paid</Shiny></div>
          <div style={{ fontSize: 18, color: C.muted }}>$71,050 · 2% early-pay discount kept</div>
        </div>
      </div>
    </>
  );
};

// --- the act -----------------------------------------------------------------------------------------------------------
export const Lifecycle: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // scene 3: fast-forward
  const ff = prog(frame, 0, 34, easeInOut);
  const win = spring({ frame: frame - 34, fps, config: { damping: 16, stiffness: 100 } });
  const panel = spring({ frame: frame - 52, fps, config: { damping: 15, stiffness: 100 } });
  const backdrop = Math.max(
    prog(frame, L.s8, L.s8 + 14) * (1 - prog(frame, L.s8 + 112, L.s8 + 126)),
    prog(frame, L.s11, L.s11 + 14) * (1 - prog(frame, L.s11 + 154, L.s11 + 170)));
  const vDim = prog(frame, at("whisper"), at("whisper") + 14) * (1 - prog(frame, L.s5, L.s5 + 14));
  const vPing = interpolate(frame, [at("diff"), at("diff") + 8, at("corrected")], [0, 1, 0], clamp);

  const vCursor = cursorPath(frame, [[L.s5 + 34, 1300, 1060], [ACCEPT_CLICK - 14, ACCEPT_ABS.x - 20, ACCEPT_ABS.y - 6],
    [ACCEPT_CLICK, ACCEPT_ABS.x - 30, ACCEPT_ABS.y - 4], [L.s5 + 110, ACCEPT_ABS.x + 600, ACCEPT_ABS.y + 80]]);
  const cCursor = cursorPath(frame, [[L.s8 + 30, 1300, 1060], [COUNT_CLICK - 14, COUNT_BTN.x - 20, COUNT_BTN.y - 6], [COUNT_CLICK, COUNT_BTN.x - 30, COUNT_BTN.y - 4],
    [L.s8 + 110, COUNT_BTN.x + 500, COUNT_BTN.y + 200], [L.s11 + 40, 1300, 1060], [RELEASE_CLICK - 14, RELEASE_BTN.x - 20, RELEASE_BTN.y - 6],
    [RELEASE_CLICK, RELEASE_BTN.x - 30, RELEASE_BTN.y - 4], [L.s11 + 150, RELEASE_BTN.x + 500, RELEASE_BTN.y + 160]]);
  const cOpacity = Math.max(interpolate(frame, [L.s8 + 30, L.s8 + 38, L.s8 + 96, L.s8 + 108], [0, 1, 1, 0], clamp),
    interpolate(frame, [L.s11 + 40, L.s11 + 48, L.s11 + 136, L.s11 + 148], [0, 1, 1, 0], clamp));

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      {/* scene 3: the 17.4 days blur away, fast-forward */}
      {frame < 60 && (
        <>
          <div style={{ position: "absolute", top: 90, width: "100%", textAlign: "center", fontSize: 190, fontWeight: 800, letterSpacing: -6, lineHeight: 1,
            opacity: 1 - ff, transform: `translateX(${ff * 900}px) scaleX(${1 + ff * 0.6})`, filter: `blur(${ff * 16}px)` }}>
            17.4<span style={{ fontSize: 90, letterSpacing: -2, marginLeft: 18 }}>days</span></div>
          <div style={{ position: "absolute", left: 960, top: 470, transform: "translate(-50%, -50%)", opacity: interpolate(frame, [2, 10, 30, 46], [0, 1, 1, 0], clamp), display: "flex" }}>
            {[0, 1].map((k) => <svg key={k} viewBox="0 0 60 60" width={130} height={130} style={{ marginLeft: k ? -40 : 0, filter: `drop-shadow(0 0 20px ${C.cyan})` }}>
              <polygon points="4,6 4,54 52,30" fill={C.cyan} opacity={0.6 + 0.4 * Math.sin(frame * 0.6 + k)} /></svg>)}
          </div>
          <svg width={1920} height={1080} style={{ position: "absolute", opacity: interpolate(frame, [2, 10, 30, 46], [0, 0.7, 0.7, 0], clamp) }}>
            {Array.from({ length: 14 }, (_, i) => {
              const y = 140 + i * 58, x = ((frame * 90 + i * 377) % 2400) - 240;
              return <line key={i} x1={x} y1={y} x2={x - 260} y2={y} stroke={i % 2 ? C.cyan : C.green} strokeWidth={3} strokeLinecap="round" opacity={0.6} />;
            })}
          </svg>
        </>
      )}

      {/* the vendor channel */}
      <div style={{ position: "absolute", left: WIN.x, top: WIN.y, width: WIN.w, height: WIN.h, opacity: Math.min(1, win * 1.5),
        transform: `translateY(${(1 - win) * 80}px) scale(${0.9 + 0.1 * win})`, boxShadow: "0 30px 90px rgba(15,18,34,0.20), 0 0 0 1px rgba(15,18,34,0.08)", borderRadius: 18,
        filter: backdrop ? `blur(${7 * backdrop}px) brightness(${1 - 0.12 * backdrop})` : undefined }}>
        <SlackWindow vDim={vDim} vPing={vPing} />
      </div>

      {/* right: the clock, the three documents, the match, the automation */}
      <div style={{ position: "absolute", inset: 0, transform: `translateX(${(1 - panel) * 600}px)`,
        opacity: Math.min(1, panel * 1.5) * (1 - 0.35 * backdrop) }}>
        <Clock />
        <Stepper />
        {DOCS.map((_, i) => <DocCard key={i} i={i} />)}
        <MatchStrip />
        <AutoGrid />
      </div>
      {DOCS.map((d, i) => {
        const t = prog(frame, d.at, d.at + FLY, easeInOut);
        return <Flight key={i} label={i === 2 ? "KM-INV-30118" : d.id} t={t} from={absAt(d.from[0], d.at, d.from[1], d.from[2])} to={{ x: RX + RW / 2, y: DOC_Y(i) + DOC_H / 2 }} />;
      })}
      <Flight label="KM-INV-30118-R" t={prog(frame, CORRECT_AT, CORRECT_AT + FLY, easeInOut)} from={absAt("corrected", CORRECT_AT, 200, 34)} to={{ x: RX + RW / 2, y: DOC_Y(2) + DOC_H / 2 }} />

      {/* scene 8: ReconAI asks the CTO to confirm the count */}
      <DmShell {...DM1} inAt={L.s8 + 6} outAt={L.s8 + 112}>
        <div style={{ position: "absolute", left: 40, top: 100, right: 40, fontSize: 24, lineHeight: 1.5 }}>
          🚚 <b>Vendor</b> says <b>PO-7001</b> shipped: 50 × HBM3E-12H-24G.
          <div style={{ color: SL.muted, fontSize: 20 }}>Nothing is received until someone at Helix counts it.</div>
        </div>
        <div style={{ position: "absolute", left: 40, top: 230, display: "flex", gap: 12 }}>
          <Btn w={260} label="All 50 received" done="✓ All 50 received" at={COUNT_CLICK} primary />
          <Btn w={260} label="Different quantity…" at={COUNT_CLICK} />
        </div>
        <div style={{ position: "absolute", left: 40, top: 310, fontSize: 21, color: SL.green, fontWeight: 700, opacity: prog(frame, COUNT_CLICK + 6, COUNT_CLICK + 16) }}>
          Recorded: 50 × HBM3E-12H-24G received on PO-7001.</div>
      </DmShell>

      {/* scene 11: all clear, release */}
      <DmShell {...DM2} inAt={L.s11 + 6} outAt={L.s11 + 154}>
        <div style={{ position: "absolute", left: 40, top: 96, display: "flex", alignItems: "center", gap: 20 }}>
          <Icon name="doc" size={70} color={SL.text} width={2.4} />
          <div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>🟢 Ready to approve: KM-INV-30118-R</div>
            <div style={{ fontSize: 46, fontWeight: 800, letterSpacing: -1 }}>$72,500</div>
          </div>
        </div>
        <div style={{ position: "absolute", left: 40, top: 230, right: 40, display: "flex", flexWrap: "wrap", gap: 10 }}>
          {ALL_CLEAR.map((c, i) => (
            <span key={c} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 14px", borderRadius: 16, background: "#e8f5ee", color: SL.green, fontSize: 19, fontWeight: 700,
              opacity: prog(frame, L.s11 + 20 + i * 6, L.s11 + 30 + i * 6) }}>✓ {c}</span>
          ))}
        </div>
        <div style={{ position: "absolute", left: 640, top: 100, display: "flex", alignItems: "center", gap: 12, opacity: prog(frame, L.s11 + 50, L.s11 + 64) }}>
          <Av bg="#e6f7fb" size={54}><Icon name="bot" size={38} color="#0891b2" /></Av>
          <Icon name="arrow" size={50} color="#999" width={3} />
          <Av bg={frame >= RELEASE_CLICK + 4 ? SL.green : "#f0e9fb"} size={54}><Icon name="user" size={38} color={frame >= RELEASE_CLICK + 4 ? "#fff" : "#7c3aed"} /></Av>
        </div>
        <div style={{ position: "absolute", left: 40, top: 380, display: "flex", gap: 12 }}>
          <Btn w={450} label="Approve & release payment" done="✓ Approved · paid" at={RELEASE_CLICK} primary />
          <Btn w={110} label="Hold" at={RELEASE_CLICK} />
        </div>
      </DmShell>
      <Payout />

      <Cursor x={vCursor.x} y={vCursor.y} press={clickPress(frame, [ACCEPT_CLICK])} sparks={[ACCEPT_CLICK]} label="Vendor" color="#5b6cff"
        opacity={interpolate(frame, [L.s5 + 34, L.s5 + 42, L.s5 + 86, L.s5 + 98], [0, 1, 1, 0], clamp)} />
      <Cursor x={cCursor.x} y={cCursor.y} press={clickPress(frame, [COUNT_CLICK, RELEASE_CLICK])} sparks={[COUNT_CLICK, RELEASE_CLICK]} label="CTO" color={C.teal} opacity={cOpacity} />

      {([
        [L.s3, L.s4, "ReconAI starts at the first quote.", 30],
        [L.s4, L.s4 + 115, "Only your side sees this.", 50],
        [L.s4 + 115, L.s5, "Best price and cash flow, before you sign.", 6],
        [L.s5, L.s6, "Signed. The vendor is onboarded automatically.", 30],
        [L.s6, L.s7, "The contract becomes document 1: the purchase order.", 10],
        [L.s7, L.s8, "The vendor tells ReconAI what shipped.", 8],
        [L.s8, L.s9, "You confirm the count. Document 2: the receipt.", 12],
        [L.s9, L.s9 + 120, "Document 3: the invoice, reconciled on arrival.", 10],
        [L.s9 + 120, L.s10, "A mismatch? The vendor is tagged, right here.", 8],
        [L.s10, L.s11, "Corrected. All three documents agree.", 20],
        [L.s11, L.s11 + 100, "All clear, in a private DM.", 12],
        [L.s11 + 100, LIFECYCLE_FRAMES, "One click to pay. The chat updates too.", 8],
      ] as [number, number, string, number][]).map(([from, to, text, start]) => (
        <Sequence key={text} from={from} durationInFrames={to - from}><Caption light text={text} duration={to - from} start={start} /></Sequence>
      ))}
    </AbsoluteFill>
  );
};
