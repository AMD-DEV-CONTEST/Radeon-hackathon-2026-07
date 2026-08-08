"""Risk Analyzer — analyzes the aggregate risk of a plan.

Risk levels:
  0 = READ_ONLY         (safe, no approval)
  1 = SAFE_LOCAL        (local file ops, no approval)
  2 = LOCAL_DESTRUCTIVE (deletes/moves, may need approval)
  3 = EXTERNAL          (touches external systems, approval required)
  4 = CRITICAL          (permanent delete, credentials, financial)

The analyzer considers:
  - Tool-level risk
  - Path sensitivity (system folders, credentials)
  - URL sensitivity (unknown domains, executables)
  - Bulk operations
  - Credential usage
  - Reversibility
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .task_decomposer import Task


@dataclass
class RiskFactor:
    """A single risk factor identified in the plan."""
    category: str
    description: str
    severity: int  # 0-4
    source: str  # which task triggered it
    mitigation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "severity": self.severity,
            "source": self.source,
            "mitigation": self.mitigation,
        }


@dataclass
class RiskAnalysis:
    """Complete risk analysis of a plan."""
    level: int  # 0-4
    score: float  # 0.0-10.0
    requires_approval: bool
    factors: List[RiskFactor] = field(default_factory=list)
    mitigations: List[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "score": round(self.score, 2),
            "requires_approval": self.requires_approval,
            "factors": [f.to_dict() for f in self.factors],
            "mitigations": self.mitigations,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class RiskAnalyzer:
    """Analyzes risk of a plan."""

    # Protected paths that always trigger high risk
    PROTECTED_PATHS = {
        "windows", "program files", "program files (x86)",
        "appdata", "system32", "boot", "recovery",
    }

    # Dangerous file extensions
    DANGEROUS_EXTENSIONS = {
        ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs",
        ".scr", ".jar", ".js", ".hta",
    }

    # Trusted domains (lower risk)
    TRUSTED_DOMAINS = {
        "google.com", "microsoft.com", "github.com",
        "wikipedia.org", "youtube.com",
    }

    # Tools that always require approval
    APPROVAL_REQUIRED_TOOLS = {
        "file.quarantine", "vault.unlock", "auth.fill_credentials",
        "download.file", "approval.request",
    }

    # Tools that are always blocked
    BLOCKED_TOOLS = {
        "system.format_disk", "system.wipe_credentials",
        "credential.export",
    }

    def analyze(self, tasks: List[Task]) -> RiskAnalysis:
        """Analyze the risk of a plan."""
        factors: List[RiskFactor] = []
        mitigations: List[str] = []
        blocked = False
        block_reason: Optional[str] = None

        for task in tasks:
            # Check for blocked tools
            if task.tool in self.BLOCKED_TOOLS:
                blocked = True
                block_reason = f"Tool {task.tool} is blocked"
                factors.append(RiskFactor(
                    category="blocked_tool",
                    description=f"Tool {task.tool} is not allowed",
                    severity=4,
                    source=task.id,
                ))
                continue

            # Tool-level risk
            tool_risk = self._tool_risk(task.tool)
            if tool_risk > 0:
                factors.append(RiskFactor(
                    category="tool",
                    description=f"Tool {task.tool} has risk level {tool_risk}",
                    severity=tool_risk,
                    source=task.id,
                    mitigation=self._tool_mitigation(task.tool),
                ))

            # Path sensitivity
            path = task.inputs.get("path", "")
            if path:
                path_risk = self._path_risk(path)
                if path_risk > 0:
                    factors.append(RiskFactor(
                        category="path",
                        description=f"Path {path} is sensitive",
                        severity=path_risk,
                        source=task.id,
                        mitigation="Require explicit approval",
                    ))

            # URL sensitivity
            url = task.inputs.get("url", "")
            if url:
                url_risk = self._url_risk(url)
                if url_risk > 0:
                    factors.append(RiskFactor(
                        category="url",
                        description=f"URL {url} has risk level {url_risk}",
                        severity=url_risk,
                        source=task.id,
                        mitigation="Verify domain before proceeding",
                    ))

            # Bulk operation
            if task.inputs.get("bulk"):
                factors.append(RiskFactor(
                    category="bulk",
                    description="Bulk operation affects multiple items",
                    severity=3,
                    source=task.id,
                    mitigation="Show count and require approval",
                ))

            # Credential usage
            if any(k in task.tool.lower() for k in ("credential", "vault", "login")):
                factors.append(RiskFactor(
                    category="credential",
                    description="Plan uses credentials",
                    severity=3,
                    source=task.id,
                    mitigation="Redact credentials from logs",
                ))

        # Compute aggregate risk
        if not factors:
            level = 0
            score = 0.0
        else:
            max_severity = max(f.severity for f in factors)
            avg_severity = sum(f.severity for f in factors) / len(factors)
            score = max_severity + avg_severity * 0.5
            level = min(4, int(round(score / 2)))

        # Check if approval is required
        requires_approval = (
            level >= 3
            or any(t.tool in self.APPROVAL_REQUIRED_TOOLS for t in tasks)
            or any(f.severity >= 3 for f in factors)
        )

        # Build mitigations list
        for factor in factors:
            if factor.mitigation and factor.mitigation not in mitigations:
                mitigations.append(factor.mitigation)

        return RiskAnalysis(
            level=level,
            score=score,
            requires_approval=requires_approval,
            factors=factors,
            mitigations=mitigations,
            blocked=blocked,
            block_reason=block_reason,
        )

    def _tool_risk(self, tool: str) -> int:
        """Get risk level for a tool."""
        tool_lower = tool.lower()
        if any(k in tool_lower for k in ("delete", "quarantine", "format", "wipe")):
            return 4
        if any(k in tool_lower for k in ("credential", "vault", "login", "download")):
            return 3
        if any(k in tool_lower for k in ("click", "submit", "fill", "type")):
            return 2
        if any(k in tool_lower for k in ("open", "navigate", "search", "scan")):
            return 1
        return 0

    def _tool_mitigation(self, tool: str) -> Optional[str]:
        """Get mitigation for a risky tool."""
        if "delete" in tool.lower() or "quarantine" in tool.lower():
            return "Use quarantine instead of permanent delete"
        if "credential" in tool.lower() or "vault" in tool.lower():
            return "Require vault unlock and redact from logs"
        if "download" in tool.lower():
            return "Verify source domain and hash"
        return None

    def _path_risk(self, path: str) -> int:
        """Get risk level for a path."""
        path_lower = path.lower()
        for protected in self.PROTECTED_PATHS:
            if protected in path_lower:
                return 4
        if any(path_lower.endswith(ext) for ext in self.DANGEROUS_EXTENSIONS):
            return 3
        return 0

    def _url_risk(self, url: str) -> int:
        """Get risk level for a URL."""
        url_lower = url.lower()
        # Check for dangerous extensions in URL
        for ext in self.DANGEROUS_EXTENSIONS:
            if url_lower.endswith(ext):
                return 3
        # Check for trusted domains
        for trusted in self.TRUSTED_DOMAINS:
            if trusted in url_lower:
                return 0
        # Unknown domain
        return 2
