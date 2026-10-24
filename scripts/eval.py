"""make eval -> run all fixtures on a fresh store, print the scoreboard. Exit 1 if any invariant fails.

Store from RECONAI_STORE (sqlite default | spacetime). Run state is reset first (scoreboard history kept),
so in-run dedup (e.g. case_14 duplicates case_13) is deterministic.
  make eval                       all cases
  python scripts/eval.py case_04  just these
  --quiet                         no per-check miss list
"""
import sys

from backend.evals.harness import format_board, run_eval
from backend.store import get_store

args = [a for a in sys.argv[1:] if not a.startswith("-")]
store = get_store()
store.reset(keep_scoreboards=True)
try:  # the ledger is derived from posted cases, which reset just wiped -> start it fresh too (A's helper)
    from backend.pipeline.lib.ledger import ledger_path
    ledger_path(store).unlink(missing_ok=True)
except ImportError:
    pass
board = run_eval(store, args or None)
print(format_board(board, verbose="--quiet" not in sys.argv))
sys.exit(0 if board.invariant_pass_rate == 1.0 else 1)
