"""Entry point for `make data`. Kept for the Makefile; the generator lives in data/generate.py (owner: C).

Builds data/world, all cases (seed case_01..05 plus the generated set), answer_key.json, memory files,
and data/onboarding. Deterministic: running it twice produces byte-identical files.
"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("generate.py")), run_name="__main__")
