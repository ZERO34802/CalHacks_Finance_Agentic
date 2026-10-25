import type { CSSProperties, FC, ReactNode } from "react";
import { AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, Cursor, Icon, type IconName, LogoTile, Mark } from "../components";
import { C, clamp, clickPress, cursorPath, easeInOut, glass, prog, ui } from "../theme";

// Scenes 6-11, the vendor relationship: one supplier (Kestrel) in one shared Slack channel, from first quote to paid.
// One continuous component so the channel keeps a single growing thread that scene 11 scrolls back through.
//  6  six scattered tools tangle around Kestrel, snap, and fly into #helix-kestrel
//  7  Kestrel quotes; ReconAI whispers the counter / aim / walk-away only to you
//  8  contract; Kestrel accepts and onboarding checks run; onboarded on probation
//  9  shipped (a claim) -> received (Helix's count) -> invoice PDF read and 3-way matched
//  10 the approver DM, out of the shared channel: approve & release, USDC payout
//  11 scroll back to the first quote and zoom out: the whole cycle is one thread
// Numbers are the product's own coach math (backend/slack/market.py) for case_01's SKU, HBM3E-12H-24G x 50:
// counter = market p25 $1,180, aim = median $1,300, walk away above p75 $1,460, so a $1,520 opening quote saves
// $11,000 at the aim. The deal lands at the MSA price $1,450 (data/world/contract_terms.json): 50 x $1,450 = the
// $72,500 bill KM-INV-30118 on PO-7001. The $1,520 opening quote is illustrative.
const S = { s6: 0, s7: 150, s8: 315, s9: 440, s10: 590, s11: 760 };
export const SLACK_ACT_FRAMES = 910;

const WIN = { x: 260, y: 50, w: 1400, h: 790 };
const HEAD = 90;
const PAD = 24;
const GAP = 22;
const AV_X = 120;      // avatar column, window x
const BODY_X = 204;    // message body, window x

// --- the thread: appear frame + height of each message -------------------------------------------------------------
const ITEMS = [
  { key: "quote", at: S.s7 + 8, h: 112 },
  { key: "whisper", at: S.s7 + 58, h: 236 },
  { key: "contract", at: S.s8 + 5, h: 204 },
  { key: "onboard", at: S.s8 + 66, h: 186 },
  { key: "shipped", at: S.s9 + 6, h: 104 },
  { key: "received", at: S.s9 + 38, h: 104 },
  { key: "invoice", at: S.s9 + 70, h: 214 },
] as const;
type Key = (typeof ITEMS)[number]["key"];

const grow = (i: number, f: number) => prog(f, ITEMS[i].at, ITEMS[i].at + 14, easeInOut);
const topOf = (i: number, f: number) => PAD + ITEMS.slice(0, i).reduce((y, it, j) => y + (it.h + GAP) * grow(j, f), 0);
const contentH = (f: number) => topOf(ITEMS.length, f) + PAD;
const naturalScroll = (f: number) => Math.max(0, contentH(f) - (WIN.h - HEAD));
const SCROLL_BACK = [S.s11 + 22, S.s11 + 62];
const scrollAt = (f: number) => f < SCROLL_BACK[0] ? naturalScroll(f)
  : interpolate(f, SCROLL_BACK, [naturalScroll(SCROLL_BACK[0]), 0], { ...clamp, easing: easeInOut });
// a message-local point -> absolute frame coordinates
const absAt = (i: number, f: number, x: number, y: number) => ({ x: WIN.x + x, y: WIN.y + HEAD + topOf(i, f) - scrollAt(f) + y });

// --- shared bits -----------------------------------------------------------------------------------------------------
const Avatar: FC<{ bg: string; children: ReactNode; size?: number; dim?: number }> = ({ bg, children, size = 64, dim = 0 }) => (
  <div style={{ position: "relative", width: size, height: size, borderRadius: size * 0.22, background: bg, display: "flex",
    alignItems: "center", justifyContent: "center", flexShrink: 0, opacity: 1 - 0.7 * dim }}>
    {children}
  </div>
);
const KAv: FC<{ size?: number; dim?: number }> = ({ size = 64, dim }) => (
  <Avatar bg="#5b6cff" size={size} dim={dim}><span style={{ color: "#fff", fontWeight: 800, fontSize: size * 0.45 }}>K</span></Avatar>
);
const BotAv = () => <Avatar bg="#fff"><LogoTile size={56} /></Avatar>;
const HAv: FC<{ size?: number }> = ({ size = 64 }) => (
  <Avatar bg={C.teal} size={size}><span style={{ color: "#fff", fontWeight: 800, fontSize: size * 0.45 }}>H</span></Avatar>
);
const AAv = () => <Avatar bg="#1f9d74"><span style={{ color: "#fff", fontWeight: 800, fontSize: 28 }}>A</span></Avatar>;

