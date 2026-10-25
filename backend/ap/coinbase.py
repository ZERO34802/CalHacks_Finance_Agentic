"""Coinbase payment rail: release approved payment runs as USDC transfers from a CDP server wallet. Owner: D.

Testnet only (Base Sepolia). Every transfer is real on-chain and gets a tx hash + explorer link, but the amount
is scaled down from the bill's USD amount (COINBASE_USD_SCALE, default 0.000001: a USD 72,500 bill sends 0.0725
USDC) because the faucet hands out tiny amounts. Labelled testnet everywhere.

Controls (code):
- The agent never initiates: a human releases the run, and the preparer can't release it (backend/ap/payments.py).
- Pay-to is the vendor master's wallet_address, never an address from an invoice or email. A vendor without one
  is refused. Demo payout wallets are created explicitly (`provision_vendor_wallets`), recorded in the vendor master.
- Balance is checked before the first transfer; each transfer waits for its receipt; a failed transfer leaves the
  run partially paid and can be retried (already-paid lines are never re-sent).

Env: CDP_API_KEY_ID, CDP_API_KEY_SECRET, CDP_WALLET_SECRET (Coinbase Developer Platform),
COINBASE_NETWORK (base-sepolia), COINBASE_TREASURY_ACCOUNT (reconai-treasury), COINBASE_USD_SCALE.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Protocol

import httpx
from dotenv import load_dotenv

from backend.core.config import ROOT
from contracts import Payment, TreasuryStatus, Vendor

load_dotenv(ROOT / ".env")

NETWORK = os.environ.get("COINBASE_NETWORK", "base-sepolia")
USDC_DECIMALS = 6
USDC_CONTRACT = {"base-sepolia": "0x036cbd53842c5426634e7929541ec2318f3dcf7e"}
EXPLORER = {"base-sepolia": "https://sepolia.basescan.org"}
RPC = {"base-sepolia": "https://sepolia.base.org"}
TREASURY = os.environ.get("COINBASE_TREASURY_ACCOUNT", "reconai-treasury")
MIN_UNITS = 1  # 0.000001 USDC


class RailError(Exception):
    pass


def usd_scale() -> Decimal:
    return Decimal(os.environ.get("COINBASE_USD_SCALE", "0.000001"))


def configured() -> bool:
    return all(os.environ.get(k) for k in ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET"))


def usdc_for(amount_usd: Decimal) -> Decimal:
    """Testnet amount for a bill: scaled, rounded down to USDC's 6 decimals, at least 0.000001."""
    q = (amount_usd * usd_scale()).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    return max(q, Decimal("0.000001"))


def to_units(usdc: Decimal) -> int:
    return int((usdc * 10 ** USDC_DECIMALS).to_integral_value(rounding=ROUND_DOWN))


def tx_url(tx_hash: str) -> str:
    return f"{EXPLORER.get(NETWORK, '')}/tx/{tx_hash}"


def address_url(addr: str) -> str:
    return f"{EXPLORER.get(NETWORK, '')}/address/{addr}"


class Rail(Protocol):
    def status(self) -> TreasuryStatus: ...
    def fund(self) -> dict[str, str]: ...
    def create_wallet(self, name: str) -> str: ...
    def transfer(self, to: str, units: int) -> str: ...
    def confirmed(self, tx_hash: str) -> bool: ...


