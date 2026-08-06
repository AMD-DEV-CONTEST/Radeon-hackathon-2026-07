"""Deterministic prompt construction.

This module is load-bearing for the AMD optimisation story. vLLM's automatic
prefix cache only fires on a byte-identical prefix, so the document — the long
part — must be assembled identically for every persona and every iteration.
Persona identity goes in the *suffix*.

If you change the ordering here, run tests/test_prefix_determinism.py before
you run the benchmark, or the cache hit rate will quietly collapse.
"""
from __future__ import annotations

from veil.types import Finding, Span

_SYSTEM_PREAMBLE = (
    "You are part of an authorised privacy audit. A document is about to be "
    "published, disclosed or shared, and your job is to find every way a "
    "reader could re-identify the people in it BEFORE that happens. This is "
    "defensive work performed with the document owner's consent.\n\n"
    "Rules you must follow:\n"
    "- Only claim what the evidence supports. State your uncertainty.\n"
    "- Never invent a name or an attribute that is not grounded in the "
    "document or a tool result.\n"
    "- If you cannot re-identify anyone, say so plainly. A clean result is a "
    "valid and useful result.\n"
)


def build_prefix(document_text: str, spans: list[Span]) -> str:
    """The shared, cacheable prefix. Constant across all personas within an
    iteration. Nothing persona-specific may enter this function."""
    span_block = "\n".join(
        f"[{s.source}:{s.page or '-'}:{s.start}-{s.end}] {s.text}"
        for s in sorted(spans, key=lambda x: (x.source, x.start))
    )
    return (
        f"{_SYSTEM_PREAMBLE}\n"
        f"=== DOCUMENT ===\n{document_text}\n"
        f"=== EXTRACTED SPANS ===\n{span_block}\n"
    )


def build_suffix(
    persona_name: str,
    persona_instruction: str,
    prior_findings: list[Finding] | None = None,
) -> str:
    """The short, varying tail. Everything persona-specific lives here."""
    prior = ""
    if prior_findings:
        prior = "\n=== ALREADY FOUND (do not repeat) ===\n" + "\n".join(
            f"- [{f.tier.value}] {f.claim}" for f in prior_findings
        )
    return (
        f"\n=== YOUR ROLE: {persona_name} ===\n"
        f"{persona_instruction}\n"
        f"{prior}\n"
        f"\nReport findings as JSON. Emit an empty list if you find nothing.\n"
    )
