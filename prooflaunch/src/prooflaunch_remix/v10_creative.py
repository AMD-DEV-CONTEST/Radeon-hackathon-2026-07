from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping, Sequence

from .v10_contracts import (
    ClaimProof,
    EvidenceClass,
    ProofManifest,
    TransformProof,
    V10ContractError,
)


TASTE_DIMENSIONS = (
    "big_idea",
    "strategy",
    "copy",
    "art_direction",
    "brand_fidelity",
    "channel_fitness",
)


@dataclass(frozen=True)
class HumanTasteRating:
    reviewer_id: str
    dimensions: Mapping[str, float]
    directly_publishable: bool
    evidence_locator: str
    evidence_class: EvidenceClass = EvidenceClass.OBSERVED

    def __post_init__(self) -> None:
        if not self.reviewer_id.strip() or not self.evidence_locator.strip():
            raise V10ContractError("taste rating reviewer and locator are required")
        if set(self.dimensions) != set(TASTE_DIMENSIONS):
            raise V10ContractError(
                "taste rating must contain the exact six 4A dimensions"
            )
        if any(
            not math.isfinite(value) or not 1 <= value <= 5
            for value in self.dimensions.values()
        ):
            raise V10ContractError("taste scores must be finite values in [1, 5]")
        if self.evidence_class not in {
            EvidenceClass.OBSERVED,
            EvidenceClass.CAUSAL,
        }:
            raise V10ContractError("self-rated or simulated taste cannot certify 4A")


@dataclass(frozen=True)
class TasteGateReport:
    passed: bool
    reviewer_count: int
    dimension_means: Mapping[str, float]
    overall_mean: float
    directly_publishable_rate: float
    failures: tuple[str, ...]
    schema: str = "ProofLaunchTasteGateReportV10"


class AgencyTasteGate:
    def evaluate(
        self,
        ratings: Sequence[HumanTasteRating],
    ) -> TasteGateReport:
        reviewers = {item.reviewer_id for item in ratings}
        failures: list[str] = []
        if len(reviewers) < 5:
            failures.append("fewer than five independent reviewers")
        if len(reviewers) != len(ratings):
            failures.append("reviewer ids are not unique")
        dimension_means = {
            dimension: (
                sum(item.dimensions[dimension] for item in ratings) / len(ratings)
                if ratings
                else 0.0
            )
            for dimension in TASTE_DIMENSIONS
        }
        overall = (
            sum(dimension_means.values()) / len(TASTE_DIMENSIONS)
            if ratings
            else 0.0
        )
        publishable = (
            sum(item.directly_publishable for item in ratings) / len(ratings)
            if ratings
            else 0.0
        )
        if overall < 4.8:
            failures.append("overall 4A mean below 4.8")
        below = [
            name for name, value in dimension_means.items() if value < 4.6
        ]
        if below:
            failures.append(f"dimensions below 4.6: {', '.join(below)}")
        if publishable < 0.97:
            failures.append("directly publishable rate below 97%")
        return TasteGateReport(
            passed=not failures,
            reviewer_count=len(reviewers),
            dimension_means=dimension_means,
            overall_mean=overall,
            directly_publishable_rate=publishable,
            failures=tuple(failures),
        )


@dataclass(frozen=True)
class MediaQualityTensor:
    ocr_accuracy: float
    brand_delta_e: float
    product_identity_rate: float
    temporal_gain: float
    audio_video_alignment: float
    claim_locator_coverage: float
    rights_locator_coverage: float
    approval_coverage: float

    def __post_init__(self) -> None:
        bounded = (
            self.ocr_accuracy,
            self.product_identity_rate,
            self.temporal_gain,
            self.audio_video_alignment,
            self.claim_locator_coverage,
            self.rights_locator_coverage,
            self.approval_coverage,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in bounded):
            raise V10ContractError("media quality rates must be finite and in [0, 1]")
        if not math.isfinite(self.brand_delta_e) or self.brand_delta_e < 0:
            raise V10ContractError("brand Delta E must be finite and non-negative")

    @property
    def failures(self) -> tuple[str, ...]:
        checks = (
            ("ocr_accuracy", self.ocr_accuracy >= 0.9995),
            ("brand_delta_e", self.brand_delta_e <= 1.0),
            ("product_identity_rate", self.product_identity_rate >= 0.995),
            ("temporal_gain", self.temporal_gain >= 0.30),
            ("audio_video_alignment", self.audio_video_alignment >= 0.96),
            ("claim_locator_coverage", self.claim_locator_coverage == 1.0),
            ("rights_locator_coverage", self.rights_locator_coverage == 1.0),
            ("approval_coverage", self.approval_coverage == 1.0),
        )
        return tuple(name for name, passed in checks if not passed)

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class RegionTimeIssue:
    issue_id: str
    asset_id: str
    region: tuple[float, float, float, float]
    frame_start: int
    frame_end: int
    category: str
    severity: float
    repair_operation: str
    protected_layers: tuple[str, ...] = ("product", "logo")

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.region
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise V10ContractError("repair region must be normalized and non-empty")
        if self.frame_start < 0 or self.frame_end < self.frame_start:
            raise V10ContractError("repair frame range is invalid")
        if not 0 < self.severity <= 1:
            raise V10ContractError("repair severity must be in (0, 1]")


