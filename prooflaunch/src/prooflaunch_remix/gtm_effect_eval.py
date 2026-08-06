from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence

from .quality_contract import wilson_lower_bound


class EffectContractError(ValueError):
    """Raised when an effect-evaluation artifact is structurally invalid."""


class Capability(str, Enum):
    STRATEGY = "strategy"
    COPY = "copy"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SCHEDULE = "schedule"
    SEO_GEO = "seo_geo"
    ANALYTICS = "analytics"


class CapabilityEvidenceLevel(str, Enum):
    PLANNED = "planned"
    MECHANICAL = "mechanical"
    HUMAN_OBSERVED = "human_observed"
    MODEL_OBSERVED = "model_observed"
    PRODUCTION_OBSERVED = "production_observed"


class DeliverableRole(str, Enum):
    CANDIDATE = "candidate"
    BASELINE = "baseline"


class MechanicalGate(str, Enum):
    RIGHTS = "rights"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    BRAND = "brand"
    CHANNEL = "channel"
    ACCESSIBILITY = "accessibility"
    EXPERIMENT_TRACE = "experiment_trace"


class CoreFailureClass(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    RIGHTS_PROVENANCE = "rights_provenance"
    BRAND_DRIFT = "brand_drift"
    CHANNEL_ACCESSIBILITY = "channel_accessibility"
    ATTRIBUTION_CAUSALITY = "attribution_causality"


class PreferenceChoice(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    ABSTAIN = "abstain"


class JudgeKind(str, Enum):
    HUMAN = "human"
    MODEL = "model"


class RelationshipClaim(str, Enum):
    CORRELATIONAL = "correlational"
    CAUSAL = "causal"


class OutcomeObservationSource(str, Enum):
    FIRST_PARTY_EXPERIMENT = "first_party_experiment"
    VERIFIED_PLATFORM_ANALYTICS = "verified_platform_analytics"
    INDEPENDENT_HUMAN_STUDY = "independent_human_study"


def _present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _parse_aware_datetime(value: str) -> datetime | None:
    if not _present(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


@dataclass(frozen=True)
class Deliverable:
    """A modality-neutral, content-addressed candidate or baseline artifact."""

    deliverable_id: str
    scenario_id: str
    capability: Capability
    role: DeliverableRole
    content_sha256: str
    blind_artifact_locator: str
    rights_locator: str
    evidence_locators: tuple[str, ...]
    claim_ids: tuple[str, ...]
    brand_profile_id: str
    channel: str
    accessibility_locator: str
    experiment_trace_id: str
    clean_room_attested: bool
    method_reference_locators: tuple[str, ...] = ()
    copied_reference_asset_ids: tuple[str, ...] = ()

    def structural_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not _present(self.deliverable_id):
            failures.append("deliverable_id is required")
        if not _present(self.scenario_id):
            failures.append("scenario_id is required")
        if not _valid_sha256(self.content_sha256):
            failures.append("content_sha256 must be a lowercase SHA-256 digest")
        for name, value in (
            ("blind_artifact_locator", self.blind_artifact_locator),
            ("rights_locator", self.rights_locator),
            ("brand_profile_id", self.brand_profile_id),
            ("channel", self.channel),
            ("accessibility_locator", self.accessibility_locator),
            ("experiment_trace_id", self.experiment_trace_id),
        ):
            if not _present(value):
                failures.append(f"{name} is required")
        if not self.evidence_locators or any(
            not _present(item) for item in self.evidence_locators
        ):
            failures.append("at least one non-empty evidence locator is required")
        if not self.clean_room_attested:
            failures.append("clean-room attestation is required")
        if self.copied_reference_asset_ids:
            failures.append("reference artifacts may not be copied into deliverables")
        if any(not _present(item) for item in self.method_reference_locators):
            failures.append("method reference locators may not be empty")
        return tuple(failures)


@dataclass(frozen=True)
class CriticalFinding:
    deliverable_id: str
    gate: MechanicalGate
    reason: str
    severity: str = "critical"


@dataclass(frozen=True)
class MechanicalGateRecord:
    deliverable_id: str
    rights_clear: bool
    evidence_bound: bool
    claims_grounded: bool
    brand_conformant: bool
    channel_valid: bool
    accessibility_passed: bool
    experiment_trace_complete: bool
    gate_evidence_locators: Mapping[MechanicalGate, str]

    def critical_findings(self, deliverable: Deliverable) -> tuple[CriticalFinding, ...]:
        findings: list[CriticalFinding] = []
        if self.deliverable_id != deliverable.deliverable_id:
            findings.append(
                CriticalFinding(
                    deliverable.deliverable_id,
                    MechanicalGate.EVIDENCE,
                    "mechanical record does not bind the deliverable",
                )
            )
        checks = {
            MechanicalGate.RIGHTS: self.rights_clear,
            MechanicalGate.EVIDENCE: self.evidence_bound,
            MechanicalGate.CLAIM: self.claims_grounded,
            MechanicalGate.BRAND: self.brand_conformant,
            MechanicalGate.CHANNEL: self.channel_valid,
            MechanicalGate.ACCESSIBILITY: self.accessibility_passed,
            MechanicalGate.EXPERIMENT_TRACE: self.experiment_trace_complete,
        }
        for gate, passed in checks.items():
            locator = self.gate_evidence_locators.get(gate)
            if passed is not True:
                findings.append(
                    CriticalFinding(
                        deliverable.deliverable_id,
                        gate,
                        f"{gate.value} gate did not pass",
                    )
                )
            if not _present(locator):
                findings.append(
                    CriticalFinding(
                        deliverable.deliverable_id,
                        gate,
                        f"{gate.value} gate lacks an evidence locator",
                    )
                )
        structural = deliverable.structural_failures()
        for reason in structural:
            gate = (
                MechanicalGate.RIGHTS
                if "clean-room" in reason or "copied" in reason
                else MechanicalGate.EVIDENCE
            )
            findings.append(CriticalFinding(deliverable.deliverable_id, gate, reason))
        return tuple(findings)


@dataclass(frozen=True)
class BlindPair:
    pair_id: str
    scenario_id: str
    capability: Capability
    candidate_id: str
    baseline_id: str
    candidate_side: PreferenceChoice
    left_blind_id: str
    right_blind_id: str
    randomization_commitment: str
    sources_hidden: bool = True
    randomized_left_right: bool = True

    def public_packet(self) -> dict[str, str]:
        """Return the source- and role-blind payload presented to a rater."""

        return {
            "pair_id": self.pair_id,
            "scenario_id": self.scenario_id,
            "capability": self.capability.value,
            "left_blind_id": self.left_blind_id,
            "right_blind_id": self.right_blind_id,
        }

    def candidate_preferred(self, choice: PreferenceChoice) -> bool | None:
        if choice == PreferenceChoice.ABSTAIN:
            return None
        return choice == self.candidate_side


def build_blind_pair(
    *,
    pair_id: str,
    candidate: Deliverable,
    baseline: Deliverable,
    randomization_key: str,
) -> BlindPair:
    if not _present(pair_id) or not _present(randomization_key):
        raise EffectContractError("pair_id and randomization_key are required")
    if candidate.role != DeliverableRole.CANDIDATE:
        raise EffectContractError("candidate deliverable has the wrong role")
    if baseline.role != DeliverableRole.BASELINE:
        raise EffectContractError("baseline deliverable has the wrong role")
    if (candidate.scenario_id, candidate.capability) != (
        baseline.scenario_id,
        baseline.capability,
    ):
        raise EffectContractError("candidate and baseline must share scenario/capability")
    if candidate.deliverable_id == baseline.deliverable_id:
        raise EffectContractError("candidate and baseline IDs must differ")
    if candidate.content_sha256 == baseline.content_sha256:
        raise EffectContractError("an exact duplicate is not a valid effect comparison")
    private = "\x00".join(
        (
            randomization_key,
            pair_id,
            candidate.deliverable_id,
            baseline.deliverable_id,
        )
    )
    commitment = hashlib.sha256(private.encode("utf-8")).hexdigest()
    candidate_side = (
        PreferenceChoice.LEFT
        if int(commitment[:8], 16) % 2 == 0
        else PreferenceChoice.RIGHT
    )
    candidate_blind_id = hashlib.sha256(
        f"{private}\x00candidate".encode("utf-8")
    ).hexdigest()
    baseline_blind_id = hashlib.sha256(
        f"{private}\x00baseline".encode("utf-8")
    ).hexdigest()
    if candidate_side == PreferenceChoice.LEFT:
        left_id, right_id = candidate_blind_id, baseline_blind_id
    else:
        left_id, right_id = baseline_blind_id, candidate_blind_id
    return BlindPair(
        pair_id=pair_id,
        scenario_id=candidate.scenario_id,
        capability=candidate.capability,
        candidate_id=candidate.deliverable_id,
        baseline_id=baseline.deliverable_id,
        candidate_side=candidate_side,
        left_blind_id=left_id,
        right_blind_id=right_id,
        randomization_commitment=commitment,
    )


@dataclass(frozen=True)
class PreferenceVote:
    pair_id: str
    rater_id: str
    choice: PreferenceChoice
    judge_kind: JudgeKind
    independent: bool
    conflict_disclosed: bool


@dataclass(frozen=True)
class JudgeCalibration:
    human_labeled_cases: int
    true_positive: int
    false_negative: int
    true_negative: int
    false_positive: int
    evidence_locator: str

    @property
    def true_positive_rate(self) -> float | None:
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in (self.true_positive, self.false_negative)
        ):
            return None
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None

    @property
    def true_negative_rate(self) -> float | None:
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in (self.true_negative, self.false_positive)
        ):
            return None
        denominator = self.true_negative + self.false_positive
        return self.true_negative / denominator if denominator else None

    def failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        counts = (
            self.true_positive,
            self.false_negative,
            self.true_negative,
            self.false_positive,
        )
        invalid_counts = any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in counts
        )
        if invalid_counts:
            failures.append("judge confusion counts must be non-negative integers")
        if (
            isinstance(self.human_labeled_cases, bool)
            or not isinstance(self.human_labeled_cases, int)
            or self.human_labeled_cases < 0
        ):
            failures.append("human_labeled_cases must be a non-negative integer")
        elif not invalid_counts and self.human_labeled_cases != sum(counts):
            failures.append("human_labeled_cases must equal the confusion-matrix total")
        if (
            not isinstance(self.human_labeled_cases, int)
            or isinstance(self.human_labeled_cases, bool)
            or self.human_labeled_cases < 100
        ):
            failures.append("model judge requires at least 100 human-labelled cases")
        if self.true_positive_rate is None or self.true_positive_rate <= 0.80:
            failures.append("model judge TPR must be greater than 0.80")
        if self.true_negative_rate is None or self.true_negative_rate <= 0.80:
            failures.append("model judge TNR must be greater than 0.80")
        if not _present(self.evidence_locator):
            failures.append("judge calibration evidence locator is required")
        return tuple(failures)

    @property
    def promotion_eligible(self) -> bool:
        return not self.failures()


