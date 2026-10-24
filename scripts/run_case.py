"""make run CASE=case_01 -> push one fixture through the pipeline and print the trace."""
import argparse

from backend.core.runner import make_ctx, run_case
from backend.evals.fixtures import load_case, seed
from backend.store.factory import make_store


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("case_id")
    args = p.parse_args()

    store = make_store()
    seed(store)
    ctx = make_ctx(store)
    case = run_case(load_case(args.case_id), ctx)

    print(f"{case.id}  run={ctx.run_id}  status={case.status.value}  decision={case.decision.value if case.decision else '-'}")
    for s in store.list_steps(case.id, ctx.run_id):
        print(f"  {s.seq:>2} {s.stage:<13} {s.role.value:<13} {s.status.value:<9} {s.duration_ms}ms"
              + (f"  ERROR {s.error}" if s.error else ""))
    if case.journal_entry:
        for post in case.journal_entry.postings:
            print(f"     {post.account:<28} {post.amount:>16} {post.currency}")


if __name__ == "__main__":
    main()
