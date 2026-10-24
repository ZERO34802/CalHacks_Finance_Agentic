"""make types -> contracts/schema/contracts.schema.json + api/openapi.json (with fixture examples).

TypeScript is generated from the schema by json-schema-to-typescript (see Makefile).
The OpenAPI examples come from running the fixtures through the current pipeline,
so the Prism mock serves realistic, contract-valid data.
Examples are built OFFLINE (no Claude / Droid calls): they only need to be contract-valid.
"""
import json
import os

os.environ["RECONAI_LLM"] = "off"
os.environ["RECONAI_DROID"] = "off"

from pydantic.json_schema import models_json_schema

from datetime import date

from backend.core.config import ROOT, load_policy
from backend.core.runner import make_ctx, run_fixture
from backend.dashboard.views import approval_queue, business_metrics, failures, stage_stats
from backend.evals.fixtures import case_dir, case_ids, load_fixture, seed
from backend.intake.ingest import ingest
from backend.evals.harness import run_eval
from backend.store.sqlite import SQLiteStore
from contracts import ALL_MODELS, CaseDetail

# 1. JSON Schema for all contracts
_, schema = models_json_schema([(m, "serialization") for m in ALL_MODELS], title="ReconAI Contracts")
for model_def in schema["$defs"].values():  # field titles make json2ts emit one alias type per field
    for prop in model_def.get("properties", {}).values():
        prop.pop("title", None)
        if "$ref" in prop:  # {$ref, default} also makes json2ts emit a duplicate enum (Role1...)
            prop.pop("default", None)
out = ROOT / "contracts" / "schema"
out.mkdir(exist_ok=True)
(out / "contracts.schema.json").write_text(json.dumps(schema, indent=2) + "\n")

# 2. Example data: run fixtures in a throwaway in-memory store
store = SQLiteStore(":memory:")
seed(store)
ctx = make_ctx(store, run_id="run_mock")
for cid in case_ids():
    run_fixture(load_fixture(cid), case_dir(cid), ctx)
board = run_eval(store)
cases = store.list_cases()
first = cases[0]
detail = CaseDetail(case=first, steps=store.list_steps(first.id, "run_mock"))
dump = lambda m: json.loads(m.model_dump_json())
examples = {
    ("/cases", "get"): [dump(c) for c in cases],
    ("/cases/{case_id}", "get"): dump(detail),
    ("/cases", "post"): dump(detail),
    ("/approvals/{case_id}", "post"): dump(first),
    ("/vendors/{vendor_id}", "get"): dump(store.get_vendor(first.vendor_id)),
    ("/memory", "get"): [dump(m) for m in store.list_memory()],
    ("/evals/scoreboard", "get"): dump(board),
    ("/evals/run", "post"): dump(board),
    ("/vendors", "get"): [dump(v) for v in store.list_vendors()],
    ("/fixtures", "get"): [dump(ingest(fx, case_dir(cid), ctx)) for cid in case_ids()
                           if (fx := load_fixture(cid)).kind == "inbound"],
    ("/dashboard/queue", "get"): [dump(i) for i in approval_queue(store, load_policy(), date(2026, 10, 24))],
    ("/dashboard/metrics", "get"): dump(business_metrics(store, load_policy())),
    ("/dashboard/failures", "get"): [dump(f) for f in failures(store)],
    ("/dashboard/stages", "get"): [dump(s) for s in stage_stats(store)],
}

# 3. OpenAPI from the FastAPI app, with examples injected
from backend.api.app import app  # noqa: E402

spec = app.openapi()
for (path, method), example in examples.items():
    resp = spec["paths"][path][method]["responses"]
    code = "201" if method == "post" and path == "/cases" else "200"
    resp[code]["content"]["application/json"]["example"] = example
api_dir = ROOT / "backend" / "api"
(api_dir / "openapi.json").write_text(json.dumps(spec, indent=2) + "\n")
print(f"wrote {out / 'contracts.schema.json'} and {api_dir / 'openapi.json'}")
