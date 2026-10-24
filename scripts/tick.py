"""make tick AS_OF=2026-10-28 -> advance the business clock and run sweeps (SLA, overdue follow-ups)."""
import argparse
from datetime import date

from backend.core import hooks
from backend.core.runner import make_ctx
from backend.store import get_store

p = argparse.ArgumentParser()
p.add_argument("as_of", type=date.fromisoformat)
args = p.parse_args()
ctx = make_ctx(get_store())
hooks.run_sweeps(ctx, args.as_of)
for s in ctx.store.list_steps("sweep", ctx.run_id):
    print(f"  {s.stage:<28} {s.status.value:<8} {s.detail}")
