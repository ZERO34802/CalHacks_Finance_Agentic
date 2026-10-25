// Coinbase rail (testnet): treasury card + on-chain payment bits. Real USDC transfers on Base Sepolia from a CDP
// server wallet; amounts are scaled down from the bill's USD amount. Money math is BigInt micro-USDC, never floats.
import { Anchor, Badge, Button, CopyButton, Group, Loader, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconExternalLink } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import type { Payment, TreasuryStatus, Vendor } from "../types/contracts";
import { ap } from "./api";
import { useApp } from "./context";
import { usd } from "./format";

const NET: Record<string, string> = { "base-sepolia": "Base Sepolia" };
export const netLabel = (n: string | null | undefined) => n === "sandbox" ? "Sandbox · simulated" : `${NET[n ?? ""] ?? n ?? "testnet"} · testnet`;
export const short = (h: string | null | undefined, n = 6) => (!h ? "—" : h.length <= n * 2 + 2 ? h : `${h.slice(0, n)}…${h.slice(-4)}`);

// Decimal string -> [digits as BigInt, decimal places]. Accepts "72500.00", "0.000001", "1E-6".
function dec(s: string): [bigint, number] {
  const m = /^(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(s.trim().replace(/^\+/, ""));
  if (!m) return [0n, 0];
  const [, i = "", f = "", e = "0"] = m;
  let v = BigInt(`${i}${f}` || "0"), places = f.length - Number(e);
  if (places < 0) { v *= 10n ** BigInt(-places); places = 0; }
  return [v, places];
}
/** Micro-USDC (6 dp) for a bill, same as backend usdc_for: amount_usd x scale, floored to 6 dp, at least 1. */
export function microUsdc(amountUsd: string, scale: string): bigint {
  const [a, pa] = dec(amountUsd), [b, pb] = dec(scale);
  const p = a * b, places = pa + pb;
  const q = places >= 6 ? p / 10n ** BigInt(places - 6) : p * 10n ** BigInt(6 - places);
  return q < 1n ? 1n : q;
}
export const microOf = (v: string | null | undefined) => {
  if (!v) return 0n;
  const [x, p] = dec(v);
  return p >= 6 ? x / 10n ** BigInt(p - 6) : x * 10n ** BigInt(6 - p);
};
export const fmtUsdc = (micro: bigint) => {
  const s = `${micro / 1_000_000n}.${String(micro % 1_000_000n).padStart(6, "0")}`.replace(/0+$/, "").replace(/\.$/, "");
  return `${s} USDC`;
};
export const usdcText = (v: string | null | undefined, token = "USDC") =>
  v == null ? "—" : `${fmtUsdc(microOf(v)).replace(/ USDC$/, "")}${token ? ` ${token}` : ""}`;

export function useTreasury(active: boolean) {
  const [t, setT] = useState<TreasuryStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    ap.treasury().then((x) => { setT(x); setErr(null); }).catch((e) => setErr(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false));
  }, []);
  useEffect(() => { if (active) reload(); }, [active, reload]);
  return { t, err, loading, reload, live: t?.mode === "live" || t?.mode === "sandbox", sandbox: t?.mode === "sandbox" };
}

export function TxLink({ p }: { p: Pick<Payment, "tx_hash" | "explorer_url"> }) {
  if (!p.tx_hash) return null;
  return p.explorer_url
    ? <Anchor href={p.explorer_url} target="_blank" rel="noreferrer" fz="xs" ff="monospace">tx {short(p.tx_hash)} <IconExternalLink size={11} style={{ verticalAlign: -1 }} /></Anchor>
    : <Text span fz="xs" ff="monospace">tx {short(p.tx_hash)}</Text>;
}

