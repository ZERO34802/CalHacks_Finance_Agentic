"""make seed -> load vendors + memory into the store."""
from backend.evals.fixtures import seed
from backend.store.sqlite import SQLiteStore

store = SQLiteStore()
seed(store)
print(f"seeded {len(store.list_vendors())} vendors, {len(store.list_memory())} memory entries")