@dataclass(frozen=True)
class LocalRepair:
    issue_id: str
    asset_id: str
    region: tuple[float, float, float, float]
    frame_start: int
    frame_end: int
    operation: str
    locks: tuple[str, ...]


@dataclass(frozen=True)
class RepairProgram:
    repairs: tuple[LocalRepair, ...]
    blocked_issues: tuple[str, ...]
    total_area_frames: float
    schema: str = "ProofLaunchRegionTimeRepairProgramV10"


class RegionTimeRepairPlanner:
    """Selects local repairs while preventing global product/brand rewrites."""

    def plan(
        self,
        issues: Sequence[RegionTimeIssue],
        *,
        maximum_repairs: int = 2,
        maximum_area_frames: float = 100.0,
    ) -> RepairProgram:
        if maximum_repairs < 0 or maximum_repairs > 2:
            raise V10ContractError("V10 allows at most two repair operations")
        ordered = sorted(
            issues,
            key=lambda item: (-item.severity, item.issue_id),
        )
        selected: list[LocalRepair] = []
        spent = 0.0
        blocked: list[str] = []
        for issue in ordered:
            x0, y0, x1, y1 = issue.region
            area_frames = (x1 - x0) * (y1 - y0) * (
                issue.frame_end - issue.frame_start + 1
            )
            if len(selected) >= maximum_repairs or spent + area_frames > (
                maximum_area_frames
            ):
                blocked.append(issue.issue_id)
                continue
            selected.append(
                LocalRepair(
                    issue_id=issue.issue_id,
                    asset_id=issue.asset_id,
                    region=issue.region,
                    frame_start=issue.frame_start,
                    frame_end=issue.frame_end,
                    operation=issue.repair_operation,
                    locks=issue.protected_layers,
                )
            )
            spent += area_frames
        return RepairProgram(
            repairs=tuple(selected),
            blocked_issues=tuple(blocked),
            total_area_frames=spent,
        )


class ProofCarryingCreativeCompiler:
    def compile(
        self,
        *,
        campaign_id: str,
        claims: Sequence[ClaimProof],
        transforms: Sequence[TransformProof],
        asset_hashes: Mapping[str, str],
    ) -> ProofManifest:
        return ProofManifest(
            campaign_id=campaign_id,
            claims=tuple(claims),
            transforms=tuple(transforms),
            asset_hashes=dict(asset_hashes),
        )


@dataclass(frozen=True)
class CampaignSnapshot:
    snapshot_id: str
    parent_ids: tuple[str, ...]
    state: Mapping[str, Any]
    author: str
    reason: str
    sequence: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                asdict(self),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class MergeResult:
    snapshot: CampaignSnapshot | None
    conflicts: Mapping[str, tuple[Any, Any]]


class CampaignOperatingSpace:
    """Append-only campaign history with fork, time travel, and safe merge."""

    def __init__(self, initial: CampaignSnapshot) -> None:
        if initial.parent_ids:
            raise V10ContractError("initial snapshot cannot have parents")
        if initial.sequence != 0:
            raise V10ContractError("initial snapshot sequence must be zero")
        self._snapshots: dict[str, CampaignSnapshot] = {
            initial.snapshot_id: initial
        }

    def get(self, snapshot_id: str) -> CampaignSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError as error:
            raise V10ContractError(f"unknown snapshot: {snapshot_id}") from error

    def compare(
        self,
        left_id: str,
        right_id: str,
    ) -> Mapping[str, tuple[Any | None, Any | None]]:
        """Return a deterministic, user-inspectable state diff."""
        left = self.get(left_id)
        right = self.get(right_id)
        keys = sorted(set(left.state) | set(right.state))
        return {
            key: (left.state.get(key), right.state.get(key))
            for key in keys
            if left.state.get(key) != right.state.get(key)
        }

    def fork(
        self,
        parent_id: str,
        *,
        snapshot_id: str,
        changes: Mapping[str, Any],
        author: str,
        reason: str,
    ) -> CampaignSnapshot:
        if snapshot_id in self._snapshots:
            raise V10ContractError("snapshot id already exists")
        parent = self.get(parent_id)
        state = dict(parent.state)
        state.update(changes)
        snapshot = CampaignSnapshot(
            snapshot_id=snapshot_id,
            parent_ids=(parent_id,),
            state=state,
            author=author,
            reason=reason,
            sequence=parent.sequence + 1,
        )
        self._snapshots[snapshot_id] = snapshot
        return snapshot

    def merge(
        self,
        left_id: str,
        right_id: str,
        *,
        snapshot_id: str,
        author: str,
        reason: str,
    ) -> MergeResult:
        left = self.get(left_id)
        right = self.get(right_id)
        merged = dict(left.state)
        conflicts: dict[str, tuple[Any, Any]] = {}
        for key, value in right.state.items():
            if key in merged and merged[key] != value:
                conflicts[key] = (merged[key], value)
            else:
                merged[key] = value
        if conflicts:
            return MergeResult(snapshot=None, conflicts=conflicts)
        snapshot = CampaignSnapshot(
            snapshot_id=snapshot_id,
            parent_ids=(left_id, right_id),
            state=merged,
            author=author,
            reason=reason,
            sequence=max(left.sequence, right.sequence) + 1,
        )
        if snapshot_id in self._snapshots:
            raise V10ContractError("snapshot id already exists")
        self._snapshots[snapshot_id] = snapshot
        return MergeResult(snapshot=snapshot, conflicts={})
