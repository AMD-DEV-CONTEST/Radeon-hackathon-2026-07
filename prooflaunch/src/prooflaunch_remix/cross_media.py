from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .mission import EvidenceObservation
from .multimodal_ingest import MediaArtifact, RightsStatus


@dataclass(frozen=True)
class DeliverableClaim:
    deliverable_id: str
    text: str
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class CrossMediaFinding:
    category: str
    message: str
    blocking: bool
    deliverable_id: str | None = None


class CrossMediaReleaseGate:
    """No output claim may escape without a valid source locator and rights gate."""

    def audit(
        self,
        *,
        artifacts: Iterable[MediaArtifact],
        observations: Iterable[EvidenceObservation],
        claims: Iterable[DeliverableClaim],
    ) -> tuple[CrossMediaFinding, ...]:
        media = {item.id: item for item in artifacts}
        evidence = {item.id: item for item in observations}
        findings: list[CrossMediaFinding] = []
        for artifact in media.values():
            if artifact.rights == RightsStatus.UNKNOWN:
                findings.append(
                    CrossMediaFinding(
                        "rights",
                        f"rights not cleared for {artifact.id}",
                        True,
                    )
                )
        for observation in evidence.values():
            if observation.source_artifact_id not in media:
                findings.append(
                    CrossMediaFinding(
                        "evidence_source",
                        f"{observation.id} references missing source",
                        True,
                    )
                )
            if not observation.locator.strip():
                findings.append(
                    CrossMediaFinding(
                        "evidence_locator",
                        f"{observation.id} has no source locator",
                        True,
                    )
                )
        for claim in claims:
            if not claim.observation_ids:
                findings.append(
                    CrossMediaFinding(
                        "ungrounded_claim",
                        "deliverable claim has no evidence reference",
                        True,
                        claim.deliverable_id,
                    )
                )
                continue
            missing = set(claim.observation_ids) - set(evidence)
            if missing:
                findings.append(
                    CrossMediaFinding(
                        "ungrounded_claim",
                        f"unknown observation IDs: {', '.join(sorted(missing))}",
                        True,
                        claim.deliverable_id,
                    )
                )
        return tuple(findings)

