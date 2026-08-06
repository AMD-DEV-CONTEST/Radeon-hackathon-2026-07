from __future__ import annotations

import math
import random
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .quality_contract import wilson_lower_bound
from .v10_contracts import V10ContractError, stable_digest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256.fullmatch(value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


class RuleState(str, Enum):
    FROZEN = "frozen"
    PASSED = "passed"
    OPEN = "open"


class DemoKind(str, Enum):
    PHYSICAL_COMMERCE = "physical_commerce"
    AI_AGENT = "ai_agent"


@dataclass(frozen=True)
class OfficialSource:
    source_id: str
    url: str
    revision: str
    content_sha256: str
    observed_at: str

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.url.startswith("https://"):
            raise V10ContractError("official source identity is incomplete")
        if not self.revision.strip() or not self.observed_at.strip():
            raise V10ContractError("official source revision and observation are required")
        _require_sha256(self.content_sha256, "official source content_sha256")


@dataclass(frozen=True)
class RuleFact:
    todo_id: str
    rule_id: str
    statement: str
    source_id: str
    source_locator: str
    state: RuleState = RuleState.FROZEN

    def __post_init__(self) -> None:
        if not re.fullmatch(r"00[0-5][0-9]", self.todo_id):
            raise V10ContractError("competition rule todo_id must be in 0001-0050")
        if not all(
            value.strip()
            for value in (
                self.rule_id,
                self.statement,
                self.source_id,
                self.source_locator,
            )
        ):
            raise V10ContractError("competition rule fact is incomplete")


@dataclass(frozen=True)
class ScoreDimensionEvidence:
    dimension: str
    claimed_points: float
    maximum_points: int
    locator: str
    sha256: str
    observed: bool
    proxy: bool = False

    def __post_init__(self) -> None:
        if not self.dimension.strip() or self.maximum_points <= 0:
            raise V10ContractError("score dimension identity is incomplete")
        if not math.isfinite(self.claimed_points) or not 0 <= self.claimed_points <= self.maximum_points:
            raise V10ContractError("claimed score lies outside its official maximum")
        if self.observed:
            if not self.locator.strip():
                raise V10ContractError("observed score requires evidence locator")
            _require_sha256(self.sha256, "score evidence sha256")
        elif self.locator or self.sha256:
            raise V10ContractError("unobserved score cannot carry evidence")


@dataclass(frozen=True)
class SelfCheckReport:
    total: float
    threshold: float
    passed: bool
    counted_points: Mapping[str, float]
    rejected_dimensions: tuple[str, ...]
    truth_boundary: str


OFFICIAL_SCORE_MAXIMA = {
    "workflow": 40,
    "innovation": 20,
    "practical_value": 20,
    "radeon_clarity_stability_diversity": 20,
}


def score_self_check(
    evidence: Sequence[ScoreDimensionEvidence],
    *,
    threshold: float = 95.0,
) -> SelfCheckReport:
    by_dimension = {item.dimension: item for item in evidence}
    if len(by_dimension) != len(evidence) or set(by_dimension) != set(OFFICIAL_SCORE_MAXIMA):
        raise V10ContractError("self-check requires each official score dimension exactly once")
    counted: dict[str, float] = {}
    rejected: list[str] = []
    for dimension, maximum in OFFICIAL_SCORE_MAXIMA.items():
        item = by_dimension[dimension]
        if item.maximum_points != maximum:
            raise V10ContractError("self-check score maxima must match official rules")
        if not item.observed or item.proxy:
            counted[dimension] = 0.0
            rejected.append(dimension)
        else:
            counted[dimension] = item.claimed_points
    total = sum(counted.values())
    return SelfCheckReport(
        total=total,
        threshold=threshold,
        passed=total >= threshold and not rejected,
        counted_points=counted,
        rejected_dimensions=tuple(rejected),
        truth_boundary=(
            "This is a preregistered internal readiness check, not an official judge score. "
            "Unobserved or proxy dimensions count as zero."
        ),
    )


@dataclass(frozen=True)
class DemoInput:
    demo_id: str
    kind: DemoKind
    asset_sha256: str
    rights_locator: str
    evidence_locator: str
    required_outputs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.demo_id.strip() or not self.rights_locator.strip() or not self.evidence_locator.strip():
            raise V10ContractError("demo input requires identity, rights and evidence")
        _require_sha256(self.asset_sha256, "demo asset_sha256")
        if not self.required_outputs or len(set(self.required_outputs)) != len(self.required_outputs):
            raise V10ContractError("demo required outputs must be unique and non-empty")


FULL_CAMPAIGN_PACK = (
    "evidence_ledger",
    "campaign_strategy",
    "landing_page",
    "lifecycle_email",
    "paid_social",
    "image_pack_1x1_4x5_9x16",
    "video_pack_hero_social_square",
    "experiment_plan",
    "human_approval_receipt",
)

REALTIME_DEMO_PACK = (
    "source_ingestion",
    "approved_claim",
    "single_key_visual",
    "single_channel_preview",
    "audit_findings",
    "human_release_gate",
)


def validate_pack(pack: Sequence[str], *, realtime: bool) -> tuple[str, ...]:
    expected = REALTIME_DEMO_PACK if realtime else FULL_CAMPAIGN_PACK
    if tuple(pack) != expected:
        raise V10ContractError("campaign pack does not match its frozen ordered contract")
    return expected


def mastering_claim(
    *,
    output_width: int,
    output_height: int,
    native_generation_observed: bool,
) -> str:
    if (output_width, output_height) != (3840, 2160):
        raise V10ContractError("4K mastering requires an actual 3840x2160 artifact")
    if native_generation_observed:
        return "Native 3840x2160 generation observed and hash-bound."
    return "Mastered and audited at 3840x2160; native 4K generation is not claimed."


@dataclass(frozen=True)
class BaselineCandidate:
    baseline_id: str
    repo_url: str
    revision: str
    license_id: str
    license_approved: bool
    overlapping_tasks: tuple[str, ...]
    executable_same_hardware: bool
    independent_rank: int
    estimated_minutes: int

    def __post_init__(self) -> None:
        if not self.baseline_id.strip() or not self.repo_url.startswith("https://"):
            raise V10ContractError("baseline identity is incomplete")
        if not _REVISION.fullmatch(self.revision):
            raise V10ContractError("baseline revision must be an immutable 40-character commit")
        if not self.license_id.strip() or not self.overlapping_tasks:
            raise V10ContractError("baseline license and overlapping tasks are required")
        if self.independent_rank <= 0 or self.estimated_minutes <= 0:
            raise V10ContractError("baseline rank and run budget must be positive")


def select_top3_baselines(
    candidates: Sequence[BaselineCandidate],
    *,
    run_budget_minutes: int,
) -> tuple[BaselineCandidate, ...]:
    eligible = [
        item
        for item in candidates
        if item.executable_same_hardware and item.license_approved
    ]
    eligible.sort(key=lambda item: (item.independent_rank, item.estimated_minutes, item.baseline_id))
    selected = eligible[:3]
    if len(selected) != 3:
        raise V10ContractError("Top-3 comparison requires three executable open baselines")
    if sum(item.estimated_minutes for item in selected) > run_budget_minutes:
        raise V10ContractError("Top-3 baseline run exceeds the frozen budget")
    return tuple(selected)


def overlapping_task_set(baselines: Sequence[BaselineCandidate]) -> tuple[str, ...]:
    if not baselines:
        raise V10ContractError("overlap requires baselines")
    overlap = set(baselines[0].overlapping_tasks)
    for item in baselines[1:]:
        overlap &= set(item.overlapping_tasks)
    if not overlap:
        raise V10ContractError("baselines have no directly comparable tasks")
    return tuple(sorted(overlap))


def noncomparable_features(
    product_features: Sequence[str],
    comparable_tasks: Sequence[str],
) -> tuple[str, ...]:
    comparable = set(comparable_tasks)
    return tuple(sorted(set(product_features) - comparable))


def blinded_order(
    prooflaunch_artifact_sha256: str,
    baseline_artifact_sha256: str,
    *,
    seed: int,
) -> tuple[str, str]:
    _require_sha256(prooflaunch_artifact_sha256, "prooflaunch artifact sha256")
    _require_sha256(baseline_artifact_sha256, "baseline artifact sha256")
    values = [prooflaunch_artifact_sha256, baseline_artifact_sha256]
    random.Random(seed).shuffle(values)
    return tuple(values)  # type: ignore[return-value]


@dataclass(frozen=True)
class HumanPreferenceCounts:
    preferred: int
    comparisons: int
    directly_publishable: int
    major_rework: int
    rater_count: int

    def __post_init__(self) -> None:
        if self.comparisons <= 0 or self.rater_count < 5:
            raise V10ContractError("blind review requires comparisons and at least five raters")
        for value in (self.preferred, self.directly_publishable, self.major_rework):
            if value < 0 or value > self.comparisons:
                raise V10ContractError("blind-review count lies outside its denominator")
        if self.directly_publishable + self.major_rework > self.comparisons:
            raise V10ContractError("publishable and major-rework counts cannot overlap")

    def report(self) -> dict[str, float | int | bool]:
        preference_rate = self.preferred / self.comparisons
        publishable_rate = self.directly_publishable / self.comparisons
        major_rework_rate = self.major_rework / self.comparisons
        lower = wilson_lower_bound(self.preferred, self.comparisons)
        return {
            "preference_rate": preference_rate,
            "preference_wilson_lower_95": lower,
            "publishable_rate": publishable_rate,
            "major_rework_rate": major_rework_rate,
            "passes_top3_preference": preference_rate >= 0.75 and lower > 0.65,
            "passes_publishable": publishable_rate >= 0.95,
            "rater_count": self.rater_count,
            "comparisons": self.comparisons,
        }


def arbitrate_dimension_scores(
    scores: Sequence[float],
    *,
    adjudicator: str | None = None,
) -> float:
    if len(scores) < 3 or any(not math.isfinite(item) or not 0 <= item <= 5 for item in scores):
        raise V10ContractError("score arbitration requires at least three finite 0-5 ratings")
    ordered = sorted(scores)
    if ordered[-1] - ordered[0] > 2 and not (adjudicator or "").strip():
        raise V10ContractError("material score conflict requires a named adjudicator")
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


_LEADERSHIP = re.compile(r"\b(?:top[- ]?1|top[- ]?3|best|leading|number one|#1)\b", re.IGNORECASE)


def approve_claim(
    claim: str,
    *,
    comparison_passed: bool,
    approval_id: str | None,
    evidence_locator: str | None,
) -> bool:
    if not claim.strip():
        raise V10ContractError("claim cannot be empty")
    if not _LEADERSHIP.search(claim):
        return True
    return bool(comparison_passed and (approval_id or "").strip() and (evidence_locator or "").strip())


@dataclass(frozen=True)
class SubmissionPreflight:
    luma_registration_approved: bool
    amd_developer_program_member: bool
    team_size: int
    radeon_local_inference_observed: bool
    pdf_present: bool
    source_and_readme_present: bool
    demo_video_present: bool
    ppt_or_poster_present: bool
    official_fork_present: bool
    english_pr_present: bool

    def evaluate(self) -> dict[str, object]:
        eligibility = {
            "luma_registration_approved": self.luma_registration_approved,
            "amd_developer_program_member": self.amd_developer_program_member,
            "team_size_between_1_and_3": 1 <= self.team_size <= 3,
            "radeon_local_inference_observed": self.radeon_local_inference_observed,
        }
        materials = {
            "pdf_present": self.pdf_present,
            "source_and_readme_present": self.source_and_readme_present,
            "demo_video_present": self.demo_video_present,
            "ppt_or_poster_present": self.ppt_or_poster_present,
            "official_fork_present": self.official_fork_present,
            "english_pr_present": self.english_pr_present,
        }
        passed = all(eligibility.values()) and all(materials.values())
        return {
            "eligible": all(eligibility.values()),
            "materials_complete": all(materials.values()),
            "submission_ready": passed,
            "eligibility": eligibility,
            "materials": materials,
            "truth_boundary": (
                "File presence cannot substitute for Luma approval, AMD Developer Program membership, "
                "real Radeon-local inference, the actual demo video, official fork, or English PR."
            ),
        }


def contract_digest(payload: Mapping[str, object]) -> str:
    return stable_digest(payload)


def serialize(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)  # type: ignore[arg-type]
    raise TypeError(f"cannot serialize {type(value).__name__}")
