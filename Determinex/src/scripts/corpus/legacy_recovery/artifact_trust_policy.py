from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from corpus.legacy_recovery.artifact_security_scan import security_scan
from corpus.legacy_recovery.artifact_source_registry import ArtifactSource

TRUST_LADDER = {
    "trusted_internal": 5,
    "verified_upstream": 4,
    "official_project": 3,
    "public_untrusted": 2,
    "unknown": 1,
    "blocked": 0,
}


@dataclass(slots=True)
class ArtifactTrustDecision:
    allowed: bool
    reason: str
    scan_policy: str = ""


def evaluate_artifact_policy(
    candidate: dict[str, Any], source: ArtifactSource | None
) -> ArtifactTrustDecision:
    if source is None:
        return ArtifactTrustDecision(False, "source_unknown")
    if source.trust_level == "blocked" or TRUST_LADDER.get(source.trust_level, 0) <= 0:
        return ArtifactTrustDecision(False, "source_blocked")

    artifact_type = str(candidate.get("artifact_type") or "")
    allowed_for = set(source.allowed_for)
    if artifact_type == "oci_image" and not (
        {"image", "image_pull_if_digest_pinned"} & allowed_for
    ):
        return ArtifactTrustDecision(False, "source_not_allowed_for_image")

    digest = str(candidate.get("resolved_digest") or candidate.get("digest") or "")
    expected_digest = str(candidate.get("expected_digest") or "")
    if expected_digest and digest != expected_digest:
        return ArtifactTrustDecision(False, "digest_mismatch")
    if source.requires_digest and not digest.startswith("sha256:"):
        return ArtifactTrustDecision(False, "digest_required")

    if artifact_type == "oci_image" and not digest.startswith("sha256:"):
        return ArtifactTrustDecision(False, "oci_digest_required")

    if source.requires_revision_pin:
        revision = str(candidate.get("revision") or "")
        if not revision or revision in {"main", "master", "latest"}:
            return ArtifactTrustDecision(False, "exact_revision_required")

    if source.requires_license and not str(candidate.get("license") or "").strip():
        return ArtifactTrustDecision(False, "license_required")

    if source.requires_security_scan or source.trust_level in {
        "public_untrusted",
        "official_project",
        "verified_upstream",
    }:
        scan = security_scan(candidate)
        if not scan.passed:
            return ArtifactTrustDecision(
                False, scan.reason or "security_scan_failed", scan_policy=scan.policy
            )
        return ArtifactTrustDecision(True, "policy_pass", scan_policy=scan.policy)

    return ArtifactTrustDecision(True, "policy_pass")
