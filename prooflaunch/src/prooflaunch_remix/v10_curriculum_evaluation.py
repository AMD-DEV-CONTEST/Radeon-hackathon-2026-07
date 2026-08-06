from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


class CurriculumArm(str, Enum):
    FAILURE_DRIVEN = "failure_driven"
    STATIC = "static"


@dataclass(frozen=True)
class VerifierIdentity:
    verifier_id: str
    principal_id: str
    model_family: str
    checkpoint_revision: str
    rubric_sha256: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "verifier_id",
            "principal_id",
            "model_family",
            "checkpoint_revision",
        ):
            if not str(getattr(self, field_name)).strip():
                raise V10ContractError(f"{field_name} is required")
        for field_name in ("rubric_sha256", "prompt_sha256"):
            value = str(getattr(self, field_name))
            if len(value) != 64:
                raise V10ContractError(f"{field_name} must be SHA-256")


@dataclass(frozen=True)
class CriticIndependenceReceipt:
    producer_principal_id: str
    producer_model_family: str
    producer_checkpoint_revision: str
    verifiers: tuple[VerifierIdentity, ...]
    candidate_ids_blinded: bool
    independent_tool_replay: bool
    collusion_blockers: tuple[str, ...]
    passed: bool
    digest: str


def audit_critic_independence(
    *,
    producer_principal_id: str,
    producer_model_family: str,
    producer_checkpoint_revision: str,
    verifiers: Iterable[VerifierIdentity],
    candidate_ids_blinded: bool,
    independent_tool_replay: bool,
) -> CriticIndependenceReceipt:
    items = tuple(verifiers)
    blockers: list[str] = []
    if len(items) < 2:
        blockers.append("fewer than two independent verifiers")
    if len({item.verifier_id for item in items}) != len(items):
        blockers.append("duplicate verifier id")
    if len({item.principal_id for item in items}) != len(items):
        blockers.append("verifiers share a principal")
    if any(item.principal_id == producer_principal_id for item in items):
        blockers.append("producer principal also acts as verifier")
    if any(
        item.model_family == producer_model_family
        and item.checkpoint_revision == producer_checkpoint_revision
        for item in items
    ):
        blockers.append("producer checkpoint also acts as verifier")
    if len({(item.model_family, item.checkpoint_revision) for item in items}) != len(items):
        blockers.append("verifiers share the same model checkpoint")
    if len({item.prompt_sha256 for item in items}) != len(items):
        blockers.append("verifiers share an identical prompt lineage")
    if not candidate_ids_blinded:
        blockers.append("candidate identity is not blinded")
    if not independent_tool_replay:
        blockers.append("no independent tool replay")
    blockers = tuple(dict.fromkeys(blockers))
    material = {
        "producer_principal_id": producer_principal_id,
        "producer_model_family": producer_model_family,
        "producer_checkpoint_revision": producer_checkpoint_revision,
        "verifiers": [asdict(item) for item in items],
        "candidate_ids_blinded": candidate_ids_blinded,
        "independent_tool_replay": independent_tool_replay,
        "collusion_blockers": blockers,
    }
    return CriticIndependenceReceipt(
        **material,
        passed=not blockers,
        digest=stable_sha256(material),
    )


@dataclass(frozen=True)
class CurriculumOutcome:
    pair_id: str
    arm: CurriculumArm
    task_id: str
    environment_revision: str
    task_seed: int
    checkpoint_revision: str
    success: bool
    verifier_score: float
    steps: int
    safety_failures: int = 0

    def __post_init__(self) -> None:
        for name in ("pair_id", "task_id", "environment_revision", "checkpoint_revision"):
            if not str(getattr(self, name)).strip():
                raise V10ContractError(f"{name} is required")
        if not 0.0 <= self.verifier_score <= 1.0:
            raise V10ContractError("verifier score must be in [0,1]")
        if self.steps < 1 or self.safety_failures < 0:
            raise V10ContractError("steps and safety failures are invalid")


