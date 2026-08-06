"""Guardian — proposes the smallest edit that defeats a finding.

Blanket redaction is the incumbent behaviour and it is a failure: it destroys
the document's usefulness while frequently leaving the actual leak in place.
The Guardian is scored on the opposite objective — kill the finding, keep the
prose — and its edit taxonomy is ordered by how much context each option costs.

Every proposed edit is validated against the live document before it is
returned, so an edit whose span has drifted is rejected here rather than
silently corrupting the text downstream.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from veil.agents.personas import GUARDIAN_INSTRUCTION
from veil.inference.client import VLLMClient
from veil.inference.prefix import build_prefix
from veil.types import Edit, EditType, Finding, Span, Tier

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_EDIT_CONTRACT = """
Output a JSON array of edits and nothing else:

[
  {
    "finding_id": "<id you are repairing>",
    "edit_type": "generalize" | "pseudonymize" | "suppress" | "restructure",
    "original": "<exact text from the document to replace>",
    "replacement": "<what to put in its place>",
    "rationale": "<why this is the smallest edit that works>"
  }
]

"original" must be copied character-for-character from the document. If you
cannot find text that carries the leak, return an edit with edit_type
"restructure" and explain in the rationale.
"""

# Aggressiveness ceilings. At low aggressiveness we will not restructure prose,
# because rewriting someone's sentences to defeat stylometry is a large cost to
# impose for a Tier S suggestion.
_ALLOWED_BY_LEVEL: dict[str, set[EditType]] = {
    "low": {EditType.GENERALIZE, EditType.PSEUDONYMIZE},
    "balanced": {EditType.GENERALIZE, EditType.PSEUDONYMIZE, EditType.SUPPRESS},
    "high": set(EditType),
}


@dataclass
class RepairPlan:
    edits: list[Edit] = field(default_factory=list)
    unrepaired: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for e in self.edits:
            by_type[e.edit_type.value] = by_type.get(e.edit_type.value, 0) + 1
        return {
            "edits": len(self.edits),
            "by_type": by_type,
            "unrepaired": len(self.unrepaired),
            "rejected": len(self.rejected),
        }


def _extract(text: str) -> list[dict[str, Any]]:
    block = _JSON_BLOCK.search(text)
    candidate = block.group(1) if block else text
    start, end = candidate.find("["), candidate.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _findings_block(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        quoted = " | ".join(s.text for s in f.spans[:3]) or "(no located span)"
        lines.append(
            f"- id={f.id} tier={f.tier.value} severity={f.severity}\n"
            f"  claim: {f.claim}\n"
            f"  leaking text: {quoted}"
        )
    return "\n".join(lines)


class Guardian:
    def __init__(self, client: VLLMClient) -> None:
        self.client = client

    async def repair(
        self,
        document_text: str,
        spans: list[Span],
        findings: list[Finding],
        aggressiveness: str = "balanced",
        overrides: dict[str, str] | None = None,
    ) -> RepairPlan:
        plan = RepairPlan()
        overrides = overrides or {}
        targets = [
            f for f in findings 
            if not f.resolved and f.severity >= 0.3 and overrides.get(f.id) != "reject"
        ]
        if not targets:
            return plan

        allowed = set(_ALLOWED_BY_LEVEL.get(aggressiveness, _ALLOWED_BY_LEVEL["balanced"]))
        for etype_str in overrides.values():
            if etype_str != "reject":
                try:
                    allowed.add(EditType(etype_str))
                except ValueError:
                    pass

        override_instructions = ""
        if overrides:
            override_instructions = "\n=== USER CUSTOM OVERRIDES ===\n" + "\n".join(
                f"- For finding {fid}, you must use edit type: {etype}"
                for fid, etype in overrides.items() if etype != "reject"
            ) + "\n"

        # Prefix stays byte-identical to the adversaries' prefix so the KV cache
        # carries straight over into the repair pass.
        prefix = build_prefix(document_text, spans)
        suffix = (
            "\n=== YOUR ROLE: Guardian ===\n"
            f"{GUARDIAN_INSTRUCTION}\n"
            f"\nAggressiveness: {aggressiveness}. "
            f"Permitted edit types: {', '.join(sorted(t.value for t in allowed))}.\n"
            f"{override_instructions}"
            f"\n=== FINDINGS TO REPAIR ===\n{_findings_block(targets)}\n"
            f"{_EDIT_CONTRACT}"
        )

        text, _ = await self.client.complete(prefix, suffix, max_tokens=1536)
        proposals = _extract(text)
        by_id = {f.id: f for f in targets}
        repaired: set[str] = set()

        for item in proposals:
            edit = self._build(item, document_text, allowed, by_id)
            if isinstance(edit, Edit):
                plan.edits.append(edit)
                repaired.add(edit.finding_id)
            else:
                plan.rejected.append(edit)

        for f in targets:
            if f.id not in repaired:
                plan.unrepaired.append(
                    {"finding_id": f.id, "tier": f.tier.value, "claim": f.claim}
                )

        return plan

    def _build(
        self,
        item: dict[str, Any],
        document: str,
        allowed: set[EditType],
        by_id: dict[str, Finding],
    ) -> Edit | dict[str, Any]:
        fid = str(item.get("finding_id", "")).strip()
        if fid not in by_id:
            return {"item": item, "reason": f"unknown finding_id {fid!r}"}

        try:
            etype = EditType(str(item.get("edit_type", "")).lower().strip())
        except ValueError:
            return {"item": item, "reason": f"unknown edit_type {item.get('edit_type')!r}"}

        if etype not in allowed:
            return {
                "item": item,
                "reason": f"{etype.value} not permitted at this aggressiveness level",
            }

        original = str(item.get("original", ""))
        if not original:
            return {"item": item, "reason": "no original text given"}

        idx = document.find(original)
        if idx == -1:
            loose = re.escape(original.strip()).replace(r"\ ", r"\s+")
            m = re.search(loose, document)
            if not m:
                return {"item": item, "reason": "original text not present in document"}
            idx, original = m.start(), m.group(0)

        replacement = str(item.get("replacement", ""))
        if etype is not EditType.SUPPRESS and not replacement:
            return {"item": item, "reason": f"{etype.value} requires a replacement"}

        # A "generalize" that removes everything is a suppression wearing a
        # nicer label; make the taxonomy mean what it says.
        if etype is EditType.GENERALIZE and len(replacement) < len(original) * 0.15:
            return {
                "item": item,
                "reason": "replacement too short to be a generalisation — use suppress",
            }

        return Edit(
            finding_id=fid,
            edit_type=etype,
            span=Span(start=idx, end=idx + len(original), text=original),
            replacement=replacement,
            rationale=str(item.get("rationale", "")).strip(),
        )
