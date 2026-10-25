// Coinbase rail (testnet): treasury card + on-chain payment bits. Real USDC transfers on Base Sepolia from a CDP
// server wallet; amounts are scaled down from the bill's USD amount. Money math is BigInt micro-USDC, never floats.
import { ActionIcon, Alert, Anchor, Badge, Button, Card, CopyButton, Group, Loader, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
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

export function TreasuryCard({ tr, onWallets }: { tr: ReturnType<typeof useTreasury>; onWallets?: (v: Vendor[]) => void }) {
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

  if (t && !live) return (
    <Alert variant="light" color="gray" title="Coinbase payments not configured">
      <Text fz="xs">Set <Text span ff="monospace" fz="xs">CDP_API_KEY_ID</Text>, <Text span ff="monospace" fz="xs">CDP_API_KEY_SECRET</Text> and <Text span ff="monospace" fz="xs">CDP_WALLET_SECRET</Text> in .env to release runs as USDC on {netLabel(t.network)}. Bank release (simulated) still works.</Text>
    </Alert>
  );
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb={6}>
        <Group gap={6}><Text fw={600}>Coinbase treasury</Text><Badge size="xs" variant="light" color={sandbox ? "yellow" : "blue"}>{netLabel(t?.network)}</Badge></Group>
        {loading && <Loader size="xs" />}
      </Group>
      {err && <Text fz="xs" c="red.8" mb={6}>{err}</Text>}
      {sandbox && <Text fz="xs" c="yellow.9" mb={6}>Sandbox: no Coinbase keys set, so transfers are recorded locally and nothing goes on-chain. Same controls as live.</Text>}
      {t?.address && (
        <Group gap={4} mb={6}>
          <Text fz="xs" c="dimmed">Wallet</Text>
          <Anchor href={t.explorer_url ?? undefined} target="_blank" rel="noreferrer" fz="xs" ff="monospace">{short(t.address)}</Anchor>
          <CopyButton value={t.address}>{({ copied, copy }) => (
            <Tooltip label={copied ? "Copied" : "Copy address"}><ActionIcon size="xs" variant="subtle" color={copied ? "green" : "gray"} onClick={copy}>{copied ? <IconCheck size={12} /> : <IconCopy size={12} />}</ActionIcon></Tooltip>
          )}</CopyButton>
        </Group>
      )}
      <Group gap="lg" mb={6}>
        <div><Text fz="xs" c="dimmed">USDC</Text><Text fz={20} fw={600} ff="monospace">{t ? usdcText(t.balances.USDC ?? "0", "") : "—"}</Text></div>
        <div><Text fz="xs" c="dimmed">ETH (gas)</Text><Text fz={20} fw={600} ff="monospace">{t ? Number(t.balances.ETH ?? 0).toLocaleString("en-US", { maximumFractionDigits: 6 }) : "—"}</Text></div>
      </Group>
      <Text fz="xs" c="dimmed" mb="sm">Testnet scale ×{scale}: a USD 72,500 bill sends {fmtUsdc(microUsdc("72500", scale))}. {sandbox ? "Simulated ledger." : "Real on-chain transfers, play money."}</Text>
      <Group gap="xs">
        <Button size="xs" variant="light" loading={busy === "fund"} disabled={!live} onClick={fund}>{sandbox ? "Add sandbox funds" : "Fund from faucet"}</Button>
        <Button size="xs" variant="default" loading={busy === "wallets"} disabled={!live} onClick={wallets}>Create vendor payout wallets</Button>
      </Group>
    </Card>
  );
}