const Bubble: FC<{ children: ReactNode; style?: CSSProperties }> = ({ children, style }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 16, background: "#2b2e35", borderRadius: "6px 24px 24px 24px", padding: "16px 28px", ...style }}>
    {children}
  </div>
);
const Chip: FC<{ color: string; children: ReactNode; p?: number }> = ({ color, children, p = 1 }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 14px", borderRadius: 18, fontSize: 20, fontWeight: 700,
    background: `${color}26`, color, border: `1px solid ${color}66`, opacity: p, transform: `scale(${0.7 + 0.3 * p})` }}>{children}</span>
);

// --- messages ----------------------------------------------------------------------------------------------------------
const Msg: FC<{ i: number; avatar: ReactNode; name: string; children: ReactNode }> = ({ i, avatar, name, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - ITEMS[i].at, fps, config: { damping: 15, stiffness: 120 } });
  if (frame < ITEMS[i].at) return null;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: topOf(i, frame), height: ITEMS[i].h, opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 34}px)` }}>
      <div style={{ position: "absolute", left: AV_X, top: 0 }}>{avatar}</div>
      <div style={{ position: "absolute", left: BODY_X, top: 0, fontSize: 19, color: C.muted, fontWeight: 600 }}>{name}</div>
      <div style={{ position: "absolute", left: BODY_X, top: 30 }}>{children}</div>
    </div>
  );
};

const Typing: FC = () => {
  const frame = useCurrentFrame();
  return (
    <Bubble style={{ padding: "24px 30px", gap: 10 }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ width: 14, height: 14, borderRadius: 7, background: "#aab",
          transform: `translateY(${Math.sin(frame * 0.35 - i * 0.9) * -6}px)`, opacity: 0.5 + 0.5 * Math.max(0, Math.sin(frame * 0.35 - i * 0.9)) }} />
      ))}
    </Bubble>
  );
};

const QUOTE_AT = S.s7 + 32;
const Quote: FC = () => {
  const frame = useCurrentFrame();
  const land = interpolate(frame, [S.s11 + 64, S.s11 + 72, S.s11 + 96], [0, 1, 0], clamp);   // scene 11 lands here
  if (frame < QUOTE_AT) return <Typing />;
  return (
    <Bubble style={{ boxShadow: `0 0 ${40 * land}px rgba(34,211,238,${0.8 * land})`, border: `2px solid rgba(34,211,238,${land})` }}>
      <Icon name="tag" size={44} color="#fff" />
      <span style={{ fontSize: 46, fontWeight: 800 }}>$1,520</span>
      <span style={{ fontSize: 22, color: C.muted }}>/ stack · 50</span>
    </Bubble>
  );
};

// price gauge: the coach's numbers on one line
const G = { w: 840, lo: 1150, hi: 1560 };
const gx = (v: number) => ((v - G.lo) / (G.hi - G.lo)) * G.w;
const PINS = [
  { v: 1520, label: "their quote", color: C.red, at: S.s7 + 74 },
  { v: 1460, label: "walk away", color: C.amber, at: S.s7 + 86 },
  { v: 1300, label: "aim", color: C.green, at: S.s7 + 98 },
  { v: 1180, label: "counter", color: C.cyan, at: S.s7 + 110 },
];
const SAVE_AT = S.s7 + 122;

const Whisper: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zone = prog(frame, PINS[1].at, PINS[1].at + 26);
  const save = interpolate(frame, [SAVE_AT, SAVE_AT + 30], [0, 11000], { ...clamp, easing: easeInOut });
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
      <div style={{ background: "rgba(167,139,250,0.08)", border: "2px dashed rgba(167,139,250,0.6)", borderRadius: "6px 24px 24px 24px", padding: "12px 30px 14px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: C.violet, fontSize: 19, fontWeight: 600 }}>
          <Icon name="eyeOff" size={26} color={C.violet} width={3} /> only visible to you
        </div>
        <div style={{ position: "relative", width: G.w, height: 124, marginTop: 6 }}>
          <div style={{ position: "absolute", top: 53, left: 0, width: G.w, height: 10, borderRadius: 5, background: "rgba(255,255,255,0.12)" }} />
          {/* the deal zone: anything up to the walk-away */}
          <div style={{ position: "absolute", top: 53, left: 0, width: gx(1460) * zone, height: 10, borderRadius: 5, background: C.green, boxShadow: `0 0 14px ${C.green}` }} />
          {PINS.map((p) => {
            const s = spring({ frame: frame - p.at, fps, config: { damping: 10, stiffness: 150 } });
            return (
              <div key={p.v} style={{ position: "absolute", left: gx(p.v), top: 0, transform: `translateX(-50%) translateY(${(1 - s) * -40}px)`,
                opacity: Math.min(1, s * 2), display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ fontSize: 27, fontWeight: 800 }}>${p.v.toLocaleString("en-US")}</div>
                <div style={{ width: 22, height: 22, borderRadius: 11, background: p.color, border: "4px solid #1a1d21", marginTop: 14, boxShadow: `0 0 14px ${p.color}` }} />
                <div style={{ fontSize: 18, color: C.muted, marginTop: 6 }}>{p.label}</div>
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ padding: "12px 22px", borderRadius: 22, background: C.green, color: "#05140c", textAlign: "center",
        boxShadow: "0 0 30px rgba(62,224,143,0.5)", opacity: prog(frame, SAVE_AT, SAVE_AT + 10), transform: `scale(${0.7 + 0.3 * spring({ frame: frame - SAVE_AT, fps, config: { damping: 9, stiffness: 160 } })})` }}>
        <div style={{ fontSize: 34, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>+${Math.round(save).toLocaleString("en-US")}</div>
        <div style={{ fontSize: 17, fontWeight: 700, opacity: 0.75 }}>at the aim</div>
      </div>
    </div>
  );
};

const ACCEPT_CLICK = S.s8 + 56;
const ACCEPT_BTN = { x: 30, y: 100, w: 360, h: 54 };   // inside the contract card
const Contract: FC = () => {
  const frame = useCurrentFrame();
  const hover = prog(frame, ACCEPT_CLICK - 12, ACCEPT_CLICK - 4);
  const press = clickPress(frame, [ACCEPT_CLICK]);
  const done = frame >= ACCEPT_CLICK + 4;
  return (
    <div style={{ position: "relative", width: 900, height: 172, borderRadius: 20, background: "#22252b", border: "1px solid rgba(255,255,255,0.1)", borderLeft: `8px solid ${done ? C.green : C.violet}` }}>
      <div style={{ position: "absolute", left: 30, top: 22, display: "flex", alignItems: "center", gap: 14 }}>
        <Icon name="doc" size={44} color="#fff" />
        <span style={{ fontSize: 28, fontWeight: 800 }}>Contract</span>
        <Chip color={C.cyan}>HBM3E × 50</Chip>
        <Chip color={C.green}>$1,450 / stack</Chip>
        <Chip color={C.muted}>net 30</Chip>
      </div>
      <div style={{
        position: "absolute", left: ACCEPT_BTN.x, top: ACCEPT_BTN.y, width: ACCEPT_BTN.w, height: ACCEPT_BTN.h, borderRadius: 12,
        background: done ? C.green : C.violet, color: done ? "#05140c" : "#140a2b", fontSize: 23, fontWeight: 800,
        display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
        transform: `scale(${1 + 0.04 * hover * (done ? 0 : 1) - 0.07 * press})`, boxShadow: `0 0 ${8 + 26 * hover}px ${done ? "rgba(62,224,143,0.6)" : "rgba(167,139,250,0.7)"}`,
      }}>
        {done ? "✓ Accepted" : "Accept & start onboarding"}
      </div>
    </div>
  );
};

const CHECKS: { icon: IconName; label: string }[] = [
  { icon: "shield", label: "Sanctions" }, { icon: "bank", label: "Bank" }, { icon: "globe", label: "Domain" }, { icon: "doc", label: "Tax form" },
];
const ONBOARD_AT = ITEMS[3].at;
const Onboard: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const badge = spring({ frame: frame - (ONBOARD_AT + 46), fps, config: { damping: 9, stiffness: 150 } });
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      {CHECKS.map((c, i) => {
        const t = ONBOARD_AT + 8 + i * 8;
        return (
          <div key={c.label} style={{ ...glass, position: "relative", width: 150, height: 132, borderRadius: 18, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 8, opacity: prog(frame, t - 6, t + 4), transform: `translateY(${(1 - prog(frame, t - 6, t + 4)) * 20}px)` }}>
            <Icon name={c.icon} size={48} />
            <span style={{ fontSize: 19, color: "#cfd2da" }}>{c.label}</span>
            <div style={{ position: "absolute", top: -12, right: -12 }}><Mark ok p={prog(frame, t + 4, t + 16)} size={38} /></div>
          </div>
        );
      })}
      <div style={{ marginLeft: 14, padding: "14px 24px", borderRadius: 24, background: "rgba(62,224,143,0.15)", border: `2px solid ${C.green}`,
        color: C.green, fontSize: 26, fontWeight: 800, boxShadow: `0 0 ${30 * badge}px rgba(62,224,143,0.45)`,
        opacity: frame < ONBOARD_AT + 46 ? 0 : 1, transform: `scale(${badge})` }}>
        Onboarded · <span style={{ color: C.amber }}>probation</span>
      </div>
    </div>
  );
};

const Shipped: FC = () => {
  const frame = useCurrentFrame();
  const t = ITEMS[4].at;
  return (
    <Bubble>
      <div style={{ transform: `translateX(${(1 - prog(frame, t, t + 16)) * -40}px)` }}><Icon name="truck" size={44} color="#fff" /></div>
      <span style={{ fontSize: 30, fontWeight: 800 }}>shipped</span>
      <span style={{ fontSize: 24, color: C.muted }}>PO-7001 · 50</span>
      <Chip color={C.amber} p={prog(frame, t + 12, t + 22)}>claim</Chip>
    </Bubble>
  );
};

const Received: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = ITEMS[5].at;
  const bounce = spring({ frame: frame - t, fps, config: { damping: 8, stiffness: 170 } });
  return (
    <Bubble>
      <div style={{ transform: `translateY(${(1 - bounce) * -24}px)` }}><Icon name="box" size={44} color="#fff" /></div>
      <span style={{ fontSize: 30, fontWeight: 800 }}>received</span>
      <span style={{ fontSize: 24, color: C.muted }}>50 counted</span>
      <Mark ok p={prog(frame, t + 10, t + 22)} size={34} />
    </Bubble>
  );
};

const INV_AT = ITEMS[6].at;
const Invoice: FC = () => {
  const frame = useCurrentFrame();
  const scan = prog(frame, INV_AT + 12, INV_AT + 40, easeInOut);
  const reading = frame >= INV_AT + 10 && frame < INV_AT + 44 ? 1 : 0;
  const parts: [IconName, string][] = [["doc", "PO"], ["box", "Received"], ["doc", "Bill"]];
  return (
    <div>
      <div style={{ position: "relative", width: 520, height: 88, borderRadius: 16, background: "#22252b", overflow: "hidden",
        border: `2px solid ${reading ? C.cyan : "rgba(255,255,255,0.1)"}`, boxShadow: reading ? `0 0 ${24 + 12 * Math.sin(frame * 0.5)}px rgba(34,211,238,0.55)` : undefined,
        display: "flex", alignItems: "center", gap: 16, padding: "0 22px", boxSizing: "border-box" }}>
        <div style={{ width: 52, height: 60, borderRadius: 8, background: C.red, color: "#fff", fontSize: 15, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>PDF</div>
        <span style={{ fontSize: 27, fontWeight: 700 }}>KM-INV-30118.pdf</span>
        {/* ReconAI reading: a cyan line sweeps down the file */}
        <div style={{ position: "absolute", left: 0, right: 0, top: scan * 88 - 3, height: 6, background: C.cyan, opacity: reading,
          boxShadow: `0 0 18px ${C.cyan}` }} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
        {parts.map(([icon, label], i) => {
          const t = INV_AT + 44 + i * 8;
          return (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {i > 0 && <span style={{ fontSize: 32, fontWeight: 700, opacity: prog(frame, t - 4, t + 4) }}>=</span>}
              <div style={{ ...glass, display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderRadius: 16,
                opacity: prog(frame, t - 6, t + 4), borderColor: frame >= t + 12 ? `${C.green}99` : undefined }}>
                <Icon name={icon} size={30} />
                <span style={{ fontSize: 20 }}>{label}</span>
                <Mark ok p={prog(frame, t + 8, t + 18)} size={30} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const RENDER: Record<Key, { avatar: ReactNode; name: string; body: ReactNode }> = {
  quote: { avatar: <KAv />, name: "Kestrel", body: <Quote /> },
  whisper: { avatar: <BotAv />, name: "ReconAI", body: <Whisper /> },
  contract: { avatar: <BotAv />, name: "ReconAI", body: <Contract /> },
  onboard: { avatar: <BotAv />, name: "ReconAI", body: <Onboard /> },
  shipped: { avatar: <KAv />, name: "Kestrel", body: <Shipped /> },
  received: { avatar: <AAv />, name: "Ana Lee · Helix", body: <Received /> },
  invoice: { avatar: <KAv />, name: "Kestrel", body: <Invoice /> },
};

// --- scene 6: the status quo, six tools tangled around one supplier ------------------------------------------------
const C6 = { x: 960, y: 440 };
const TOOLS: { icon: IconName; label: string }[] = [
  { icon: "mail", label: "Re: Re: Re: pricing" }, { icon: "doc", label: "contract.pdf" }, { icon: "sheet", label: "receiving.xlsx" },
  { icon: "window", label: "ERP" }, { icon: "shield", label: "Approval portal" }, { icon: "chat", label: "Chat" },
];
const toolPos = (i: number) => {
  const a = -Math.PI / 2 + (i * Math.PI * 2) / TOOLS.length;
  return { x: C6.x + Math.cos(a) * 560, y: C6.y + Math.sin(a) * 300 };
};
// tangled strings: every tool to two others, with big crossing control points
const STRINGS = TOOLS.flatMap((_, i) => [2, 3].map((k) => {
  const a = toolPos(i), b = toolPos((i + k) % TOOLS.length);
  const c1 = { x: C6.x + (b.y - C6.y) * 0.9, y: C6.y - (b.x - C6.x) * 0.5 };
  const c2 = { x: C6.x - (a.y - C6.y) * 0.9, y: C6.y + (a.x - C6.x) * 0.5 };
  return { d: `M ${a.x} ${a.y} C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${b.x} ${b.y}`, at: 34 + i * 4 + k * 3 };
}));
const SNAP = 92;
const FLY = 100;

const Tangle: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = spring({ frame, fps, config: { damping: 13, stiffness: 120 } });
  const snap = prog(frame, SNAP, SNAP + 10);
  const shake = frame >= SNAP && frame < SNAP + 10 ? Math.sin((frame - SNAP) * 2.6) * (SNAP + 10 - frame) : 0;
  const q = spring({ frame: frame - 70, fps, config: { damping: 9, stiffness: 170 } });
  const out = prog(frame, FLY + 4, FLY + 26, easeInOut);
  return (
    <AbsoluteFill style={{ transform: `translateX(${shake}px)` }}>
      <svg width={1920} height={1080} style={{ position: "absolute", opacity: 1 - snap }}>
        {STRINGS.map((s, i) => (
          <path key={i} d={s.d} fill="none" stroke={i % 2 ? "rgba(255,84,112,0.55)" : "rgba(251,191,36,0.45)"} strokeWidth={3}
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - prog(frame, s.at, s.at + 30, easeInOut)} />
        ))}
      </svg>
      {/* snap flash */}
      <div style={{ position: "absolute", left: C6.x - 260, top: C6.y - 260, width: 520, height: 520, borderRadius: 260,
        background: "radial-gradient(circle, rgba(255,255,255,0.5), transparent 65%)", opacity: interpolate(frame, [SNAP, SNAP + 3, SNAP + 14], [0, 1, 0], clamp) }} />

      {/* Kestrel in the middle, with a "?" over a price tag */}
      <div style={{ position: "absolute", left: C6.x, top: C6.y, transform: `translate(-50%, -50%) scale(${(0.5 + 0.5 * k) * (1 - 0.6 * out)})`, opacity: 1 - out,
        filter: "drop-shadow(0 0 40px rgba(91,108,255,0.6))" }}>
        <KAv size={150} />
      </div>
      <div style={{ position: "absolute", left: C6.x + 90, top: C6.y - 150, transform: `scale(${q * (1 - snap)})` }}>
        <div style={{ ...glass, width: 84, height: 84, borderRadius: 22, display: "flex", alignItems: "center", justifyContent: "center" }}><Icon name="tag" size={46} /></div>
        <div style={{ position: "absolute", top: -18, right: -18, width: 46, height: 46, borderRadius: 23, background: C.red, color: "#fff",
          fontWeight: 800, fontSize: 30, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 20px ${C.red}` }}>?</div>
      </div>

      {TOOLS.map((t, i) => {
        const p = toolPos(i);
        const s = spring({ frame: frame - 8 - i * 6, fps, config: { damping: 12, stiffness: 130 } });
        const fly = prog(frame, FLY + i * 2, FLY + 24 + i * 2, easeInOut);
        const x = p.x + (C6.x - p.x) * fly;
        const y = p.y + (C6.y - p.y) * fly;
        const jitter = (1 - snap) * Math.sin(frame * 0.2 + i) * 4;
        return (
          <div key={t.label} style={{ ...glass, position: "absolute", left: x, top: y + jitter, transform: `translate(-50%, -50%) scale(${s * (1 - 0.8 * fly)})`,
            opacity: Math.min(1, s * 1.5) * (1 - fly), borderRadius: 22, padding: "18px 24px", display: "flex", alignItems: "center", gap: 14, background: "rgba(20,22,30,0.75)" }}>
            <Icon name={t.icon} size={44} />
            <span style={{ fontSize: 24, fontWeight: 600, whiteSpace: "nowrap" }}>{t.label}</span>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// --- scene 10: the approver DM ---------------------------------------------------------------------------------------
const DM = { x: 440, y: 180, w: 1040, h: 470 };
const CARD = { x: 40, y: 110, w: 960, h: 300 };
const BTN = { x: 40, y: 200, w: 500, h: 68 };   // card-relative
const BTN_ABS = { x: DM.x + CARD.x + BTN.x + BTN.w / 2, y: DM.y + CARD.y + BTN.y + BTN.h / 2 };
const DM_IN = S.s10 + 6;
const APPROVE_CLICK = S.s10 + 104;
const TOAST = { right: 90, top: 60 };

const DmWindow: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - DM_IN, fps, config: { damping: 15, stiffness: 110 } });
  const away = prog(frame, S.s11, S.s11 + 20, easeInOut);
  const hover = prog(frame, APPROVE_CLICK - 16, APPROVE_CLICK - 6);
  const press = clickPress(frame, [APPROVE_CLICK]);
  const done = frame >= APPROVE_CLICK + 4;
  const arrow = prog(frame, DM_IN + 34, DM_IN + 52);
  if (frame < DM_IN || away >= 1) return null;
  return (
    <div style={{ position: "absolute", left: DM.x, top: DM.y, width: DM.w, height: DM.h, borderRadius: 26, background: "#1a1d21",
      border: "1px solid rgba(167,139,250,0.4)", boxShadow: "0 50px 140px rgba(0,0,0,0.75), 0 0 60px rgba(167,139,250,0.2)",
      opacity: Math.min(1, s * 1.5) * (1 - away), transform: `translateY(${(1 - s) * 140 + away * 260}px) scale(${0.9 + 0.1 * s})`, fontFamily: ui, color: C.text, zIndex: 20 }}>
      {/* DM header: private, not the shared channel */}
      <div style={{ height: 82, borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", alignItems: "center", gap: 16, padding: "0 32px" }}>
        <div style={{ width: 46, height: 46, borderRadius: 23, background: "rgba(167,139,250,0.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon name="lock" size={28} color={C.violet} width={3} />
        </div>
        <Avatar bg="#fff" size={48}><LogoTile size={42} /></Avatar>
        <Icon name="arrow" size={34} color="#777" />
        <Avatar bg="rgba(167,139,250,0.25)" size={48}><Icon name="user" size={32} color={C.violet} /></Avatar>
        <span style={{ fontSize: 26, fontWeight: 700 }}>M. Chen</span>
        <span style={{ fontSize: 20, color: C.muted }}>Controller</span>
      </div>
      <div style={{ position: "absolute", left: CARD.x, top: CARD.y, width: CARD.w, height: CARD.h, borderRadius: 22, background: "#22252b",
        border: "1px solid rgba(255,255,255,0.1)", borderLeft: `8px solid ${done ? C.green : C.violet}` }}>
        <div style={{ position: "absolute", left: 36, top: 34, display: "flex", alignItems: "center", gap: 22 }}>
          <Icon name="doc" size={92} color="#fff" width={2.4} />
          <div>
            <div style={{ fontSize: 52, fontWeight: 800, letterSpacing: -1 }}>$72,500</div>
            <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
              {[0, 1, 2].map((i) => <Mark key={i} ok p={prog(frame, DM_IN + 18 + i * 6, DM_IN + 30 + i * 6)} size={38} />)}
            </div>
          </div>
        </div>
        {/* agent prepared it -> you release it */}
        <div style={{ position: "absolute", left: 560, top: 52, display: "flex", alignItems: "center", gap: 14 }}>
          <Avatar bg="rgba(34,211,238,0.15)"><Icon name="bot" size={44} color={C.cyan} /></Avatar>
          <div style={{ width: 110, overflow: "hidden", opacity: arrow }}>
            <div style={{ transform: `translateX(${(arrow - 1) * 80}px)` }}><Icon name="arrow" size={70} color="#888" width={3} /></div>
          </div>
          <Avatar bg={done ? C.green : "rgba(167,139,250,0.18)"}><Icon name="user" size={44} color={done ? "#05140c" : C.violet} /></Avatar>
        </div>
        <div style={{
          position: "absolute", left: BTN.x, top: BTN.y, width: BTN.w, height: BTN.h, borderRadius: 14, background: done ? C.green : C.violet,
          color: done ? "#05140c" : "#140a2b", fontSize: 25, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
          transform: `scale(${1 + 0.04 * hover * (done ? 0 : 1) - 0.07 * press})`, boxShadow: `0 0 ${10 + 30 * hover}px ${done ? "rgba(62,224,143,0.6)" : "rgba(167,139,250,0.7)"}`,
        }}>
          {done ? "✓ Approved · released" : "Approve & release via Coinbase"}
        </div>
      </div>
    </div>
  );
};

const Payout: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const coinT = interpolate(frame, [APPROVE_CLICK + 8, APPROVE_CLICK + 40], [0, 1], { ...clamp, easing: easeInOut });
  const toastAt = { x: 1920 - TOAST.right - 400, y: TOAST.top + 50 };
  const toast = spring({ frame: frame - (APPROVE_CLICK + 36), fps, config: { damping: 11, stiffness: 120 } });
  const away = prog(frame, S.s11, S.s11 + 16);
  const at = (t: number) => ({
    x: interpolate(t, [0, 1], [BTN_ABS.x, toastAt.x]),
    y: interpolate(t, [0, 1], [BTN_ABS.y, toastAt.y]) - Math.sin(t * Math.PI) * 200,
  });
  return (
    <>
      {coinT > 0 && coinT < 1 && [0.12, 0.06, 0].map((lag, j) => {
        const t = Math.max(0, coinT - lag);
        const p = at(t);
        return (
          <div key={j} style={{ position: "absolute", left: p.x - 34, top: p.y - 34, width: 68, height: 68, borderRadius: 34, background: "#2775ca",
            border: "5px solid #fff", color: "#fff", fontFamily: ui, fontWeight: 800, fontSize: 36, display: "flex", alignItems: "center", justifyContent: "center",
            opacity: j === 2 ? 1 : 0.25 + j * 0.15, transform: `scale(${(1 + Math.sin(t * Math.PI) * 0.4) * (j === 2 ? 1 : 0.8)})`,
            boxShadow: "0 0 30px rgba(39,117,202,0.7)", zIndex: 40 }}>$</div>
        );
      })}
      <div style={{
        ...glass, position: "absolute", right: TOAST.right, top: TOAST.top, display: "flex", alignItems: "center", gap: 20, padding: "22px 34px",
        background: "rgba(24,27,36,0.9)", borderRadius: 22, zIndex: 30, borderColor: "rgba(62,224,143,0.5)", fontFamily: ui, color: C.text,
        transform: `translate(${(1 - toast) * 300}px, ${(1 - toast) * -120}px)`, opacity: frame < APPROVE_CLICK + 36 ? 0 : Math.min(1, toast * 1.5) * (1 - away),
      }}>
        <Mark ok p={prog(frame, APPROVE_CLICK + 44, APPROVE_CLICK + 60)} size={64} />
        <div>
          <div style={{ fontSize: 36, fontWeight: 800 }}>Paid · USDC</div>
          <div style={{ fontSize: 20, color: C.muted }}>testnet</div>
        </div>
      </div>
    </>
  );
};

// --- the act ---------------------------------------------------------------------------------------------------------
const CONTRACT_I = 2;
const ACCEPT_ABS = absAt(CONTRACT_I, ACCEPT_CLICK, BODY_X + ACCEPT_BTN.x + ACCEPT_BTN.w / 2, 30 + ACCEPT_BTN.y + ACCEPT_BTN.h / 2);
const ZOOM = [S.s11 + 92, S.s11 + 124];
const FULL_H = HEAD + PAD + ITEMS.reduce((y, it) => y + it.h + GAP, 0) + PAD;

export const SlackAct: FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const win = spring({ frame: frame - (FLY + 6), fps, config: { damping: 16, stiffness: 100 } });
  const scroll = scrollAt(frame);
  const speed = Math.abs(scrollAt(frame) - scrollAt(frame - 1));
  const backdrop = prog(frame, S.s10, S.s10 + 18) * (1 - prog(frame, S.s11 + 4, S.s11 + 22));   // channel blurs behind the DM
  const kDim = prog(frame, ITEMS[1].at, ITEMS[1].at + 16) * (1 - prog(frame, S.s8, S.s8 + 16));  // Kestrel can't see the whisper
  const z = prog(frame, ZOOM[0], ZOOM[1], easeInOut);
  const h = interpolate(z, [0, 1], [WIN.h, FULL_H]);
  const scale = interpolate(z, [0, 1], [1, 0.6]);
  const kCursor = cursorPath(frame, [[S.s8 + 18, 1840, 1060], [ACCEPT_CLICK - 14, ACCEPT_ABS.x - 30, ACCEPT_ABS.y - 6], [ACCEPT_CLICK, ACCEPT_ABS.x - 40, ACCEPT_ABS.y - 4], [S.s8 + 110, ACCEPT_ABS.x + 160, ACCEPT_ABS.y + 260]]);
  const mCursor = cursorPath(frame, [[S.s10 + 50, 1840, 1060], [APPROVE_CLICK - 18, BTN_ABS.x - 20, BTN_ABS.y - 6], [APPROVE_CLICK, BTN_ABS.x - 30, BTN_ABS.y - 2], [S.s11, BTN_ABS.x + 60, BTN_ABS.y + 120]]);

  return (
    <AbsoluteFill style={{ fontFamily: ui, color: C.text }}>
      {frame < FLY + 40 && <Tangle />}

      {/* the shared channel */}
      <div style={{
        position: "absolute", left: WIN.x, top: WIN.y - 12 * z, width: WIN.w, height: h, borderRadius: 26, overflow: "hidden",
        background: "#1a1d21", border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
        opacity: Math.min(1, win * 1.5), transformOrigin: "50% 0", transform: `scale(${(0.85 + 0.15 * win) * scale})`,
        filter: backdrop ? `blur(${7 * backdrop}px) brightness(${1 - 0.45 * backdrop})` : undefined,
      }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 92, background: "#121418", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 26, gap: 18 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>{["#ff5f57", "#febc2e", "#28c840"].map((d) => <div key={d} style={{ width: 12, height: 12, borderRadius: 6, background: d }} />)}</div>
          {[C.violet, "#2b2e35", "#2b2e35", "#2b2e35"].map((b, i) => <div key={i} style={{ width: 50, height: 50, borderRadius: 12, background: b }} />)}
        </div>
        <div style={{ position: "absolute", left: 92, right: 0, top: 0, height: HEAD, borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", alignItems: "center", gap: 14, padding: "0 32px", background: "#1a1d21", zIndex: 2 }}>
          <span style={{ fontSize: 36, fontWeight: 300, color: "#777" }}>#</span>
          <span style={{ fontSize: 30, fontWeight: 800 }}>helix-kestrel</span>
          <div style={{ flex: 1 }} />
          <HAv size={52} />
          <div style={{ position: "relative" }}>
            <KAv size={52} dim={kDim} />
            <div style={{ position: "absolute", right: -10, bottom: -10, width: 30, height: 30, borderRadius: 15, background: "#1a1d21", display: "flex",
              alignItems: "center", justifyContent: "center", opacity: kDim }}><Icon name="eyeOff" size={22} color={C.violet} width={3.4} /></div>
          </div>
        </div>
        <div style={{ position: "absolute", left: 92, right: 0, top: HEAD, height: 4000, transform: `translateY(${-scroll}px)`,
          filter: frame >= SCROLL_BACK[0] && speed > 2 ? `blur(${Math.min(9, speed * 0.18)}px)` : undefined }}>
          <div style={{ position: "absolute", left: -92, right: 0, top: 0, bottom: 0 }}>
            {ITEMS.map((it, i) => <Msg key={it.key} i={i} avatar={RENDER[it.key].avatar} name={RENDER[it.key].name}>{RENDER[it.key].body}</Msg>)}
          </div>
        </div>
      </div>

      <DmWindow />
      <Payout />
      <Cursor x={kCursor.x} y={kCursor.y} press={clickPress(frame, [ACCEPT_CLICK])} label="Kestrel" color="#5b6cff"
        opacity={interpolate(frame, [S.s8 + 18, S.s8 + 26, S.s8 + 100, S.s8 + 110], [0, 1, 1, 0], clamp)} />
      <Cursor x={mCursor.x} y={mCursor.y} press={clickPress(frame, [APPROVE_CLICK])} label="M. Chen"
        opacity={interpolate(frame, [S.s10 + 50, S.s10 + 58, S.s11 - 6, S.s11 + 4], [0, 1, 1, 0], clamp)} />

      <Sequence durationInFrames={84}><Caption text="One supplier. Six tools." duration={84} start={10} /></Sequence>
      <Sequence from={84} durationInFrames={S.s7 - 84}><Caption text="One supplier. One channel." duration={S.s7 - 84} start={18} /></Sequence>
      <Sequence from={S.s7} durationInFrames={S.s8 - S.s7}><Caption text="Only you see this." duration={S.s8 - S.s7} start={60} /></Sequence>
      <Sequence from={S.s8} durationInFrames={S.s9 - S.s8}><Caption text="Signed and checked." duration={S.s9 - S.s8} start={10} /></Sequence>
      <Sequence from={S.s9} durationInFrames={S.s10 - S.s9}><Caption text="Shipped. Received. Matched." duration={S.s10 - S.s9} start={10} /></Sequence>
      <Sequence from={S.s10} durationInFrames={S.s11 - S.s10}><Caption text="Money stays on your side." duration={S.s11 - S.s10} start={14} /></Sequence>
      <Sequence from={S.s11}><Caption text="Quote to paid. One chat." duration={SLACK_ACT_FRAMES - S.s11} start={20} /></Sequence>
    </AbsoluteFill>
  );
};
