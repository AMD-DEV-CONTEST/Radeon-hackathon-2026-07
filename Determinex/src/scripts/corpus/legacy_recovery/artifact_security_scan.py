from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ArtifactSecurityScan:
    scanner: str
    critical: int
    high: int
    policy: str
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.policy == "pass" and self.critical == 0 and self.high == 0


def security_scan(candidate: dict[str, Any]) -> ArtifactSecurityScan:
    """
    Normalize an artifact security scan result.

    This does not invoke a scanner. Online discovery is discovery-only in this
    lock; callers must provide scanner output before a candidate can be pinned.
    """
    raw = candidate.get("security_scan")
    if not isinstance(raw, dict):
        return ArtifactSecurityScan(
            scanner="none",
            critical=0,
            high=0,
            policy="missing",
            reason="security_scan_missing",
        )
    critical = int(raw.get("critical") or 0)
    high = int(raw.get("high") or 0)
    policy = str(raw.get("policy") or "fail")
    reason = str(raw.get("reason") or "")
    if critical or high:
        policy = "fail"
        reason = reason or "critical_or_high_findings"
    return ArtifactSecurityScan(
        scanner=str(raw.get("scanner") or "metadata"),
        critical=critical,
        high=high,
        policy=policy,
        reason=reason,
    )