@dataclass(frozen=True)
class CurriculumEffect:
    matched_pairs: int
    failure_driven_success_rate: float
    static_success_rate: float
    success_rate_difference: float
    verifier_score_difference: float
    mean_step_difference: float
    discordant_wins: int
    discordant_losses: int
    safety_failure_difference: int


def evaluate_paired_curriculum(outcomes: Iterable[CurriculumOutcome]) -> CurriculumEffect:
    items = tuple(outcomes)
    pairs: dict[str, dict[CurriculumArm, CurriculumOutcome]] = {}
    for item in items:
        by_arm = pairs.setdefault(item.pair_id, {})
        if item.arm in by_arm:
            raise V10ContractError("duplicate curriculum arm in pair")
        by_arm[item.arm] = item
    if not pairs or any(set(value) != set(CurriculumArm) for value in pairs.values()):
        raise V10ContractError("each curriculum pair needs static and failure-driven arms")
    dynamic: list[CurriculumOutcome] = []
    static: list[CurriculumOutcome] = []
    for pair_id, by_arm in pairs.items():
        left = by_arm[CurriculumArm.FAILURE_DRIVEN]
        right = by_arm[CurriculumArm.STATIC]
        if (
            left.task_id != right.task_id
            or left.environment_revision != right.environment_revision
            or left.task_seed != right.task_seed
            or left.checkpoint_revision != right.checkpoint_revision
        ):
            raise V10ContractError(f"unmatched experimental pair: {pair_id}")
        dynamic.append(left)
        static.append(right)
    count = len(dynamic)
    dynamic_success = sum(item.success for item in dynamic) / count
    static_success = sum(item.success for item in static) / count
    dynamic_score = sum(item.verifier_score for item in dynamic) / count
    static_score = sum(item.verifier_score for item in static) / count
    dynamic_steps = sum(item.steps for item in dynamic) / count
    static_steps = sum(item.steps for item in static) / count
    wins = sum(left.success and not right.success for left, right in zip(dynamic, static, strict=True))
    losses = sum(right.success and not left.success for left, right in zip(dynamic, static, strict=True))
    return CurriculumEffect(
        matched_pairs=count,
        failure_driven_success_rate=round(dynamic_success, 6),
        static_success_rate=round(static_success, 6),
        success_rate_difference=round(dynamic_success - static_success, 6),
        verifier_score_difference=round(dynamic_score - static_score, 6),
        mean_step_difference=round(dynamic_steps - static_steps, 6),
        discordant_wins=wins,
        discordant_losses=losses,
        safety_failure_difference=sum(item.safety_failures for item in dynamic)
        - sum(item.safety_failures for item in static),
    )


def build_evolution_report(
    effect: CurriculumEffect,
    critic_receipt: CriticIndependenceReceipt,
    *,
    observed_model_inference: bool,
    external_held_out: bool,
    minimum_pairs: int = 100,
) -> dict:
    promotion_failures = []
    if not critic_receipt.passed:
        promotion_failures.append("critic independence failed")
    if not observed_model_inference:
        promotion_failures.append("no observed model inference")
    if not external_held_out:
        promotion_failures.append("comparison is not external held-out")
    if effect.matched_pairs < minimum_pairs:
        promotion_failures.append("insufficient matched pairs")
    if effect.success_rate_difference <= 0:
        promotion_failures.append("no positive task-success difference")
    if effect.verifier_score_difference <= 0:
        promotion_failures.append("no positive verifier-score difference")
    if effect.safety_failure_difference > 0:
        promotion_failures.append("safety failures regressed")
    payload = {
        "schema": "ProofLaunchCurriculumEvolutionReportV1",
        "effect": asdict(effect),
        "critic_independence_digest": critic_receipt.digest,
        "observed_model_inference": observed_model_inference,
        "external_held_out": external_held_out,
        "promotion_eligible": not promotion_failures,
        "promotion_failures": promotion_failures,
        "truth_boundary": (
            "Matched local controls measure the supplied outcomes only; without observed "
            "model inference and external held-out tasks they are not curriculum uplift."
        ),
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
