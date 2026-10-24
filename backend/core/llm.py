"""Shared Claude access. Every LLM call goes through `structured()`.

- Returns a validated Pydantic object (structured outputs); callers never parse text.
- RECONAI_LLM=live (default when a key is set) | replay (cache only, fail on miss) | off.
  Responses are cached under .data/llm_cache keyed by the full request, so evals
  are reproducible and re-runs cost nothing.
- Never pass tools here together with untrusted document text (see CLAUDE.md).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

from backend.core.config import ROOT

load_dotenv(ROOT / ".env")

MODEL = os.environ.get("RECONAI_MODEL", "claude-opus-5-5")
CACHE_DIR = ROOT / ".data" / "llm_cache"
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No key / mode off / replay miss. Callers escalate; nothing is guessed."""


@dataclass
class LLMResult:
    output: Any
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


def mode() -> str:
    m = os.environ.get("RECONAI_LLM")
    if m:
        return m
    return "live" if os.environ.get("ANTHROPIC_API_KEY") else "off"


def available() -> bool:
    return mode() != "off"


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def structured(output_model: type[T], system: str, content: list[dict] | str, *,
               effort: str = "medium", max_tokens: int = 16000, role: str = "llm") -> LLMResult:
    """One tool-less Claude call whose answer must validate as `output_model`."""
    if mode() == "off":
        raise LLMUnavailable("RECONAI_LLM=off or no ANTHROPIC_API_KEY")
    messages = [{"role": "user", "content": content}]
    key = hashlib.sha256(json.dumps(
        {"m": MODEL, "s": system, "c": content, "o": output_model.model_json_schema(), "e": effort, "r": role},
        sort_keys=True, default=str).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        data = json.loads(path.read_text())
        return LLMResult(output_model.model_validate(data["output"]), data["in"], data["out"], cached=True)
    if mode() == "replay":
        raise LLMUnavailable(f"replay miss for {role}")

    import anthropic
    try:
        resp = _get_client().beta.messages.parse(
            model=MODEL, max_tokens=max_tokens, system=system, messages=messages,
            output_format=output_model, thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
        raise LLMUnavailable(f"{role}: {type(e).__name__}: {e}") from e
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise LLMUnavailable(f"{role}: no parsed output (stop_reason={resp.stop_reason})")

    out: Optional[BaseModel] = resp.parsed_output
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"role": role, "output": out.model_dump(mode="json"),
                                "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}))
    return LLMResult(out, resp.usage.input_tokens, resp.usage.output_tokens)
