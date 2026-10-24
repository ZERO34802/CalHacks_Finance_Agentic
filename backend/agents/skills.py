"""Skill loader. Skills live in backend/skills/<name>/ and are written by the team only.

Never loaded from incoming documents: the name comes from the Router (code), and only
names that exist on disk under SKILLS_DIR resolve.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def skills_dir() -> Path:
    """RECONAI_SKILLS_DIR overrides the skills root (skill-evolution replay against a proposed copy)."""
    return Path(os.environ.get("RECONAI_SKILLS_DIR") or SKILLS_DIR).resolve()


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    status: str
    path: Path
    body: str                 # SKILL.md without frontmatter
    skill_md: str             # full SKILL.md text
    policy_yaml: str
    tools: tuple[str, ...]    # Droid restrict_tools allowlist
    sha: str                  # hash of SKILL.md + policy.yaml + tools.yaml

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


def _frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.strip()
    return {}, text


def load_skill(name: str) -> Skill:
    root = skills_dir()
    path = (root / name).resolve()
    if path.parent != root or not (path / "SKILL.md").exists():
        raise KeyError(f"unknown skill {name!r}")
    md = (path / "SKILL.md").read_text()
    fm, body = _frontmatter(md)
    pol = (path / "policy.yaml").read_text() if (path / "policy.yaml").exists() else ""
    tools_txt = (path / "tools.yaml").read_text() if (path / "tools.yaml").exists() else ""
    tools = tuple((yaml.safe_load(tools_txt) or {}).get("tools", ["Read", "Grep", "Glob", "LS"]))
    sha = hashlib.sha256((md + pol + tools_txt).encode()).hexdigest()[:12]
    return Skill(name=fm.get("name", name), version=str(fm.get("version", "v0")), status=str(fm.get("status", "shadow")),
                 path=path, body=body, skill_md=md, policy_yaml=pol, tools=tools, sha=sha)
