"""Factory Droid runner for the sandboxed Investigator. Owner: B.

RECONAI_DROID=live (default when FACTORY_API_KEY is set and `droid` is on PATH) | replay (cache only) | off.
Results are cached under .data/droid_cache keyed by model + prompts + tool allowlist + the hashes of every
mounted read-only file, so evals are reproducible and re-runs cost nothing.

Enforcement layers (see sandbox.py for the mounts):
  1. restrict_tools = the skill's tools.yaml allowlist (no Execute, no FetchUrl/WebSearch, no Task).
  2. Autonomy.OFF (Droid's read-only mode: write tools are not even offered) + our permission handler as a
     backstop: any Create/Edit/ApplyPatch outside proposal.json / scratch/, shell, or sandbox violation is
     cancelled and logged.
  The exit is Droid's structured output (`output=AgentFinding`), validated by code; code then writes it to
  the sandbox's proposal.json (hashed into the archive). The agent itself has no write capability.
  3. Droid OS sandbox via a per-run `--settings` file: writes denied to ro/, reads denied to repo
     secrets/config, no extra network domains. (Per-command mode: confines Execute/hooks at the kernel
     level; file tools are policy-checked by Droid.)
  4. ro/ files are chmod 0444 (dirs 0555); the child env is scrubbed of other secrets by a wrapper.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

from backend.agents.sandbox import Sandbox
from backend.core.config import ROOT

load_dotenv(ROOT / ".env")

MODEL = os.environ.get("RECONAI_DROID_MODEL", "claude-opus-5-5")
CACHE_DIR = ROOT / ".data" / "droid_cache"
SECRETISH = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE", re.I)


class DroidUnavailable(RuntimeError):
    """Droid off / not installed / replay miss / run failed / no structured output. Caller falls back."""

    def __init__(self, msg: str, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(msg)
        self.input_tokens, self.output_tokens, self.cached = input_tokens, output_tokens, False


@dataclass
class DroidRun:
    finding: dict[str, Any]
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    session_id: Optional[str] = None
    subtype: Optional[str] = None
    text: str = ""
    layers: list[str] = field(default_factory=list)


def mode() -> str:
    m = os.environ.get("RECONAI_DROID")
    if m:
        return m
    return "live" if os.environ.get("FACTORY_API_KEY") and shutil.which("droid") else "off"


def _key(sb: Sandbox, system: str, prompt: str) -> str:
    return hashlib.sha256(json.dumps({"m": MODEL, "s": system, "p": prompt, "t": sorted(sb.skill.tools),
                                      "mounts": sb.mount_hash()}, sort_keys=True).encode()).hexdigest()


def _wrapper(sb: Sandbox) -> str:
    """Shell wrapper that drops secret-looking env vars (names only, no values) before exec'ing droid.
    The SDK re-adds FACTORY_API_KEY, which Droid itself needs to authenticate."""
    droid = shutil.which("droid") or "droid"
    unset = " ".join(f"-u {k}" for k in sorted(os.environ) if SECRETISH.search(k) and k != "FACTORY_API_KEY")
    path = sb.root.parent / f"{sb.root.name}.droid.sh"
    path.write_text(f'#!/bin/sh\nexec /usr/bin/env {unset} "{droid}" "$@"\n')
    path.chmod(0o500)
    return str(path)


def permission_handler(sb: Sandbox):
    """Allow only Create/Edit/ApplyPatch of proposal.json or scratch/; cancel everything else. Logs each decision."""
    from droid_sdk import PermissionRequest, ToolConfirmationOutcome
    from droid_sdk.permissions import ApplyPatchAction, CreateFile, EditAction, SandboxViolationAction

    def on_permission(req: PermissionRequest):
        ok = bool(req.actions)
        for a in req.actions:
            target = getattr(a, "file_path", None) or getattr(a, "full_command", None) or getattr(a, "target", None)
            allowed = False
            if isinstance(a, (CreateFile, EditAction)):
                allowed = sb.may_write(a.file_path)
            elif isinstance(a, ApplyPatchAction):
                files = a.files or []
                paths = [a.file_path, *[f.file_path for f in files], *[f.move_to for f in files if f.move_to]]
                allowed = all(sb.may_write(p) for p in paths)
            sb.event("permission", tool=type(a).__name__, target=str(target), allowed=allowed,
                     violation=isinstance(a, SandboxViolationAction) or None)
            ok = ok and allowed
        offered = {o.value for o in req.options}
        if ok and ToolConfirmationOutcome.PROCEED_ONCE in offered:
            return req.respond(ToolConfirmationOutcome.PROCEED_ONCE)
        return req.respond(ToolConfirmationOutcome.CANCEL)

    return on_permission


async def _run_async(sb: Sandbox, system: str, prompt: str, timeout: float, output_model=None):
    from droid_sdk import Autonomy, InteractionHandlers, Runtime, SessionConfig, run

    config = SessionConfig(
        autonomy=Autonomy.OFF,
        restrict_tools=set(sb.skill.tools),
        disable_builtin_skills=True,
        system_prompt={"type": "preset", "preset": "droid", "append": system},
    )
    runtime = Runtime(executable=_wrapper(sb), args=["--settings", str(sb.settings_path)])
    return await run(prompt, cwd=sb.root, model=MODEL, timeout=timeout, config=config, output=output_model,
                     interactions=InteractionHandlers(on_permission=permission_handler(sb)), runtime=runtime)


def _run_sync(coro_fn, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn(*args))
    with concurrent.futures.ThreadPoolExecutor(1) as pool:  # called from inside an event loop (API)
        return pool.submit(lambda: asyncio.run(coro_fn(*args))).result()


def transcript(result) -> dict:
    """Diagnosable summary of a Droid run: tool calls (name + target), final text excerpt."""
    calls = []
    for m in getattr(result, "messages", ()) or ():
        if type(m).__name__ == "ToolCall":
            inp = dict(getattr(m, "input", {}) or {})
            target = inp.get("file_path") or inp.get("directory_path") or inp.get("pattern") or ""
            calls.append(f"{m.name} {target}".strip())
    return {"tool_calls": calls[:50], "text": (getattr(result, "text", "") or "")[:1500]}


def investigate(sb: Sandbox, system: str, prompt: str, output_model, timeout: float = 300) -> DroidRun:
    m = mode()
    if m == "off":
        raise DroidUnavailable("RECONAI_DROID=off or no FACTORY_API_KEY / droid CLI")
    key = _key(sb, system, prompt)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        data = json.loads(path.read_text())
        sb.event("droid.cache_hit", key=key[:12], session_id=data.get("session_id"))
        sb.proposal_path.write_text(json.dumps(data["finding"], indent=2))  # same exit file as a live run
        return DroidRun(finding=data["finding"], tokens=data.get("tokens", 0), cached=True,
                        session_id=data.get("session_id"), subtype="success")
    if m == "replay":
        raise DroidUnavailable("droid replay miss")
    try:
        result = _run_sync(_run_async, sb, system, prompt, timeout, output_model)
    except Exception as e:  # setup / connection failures raise; we fall back, never guess
        raise DroidUnavailable(f"droid run failed: {type(e).__name__}: {e}") from e
    u = result.usage
    tout = u.output_tokens if u else 0
    # cost-equivalent input tokens: cache writes bill at 1.25x, cache reads at 0.1x of base input price
    tin = int(u.input_tokens + 1.25 * u.cache_creation_tokens + 0.1 * u.cache_read_tokens) if u else 0
    sb.event("droid.usage", input=u.input_tokens if u else 0, output=tout,
             cache_creation=u.cache_creation_tokens if u else 0, cache_read=u.cache_read_tokens if u else 0,
             thinking=u.thinking_tokens if u else 0, factory_credits=u.factory_credits if u else None)
    err = getattr(result, "error", None) or getattr(result, "structured_output_error", None)
    sb.event("droid.result", subtype=result.subtype, session_id=result.session_id, input_tokens=tin,
             output_tokens=tout, error=str(getattr(err, "message", err))[:300] if err else None,
             output_validation_error=str(result.output_validation_error)[:300] if result.output_validation_error else None)
    sb.event("droid.transcript", **transcript(result))
    out = result.output
    if out is None and result.structured_output is not None:
        out = dict(result.structured_output)
    if out is None:
        raise DroidUnavailable(f"droid returned no structured output (subtype={result.subtype}, "
                               f"error={str(err)[:200]})", tin, tout)
    finding = out.model_dump(mode="json") if hasattr(out, "model_dump") else json.loads(json.dumps(out, default=str))
    sb.proposal_path.write_text(json.dumps(finding, indent=2))  # code writes the exit file, not the agent
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"finding": finding, "tokens": tin + tout, "session_id": result.session_id}))
    return DroidRun(finding=finding, tokens=tin + tout, input_tokens=tin, output_tokens=tout,
                    session_id=result.session_id, subtype=result.subtype, text=(result.text or "")[:1500])
