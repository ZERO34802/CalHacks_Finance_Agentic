"""Set up Helix's Odoo 17 (make erp && make erp-setup). Idempotent: safe to run again.

Creates database ODOO_DB (default helix) with login ODOO_USER / ODOO_PASSWORD (admin / admin), names the company
"Helix Silicon, Inc." (USD), installs Purchase + Inventory, activates the vendor currencies with the SIMULATED fixed
rates from config/policy.yaml, and appends the ODOO_* keys missing from .env (never touches other values).
Master password: ODOO_MASTER_PASSWORD (the odoo:17 image default is "admin").
--reset drops the database first (a clean ERP for a demo): make erp-setup ARGS=--reset
"""
from __future__ import annotations

import os
import sys
import time
import xmlrpc.client
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
DEFAULTS = {"ODOO_URL": "http://localhost:8069", "ODOO_DB": "helix", "ODOO_USER": "admin", "ODOO_PASSWORD": "admin"}
URL, DB, USER, PWD = (os.getenv(k) or v for k, v in DEFAULTS.items())
URL = URL.rstrip("/")
MASTER = os.getenv("ODOO_MASTER_PASSWORD", "admin")
COMPANY = "Helix Silicon, Inc."
ADMIN_EMAIL = "erp.admin@helix.example"


def rpc(path: str) -> xmlrpc.client.ServerProxy:
    return xmlrpc.client.ServerProxy(f"{URL}{path}", allow_none=True)


def wait_for_odoo(seconds: int = 240) -> None:
    end = time.time() + seconds
    while True:
        try:
            print(f"Odoo {rpc('/xmlrpc/2/common').version()['server_version']} at {URL}")
            return
        except (OSError, xmlrpc.client.Error) as e:
            if time.time() > end:
                sys.exit(f"Odoo is not answering at {URL} ({e}). Start it with: make erp")
            time.sleep(3)


def ensure_db() -> None:
    dbs = rpc("/xmlrpc/2/db").list()
    if DB in dbs:
        print(f"database {DB}: exists")
        return
    print(f"database {DB}: creating (about a minute)...")
    try:  # master pwd, name, demo data, lang, admin password, admin login, country, phone
        rpc("/xmlrpc/2/db").create_database(MASTER, DB, False, "en_US", PWD, USER, "US", "")
    except xmlrpc.client.Fault as e:
        sys.exit(f"Could not create {DB}: {e.faultString.strip().splitlines()[-1]}. "
                 "Set ODOO_MASTER_PASSWORD if the Odoo master password is not 'admin'.")


class Odoo:
    def __init__(self):
        self.uid = rpc("/xmlrpc/2/common").authenticate(DB, USER, PWD, {})
        if not self.uid:
            sys.exit(f"Login {USER} on {DB} failed: check ODOO_USER / ODOO_PASSWORD.")
        self.obj = rpc("/xmlrpc/2/object")

    def __call__(self, model, method, *args, **kw):
        return self.obj.execute_kw(DB, self.uid, PWD, model, method, list(args), kw)


def install(odoo: Odoo, names: list[str]) -> None:
    for name in names:
        mod = odoo("ir.module.module", "search_read", [("name", "=", name)], fields=["state"])
        if not mod:
            sys.exit(f"Odoo has no module {name}")
        if mod[0]["state"] == "installed":
            print(f"module {name}: installed")
            continue
        print(f"module {name}: installing (can take a minute)...")
        odoo("ir.module.module", "button_immediate_install", [mod[0]["id"]])


def setup_company(odoo: Odoo) -> None:
    usd = odoo("res.currency", "search", [("name", "=", "USD")], context={"active_test": False})[0]
    us = odoo("res.country", "search", [("code", "=", "US")])[0]
    cid = odoo("res.users", "read", [odoo.uid], fields=["company_id"])[0]["company_id"][0]
    company = odoo("res.company", "read", [cid], fields=["name", "currency_id"])[0]
    vals = {"name": COMPANY, "country_id": us, "email": "ap@helix.example", "website": "helix.example"}
    if company["currency_id"][0] != usd:
        vals["currency_id"] = usd
    odoo("res.company", "write", [cid], vals)
    odoo("res.users", "write", [odoo.uid], {"email": ADMIN_EMAIL})
    print(f"company: {COMPANY} (USD)")


def setup_currencies(odoo: Odoo) -> None:
    """Vendor currencies with the SIMULATED fixed table in policy.yaml (USD per unit), so Odoo totals agree with ours."""
    import yaml
    rates = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text())["fx_rates"]
    for code, usd_per_unit in rates.items():
        if code == "USD":
            continue
        cur = odoo("res.currency", "search_read", [("name", "=", code)], fields=["active"], context={"active_test": False})
        if not cur:
            continue
        if not cur[0]["active"]:
            odoo("res.currency", "write", [cur[0]["id"]], {"active": True})
        if not odoo("res.currency.rate", "search", [("currency_id", "=", cur[0]["id"])]):
            odoo("res.currency.rate", "create", {"currency_id": cur[0]["id"], "inverse_company_rate": str(usd_per_unit)})
        print(f"currency {code}: active, {usd_per_unit} USD (simulated fixed rate)")


def update_env() -> None:
    """Append the ODOO_* keys missing from .env. Existing lines are left exactly as they are."""
    path = ROOT / ".env"
    text = path.read_text() if path.exists() else ""
    have = {ln.split("=", 1)[0].strip() for ln in text.splitlines() if "=" in ln and not ln.lstrip().startswith("#")}
    add = [f"{k}={v}" for k, v in DEFAULTS.items() if k not in have]
    if add:
        sep = "" if not text or text.endswith("\n") else "\n"
        path.write_text(text + sep + "# Helix ERP (Odoo 17, make erp && make erp-setup)\n" + "\n".join(add) + "\n")
        print(f".env: added {', '.join(a.split('=')[0] for a in add)}")
    else:
        print(".env: ODOO_* already set")


def reset_db() -> None:
    if DB in rpc("/xmlrpc/2/db").list():
        print(f"database {DB}: dropping (--reset)")
        rpc("/xmlrpc/2/db").drop(MASTER, DB)


def main() -> None:
    wait_for_odoo()
    if "--reset" in sys.argv[1:]:
        reset_db()
    ensure_db()
    odoo = Odoo()
    setup_company(odoo)
    install(odoo, ["purchase", "stock"])
    odoo = Odoo()  # fresh registry after installs
    setup_currencies(odoo)
    update_env()
    print(f"\nHelix ERP ready: {URL}/web?db={DB}  (login {USER} / {PWD})")
    print("Restart `make api` (or wait ~30s) and the Purchasing page shows 'Odoo · connected'.")


if __name__ == "__main__":
    main()