class LiveCoinbase:
    """CDP server wallet (cdp-sdk v1.x, async API run on a private event loop)."""

    def _run(self, coro_fn):
        from cdp import CdpClient

        async def go():
            async with CdpClient() as cdp:
                return await coro_fn(cdp)
        try:
            return asyncio.run(go())
        except RailError:
            raise
        except Exception as e:
            raise RailError(f"Coinbase CDP: {type(e).__name__}: {str(e)[:240]}") from e

    def status(self) -> TreasuryStatus:
        async def go(cdp):
            acct = await cdp.evm.get_or_create_account(name=TREASURY)
            res = await cdp.evm.list_token_balances(address=acct.address, network=NETWORK)
            bal = {"USDC": "0", "ETH": "0"}
            for b in res.balances:
                sym = "ETH" if b.token.contract_address.lower().startswith("0xeeee") else (
                    "USDC" if b.token.contract_address.lower() == USDC_CONTRACT.get(NETWORK) else
                    (getattr(b.token, "symbol", None) or b.token.contract_address[:10]))
                bal[sym] = str(Decimal(b.amount.amount) / (Decimal(10) ** b.amount.decimals))
            return acct.address, bal
        addr, bal = self._run(go)
        return TreasuryStatus(mode="live", network=NETWORK, address=addr, balances=bal, usd_scale=usd_scale(),
                              explorer_url=address_url(addr),
                              note=f"Coinbase CDP server wallet '{TREASURY}' on {NETWORK} (testnet)")

    def fund(self) -> dict[str, str]:
        async def go(cdp):
            acct = await cdp.evm.get_or_create_account(name=TREASURY)
            out = {}
            for token in ("eth", "usdc"):
                try:
                    out[token] = await cdp.evm.request_faucet(address=acct.address, network=NETWORK, token=token)
                except Exception as e:  # faucet rate limits: report, keep going
                    out[token] = f"error: {str(e)[:160]}"
            return out
        return self._run(go)

    def create_wallet(self, name: str) -> str:
        async def go(cdp):
            return (await cdp.evm.get_or_create_account(name=name)).address
        return self._run(go)

    def transfer(self, to: str, units: int) -> str:
        async def go(cdp):
            acct = await cdp.evm.get_or_create_account(name=TREASURY)
            return await acct.transfer(to=to, amount=units, token="usdc", network=NETWORK)
        tx = self._run(go)
        return tx if isinstance(tx, str) else getattr(tx, "transaction_hash", str(tx))

    def confirmed(self, tx_hash: str, timeout: float = 90) -> bool:
        """Poll the public RPC for the receipt. True = mined and succeeded."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = httpx.post(RPC[NETWORK], timeout=10, json={"jsonrpc": "2.0", "id": 1,
                                                                "method": "eth_getTransactionReceipt", "params": [tx_hash]})
                rec = r.json().get("result")
                if rec:
                    return rec.get("status") == "0x1"
            except httpx.HTTPError:
                pass
            time.sleep(2)
        raise RailError(f"no receipt for {tx_hash} after {timeout:.0f}s (check the explorer)")


class SandboxCoinbase:
    """No CDP keys: the same release flow against a local, SIMULATED ledger (balances, payout wallets, transfers)
    persisted in .data/coinbase_sandbox.json. Nothing touches a chain; tx ids are labelled sandbox, no explorer."""
    on_chain = False
    network = "sandbox"

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.environ.get("RECONAI_COINBASE_SANDBOX", str(ROOT / ".data" / "coinbase_sandbox.json")))
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"usdc_units": 0, "eth_wei": 0, "txs": {}}

    def _save(self, st: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(st, indent=1))

    @staticmethod
    def _addr(name: str) -> str:
        return "0x" + hashlib.sha256(f"reconai-sandbox:{name}".encode()).hexdigest()[:40]

    def status(self) -> TreasuryStatus:
        st = self._load()
        return TreasuryStatus(mode="sandbox", network="sandbox", address=self._addr(TREASURY),
                              balances={"USDC": str(Decimal(st["usdc_units"]) / 10 ** USDC_DECIMALS),
                                        "ETH": str(Decimal(st["eth_wei"]) / 10 ** 18)},
                              usd_scale=usd_scale(), explorer_url=None,
                              note="Coinbase sandbox (SIMULATED): no CDP keys set, transfers are recorded locally, "
                                   "nothing is sent on-chain. Set CDP_* keys for real Base Sepolia USDC.")

    def fund(self) -> dict[str, str]:
        with self._lock:
            st = self._load()
            st["usdc_units"] += 1 * 10 ** USDC_DECIMALS  # like the CDP faucet: 1 USDC per claim
            st["eth_wei"] += 10 ** 14
            self._save(st)
        n = len(st["txs"])
        return {"eth": "sandbox-" + hashlib.sha256(f"faucet-eth-{n}-{time.time()}".encode()).hexdigest()[:16],
                "usdc": "sandbox-" + hashlib.sha256(f"faucet-usdc-{n}-{time.time()}".encode()).hexdigest()[:16]}

    def create_wallet(self, name: str) -> str:
        return self._addr(name)

    def transfer(self, to: str, units: int) -> str:
        with self._lock:
            st = self._load()
            if units > st["usdc_units"]:
                raise RailError("sandbox treasury has insufficient USDC")
            st["usdc_units"] -= units
            tx = "0x" + hashlib.sha256(f"{to}:{units}:{len(st['txs'])}:{time.time()}".encode()).hexdigest()
            st["txs"][tx] = {"to": to, "units": units, "at": time.time()}
            self._save(st)
        return tx

    def confirmed(self, tx_hash: str, timeout: float = 0) -> bool:
        return tx_hash in self._load()["txs"]


_rail: Optional[Rail] = None


def sandbox_enabled() -> bool:
    return os.environ.get("COINBASE_MODE", "sandbox").lower() == "sandbox"


def get_rail() -> Optional[Rail]:
    """Live CDP rail when the keys are set; else the local sandbox (COINBASE_MODE=sandbox, the default; off disables).
    Tests inject a fake with set_rail()."""
    global _rail
    if _rail is None:
        if configured():
            _rail = LiveCoinbase()
        elif sandbox_enabled():
            _rail = SandboxCoinbase()
    return _rail


def set_rail(rail: Optional[Rail]) -> None:
    global _rail
    _rail = rail


def not_configured() -> TreasuryStatus:
    return TreasuryStatus(mode="not_configured", network=NETWORK, usd_scale=usd_scale(),
                          note="Set CDP_API_KEY_ID, CDP_API_KEY_SECRET and CDP_WALLET_SECRET to pay via Coinbase")


def wallet_name(vendor: Vendor) -> str:
    return f"reconai-vendor-{vendor.id.lower().replace('_', '-')}"


def settle(payments: list[Payment], vendors: dict[str, Vendor], rail: Rail) -> None:
    """Send each unpaid payment as USDC to the vendor master's wallet. Mutates the payments in place."""
    todo = [p for p in payments if p.status != "paid"]
    for p in todo:
        v = vendors.get(p.vendor_id)
        if v is None or not v.wallet_address:
            raise RailError(f"{p.case_id}: {v.name if v else p.vendor_id} has no payout wallet on file. "
                            "Add one to the vendor master first (never from an invoice).")
    # a line that already has a tx hash from an earlier attempt may still be in flight (receipt timed out):
    # re-check it first and never re-send it unless the chain says it reverted
    send = []
    for p in todo:
        if p.tx_hash and p.error != "transaction reverted":
            try:
                ok = rail.confirmed(p.tx_hash)
            except Exception as e:  # still no receipt: keep it failed, do not send a second transfer
                p.status, p.error = "failed", f"pending, not re-sent: {str(e)[:260]}"
                continue
            if ok:
                p.status, p.error = "paid", None
                continue
        send.append(p)
    need = sum((usdc_for(p.amount_usd) for p in send), Decimal(0))
    bal = Decimal(rail.status().balances.get("USDC", "0")) if send else Decimal(0)
    if bal < need:
        raise RailError(f"Treasury has {bal} USDC; this run needs {need} USDC (testnet scale {usd_scale()}). "
                        "Fund the treasury from the faucet first.")
    for p in send:
        v = vendors[p.vendor_id]
        p.rail, p.network, p.onchain_token = "coinbase", getattr(rail, "network", NETWORK), "USDC"
        p.onchain_amount, p.payee_address, p.error = usdc_for(p.amount_usd), v.wallet_address, None
        p.tx_hash = p.explorer_url = None
        try:
            p.tx_hash = rail.transfer(v.wallet_address, to_units(p.onchain_amount))
            p.explorer_url = tx_url(p.tx_hash) if getattr(rail, "on_chain", True) else None
            if not rail.confirmed(p.tx_hash):
                raise RailError("transaction reverted")
            p.status = "paid"
        except Exception as e:  # any failure leaves this line unpaid (and the rest of the run still goes)
            p.status, p.error = "failed", (str(e) if isinstance(e, RailError) else f"{type(e).__name__}: {e}")[:300]