@dataclass(frozen=True)
class CapabilityEvidence:
    capability: Capability
    level: CapabilityEvidenceLevel
    evidence_locator: str
    observed_case_count: int
    limitations: tuple[str, ...]

    @property
    def can_claim_four_a_effect(self) -> bool:
        return self.level in {
            CapabilityEvidenceLevel.HUMAN_OBSERVED,
            CapabilityEvidenceLevel.PRODUCTION_OBSERVED,
        }

    def failures(self, minimum_cases: int) -> tuple[str, ...]:
        failures: list[str] = []
        if not _present(self.evidence_locator):
            failures.append(f"{self.capability.value}: capability evidence locator missing")
        if (
            isinstance(self.observed_case_count, bool)
            or not isinstance(self.observed_case_count, int)
            or self.observed_case_count < 0
        ):
            failures.append(f"{self.capability.value}: observed_case_count is invalid")
        elif self.can_claim_four_a_effect and self.observed_case_count < minimum_cases:
            failures.append(
                f"{self.capability.value}: fewer than {minimum_cases} observed cases"
            )
        if not self.limitations or any(not _present(item) for item in self.limitations):
            failures.append(f"{self.capability.value}: limitations must be disclosed")
        if not self.can_claim_four_a_effect:
            failures.append(
                f"{self.capability.value}: {self.level.value} cannot claim 4A effect"
            )
        return tuple(failures)


