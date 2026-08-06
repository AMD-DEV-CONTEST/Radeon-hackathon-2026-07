"""Agent 3: Deep Verifier - Triple Cross-Validation

Implements three verification strategies:
1. Tool cross-validation (Semgrep + pattern matching confirmation)
2. Knowledge base cross-validation (CWE/CVE lookup via local SQLite database)
3. Memory-based validation (recall known patterns, suppress false positives)

Also implements the self-reflection loop: if Agent 2 missed something,
Agent 3 can flag it and trigger re-analysis.
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console

from core.cve_client import CVEClient
from core.llm_client import LLMClient
from core.memory import MemoryLayer
from core.models import (
    CodeFile,
    Confidence,
    Evidence,
    ReflectionResponse,
    Risk,
    Severity,
)

console = Console()

# Thresholds for confidence adjustment
HIGH_CONFIRMATIONS = 2
MEDIUM_CONFIRMATIONS = 1

REFLECTION_PROMPT = """You are a security verification expert. Given a code file and a list of risks found by static + semantic analysis, your job is to:

1. VERIFY each risk: Is it confirmed by multiple sources?
2. FIND MISSED vulnerabilities: Are there risks the previous agents missed?
3. FLAG FALSE POSITIVES: Are any risks likely wrong?

For each risk, assess:
- Is the evidence strong? (multiple independent sources agree?)
- Is the attack scenario realistic?
- Would a real attacker exploit this?

