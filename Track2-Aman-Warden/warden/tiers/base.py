"""
Base interfaces and data models for the tier system.

All tiers (0, 1, 2) implement the TierChecker interface and return
CheckResult objects. This ensures consistent data flow through the
routing engine.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from warden.config import Decision, TrustLevel


@dataclass
class CheckResult:
    """Result from any tier check."""

    decision: Decision
    confidence: float               # 0.0 = certainly safe, 1.0 = certainly malicious
    tier: int                       # Which tier produced this result (0, 1, 2)
    latency_ms: float = 0.0        # How long this check took
    matched_patterns: list[str] = field(default_factory=list)
    explanation: str = ""           # Human-readable reason for the decision
    raw_output: Any = None          # Raw model output (for debugging)
    errored: bool = False           # True if the tier threw an exception or failed to run

    @property
    def is_definitive(self) -> bool:
        """Whether this result is confident enough to stop escalating."""
        return self.decision in (Decision.ALLOW, Decision.BLOCK)


@dataclass
class ScanResult:
    """Result from a code/diff scan (DiffGuard)."""

    vulnerabilities: list[VulnerabilityFinding] = field(default_factory=list)
    latency_ms: float = 0.0
    scanner: str = ""               # "semgrep", "llm", or "both"
    diff_size_lines: int = 0

    @property
    def has_findings(self) -> bool:
        return len(self.vulnerabilities) > 0

    @property
    def max_severity(self) -> str:
        if not self.vulnerabilities:
            return "none"
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        return max(self.vulnerabilities, key=lambda v: severity_order.get(v.severity, 0)).severity


@dataclass
class VulnerabilityFinding:
    """A single vulnerability finding from a scan."""

    vuln_type: str                  # e.g., "IDOR", "SQLi", "hardcoded_secret"
    severity: str                   # "critical", "high", "medium", "low", "info"
    line: int = 0
    file_path: str = ""
    explanation: str = ""
    cwe: str = ""                   # e.g., "CWE-639"
    source: str = ""                # "semgrep" or "llm"


@dataclass
class SecurityEvent:
    """A complete security event for the audit log."""

    input_hash: str
    input_preview: str              # First 200 chars (never store full untrusted content)
    source: str                     # ContentSource value
    trust_level: str                # TrustLevel value
    tier_reached: int               # Highest tier invoked (0, 1, or 2)
    decision: str                   # Decision value
    confidence: float
    latency_ms: float
    explanation_chain: list[str] = field(default_factory=list)  # Explanations from each tier
    user_override: bool = False     # Did the user override this decision?
    timestamp: str = ""             # ISO format


@dataclass
class RoutingResult:
    """Complete routing decision with full audit trail."""

    decision: Decision = Decision.UNCERTAIN
    confidence: float = 0.0
    tier_results: list[CheckResult] = field(default_factory=list)
    memory_hit: bool = False        # Resolved via pattern memory
    policy_hit: bool = False        # Resolved via policy rule
    rag_context_used: bool = False  # RAG augmentation was used
    total_latency_ms: float = 0.0
    explanation: str = ""

    _start_time: float = field(default=0.0, repr=False)

    def start_timer(self) -> None:
        self._start_time = time.perf_counter()

    def add_tier_result(self, tier: int, result: CheckResult) -> None:
        self.tier_results.append(result)

    def finalize(self, decision: Decision, explanation: str = "") -> "RoutingResult":
        self.decision = decision
        self.explanation = explanation
        if self._start_time > 0:
            self.total_latency_ms = (time.perf_counter() - self._start_time) * 1000
        if self.tier_results:
            self.confidence = self.tier_results[-1].confidence
        return self

    def auto_block(self, reason: str) -> "RoutingResult":
        self.memory_hit = True
        return self.finalize(Decision.BLOCK, reason)

    def auto_allow(self, reason: str) -> "RoutingResult":
        self.memory_hit = True
        return self.finalize(Decision.ALLOW, reason)

    def policy_decision(self, decision: Decision, reason: str) -> "RoutingResult":
        self.policy_hit = True
        return self.finalize(decision, reason)

    @property
    def tier_reached(self) -> int:
        if not self.tier_results:
            return -1
        return max(r.tier for r in self.tier_results)


class TierChecker(ABC):
    """Abstract interface for all security check tiers."""

    @property
    @abstractmethod
    def tier_number(self) -> int:
        """Return the tier number (0, 1, or 2)."""
        ...

    @abstractmethod
    def check(self, text: str, context: str = "") -> CheckResult:
        """
        Run a security check on the input text.

        Args:
            text: The content to check.
            context: Optional context (e.g., RAG-retrieved similar attacks).

        Returns:
            CheckResult with decision, confidence, and explanation.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this tier is currently available (model loaded, etc.)."""
        ...
