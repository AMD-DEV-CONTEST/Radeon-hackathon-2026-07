"""
CIAAgent — ties planning (planner.py), tool invocation (tools.py), and local
LLM classification (llm_client.py) into a single orchestrator.

Why the LLM classifies structured module output rather than driving a ReAct
tool-calling loop: the fine-tuned model (Qwen3-14B QLoRA) was trained on
358,000+ structured CIA/V5/V6 scan-evidence records to predict a verdict from
exactly that kind of structured input (read-only reference:
Syndicate-Protocol/README.md). Wrapping it in a free-form ReAct loop would
ask a quantized local 14B model to reliably emit tool-call syntax it was
never trained to produce, which is fragile. Instead:

  1. TaskPlanner decides which tools to call and in what order (multi-step
     planning, explicit and inspectable).
  2. Tools run (7 CIA modules via LangChain StructuredTool).
  3. The local LLM reads the aggregated structured findings and produces the
     final natural-language verdict + reasoning — the exact task shape it
     was fine-tuned for.

This keeps "tool invocation" (capability #1) and "multi-step task planning"
(capability #2) as clean, LangChain-native, inspectable steps, and uses local
inference (capability requirement) for the part of the pipeline where an LLM
actually adds value over the deterministic engine.

Guardrail: the current fine-tuned checkpoint is an early/trial run and known
to hallucinate on some inputs (see docs/PROJECT_SPEC.md "Model Status &
Roadmap"). scan_with_verdict() does not return the LLM's verdict as-is — it
also computes a deterministic, LLM-free baseline risk level directly from
the raw findings (risk_baseline.py) and flags any disagreement, so a wrong
LLM answer shows up as "needs review" rather than standing unchallenged.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

from .planner import Plan, ScanRequest, TaskPlanner
from .risk_baseline import check_guardrail, compute_baseline_risk
from .tools import TOOLS_BY_NAME

VERDICT_PROMPT_TEMPLATE = """You are the RugBuster CIA Intelligence Engine's fraud classifier.
You are given structured on-chain findings for one token, gathered by 7 detection modules.
Some modules may be missing (see skipped_modules) — treat missing modules as reduced confidence, not as a clean signal.

Findings (JSON):
{findings_json}

Skipped modules:
{skipped_json}

Respond with a verdict of GOOD, WARN, or DANGER, followed by a one-paragraph explanation
citing the specific findings that drove the verdict.
"""


@dataclass
class ScanResult:
    request: dict[str, Any]
    plan: list[dict[str, Any]]
    skipped_modules: list[dict[str, str]]
    findings: dict[str, Any]
    verdict_text: Optional[str]
    baseline_risk: Optional[dict[str, Any]] = None
    guardrail: Optional[dict[str, Any]] = None


class CIAAgent:
    """The agent: plans, invokes tools, then (optionally) classifies with the local LLM."""

    def __init__(self, llm_factory: Optional[Callable[[], Any]] = None):
        self._planner = TaskPlanner()
        # llm_factory is lazy so importing/instantiating CIAAgent never requires
        # llama-cpp-python or a downloaded model unless run_with_verdict() is called.
        self._llm_factory = llm_factory

    def plan(self, request: ScanRequest) -> Plan:
        return self._planner.plan(request)

    def run_tools(self, plan: Plan) -> dict[str, Any]:
        findings: dict[str, Any] = {}
        for step in plan.steps:
            tool = TOOLS_BY_NAME[step.tool_name]
            findings[step.tool_name] = tool.invoke(step.args)
        return findings

    def scan(self, request: ScanRequest) -> ScanResult:
        """Plan + invoke tools only. No LLM call — deterministic, fast, GPU-free."""
        plan = self.plan(request)
        findings = self.run_tools(plan)
        return ScanResult(
            request=asdict(request),
            plan=[{"tool": s.tool_name, "args": s.args, "rationale": s.rationale} for s in plan.steps],
            skipped_modules=plan.skipped_modules,
            findings=findings,
            verdict_text=None,
        )

    def scan_with_verdict(self, request: ScanRequest) -> ScanResult:
        """
        Full pipeline: plan + tools + local LLM verdict, cross-checked against
        the deterministic baseline (see module docstring / risk_baseline.py).
        Requires the local model.
        """
        result = self.scan(request)
        result.baseline_risk = compute_baseline_risk(result.findings)

        llm = (self._llm_factory or self._default_llm_factory)()
        prompt = VERDICT_PROMPT_TEMPLATE.format(
            findings_json=json.dumps(result.findings, indent=2, default=str),
            skipped_json=json.dumps(result.skipped_modules, indent=2),
        )
        result.verdict_text = llm.invoke(prompt)
        result.guardrail = check_guardrail(result.verdict_text, result.baseline_risk)
        return result

    @staticmethod
    def _default_llm_factory():
        from .llm_client import build_llm

        return build_llm()
