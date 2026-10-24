"""make seed -> load the system of record (world), vendors and memory into the store (RECONAI_STORE)."""
from backend.evals.fixtures import seed
from backend.store import get_store

store = get_store()
seed(store)
print(f"seeded {len(store.list_vendors())} vendors, {len(store.list_memory())} memory entries")
