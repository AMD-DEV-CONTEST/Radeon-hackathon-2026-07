from __future__ import annotations

import json
from dataclasses import dataclass, replace
from time import perf_counter

from .models import Action, Hypothesis, Incident, IncidentReport
from .retrieval import rank_evidence
from .llm import OpenAICompatibleClient


@dataclass(frozen=True)
class Pattern:
    title: str
    keywords: tuple[str, ...]
    rationale: str
    action: str
    safety: str


PATTERNS = (
    Pattern(
        "Deployment regression",
        ("deploy", "deployment", "release", "version", "rollback", "image"),
        "The incident is temporally associated with a software or configuration change.",
        "Pause the rollout and compare the current release with the last known-good version.",
        "Use a canary rollback first; preserve logs and traces before replacing workloads.",
    ),
    Pattern(
        "Database saturation or contention",
        ("database", "db", "connection", "pool", "query", "lock", "postgres", "mysql"),
        "Database errors, pool pressure, or query contention can explain correlated latency and failures.",
        "Inspect connection-pool saturation, slow queries, locks, and database resource pressure.",
        "Do not increase pool size until database headroom is confirmed; it can amplify overload.",
    ),
    Pattern(
        "Resource exhaustion",
        ("cpu", "memory", "oom", "disk", "throttle", "saturation", "capacity"),
        "Compute, memory, or storage pressure is present in the evidence.",
        "Confirm the constrained resource, reduce non-critical load, and add bounded capacity.",
        "Prefer reversible scaling and rate limits; avoid restarting every replica simultaneously.",
    ),
    Pattern(
        "Downstream dependency failure",
        ("timeout", "upstream", "downstream", "dependency", "gateway", "503", "502"),
        "Timeouts or gateway failures indicate a dependency may be propagating failure upstream.",
        "Measure dependency error rate and latency, then enable circuit breaking or graceful degradation.",
        "Keep retries bounded with jitter; unbounded retries can create a retry storm.",
    ),
)


class IncidentAnalyzer:
    """Deterministic evidence-first baseline that remains useful without a model."""

    def analyze(self, incident: Incident) -> IncidentReport:
        started = perf_counter()
        corpus = f"{incident.title} {incident.summary} " + " ".join(item.content for item in incident.evidence)
        lowered = corpus.lower()
        candidates: list[tuple[int, Pattern, tuple[str, ...]]] = []

        for pattern in PATTERNS:
            matched = tuple(keyword for keyword in pattern.keywords if keyword in lowered)
            if matched:
                candidates.append((len(matched), pattern, matched))

        if not candidates:
            candidates.append(
                (
                    1,
                    Pattern(
                        "Undifferentiated service degradation",
                        (),
                        "The supplied evidence confirms impact but does not yet isolate a failure domain.",
                        "Capture golden signals, recent changes, and dependency health before intervening.",
                        "Avoid destructive remediation until a failure domain is supported by evidence.",
                    ),
                    (),
                )
            )

        candidates.sort(key=lambda row: row[0], reverse=True)
        max_score = max(score for score, _, _ in candidates)
        hypotheses: list[Hypothesis] = []
        actions: list[Action] = []
        for index, (score, pattern, matched) in enumerate(candidates[:3]):
            query = f"{pattern.title} {' '.join(matched)}"
            support = rank_evidence(query, incident.evidence, limit=3)
            confidence = min(0.92, 0.42 + (score / max_score) * 0.38 - index * 0.04)
            hypotheses.append(
                Hypothesis(pattern.title, round(confidence, 2), pattern.rationale, tuple(item.id for item in support))
            )
            actions.append(Action(f"P{index}", pattern.action, pattern.rationale, pattern.safety))

        timeline = tuple(sorted(incident.evidence, key=lambda item: (item.timestamp == "unknown", item.timestamp)))
        uncertainties = self._uncertainties(lowered)
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        return IncidentReport(
            incident=incident,
            executive_summary=(
                f"{incident.severity} incident affecting {incident.service}. "
                f"The leading evidence-backed hypothesis is {hypotheses[0].title.lower()} "
                f"({hypotheses[0].confidence:.0%} confidence)."
            ),
            hypotheses=tuple(hypotheses),
            actions=tuple(actions),
            timeline=timeline,
            uncertainties=uncertainties,
            metadata={"engine": "deterministic-baseline", "analysis_ms": elapsed_ms, "evidence_count": len(incident.evidence)},
        )

    @staticmethod
    def _uncertainties(corpus: str) -> tuple[str, ...]:
        checks = (
            (
                ("deploy", "release", "rollout", "version", "change"),
                "No explicit deployment or change record was supplied.",
            ),
            (("latency", "p50", "p95", "p99"), "No latency measurement or percentile was supplied."),
            (
                ("error", "exception", "timeout", "5xx", "502", "503", "failed", "failure"),
                "No concrete error signature was supplied.",
            ),
            (
                ("dependency", "upstream", "downstream", "gateway"),
                "Downstream dependency health has not been established.",
            ),
        )
        missing = tuple(
            message for signals, message in checks if not any(signal in corpus for signal in signals)
        )
        return missing or ("Causality is not proven; the ranked hypotheses remain provisional.",)


class AIIncidentAnalyzer:
    """Adds a model-written commander brief without weakening deterministic safeguards."""

    def __init__(self, client: OpenAICompatibleClient | None = None):
        self.client = client or OpenAICompatibleClient()
        self.baseline = IncidentAnalyzer()

    def analyze(self, incident: Incident) -> IncidentReport:
        report = self.baseline.analyze(incident)
        evidence = [
            {"id": item.id, "timestamp": item.timestamp, "source": item.source, "content": item.content}
            for item in report.timeline
        ]
        hypotheses = [
            {"title": item.title, "confidence": item.confidence, "evidence_ids": item.evidence_ids}
            for item in report.hypotheses
        ]
        try:
            result = self.client.complete(
                "You are an SRE incident commander. Use only the supplied evidence and hypotheses. "
                "Return one concise English sentence with impact, leading hypothesis, and safest next action. "
                "Do not add facts, markdown, or analysis.",
                json.dumps(
                    {
                        "incident": {"service": incident.service, "severity": incident.severity, "summary": incident.summary},
                        "evidence": evidence,
                        "hypotheses": hypotheses,
                        "safest_action": report.actions[0].action,
                    },
                    ensure_ascii=False,
                ),
                max_tokens=256,
            )
            brief = result.content.strip()
            if not brief or brief.lower() in {"none", "null"} or len(brief) > 800:
                raise ValueError("model brief is empty or too long")
            metadata = {
                **report.metadata,
                "engine": "hybrid-radeon-llm",
                "llm_model": result.model,
                "llm_latency_ms": result.latency_ms,
                "llm_usage": result.usage,
            }
            return replace(report, executive_summary=brief, metadata=metadata)
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            return replace(report, metadata={**report.metadata, "llm_fallback": str(exc)})
