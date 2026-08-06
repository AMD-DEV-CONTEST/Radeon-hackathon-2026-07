"""Planner — decides which personas to run before spending a GPU on them.

The orchestrator's default is to run all five personas every iteration. That is
the right default, but it is wasteful in two specific cases the demo will hit:

  - A .txt or .md input has no container to examine. The Layout-Forensicist has
    literally nothing to do: no metadata dictionary, no redaction rectangles,
    no revision history. Running it costs a full generation and returns [].
  - A three-sentence document does not support stylometry. The Stylometrist
    needs enough text to characterise idiolect; below the floor it either
    returns nothing or — worse — invents a confident-sounding attribution from
    noise, which is exactly the failure mode Tier S exists to contain.

So the planner triages first, on cheap local signals only. No model call: this
runs in microseconds off the file extension, the character count, and what the
loader already found. A planner that needed the GPU to decide how to use the
GPU would be self-defeating.

It also allocates the iteration budget. A document that comes back CRITICAL on
iteration 1 has earned its full three passes; one that comes back LOW has not,
and on a 24-hour clock with a live demo those saved passes are the difference
between a run that fits in the slot and one that doesn't.

Design constraint worth stating explicitly: the planner may only ever REMOVE a
persona that cannot produce evidence, never one that merely seems unlikely to.
"Probably won't find anything" is the adversary's reasoning, not ours. If a
persona could in principle produce a finding, it runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veil.agents.personas import ALL_PERSONAS, Persona
from veil.types import Span

# Below this many characters, stylometric attribution is noise. Chosen from the
# authorship-attribution literature's rough consensus that reliable idiolect
# characterisation needs several hundred words; we set the floor generously low
# so we skip only the cases that are indefensible.
_STYLOMETRY_FLOOR_CHARS = 1200

# Container formats that carry metadata, revision history, or drawn geometry.
_STRUCTURED_SUFFIXES = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".odt"}


@dataclass
class Plan:
    """What the orchestrator should actually do with this document."""

    personas: tuple[Persona, ...]
    max_iterations: int
    skipped: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "personas": [p.name for p in self.personas],
            "max_iterations": self.max_iterations,
            "skipped": self.skipped,
            "notes": self.notes,
        }


def _has_structure(source_path: str | None, spans: list[Span]) -> bool:
    """Is there a container worth examining?

    Two independent signals, because either alone is fooled. A .pdf extension
    on a file the loader could not parse gives nothing; conversely a document
    whose spans already carry metadata or underlay evidence is worth attacking
    regardless of what its extension says.
    """
    if any(s.source in {"metadata", "redaction_underlay", "revision"} for s in spans):
        return True
    if source_path and Path(source_path).suffix.lower() in _STRUCTURED_SUFFIXES:
        return True
    return False


def plan(
    document_text: str,
    spans: list[Span],
    source_path: str | None = None,
    requested_iterations: int | None = None,
    personas: tuple[Persona, ...] = ALL_PERSONAS,
) -> Plan:
    """Triage a document into an execution plan. Cheap, local, no model call."""
    selected: list[Persona] = []
    skipped: list[dict[str, str]] = []
    notes: list[str] = []

    structured = _has_structure(source_path, spans)
    long_enough = len(document_text) >= _STYLOMETRY_FLOOR_CHARS

    for persona in personas:
        if persona.name == "Layout-Forensicist" and not structured:
            skipped.append(
                {
                    "persona": persona.name,
                    "reason": (
                        "Plain-text input has no container to examine — no metadata, "
                        "no drawn rectangles, no revision history."
                    ),
                }
            )
            continue
        if persona.name == "Stylometrist" and not long_enough:
            skipped.append(
                {
                    "persona": persona.name,
                    "reason": (
                        f"Document is {len(document_text)} chars; below the "
                        f"{_STYLOMETRY_FLOOR_CHARS}-char floor, stylometric "
                        "attribution is indistinguishable from noise."
                    ),
                }
            )
            continue
        selected.append(persona)

    if structured:
        notes.append("Structured container detected — mechanical evidence path is live.")
    if not selected:
        # Belt and braces. Cannot happen with the current rules, but a future
        # rule that empties the list would silently produce a run with no
        # attackers and a reassuring risk score of zero. That failure is far
        # worse than a wasted generation.
        notes.append("All personas filtered out; falling back to the full set.")
        selected = list(personas)
        skipped = []

    return Plan(
        personas=tuple(selected),
        max_iterations=requested_iterations or 3,
        skipped=skipped,
        notes=notes,
    )


def revise_budget(plan_: Plan, residual_risk: float, iteration: int) -> int:
    """How many more iterations does this document deserve?

    Called after each scoring pass. Returns the revised ceiling. Repair is not
    free — every edit costs utility — so a document that is already close to
    clean should stop rather than grind away at Tier S findings that were only
    ever suggestive.
    """
    if residual_risk >= 0.6:
        return plan_.max_iterations          # critical: use the whole budget
    if residual_risk >= 0.3:
        return min(plan_.max_iterations, iteration + 1)
    return iteration                          # low risk: this pass was the last
