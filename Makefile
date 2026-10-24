PY := PYTHONPATH=. .venv/bin/python
CASE ?= case_01

.PHONY: setup run eval seed api mock ui types test clean data stdb-start stdb-publish

setup:            ## venv + python deps + ui deps
	python3.12 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	cd ui && npm install

run:              ## make run CASE=case_01 -> one fixture through the pipeline
	$(PY) scripts/run_case.py $(CASE)

eval:             ## all fixtures -> scoreboard (exit 1 if any invariant fails)
	$(PY) scripts/eval.py

seed:
	$(PY) scripts/seed.py

api:              ## real backend (stub stages) on :8000, with WS /events
	$(PY) -m uvicorn backend.api.app:app --reload --port 8000

mock:             ## Prism mock of the OpenAPI spec on :4010 (no WS)
	cd ui && npm run mock

ui:               ## frontend on :5173 (VITE_API_URL picks mock or real)
	cd ui && npm run dev

types:            ## contracts -> JSON Schema + OpenAPI (+ examples) -> TypeScript
	$(PY) scripts/export_contracts.py
	cd ui && npm run types

test:
	$(PY) -m pytest -q tests

data:             ## rebuild data/world + data/cases from the generator
	$(PY) data/build_seed_cases.py

STDB := $(HOME)/.local/bin/spacetime

stdb-start:       ## local SpacetimeDB on :3000 (foreground); then RECONAI_STORE=spacetime make eval
	$(STDB) start --listen-addr 127.0.0.1:3000

stdb-publish:     ## publish the module (add ARGS=--yes=delete-data to reset)
	$(STDB) publish reconai -s local --module-path spacetime/spacetimedb --yes=skip-login $(ARGS)

clean:            ## wipe the dev DB (keeps the LLM response cache)
	rm -f .data/reconai.db .data/ledger.beancount
