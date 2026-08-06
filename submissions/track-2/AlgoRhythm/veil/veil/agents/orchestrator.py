"""Orchestrator — the attack/adjudicate/repair/re-attack loop.

This is the control flow the whole project turns on:

    for iteration in 1..N:
        run all five personas CONCURRENTLY against the current document
        adjudicate their findings into one defensible list
        Guardian proposes minimal edits
        apply edits -> new document version
        re-attack: a finding is only resolved when every persona fails to
                   reproduce it against the repaired text

The concurrency is not incidental. Five personas share one byte-identical
prefix, so vLLM computes the document's KV once and reuses it across all five
— which is why five 14B agents fit on one Radeon GPU at all. See
inference/prefix.py before changing anything about prompt assembly.

Progress is emitted through an async callback so the UI can narrate the attack
live rather than showing a spinner for ninety seconds.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from veil.agents.adjudicator import Adjudication, adjudicate
from veil.agents.adversary import Adversary
from veil.agents.guardian import Guardian, RepairPlan
from veil.agents.personas import ALL_PERSONAS, Persona
from veil.agents.planner import plan as make_plan
from veil.agents.planner import revise_budget
from veil.config import CONFIG
from veil.inference.client import MetricsCollector, VLLMClient
from veil.scoring import risk as risk_scoring
from veil.scoring import utility as utility_scoring
from veil.security.audit import AuditLog
from veil.tools.redact_apply import apply_edits
from veil.types import Finding, IterationResult, Span, content_hash

ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RunReport:
    document_id: str
    original_text: str
    final_text: str
    iterations: list[IterationResult] = field(default_factory=list)
    curve: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    stopped_because: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "iterations": len(self.iterations),
            "curve": self.curve,
            "stopped_because": self.stopped_because,
            "metrics": self.metrics,
            "plan": self.plan,
            "final_residual_risk": self.curve[-1]["residual_risk"] if self.curve else None,
            "final_utility": self.curve[-1]["utility_retained"] if self.curve else None,
        }


class Orchestrator:
    def __init__(
        self,
        personas: tuple[Persona, ...] = ALL_PERSONAS,
        audit: AuditLog | None = None,
        on_progress: ProgressFn | None = None,
    ) -> None:
        self.personas = personas
        self.metrics = MetricsCollector()
        self.client = VLLMClient(metrics=self.metrics)
        self.guardian = Guardian(self.client)
        self.audit = audit
        self.on_progress = on_progress
        self._sem = asyncio.Semaphore(CONFIG.orchestrator.max_concurrent_personas)
    async def custom_repair_and_verify(
        self,
        document_text: str,
        spans: list[Span],
        findings: list[Finding],
        aggressiveness: str,
        overrides: dict[str, str],
        source_path: str | None = None,
    ) -> tuple[str, list[Finding], float, float]:
        """Custom human-in-the-loop repair and verification.
        
        Applies custom user overrides to edit proposals, regenerates the document,
        runs a fresh re-attack wave to verify remaining findings, and recomputes risk/utility.
        """
        plan = await self.guardian.repair(
            document_text, spans, findings, aggressiveness, overrides
        )
        applied_text = document_text
        if plan.edits:
            applied = apply_edits(document_text, plan.edits)
            applied_text = applied.text

        current_spans = [
            Span(start=0, end=len(applied_text), text=applied_text, page=None, source="body")
        ]
        verified = await self._verify(findings, applied_text, current_spans, source_path)
        
        # Mark findings as resolved based on verification re-attack results
        surviving = {f.claim for f in verified.accepted}
        for f in findings:
            f.resolved = f.claim not in surviving
            
        r = risk_scoring.score(verified.accepted)
        u = utility_scoring.score(document_text, applied_text)
        return applied_text, findings, r.value, u.value

    async def _emit(self, event: str, **payload: Any) -> None:
        if self.on_progress:
            await self.on_progress({"event": event, **payload})

    async def _run_persona(
        self,
        persona: Persona,
        text: str,
        spans: list[Span],
        prior: list[Finding],
        source_path: str | None,
    ) -> list[Finding]:
        async with self._sem:
            await self._emit("persona_start", persona=persona.name)
            started = time.perf_counter()
            adversary = Adversary(persona, self.client)
            try:
                result = await adversary.attack(text, spans, prior, source_path)
            except Exception as exc:  # noqa: BLE001 - one persona failing must not kill the run
                await self._emit("persona_error", persona=persona.name, error=str(exc))
                return []
            await self._emit(
                "persona_done",
                persona=persona.name,
                findings=len(result.findings),
                tool_calls=result.tool_calls,
                rejected=len(result.rejected),
                elapsed_s=round(time.perf_counter() - started, 2),
            )
            return result.findings

    async def _attack_wave(
        self,
        text: str,
        spans: list[Span],
        prior: list[Finding],
        source_path: str | None,
        personas: tuple[Persona, ...] | None = None,
    ) -> list[Finding]:
        """All personas, concurrently, against one shared prefix."""
        wave = personas if personas is not None else self.personas
        results = await asyncio.gather(
            *(self._run_persona(p, text, spans, prior, source_path) for p in wave)
        )
        return [f for group in results for f in group]

    async def _verify(
        self,
        findings: list[Finding],
        text: str,
        spans: list[Span],
        source_path: str | None,
        personas: tuple[Persona, ...] | None = None,
    ) -> Adjudication:
        """Re-attack the repaired document.

        A finding is resolved only if the re-attack fails to reproduce it. This
        is what makes the system self-validating rather than self-congratulatory.
        """
        await self._emit("verify_start", target_count=len(findings))
        fresh = await self._attack_wave(
            text, spans, prior=[], source_path=source_path, personas=personas
        )
        return adjudicate(fresh)

    async def run(
        self,
        document_text: str,
        spans: list[Span],
        source_path: str | None = None,
        max_iterations: int | None = None,
        aggressiveness: str = "balanced",
        target_risk: float = 0.15,
    ) -> RunReport:
        max_iterations = max_iterations or CONFIG.orchestrator.max_iterations
        doc_id = content_hash(document_text)[:12]
        report = RunReport(doc_id, document_text, document_text)

        # Triage before spending a GPU: which personas can actually produce
        # evidence against this document, and how many passes does it deserve?
        execution = make_plan(
            document_text, spans, source_path, max_iterations, self.personas
        )
        wave = execution.personas
        budget = execution.max_iterations
        report.plan = execution.summary()
        await self._emit("planned", **execution.summary())

        if self.audit:
            self.audit.append(
                "run_start",
                {
                    "document_id": doc_id,
                    "chars": len(document_text),
                    "plan": execution.summary(),
                },
            )

        current = document_text
        current_spans = spans
        carried: list[Finding] = []
        iteration = 0

        while iteration < budget:
            iteration += 1
            started = time.perf_counter()
            await self._emit("iteration_start", iteration=iteration, budget=budget)

            raw = await self._attack_wave(
                current, current_spans, carried, source_path, personas=wave
            )
            verdict = adjudicate(raw)
            await self._emit("adjudicated", iteration=iteration, **verdict.summary())

            r = risk_scoring.score(verdict.accepted)
            u = utility_scoring.score(document_text, current)
            elapsed = round(time.perf_counter() - started, 2)

            report.iterations.append(
                IterationResult(
                    iteration=iteration,
                    findings=verdict.accepted,
                    residual_risk=r.value,
                    utility_retained=u.value,
                    elapsed_s=elapsed,
                )
            )
            report.curve.append(
                {
                    "iteration": iteration,
                    "residual_risk": r.value,
                    "risk_band": r.band,
                    "utility_retained": u.value,
                    "findings": len(verdict.accepted),
                    "elapsed_s": elapsed,
                    **u.as_dict(),
                }
            )
            if self.audit:
                self.audit.append(
                    "iteration",
                    {"iteration": iteration, "risk": r.as_dict(), "utility": u.as_dict()},
                )
            await self._emit("scored", iteration=iteration, risk=r.as_dict(), utility=u.as_dict())

            if r.value <= target_risk:
                report.stopped_because = f"Residual risk {r.value} met target {target_risk}."
                break
            if not verdict.accepted:
                report.stopped_because = "No findings survived adjudication."
                break

            # Repair costs utility, so a nearly-clean document should stop
            # rather than grind at findings that were only ever suggestive.
            revised = revise_budget(execution, r.value, iteration)
            if revised != budget:
                await self._emit(
                    "budget_revised", iteration=iteration, was=budget, now=revised
                )
                budget = revised

            plan: RepairPlan = await self.guardian.repair(
                current, current_spans, verdict.accepted, aggressiveness
            )
            await self._emit("repaired", iteration=iteration, **plan.summary())

            if not plan.edits:
                report.stopped_because = (
                    "Guardian proposed no applicable edits; remaining findings "
                    "need a human decision."
                )
                carried = verdict.accepted
                break

            applied = apply_edits(current, plan.edits)
            current = applied.text
            # Offsets have moved; re-locating every span is not worth it mid-run,
            # so subsequent iterations work from body text only.
            current_spans = [
                Span(start=0, end=len(current), text=current, page=None, source="body")
            ]
            if self.audit:
                self.audit.append(
                    "edits_applied",
                    {
                        "iteration": iteration,
                        "applied": applied.applied,
                        "skipped": applied.skipped,
                        "version_hash": applied.version_hash,
                    },
                )

            if iteration >= budget:
                verified = await self._verify(
                    verdict.accepted, current, current_spans, source_path, personas=wave
                )
                surviving = {f.claim for f in verified.accepted}
                for f in verdict.accepted:
                    f.resolved = f.claim not in surviving
                carried = verified.accepted
                final_r = risk_scoring.score(verified.accepted)
                final_u = utility_scoring.score(document_text, current)
                report.curve.append(
                    {
                        "iteration": iteration + 1,
                        "residual_risk": final_r.value,
                        "risk_band": final_r.band,
                        "utility_retained": final_u.value,
                        "findings": len(verified.accepted),
                        "verified": True,
                        **final_u.as_dict(),
                    }
                )
                report.stopped_because = "Iteration budget reached; final state verified by re-attack."
            else:
                carried = verdict.accepted

        # Extract entities to populate the cross-document entity ledger
        try:
            from veil.tools.entity_ledger import record_mention
            from veil.agents.adversary import _extract_json
            
            extract_prompt = (
                "You are an entity extraction assistant. Identify any key individuals (persons) "
                "in the document and return their canonical names and attributes (like job title, city, tenure) "
                "in this exact JSON format:\n\n"
                "[\n"
                "  {\n"
                "    \"canonical\": \"J. Okafor\",\n"
                "    \"kind\": \"person\",\n"
                "    \"surface\": \"Okafor\",\n"
                "    \"attributes\": {\n"
                "      \"job_title\": \"Director of Governance\",\n"
                "      \"city\": \"Bristol\"\n"
                "    }\n"
                "  }\n"
                "]\n\n"
                "Only return the JSON list, no other text."
            )
            
            payload, _ = await self.client.complete(
                prefix=extract_prompt,
                suffix=f"=== DOCUMENT ===\n{document_text}"
            )
            parsed = _extract_json(payload)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        canonical = item.get("canonical")
                        kind = item.get("kind", "person")
                        surface = item.get("surface", canonical or "")
                        attrs = item.get("attributes", {})
                        if canonical:
                            record_mention(
                                canonical=str(canonical),
                                kind=str(kind),
                                document_id=doc_id,
                                surface=str(surface),
                                attributes=attrs
                            )
        except Exception:
            pass # extraction errors must not block report generation

        report.final_text = current
        report.metrics = self.metrics.summary()
        try:
            report.metrics["prefix_cache"] = await self.client.prefix_cache_stats()
        except Exception:  # noqa: BLE001 - metrics are never load-bearing
            pass

        if self.audit:
            self.audit.append("run_end", report.as_dict())
        await self._emit("run_complete", **report.as_dict())
        return report