/** One line of on-chain result for a payment: amount, payee, tx link, status / error. */
export function OnchainLine({ p, vendor }: { p: Payment; vendor?: string }) {
  const failed = p.status === "failed";
  return (
    <Group gap={6} wrap="nowrap" py={2} align="flex-start">
      <Badge size="xs" variant="light" maw="none" style={{ flexShrink: 0 }} color={failed ? "red" : p.status === "paid" ? "green" : "gray"}>{failed ? "failed" : p.status}</Badge>
      <div style={{ minWidth: 0 }}>
        <Text fz="xs">{vendor ?? p.vendor_id} · {usdcText(p.onchain_amount, p.onchain_token ?? "USDC")} <Text span c="dimmed">for {usd(p.amount_usd)}</Text>
          {p.payee_address && <Text span c="dimmed" ff="monospace"> → {short(p.payee_address)}</Text>}{" "}<TxLink p={p} /></Text>
        {p.error && <Text fz="xs" c="red.8">{p.error}</Text>}
      </div>
    </Group>
  );
}

/** Coinbase treasury in one line (for the payment panel header): network, balance, wallet, faucet and vendor payout wallets. */
export function TreasuryBar({ tr, onWallets }: { tr: ReturnType<typeof useTreasury>; onWallets?: (v: Vendor[]) => void }) {
  const { refresh } = useApp();
  const { t, err, loading, reload, live, sandbox } = tr;
  const [busy, setBusy] = useState<"fund" | "wallets" | null>(null);
  const fund = async () => {
    setBusy("fund");
    try {
      const r = await ap.fundTreasury();
      const bad = Object.entries(r).filter(([, v]) => v.startsWith("error"));
      notifications.show({ color: bad.length ? "orange" : "brand", title: bad.length ? "Faucet partly refused" : "Faucet requested",
        message: Object.entries(r).map(([k, v]) => `${k.toUpperCase()}: ${v.startsWith("error") ? v : short(v)}`).join(" · ") + ". Balances update once mined." });
      setTimeout(reload, 6000);
    } catch (e) { notifications.show({ color: "red", title: "Faucet failed", message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(null); }
  };
  const wallets = async () => {
    setBusy("wallets");
    try {
      const vs = await ap.provisionWallets();
      onWallets?.(vs);
      refresh();
      notifications.show({ color: "brand", title: "Vendor payout wallets ready", message: `${vs.filter((v) => v.wallet_address).length} vendors have a testnet wallet in the vendor master.` });
    } catch (e) { notifications.show({ color: "red", title: "Couldn't create wallets", message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(null); }
  };
  const scale = t?.usd_scale ?? "0.000001";
  const about = !t ? "Checking the Coinbase treasury…"
    : !live ? "Coinbase isn't configured: set CDP_API_KEY_ID, CDP_API_KEY_SECRET and CDP_WALLET_SECRET in .env. Bank release (simulated) still works."
      : `${sandbox ? "Sandbox: no Coinbase keys, transfers are recorded locally, nothing goes on-chain. Same controls as live. " : "Real USDC transfers on testnet, play money. "}Scale ×${scale}: a $72,500 bill sends ${fmtUsdc(microUsdc("72500", scale))}.`;
  return (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
        <Text fz="xs" fw={600}>Coinbase</Text>
        <Tooltip label={about} multiline w={300}><Badge size="xs" variant="light" color={!live ? "gray" : sandbox ? "yellow" : "blue"} style={{ cursor: "help" }}>{t ? (!live ? "Not configured" : sandbox ? "Sandbox" : netLabel(t.network)) : "…"}</Badge></Tooltip>
        {live && (
          <CopyButton value={t?.address ?? ""}>{({ copied, copy }) => (
            <Tooltip label={copied ? "Copied" : `Treasury wallet ${t?.address ?? ""} · click to copy`}>
              <Anchor fz="xs" ff="monospace" c="dark" onClick={copy} style={{ whiteSpace: "nowrap" }}>{usdcText(t?.balances.USDC ?? "0")}</Anchor></Tooltip>
          )}</CopyButton>
        )}
        {loading && <Loader size={10} />}
        {err && <Tooltip label={err}><Text fz="xs" c="red.8">error</Text></Tooltip>}
      </Group>
      {live && <Group gap={4} wrap="nowrap">
        <Button size="compact-xs" variant="light" loading={busy === "fund"} onClick={fund}>{sandbox ? "Add funds" : "Faucet"}</Button>
        <Tooltip label="Create a testnet payout wallet for each vendor in the vendor master"><Button size="compact-xs" variant="default" loading={busy === "wallets"} onClick={wallets}>Wallets</Button></Tooltip>
      </Group>}
    </Group>
  );
}
