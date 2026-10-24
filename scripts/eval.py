"""make eval -> run all fixtures, print the scoreboard. Exit 1 if any invariant fails."""
import sys

from backend.evals.harness import format_board, run_eval
from backend.store.factory import make_store

board = run_eval(make_store())
print(format_board(board))
sys.exit(0 if board.invariant_pass_rate == 1.0 else 1)