@dataclass(frozen=True)
class ScenarioPreferenceResult:
    capability: Capability
    scenario_id: str
    pair_count: int
    resolved_pair_count: int
    candidate_wins: int
    win_rate: float | None
    wilson_lower_95: float | None
    abstention_rate: float | None
    minimum_pair_agreement: float | None
    passed: bool


@dataclass(frozen=True)
class EffectPromotionReport:
    promoted: bool
    four_a_effect_claimable: bool
    critical_failure_count: int
    failures: tuple[str, ...]
    scenario_results: tuple[ScenarioPreferenceResult, ...]
    capability_levels: Mapping[str, str]
    judge_calibrated: bool | None
    truth_boundary: str = (
        "Promotion denotes this contract's clean-room, mechanically safe, blind "
        "preference result only; it is not proof of universal, causal, or Top-1 effect."
    )
    schema: str = "ProofLaunchGTMEffectPromotionReportV1"


@dataclass(frozen=True)
class EffectPromotionContract:
    required_capabilities: tuple[Capability, ...] = tuple(Capability)
    minimum_pairs_per_scenario: int = 30
    minimum_candidate_win_rate: float = 0.60
    minimum_wilson_lower_95_exclusive: float = 0.50
    minimum_votes_per_pair: int = 3
    minimum_human_raters_per_pair: int = 2
    minimum_pair_agreement: float = 2 / 3
    maximum_abstention_rate: float = 0.20
    minimum_failure_cases_per_class: int = 50

    def evaluate(
        self,
        *,
        deliverables: Sequence[Deliverable],
        mechanical_records: Sequence[MechanicalGateRecord],
        pairs: Sequence[BlindPair],
        votes: Sequence[PreferenceVote],
        failure_case_counts: Mapping[CoreFailureClass, int],
        capability_evidence: Sequence[CapabilityEvidence],
        evaluation_limitations: Sequence[str],
        judge_calibration: JudgeCalibration | None = None,
    ) -> EffectPromotionReport:
        failures: list[str] = []
        critical_findings: list[CriticalFinding] = []

        deliverable_by_id: dict[str, Deliverable] = {}
        for item in deliverables:
            if item.deliverable_id in deliverable_by_id:
                failures.append(f"duplicate deliverable_id: {item.deliverable_id}")
            deliverable_by_id[item.deliverable_id] = item
        records_by_id: dict[str, MechanicalGateRecord] = {}
        for record in mechanical_records:
            if record.deliverable_id in records_by_id:
                failures.append(f"duplicate mechanical record: {record.deliverable_id}")
            records_by_id[record.deliverable_id] = record

        used_deliverable_ids = {
            value for pair in pairs for value in (pair.candidate_id, pair.baseline_id)
        }
        for deliverable_id in sorted(used_deliverable_ids):
            deliverable = deliverable_by_id.get(deliverable_id)
            record = records_by_id.get(deliverable_id)
            if deliverable is None:
                critical_findings.append(
                    CriticalFinding(
                        deliverable_id,
                        MechanicalGate.EVIDENCE,
                        "pair references an unknown deliverable",
                    )
                )
                continue
            if record is None:
                critical_findings.append(
                    CriticalFinding(
                        deliverable_id,
                        MechanicalGate.EVIDENCE,
                        "missing mechanical gate record",
                    )
                )
                continue
            critical_findings.extend(record.critical_findings(deliverable))
        if critical_findings:
            failures.extend(
                f"{item.deliverable_id}:{item.gate.value}:{item.reason}"
                for item in critical_findings
            )

        for failure_class in CoreFailureClass:
            count = failure_case_counts.get(failure_class)
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < self.minimum_failure_cases_per_class
            ):
                failures.append(
                    f"{failure_class.value}: requires at least "
                    f"{self.minimum_failure_cases_per_class} failure cases"
                )

        capability_by_kind: dict[Capability, CapabilityEvidence] = {}
        for evidence in capability_evidence:
            if evidence.capability in capability_by_kind:
                failures.append(
                    f"duplicate capability evidence: {evidence.capability.value}"
                )
            capability_by_kind[evidence.capability] = evidence
        for capability in self.required_capabilities:
            evidence = capability_by_kind.get(capability)
            if evidence is None:
                failures.append(f"{capability.value}: capability evidence missing")
            else:
                failures.extend(evidence.failures(self.minimum_pairs_per_scenario))

        if not evaluation_limitations or any(
            not _present(item) for item in evaluation_limitations
        ):
            failures.append("evaluation limitations must be explicitly disclosed")

        has_model_votes = any(vote.judge_kind == JudgeKind.MODEL for vote in votes)
        judge_calibrated: bool | None = None
        if has_model_votes:
            judge_calibrated = bool(
                judge_calibration is not None and judge_calibration.promotion_eligible
            )
            if judge_calibration is None:
                failures.append("model judge votes lack human calibration")
            else:
                failures.extend(judge_calibration.failures())

        pair_by_id: dict[str, BlindPair] = {}
        compared_content_pairs: set[tuple[str, str, Capability, str]] = set()
        for pair in pairs:
            if pair.pair_id in pair_by_id:
                failures.append(f"duplicate pair_id: {pair.pair_id}")
            pair_by_id[pair.pair_id] = pair
            candidate = deliverable_by_id.get(pair.candidate_id)
            baseline = deliverable_by_id.get(pair.baseline_id)
            if candidate is not None and (
                candidate.role != DeliverableRole.CANDIDATE
                or candidate.scenario_id != pair.scenario_id
                or candidate.capability != pair.capability
            ):
                failures.append(f"{pair.pair_id}: candidate binding mismatch")
            if baseline is not None and (
                baseline.role != DeliverableRole.BASELINE
                or baseline.scenario_id != pair.scenario_id
                or baseline.capability != pair.capability
            ):
                failures.append(f"{pair.pair_id}: baseline binding mismatch")
            if candidate is not None and baseline is not None:
                content_pair = (
                    candidate.content_sha256,
                    baseline.content_sha256,
                    pair.capability,
                    pair.scenario_id,
                )
                if content_pair in compared_content_pairs:
                    failures.append(
                        f"{pair.pair_id}: repeated content pair cannot inflate sample size"
                    )
                compared_content_pairs.add(content_pair)
            if not pair.sources_hidden or not pair.randomized_left_right:
                failures.append(f"{pair.pair_id}: comparison is not blind/randomized")
            if pair.candidate_side not in {PreferenceChoice.LEFT, PreferenceChoice.RIGHT}:
                failures.append(f"{pair.pair_id}: invalid candidate side")

        votes_by_pair: dict[str, list[PreferenceVote]] = defaultdict(list)
        vote_keys: set[tuple[str, str]] = set()
        for vote in votes:
            if vote.pair_id not in pair_by_id:
                failures.append(f"vote references unknown pair: {vote.pair_id}")
                continue
            vote_key = (vote.pair_id, vote.rater_id)
            if vote_key in vote_keys:
                failures.append(
                    f"duplicate vote by {vote.rater_id} on {vote.pair_id}"
                )
                continue
            vote_keys.add(vote_key)
            if not _present(vote.rater_id):
                failures.append(f"{vote.pair_id}: rater_id is required")
            if not vote.independent:
                failures.append(f"{vote.pair_id}: non-independent vote")
            if not vote.conflict_disclosed:
                failures.append(f"{vote.pair_id}: rater conflict not disclosed")
            votes_by_pair[vote.pair_id].append(vote)

        groups: dict[tuple[Capability, str], list[BlindPair]] = defaultdict(list)
        for pair in pairs:
            groups[(pair.capability, pair.scenario_id)].append(pair)

        scenario_results: list[ScenarioPreferenceResult] = []
        for capability in self.required_capabilities:
            capability_groups = [key for key in groups if key[0] == capability]
            if not capability_groups:
                failures.append(f"{capability.value}: no blind-pair scenario")
        for (capability, scenario_id), scenario_pairs in sorted(
            groups.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            pair_count = len(scenario_pairs)
            if pair_count < self.minimum_pairs_per_scenario:
                failures.append(
                    f"{capability.value}/{scenario_id}: fewer than "
                    f"{self.minimum_pairs_per_scenario} pairs"
                )
            wins = 0
            resolved = 0
            total_votes = 0
            abstentions = 0
            agreements: list[float] = []
            for pair in scenario_pairs:
                pair_votes = votes_by_pair.get(pair.pair_id, [])
                human_pair_votes = [
                    vote
                    for vote in pair_votes
                    if vote.judge_kind == JudgeKind.HUMAN
                ]
                total_votes += len(human_pair_votes)
                abstentions += sum(
                    vote.choice == PreferenceChoice.ABSTAIN
                    for vote in human_pair_votes
                )
                eligible_non_abstain = [
                    vote
                    for vote in human_pair_votes
                    if vote.choice != PreferenceChoice.ABSTAIN
                ]
                human_raters = {
                    vote.rater_id
                    for vote in eligible_non_abstain
                }
                if len(eligible_non_abstain) < self.minimum_votes_per_pair:
                    failures.append(f"{pair.pair_id}: too few eligible preference votes")
                    continue
                if len(human_raters) < self.minimum_human_raters_per_pair:
                    failures.append(f"{pair.pair_id}: too few independent human raters")
                    continue
                counts = Counter(vote.choice for vote in eligible_non_abstain)
                left, right = counts[PreferenceChoice.LEFT], counts[PreferenceChoice.RIGHT]
                if left == right:
                    failures.append(f"{pair.pair_id}: tied preference is unresolved")
                    continue
                majority_choice = (
                    PreferenceChoice.LEFT if left > right else PreferenceChoice.RIGHT
                )
                agreement = max(left, right) / (left + right)
                agreements.append(agreement)
                if agreement < self.minimum_pair_agreement:
                    failures.append(f"{pair.pair_id}: inter-rater agreement too low")
                    continue
                resolved += 1
                if pair.candidate_preferred(majority_choice):
                    wins += 1
            abstention_rate = (
                abstentions / total_votes if total_votes else None
            )
            if abstention_rate is None or abstention_rate > self.maximum_abstention_rate:
                failures.append(
                    f"{capability.value}/{scenario_id}: abstention rate exceeds "
                    f"{self.maximum_abstention_rate:.0%}"
                )
            win_rate = wins / resolved if resolved else None
            lower = wilson_lower_bound(wins, resolved) if resolved else None
            passed = (
                resolved >= self.minimum_pairs_per_scenario
                and win_rate is not None
                and win_rate >= self.minimum_candidate_win_rate
                and lower is not None
                and lower > self.minimum_wilson_lower_95_exclusive
                and abstention_rate is not None
                and abstention_rate <= self.maximum_abstention_rate
                and bool(agreements)
                and min(agreements) >= self.minimum_pair_agreement
            )
            if resolved < self.minimum_pairs_per_scenario:
                failures.append(
                    f"{capability.value}/{scenario_id}: fewer than "
                    f"{self.minimum_pairs_per_scenario} resolved pairs"
                )
            if win_rate is None or win_rate < self.minimum_candidate_win_rate:
                failures.append(
                    f"{capability.value}/{scenario_id}: candidate win rate below "
                    f"{self.minimum_candidate_win_rate:.0%}"
                )
            if lower is None or lower <= self.minimum_wilson_lower_95_exclusive:
                failures.append(
                    f"{capability.value}/{scenario_id}: Wilson lower bound must be "
                    f"greater than {self.minimum_wilson_lower_95_exclusive:.2f}"
                )
            scenario_results.append(
                ScenarioPreferenceResult(
                    capability=capability,
                    scenario_id=scenario_id,
                    pair_count=pair_count,
                    resolved_pair_count=resolved,
                    candidate_wins=wins,
                    win_rate=win_rate,
                    wilson_lower_95=lower,
                    abstention_rate=abstention_rate,
                    minimum_pair_agreement=min(agreements) if agreements else None,
                    passed=passed,
                )
            )

        failures = list(dict.fromkeys(failures))
        four_a_effect_claimable = all(
            capability_by_kind.get(capability) is not None
            and capability_by_kind[capability].can_claim_four_a_effect
            for capability in self.required_capabilities
        )
        promoted = (
            not failures
            and not critical_findings
            and bool(scenario_results)
            and all(item.passed for item in scenario_results)
            and four_a_effect_claimable
        )
        return EffectPromotionReport(
            promoted=promoted,
            four_a_effect_claimable=four_a_effect_claimable,
            critical_failure_count=len(critical_findings),
            failures=tuple(failures),
            scenario_results=tuple(scenario_results),
            capability_levels={
                capability.value: capability_by_kind[capability].level.value
                for capability in self.required_capabilities
                if capability in capability_by_kind
            },
            judge_calibrated=judge_calibrated,
        )


_ACCEPTED_CAUSAL_METHODS = frozenset(
    {
        "randomized_controlled_trial",
        "difference_in_differences",
        "regression_discontinuity",
        "instrumental_variable",
    }
)


@dataclass(frozen=True)
class ObservedOutcome:
    outcome_id: str
    capability: Capability
    experiment_id: str
    metric_name: str
    observed_value: float
    sample_denominator: int
    attribution_window_start: str
    attribution_window_end: str
    baseline_id: str
    observation_source: OutcomeObservationSource
    relationship_claim: RelationshipClaim = RelationshipClaim.CORRELATIONAL
    causal_language_used: bool = False
    causal_method: str | None = None
    causal_assumptions_locator: str | None = None

    def learning_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        for name, value in (
            ("outcome_id", self.outcome_id),
            ("experiment_id", self.experiment_id),
            ("metric_name", self.metric_name),
            ("baseline_id", self.baseline_id),
        ):
            if not _present(value):
                failures.append(f"{name} is required")
        if isinstance(self.observed_value, bool) or not isinstance(
            self.observed_value, (int, float)
        ) or not math.isfinite(float(self.observed_value)):
            failures.append("observed_value must be finite")
        if (
            isinstance(self.sample_denominator, bool)
            or not isinstance(self.sample_denominator, int)
            or self.sample_denominator <= 0
        ):
            failures.append("sample_denominator must be a positive integer")
        start = _parse_aware_datetime(self.attribution_window_start)
        end = _parse_aware_datetime(self.attribution_window_end)
        if start is None or end is None or start >= end:
            failures.append("attribution window must be timezone-aware and increasing")
        if self.relationship_claim == RelationshipClaim.CORRELATIONAL:
            if self.causal_language_used:
                failures.append("correlational observations may not use causal language")
            if self.causal_method is not None:
                failures.append("correlational observations may not declare a causal method")
        else:
            if self.causal_method not in _ACCEPTED_CAUSAL_METHODS:
                failures.append("causal claim lacks an accepted identification method")
            if not _present(self.causal_assumptions_locator):
                failures.append("causal claim lacks an assumptions/diagnostics locator")
        return tuple(failures)

    @property
    def admissible_for_learning(self) -> bool:
        return not self.learning_failures()


@dataclass(frozen=True)
class LearningAdmission:
    admitted_outcome_ids: tuple[str, ...]
    rejected: Mapping[str, tuple[str, ...]]
    schema: str = "ProofLaunchObservedOutcomeLearningAdmissionV1"


def admit_observed_outcomes(outcomes: Sequence[ObservedOutcome]) -> LearningAdmission:
    admitted: list[str] = []
    rejected: dict[str, tuple[str, ...]] = {}
    id_counts = Counter(outcome.outcome_id for outcome in outcomes)
    for outcome in outcomes:
        failures = list(outcome.learning_failures())
        if id_counts[outcome.outcome_id] > 1:
            failures.append("duplicate outcome_id")
        if failures:
            rejected[outcome.outcome_id] = tuple(dict.fromkeys(failures))
        else:
            admitted.append(outcome.outcome_id)
    return LearningAdmission(tuple(admitted), rejected)
