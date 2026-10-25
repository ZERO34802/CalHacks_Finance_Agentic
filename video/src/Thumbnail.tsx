import type { CSSProperties, FC, ReactNode } from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { BrandLogo, Chevrons, Mark } from "./components";
import { SL } from "./scenes/slackParts";
import { mono, ui, W } from "./theme";

// Devpost thumbnail (3:2, 2400 x 1600): the real ReconAI dashboard on a laptop, and the same flow on a phone in Slack.
// Render: npx remotion still src/index.ts Thumbnail ../docs/assets/devpost-thumbnail.png
// The dashboard is a capture of the running app (public/ui/home.png, 1600 x 1000 at 2x). The Slack messages follow the
// product's real flow, cut to a few words (case_01: PO-7001, 50 x $1,450, KM-INV-30118, paid $71,050 with 2/15).
export const THUMB = { width: 2400, height: 1600 };

const LAPTOP = { x: 90, y: 300, w: 1640, h: 1025 };
const PHONE = { x: 1700, y: 210, w: 610, h: 1300 };

const Av: FC<{ bg: string; children: ReactNode }> = ({ bg, children }) => (
  <div style={{ width: 52, height: 52, borderRadius: 12, background: bg, color: "#fff", fontWeight: 800, fontSize: 22, display: "flex",
    alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{children}</div>
);
const Bot = () => <Av bg={W.teal}><Chevrons width={32} color="#fff" /></Av>;
const Vendor = () => <Av bg="#5b6cff">V</Av>;
const App = () => <span style={{ fontSize: 13, fontWeight: 700, background: "#e8e8e8", color: SL.muted, padding: "1px 5px", borderRadius: 4, marginLeft: 6 }}>APP</span>;

const Msg: FC<{ av: ReactNode; name: ReactNode; time: string; eph?: boolean; children: ReactNode }> = ({ av, name, time, eph, children }) => (
  <div style={{ display: "flex", gap: 14, padding: eph ? "12px 22px 14px" : "10px 22px", background: eph ? SL.eph : undefined }}>
    {av}
    <div style={{ flex: 1, minWidth: 0 }}>
      {eph && <div style={{ fontSize: 15, color: SL.muted, marginBottom: 2 }}>👁 Only visible to you</div>}
      <div style={{ fontSize: 21, fontWeight: 800, color: SL.text }}>{name}<span style={{ fontSize: 15, fontWeight: 400, color: SL.muted, marginLeft: 8 }}>{time}</span></div>
      <div style={{ fontSize: 21, color: SL.text, lineHeight: 1.35, marginTop: 2 }}>{children}</div>
    </div>
  </div>
);
const Pill: FC<{ c: string; bg: string; children: ReactNode; style?: CSSProperties }> = ({ c, bg, children, style }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 10px", borderRadius: 14, background: bg, color: c, fontSize: 16, fontWeight: 800,
    whiteSpace: "nowrap", ...style }}>{children}</span>
);
const DocTag: FC<{ n: number; label: string }> = ({ n, label }) => (
  <Pill c="#fff" bg={W.green} style={{ marginTop: 6 }}><b style={{ background: "#fff", color: W.green, borderRadius: 10, width: 20, height: 20, display: "inline-flex",
    alignItems: "center", justifyContent: "center", fontSize: 13 }}>{n}</b>{label}</Pill>
);

