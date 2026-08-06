"""Adversary agent — one persona, one attack pass.

The adversary runs a bounded tool-use loop: think, call tools, think again,
then emit findings as JSON. The loop is bounded by the persona's tool budget
rather than by a turn count, because a persona that burns its budget has
already told us what it can see.

Findings are constructed through veil.types.Finding, so the tier invariants
(Tier C needs a candidate-set size, Tier S needs a caveat) reject malformed
output at the boundary rather than letting it reach the UI.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from veil.agents.personas import Persona
from veil.config import CONFIG
from veil.inference.client import VLLMClient
from veil.inference.prefix import build_prefix, build_suffix
from veil.tools.registry import REGISTRY, ToolBudgetExceeded, ToolNotPermitted
from veil.types import Finding, Span, Tier

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_OUTPUT_CONTRACT = """
When you have finished investigating, output a JSON array and nothing else:

[
  {
    "claim": "one sentence: what you concluded",
    "reasoning": "how you got there, naming tool results (extremely concise, 1-2 sentences maximum)",
    "tier": "M" | "C" | "S",
    "severity": 0.0-1.0,
    "candidate_set_size": <integer, REQUIRED for tier C>,
    "caveat": "<string, REQUIRED for tier S>",
    "quotes": ["exact text from the document that carries the leak"]
  }
]

An empty array is a valid and useful answer. Do not pad it.
To call a tool instead, output exactly:
TOOL: <tool_name> <json arguments>
"""

_TOOL_LINE = re.compile(r"TOOL:\s*(\w+)\s*(\{.*\})", re.DOTALL)


@dataclass
class AttackResult:
    persona: str
    findings: list[Finding] = field(default_factory=list)
    tool_calls: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    raw: str = ""


def _extract_json(text: str) -> Any:
    block = _JSON_BLOCK.search(text)
    candidate = block.group(1) if block else text
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def _locate(quote: str, document: str) -> Span | None:
    idx = document.find(quote)
    if idx == -1:
        # Whitespace in extracted PDF text rarely survives round-tripping.
        loose = re.escape(quote.strip()).replace(r"\ ", r"\s+")
        m = re.search(loose, document)
        if not m:
            return None
        idx, quote = m.start(), m.group(0)
    return Span(start=idx, end=idx + len(quote), text=quote)


class Adversary:
    def __init__(self, persona: Persona, client: VLLMClient) -> None:
        self.persona = persona
        self.client = client
        self.tools = REGISTRY.for_persona(
            persona.name,
            persona.tools,
            CONFIG.orchestrator.per_persona_tool_call_budget,
        )

    async def attack(
        self,
        document_text: str,
        spans: list[Span],
        prior_findings: list[Finding] | None = None,
        source_path: str | None = None,
    ) -> AttackResult:
        prefix = build_prefix(document_text, spans)
        instruction = self.persona.instruction
        if self.persona.tools:
            names = ", ".join(self.persona.tools)
            instruction += (
                f"\n\nTools available to you: {names}. "
                f"Budget: {self.tools.budget} calls."
            )
            if source_path:
                instruction += f"\nThe source file is at: {source_path}"
        instruction += "\n" + _OUTPUT_CONTRACT

        suffix = build_suffix(self.persona.name, instruction, prior_findings)
        transcript: list[str] = []
        result = AttackResult(persona=self.persona.name)

        # Bounded loop: budget + 1 gives one turn to write findings after the
        # last tool call.
        for _ in range(self.tools.budget + 1):
            tail = suffix + ("\n" + "\n".join(transcript) if transcript else "")
            text, _metrics = await self.client.complete(prefix, tail)
            result.raw = text

            m = _TOOL_LINE.search(text)
            if m and self.persona.tools:
                name, arg_json = m.group(1), m.group(2)
                try:
                    args = json.loads(arg_json)
                except json.JSONDecodeError as exc:
                    transcript.append(f"TOOL {name} ERROR: malformed arguments ({exc})")
                    continue
                try:
                    out = await self.tools.call(name, args)
                    result.tool_calls += 1
                    transcript.append(
                        f"TOOL {name} RESULT: {json.dumps(out, default=str)[:1800]}"
                    )
                except (ToolNotPermitted, ToolBudgetExceeded) as exc:
                    transcript.append(f"TOOL {name} REFUSED: {exc}")
                except Exception as exc:  # noqa: BLE001 - the model should see failures
                    transcript.append(f"TOOL {name} ERROR: {type(exc).__name__}: {exc}")
                continue

            parsed = _extract_json(text)
            if parsed is None:
                transcript.append(
                    "SYSTEM: Your last output was neither a TOOL line nor a JSON "
                    "array. Emit the JSON array now."
                )
                continue

            for item in parsed if isinstance(parsed, list) else []:
                if not isinstance(item, dict):
                    result.rejected.append({"item": item, "reason": "not a dict"})
                    continue
                finding = self._build(item, document_text)
                if isinstance(finding, Finding):
                    result.findings.append(finding)
                else:
                    result.rejected.append(finding)
            break

        return result

    def _build(self, item: dict[str, Any], document: str) -> Finding | dict[str, Any]:
        """Construct a Finding, or return a rejection record explaining why not.

        A persona that cannot meet its tier's evidential burden does not get to
        publish. That is the whole design.
        """
        try:
            tier = Tier(str(item.get("tier", "")).upper().strip())
        except ValueError:
            return {"item": item, "reason": f"unknown tier {item.get('tier')!r}"}

        spans = []
        for q in item.get("quotes", []) or []:
            located = _locate(str(q), document)
            if located:
                spans.append(located)

        try:
            return Finding(
                persona=self.persona.name,
                tier=tier,
                claim=str(item.get("claim", "")).strip(),
                reasoning=str(item.get("reasoning", "")).strip(),
                spans=spans,
                severity=float(item.get("severity", 0.5) or 0.5),
                candidate_set_size=item.get("candidate_set_size"),
                caveat=item.get("caveat"),
            )
        except (ValueError, TypeError) as exc:
            return {"item": item, "reason": str(exc)}
