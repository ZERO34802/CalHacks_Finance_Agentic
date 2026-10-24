"""Deterministic scan for instruction-like text inside untrusted documents."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [(n, re.compile(p, re.I)) for n, p in [
    ("ignore_instructions", r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instruction|prompt|rule|polic|guideline|context)"),
    ("approve_and_pay", r"\b(approve|authori[sz]e|release)\b[^.\n]{0,30}\b(and|&|then)\b[^.\n]{0,15}\b(pay|post|remit)"),
    ("auto_approve", r"\bauto[- ]?(approve|pay)\b|\bmark\b[^.\n]{0,20}\bas\s+(approved|paid|verified)\b"),
    ("addressed_to_ai", r"\b(you are|act as|as an?|note to|message to|attention|dear)\b[^.\n]{0,20}\b(ai|assistant|language model|llm|agent|claude|gpt|bot)\b"),
    ("system_prompt", r"\b(system prompt|developer message|new instructions|jailbreak)\b"),
    ("suppress_controls", r"\b(do not|don't|never)\b[^.\n]{0,20}\b(flag|escalate|report|verify|check|hold|review)\b"),
    ("skip_approval", r"\b(skip|bypass|without)\b[^.\n]{0,20}\b(approval|review|verification|validation|controls?|match|check)\b"),
]]


def scan(text: str) -> list[dict]:
    """-> [{'pattern': name, 'quote': matched text}]; empty when nothing instruction-like."""
    hits = []
    flat = re.sub(r"\s+", " ", text or "")  # PDF text wraps mid-sentence
    for name, pat in PATTERNS:
        for m in pat.finditer(flat):
            hits.append({"pattern": name, "quote": m.group(0)[:160]})
    return hits