const Phone: FC = () => (
  <div style={{ position: "absolute", left: PHONE.x, top: PHONE.y, width: PHONE.w, height: PHONE.h, borderRadius: 86, background: "#0b0d10", padding: 18,
    boxSizing: "border-box", boxShadow: "0 60px 140px rgba(10,31,33,0.35), 0 0 0 3px #2a2e35 inset" }}>
    <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: 70, overflow: "hidden", background: "#fff", fontFamily: ui }}>
      {/* status bar + Slack header */}
      <div style={{ background: SL.side, color: "#fff", padding: "22px 34px 18px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 20, fontWeight: 700 }}>
          <span>9:41</span>
          <span style={{ position: "absolute", left: "50%", top: 14, transform: "translateX(-50%)", width: 150, height: 40, borderRadius: 20, background: "#0b0d10" }} />
          <span>●●● ▮</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 22 }}>
          <span style={{ fontSize: 34, opacity: 0.8 }}>‹</span>
          <div>
            <div style={{ fontSize: 26, fontWeight: 800 }}>🔒 vendor-deal</div>
            <div style={{ fontSize: 16, opacity: 0.75 }}>Helix + Vendor · ReconAI</div>
          </div>
        </div>
      </div>
      {/* the flow, top to bottom */}
      <div style={{ paddingTop: 8 }}>
        <Msg av={<Vendor />} name="Vendor" time="09:14">We can do <b>$1,520</b>/stack for 50, net 30.</Msg>
        <Msg av={<Bot />} name={<>ReconAI<App /></>} time="09:14" eph>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            <Pill c="#0891b2" bg="#e6f7fb">counter $1,180</Pill><Pill c={SL.green} bg="#e8f5ee">aim $1,300</Pill><Pill c="#b45309" bg="#fff4e0">walk $1,460</Pill>
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}><Pill c={SL.green} bg="#e8f5ee">+$11,000</Pill><Pill c="#1d4ed8" bg="#eef6ff">ask 2/15 net 30</Pill></div>
        </Msg>
        <Msg av={<Bot />} name={<>ReconAI<App /></>} time="09:43">✅ Vendor onboarded · contract signed<br /><DocTag n={1} label="PO-7001 created in ERP" /></Msg>
        <Msg av={<Bot />} name={<>ReconAI<App /></>} time="Oct 11">✅ 50 received, counted by Helix<br /><DocTag n={2} label="Goods receipt GRN-PO-7001-1" /></Msg>
        <Msg av={<Vendor />} name="Vendor" time="Oct 12">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10, border: "1px solid #ddd", borderRadius: 10, padding: "6px 12px" }}>
            <span style={{ background: SL.code, color: "#fff", fontSize: 12, fontWeight: 800, borderRadius: 4, padding: "6px 5px" }}>PDF</span><b>KM-INV-30118.pdf</b></span>
          <br /><DocTag n={3} label="Invoice" />
        </Msg>
        <Msg av={<Bot />} name={<>ReconAI<App /></>} time="10:02">
          <b>🟢 Ready to approve · $72,500</b>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
            <Pill c={SL.green} bg="#e8f5ee">✓ PO = Receipt = Invoice</Pill><Pill c={SL.green} bg="#e8f5ee">✓ Bank on file</Pill>
          </div>
          <div style={{ marginTop: 10, display: "inline-block", background: SL.green, color: "#fff", fontWeight: 800, fontSize: 20, borderRadius: 8, padding: "10px 18px" }}>
            Approve & release payment</div>
        </Msg>
        <Msg av={<Bot />} name={<>ReconAI<App /></>} time="10:33">💸 Payment sent: <b>$71,050</b> <span style={{ color: SL.muted }}>(2% early-pay kept)</span></Msg>
      </div>
      {/* composer */}
      <div style={{ position: "absolute", left: 20, right: 20, bottom: 26, height: 64, borderRadius: 14, border: "1px solid #ccc", display: "flex", alignItems: "center",
        padding: "0 18px", fontSize: 20, color: "#999" }}>Message 🔒 vendor-deal</div>
    </div>
  </div>
);

const Laptop: FC = () => (
  <div style={{ position: "absolute", left: LAPTOP.x, top: LAPTOP.y, width: LAPTOP.w }}>
    <div style={{ borderRadius: 26, overflow: "hidden", background: "#fff", boxShadow: "0 50px 120px rgba(10,31,33,0.28), 0 0 0 1px #dbe2de" }}>
      <div style={{ height: 50, background: "#eef1ed", display: "flex", alignItems: "center", gap: 10, padding: "0 20px", borderBottom: "1px solid #dbe2de" }}>
        {["#ff5f57", "#febc2e", "#28c840"].map((c) => <span key={c} style={{ width: 14, height: 14, borderRadius: 7, background: c }} />)}
        <span style={{ marginLeft: 24, flex: 1, maxWidth: 620, height: 30, borderRadius: 8, background: "#fff", border: "1px solid #dbe2de", fontFamily: mono, fontSize: 16,
          color: W.muted, display: "flex", alignItems: "center", padding: "0 14px" }}>app.reconai · AP workspace</span>
      </div>
      <Img src={staticFile("ui/home.png")} style={{ width: LAPTOP.w, height: (LAPTOP.w * 1000) / 1600, display: "block" }} />
    </div>
  </div>
);

export const Thumbnail: FC = () => (
  <AbsoluteFill style={{ fontFamily: ui, color: W.text, overflow: "hidden",
    background: "radial-gradient(1200px 800px at 15% 10%, rgba(14,110,118,0.16), transparent 60%), radial-gradient(1000px 700px at 90% 85%, rgba(58,175,167,0.20), transparent 60%), linear-gradient(160deg, #ffffff, #f4f7f6 55%, #e6f1f0)" }}>
    {/* brand + one line */}
    <div style={{ position: "absolute", left: 100, top: 82 }}><BrandLogo size={92} /></div>
    <div style={{ position: "absolute", left: 104, top: 200, fontSize: 62, fontWeight: 800, letterSpacing: -2, lineHeight: 1.05 }}>
      Quote to paid. <span style={{ color: W.teal }}>Dashboard or Slack.</span>
    </div>
    <Laptop />
    <Phone />
    {/* the three documents, matched */}
    <div style={{ position: "absolute", left: 100, top: 1426, display: "flex", alignItems: "center", gap: 16, fontSize: 30, fontWeight: 800 }}>
      {[["1", "PO"], ["2", "Receipt"], ["3", "Invoice"]].map(([n, l], i) => (
        <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
          {i > 0 && <span style={{ color: W.muted, fontWeight: 400 }}>=</span>}
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "12px 22px", borderRadius: 18, background: "rgba(22,163,74,0.10)", color: W.green,
            border: "2px solid rgba(22,163,74,0.35)" }}>
            <b style={{ background: W.green, color: "#fff", borderRadius: 18, width: 36, height: 36, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>{n}</b>{l}
          </span>
        </span>
      ))}
      <span style={{ marginLeft: 8, display: "inline-flex", alignItems: "center", gap: 10 }}><Mark ok p={1} size={48} color={W.green} /> 3-way matched · paid in one click</span>
    </div>
  </AbsoluteFill>
);