Output JSON:
{
  "verified_risks": [
    {
      "id": "RISK-001",
      "confirmed": true,
      "confidence_reason": "Both static analysis and LLM agree this is a real vulnerability",
      "false_positive_likelihood": "low"
    }
  ],
  "missed_risks": [
    {
      "title": "...",
      "description": "...",
      "severity": "critical|high|medium|low",
      "cwe_id": "CWE-xxx",
      "line_start": 10,
      "line_end": 10,
      "reasoning": "Why this was missed by previous agents"
    }
  ]
}"""


class DeepVerifier:
    """Agent 3: Deep verification with triple cross-validation and self-reflection."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        memory: Optional[MemoryLayer] = None,
        cve_client: Optional[CVEClient] = None,
        max_reflection_rounds: int = 2,
    ):
        self.llm = llm_client
        self.memory = memory or MemoryLayer()
        self.cve = cve_client or CVEClient()
        self.max_reflection_rounds = max_reflection_rounds

    def verify_batch(
        self,
        files: list[CodeFile],
        risks: list[Risk],
    ) -> list[Risk]:
        """Verify all risks across all files."""
        if not risks:
            return risks

        console.print("[bold cyan]  Agent 3: Deep verification...[/]")

        # Pre-fetch CVE data for all unique CWEs (batch, avoid N+1 queries)
        critical_cwes = {
            r.cwe_id for r in risks
            if r.cwe_id and r.severity in (Severity.CRITICAL, Severity.HIGH)
        }
        for cwe in critical_cwes:
            try:
                self.cve.get_cve_summary(cwe)
            except Exception:
                pass  # best-effort

        verified_risks = []
        suppressed = 0

        for risk in risks:
            # Check memory first
            memory_result = self.memory.recall(risk)

            if memory_result:
                entry, mem_type = memory_result
                if mem_type == "error" and entry.source_count >= 2:
                    # Known false positive - suppress
                    if risk.id not in [r.id for r in verified_risks]:
                        suppressed += 1
                        continue
                elif mem_type == "correct":
                    # Known true positive - boost confidence
                    if risk.confidence != Confidence.HIGH:
                        risk = risk.model_copy(update={"confidence": Confidence.HIGH})

            # Triple cross-validation
            verified = self._verify_single_risk(risk)
            verified_risks.append(verified)

            # Store in appropriate memory
            if verified.confidence == Confidence.HIGH:
                self.memory.store_correct(verified)

        if suppressed > 0:
            console.print(f"  [dim]  Suppressed {suppressed} known false positives[/]")

        # Self-reflection: ask LLM to find missed risks (ITERATIVE)
        if self.llm:
            for f in files:
                file_risks = [r for r in verified_risks if r.file_path == f.path]
                all_new_risks: list[Risk] = []
                current_risks = list(file_risks)

                for round_num in range(self.max_reflection_rounds):
                    missed = self._reflect_on_file(f, current_risks)
                    if not missed:
                        if round_num > 0:
                            console.print(
                                f"  [dim]  Reflection converged after {round_num + 1} rounds[/]"
                            )
                        break

                    console.print(
                        f"  [yellow]  Agent 3 round {round_num + 1}: "
                        f"found {len(missed)} more risks in {f.path}[/]"
                    )
                    all_new_risks.extend(missed)
                    current_risks = current_risks + missed

                verified_risks.extend(all_new_risks)

        return verified_risks

    def _verify_single_risk(self, risk: Risk) -> Risk:
        """Triple cross-validation for a single risk."""
        confirmations = 0
        reasons = []

        # Strategy 1: Tool cross-validation
        has_semgrep = any(e.source == "semgrep" for e in risk.evidence)
        has_pattern = any(e.source == "pattern_match" for e in risk.evidence)
        has_ai = any(e.source == "ai" for e in risk.evidence)

        if has_semgrep:
            confirmations += 1
            reasons.append("confirmed by Semgrep")

        if has_pattern:
            confirmations += 1
            reasons.append("confirmed by pattern matching")

        if has_ai:
            confirmations += 1
            reasons.append("confirmed by LLM analysis")

        # Strategy 2: Knowledge base cross-validation (CVE lookup)
        if risk.cwe_id and risk.cwe_id.startswith("CWE-"):
            # Don't auto-confirm: CWE ID from Agent 1 is not cross-validation.
            # Only confirm if CVE data exists (real knowledge-base validation).
            reasons.append(f"CWE tagged: {risk.cwe_id}")

            # Active CVE lookup for critical/high risks
            if risk.severity in (Severity.CRITICAL, Severity.HIGH):
                try:
                    cve_summary = self.cve.get_cve_summary(risk.cwe_id)
                    if "No CVE data" not in cve_summary:
                        confirmations += 1
                        reasons.append(f"CVE data exists for {risk.cwe_id}")
                        # Append CVE info to description
                        risk = risk.model_copy(update={
                            "description": risk.description + f" [CVE: {cve_summary[:150]}]",
                        })
                except Exception:
                    pass  # CVE lookup is best-effort

        # Strategy 3: Severity consistency check
        if risk.severity in (Severity.CRITICAL, Severity.HIGH):
            if len(risk.evidence) >= 2:
                confirmations += 1
                reasons.append("multiple evidence for high-severity risk")

        # Adjust confidence
        new_confidence = self._calculate_confidence(confirmations)

        if new_confidence != risk.confidence:
            reason_str = "; ".join(reasons) if reasons else "no cross-validation"
            updated_desc = (
                risk.description
                + f" [Verification: {confirmations} confirmations ({reason_str})]"
            )
            risk = risk.model_copy(update={
                "confidence": new_confidence,
                "description": updated_desc,
            })

        return risk

    def _calculate_confidence(self, confirmations: int) -> Confidence:
        if confirmations >= HIGH_CONFIRMATIONS:
            return Confidence.HIGH
        elif confirmations >= MEDIUM_CONFIRMATIONS:
            return Confidence.MEDIUM
        else:
            return Confidence.LOW

    def _reflect_on_file(
        self,
        code_file: CodeFile,
        existing_risks: list[Risk],
    ) -> list[Risk]:
        """Ask LLM to find risks that previous agents missed."""
        if not self.llm:
            return []

        risk_summaries = []
        for r in existing_risks:
            risk_summaries.append(
                f"- {r.id}: [{r.severity.value}] {r.title} "
                f"(CWE: {r.cwe_id or 'N/A'}, Lines: {r.line_start}-{r.line_end})"
            )

        existing_text = "\n".join(risk_summaries) if risk_summaries else "No risks found."

        prompt = f"""## Source File: {code_file.path}
Language: {code_file.language.value}

```{code_file.language.value}
{code_file.content}
```

## Risks Found by Previous Agents
{existing_text}

Please verify these risks and find any missed vulnerabilities."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": REFLECTION_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                schema=ReflectionResponse,
            )
        except Exception as e:
            console.print(f"[dim]Reflection failed: {e}[/]")
            return []

        missed_raw = response.get("missed_risks", [])
        missed_risks = []
        import uuid as _uuid

        for mr in missed_raw:
            sev_str = mr.get("severity", "medium").lower()
            sev = Severity(sev_str) if sev_str in [s.value for s in Severity] else Severity.MEDIUM

            missed_risks.append(Risk(
                id=f"RISK-{_uuid.uuid4().hex[:8].upper()}",
                title=mr.get("title", "Missed risk (Agent 3 reflection)"),
                description=mr.get("description", ""),
                severity=sev,
                confidence=Confidence.MEDIUM,
                cwe_id=mr.get("cwe_id"),
                language=code_file.language,
                file_path=code_file.path,
                line_start=mr.get("line_start", 0),
                line_end=mr.get("line_end", 0),
                evidence=[Evidence(
                    source="ai",
                    snippet="",
                    line_start=mr.get("line_start", 0),
                    line_end=mr.get("line_end", 0),
                    reasoning=f"Agent 3 reflection: {mr.get('reasoning', 'missed by previous agents')}",
                )],
                suggestion=mr.get("suggestion", "Review this code section."),
            ))

        return missed_risks
