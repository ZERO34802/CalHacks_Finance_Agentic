"""Record the CRS sandbox's answers for every test persona (minimised) -> backend/vendors/crs_recorded.json.

Offline mode (tests, no credentials) replays these, so offline and live share one parser. Run once with
CRS_USERNAME / CRS_PASSWORD in .env:  PYTHONPATH=. .venv/bin/python scripts/crs_record.py
One login for the whole run; only sandbox personas are sent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.vendors.crs import HERE, PRODUCTS, SandboxCRS, personas


def main() -> int:
    crs = SandboxCRS()
    out: dict = {}
    for pid in personas():
        rep = crs.check_principal(pid, PRODUCTS)
        out[pid] = {prod: {"result": rep.results[prod], "request_id": rep.request_ids.get(prod, "")} for prod in rep.results}
        print(pid, rep.name, {k: ("ok" if v else "-") for k, v in rep.results.items()})
    Path(HERE / "crs_recorded.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"wrote {HERE / 'crs_recorded.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
