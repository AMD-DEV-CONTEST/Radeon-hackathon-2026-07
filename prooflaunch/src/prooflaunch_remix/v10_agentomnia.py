from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError


class ApplicationSplit(str, Enum):
    TO_CONSUMER = "toc"
    TO_BUSINESS = "tob"
    TO_EMPLOYEE = "toe"


class Capability(str, Enum):
    TASK_UNDERSTANDING = "task_understanding"
    INFORMATION_GATHERING = "information_gathering"
    PLANNING_DECISION = "planning_decision_making"
    STATE_MANAGEMENT = "state_management"
    TOOL_USE = "tool_use"
    CODE_OPERATIONS = "code_programmatic_operations"
    DATA_ANALYSIS = "data_analysis"
    OFFICE_DOCUMENTS = "office_document_handling"
    INTERACTIVE_COLLABORATION = "interactive_collaboration"
    RELIABILITY_SAFETY = "reliability_safety"


class AtomicDifficulty(str, Enum):
    AMBIGUOUS_GOAL = "ambiguous_goal_contextual_constraints"
    TOOL_GROUNDING = "tool_parameter_grounding"
    STRUCTURED_INFORMATION = "structured_information_complexity"
    LONG_CONTEXT = "long_context_multi_artifact_evidence"
    DYNAMIC_PLANNING = "dynamic_multi_step_planning"
    SOURCE_INCONSISTENCY = "multi_source_inconsistency"
    STATE_EVOLUTION = "progressive_disclosure_state_evolution"
    RISK_CLARIFICATION = "risk_reliability_clarification"


class ReasoningRoute(str, Enum):
    DAG = "dag"
    DAG_SINGLE_TURN = "dag_s"
    SOLVER = "solver"
    PROGRAM = "program"


class DatasetPartition(str, Enum):
    SFT = "sft"
    RL = "rl"
    VALIDATION = "validation"
    EVALUATION = "evaluation"


class EvolutionStatus(str, Enum):
    HOLD = "hold"
    ADMITTED = "admitted"


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _stable_digest(payload: object) -> str:
    def jsonable(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(key): jsonable(item) for key, item in value.items()}
        if isinstance(value, (set, frozenset)):
            return sorted(jsonable(item) for item in value)
        if isinstance(value, (tuple, list)):
            return [jsonable(item) for item in value]
        return value

    return hashlib.sha256(
        json.dumps(
            jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class AgentCoordinate:
    application_split: ApplicationSplit
    domain_l1: str
    scenario_l2: str
    capabilities: frozenset[Capability]
    difficulties: frozenset[AtomicDifficulty]
    primary_difficulty: AtomicDifficulty
    route: ReasoningRoute

    def __post_init__(self) -> None:
        if not self.domain_l1.strip() or not self.scenario_l2.strip():
            raise V10ContractError("domain L1 and scenario L2 are required")
        if not self.capabilities:
            raise V10ContractError("a task needs at least one capability label")
        if not self.difficulties:
            raise V10ContractError("a task needs at least one atomic difficulty")
        if self.primary_difficulty not in self.difficulties:
            raise V10ContractError(
                "primary difficulty must be active in the difficulty profile"
            )

    @property
    def key(self) -> str:
        return "/".join(
            (
                self.application_split.value,
                self.domain_l1.strip().lower().replace(" ", "_"),
                self.scenario_l2.strip().lower().replace(" ", "_"),
                "+".join(sorted(item.value for item in self.capabilities)),
                "+".join(sorted(item.value for item in self.difficulties)),
                self.route.value,
            )
        )


@dataclass(frozen=True)
class ToolContract:
    name: str
    schema_sha256: str
    read_only: bool
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise V10ContractError("tool name is required")
        _require_sha256(self.schema_sha256, "tool schema_sha256")
        if not self.read_only and not self.requires_confirmation:
            raise V10ContractError(
                "state-changing tools must require an explicit confirmation boundary"
            )


@dataclass(frozen=True)
class ExecutableEnvironment:
    environment_id: str
    revision_sha256: str
    license_id: str
    tools: tuple[ToolContract, ...]
    resettable: bool
    golden_replay_verified: bool
    healthcheck_passed: bool
    deterministic_seed: int

    def __post_init__(self) -> None:
        if not self.environment_id.strip() or not self.license_id.strip():
            raise V10ContractError("environment id and license are required")
        _require_sha256(self.revision_sha256, "environment revision_sha256")
        if not self.tools:
            raise V10ContractError("an executable environment needs tools")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise V10ContractError("environment tool names must be unique")

    @property
    def rcrl_eligible(self) -> bool:
        return (
            self.resettable
            and self.golden_replay_verified
            and self.healthcheck_passed
        )


@dataclass(frozen=True)
class StepTransition:
    step_index: int
    observation_sha256: str
    action_name: str
    action_arguments_sha256: str
    tool_response_sha256: str
    next_observation_sha256: str
    terminal: bool
    terminal_signal: str | None = None

    def __post_init__(self) -> None:
        if self.step_index < 0 or not self.action_name.strip():
            raise V10ContractError("step index and action are invalid")
        for name, value in (
            ("observation_sha256", self.observation_sha256),
            ("action_arguments_sha256", self.action_arguments_sha256),
            ("tool_response_sha256", self.tool_response_sha256),
            ("next_observation_sha256", self.next_observation_sha256),
        ):
            _require_sha256(value, name)
        if self.terminal != bool(self.terminal_signal):
            raise V10ContractError(
                "terminal steps need a signal and non-terminal steps cannot have one"
            )


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    environment_id: str
    environment_revision_sha256: str
    partition: DatasetPartition
    coordinate: AgentCoordinate
    verifier_ids: tuple[str, ...]
    maximum_steps: int
    task_seed: int
    checkpoint_revision: str
    golden_trajectory: tuple[StepTransition, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.environment_id.strip():
            raise V10ContractError("task and environment ids are required")
        _require_sha256(
            self.environment_revision_sha256,
            "task environment_revision_sha256",
        )
        if not self.verifier_ids or any(not item.strip() for item in self.verifier_ids):
            raise V10ContractError("task requires one or more explicit verifiers")
        if self.maximum_steps < 1 or not self.checkpoint_revision.strip():
            raise V10ContractError("task step budget and checkpoint are required")
        indices = [step.step_index for step in self.golden_trajectory]
        if indices and indices != list(range(len(indices))):
            raise V10ContractError("golden trajectory steps must be contiguous from zero")
        if self.golden_trajectory and not self.golden_trajectory[-1].terminal:
            raise V10ContractError("a golden trajectory must terminate explicitly")


@dataclass(frozen=True)
class FailureAttribution:
    trajectory_length: int
    first_error_step: int
    propagation_steps: tuple[int, ...]
    missed_detection_step: int | None
    repair_step: int | None
    stop_step: int
    failure_kind: str

    def __post_init__(self) -> None:
        if self.trajectory_length < 1 or not self.failure_kind.strip():
            raise V10ContractError("failure trajectory and kind are required")
        all_indices = (
            (self.first_error_step, self.stop_step)
            + self.propagation_steps
            + tuple(
                value
                for value in (self.missed_detection_step, self.repair_step)
                if value is not None
            )
        )
        if any(index < 0 or index >= self.trajectory_length for index in all_indices):
            raise V10ContractError("failure attribution step is outside trajectory")
        if self.stop_step < self.first_error_step:
            raise V10ContractError("stop step cannot precede the first error")
        if any(index <= self.first_error_step for index in self.propagation_steps):
            raise V10ContractError("propagation must follow the first error")
        if self.missed_detection_step is not None and (
            self.missed_detection_step < self.first_error_step
        ):
            raise V10ContractError("missed detection cannot precede the first error")
        if self.repair_step is not None and self.repair_step <= self.first_error_step:
            raise V10ContractError("repair must follow the first error")


@dataclass(frozen=True)
class RolloutResult:
    rollout_id: str
    reward: float
    policy_failure: bool
    environment_failure: bool = False
    truncated: bool = False

    def __post_init__(self) -> None:
        if not self.rollout_id.strip() or not math.isfinite(self.reward):
            raise V10ContractError("rollout id and finite reward are required")
        if not 0.0 <= self.reward <= 1.0:
            raise V10ContractError("rollout reward must be in [0, 1]")


@dataclass(frozen=True)
class RCRLRecovery:
    task_id: str
    environment_revision_sha256: str
    checkpoint_revision: str
    prefix_steps: tuple[StepTransition, ...]
    unresolved_suffix_steps: int
    group_rollout_ids: tuple[str, ...]
    reason: str = "all_policy_rollouts_failed"

    @classmethod
    def from_all_fail_group(
        cls,
        task: AgentTask,
        environment: ExecutableEnvironment,
        rollouts: Sequence[RolloutResult],
        *,
        prefix_fraction: float = 0.20,
    ) -> "RCRLRecovery":
        if task.partition != DatasetPartition.RL:
            raise V10ContractError("RCRL recovery accepts RL tasks only")
        if task.environment_id != environment.environment_id or (
            task.environment_revision_sha256 != environment.revision_sha256
        ):
            raise V10ContractError("task and environment revisions do not match")
        if not environment.rcrl_eligible:
            raise V10ContractError("RCRL requires a healthy resettable replay-verified environment")
        if not task.golden_trajectory:
            raise V10ContractError("RCRL requires a verified golden trajectory")
        if not rollouts:
            raise V10ContractError("RCRL requires a non-empty rollout group")
        if any(item.environment_failure or item.truncated for item in rollouts):
            raise V10ContractError("environment failures and truncations cannot trigger RCRL")
        if any((not item.policy_failure) or item.reward != 0.0 for item in rollouts):
            raise V10ContractError("a golden prefix is allowed only for an all-fail group")
        if not 0.0 < prefix_fraction < 1.0:
            raise V10ContractError("prefix fraction must preserve an unresolved suffix")
        prefix_count = max(1, math.ceil(len(task.golden_trajectory) * prefix_fraction))
        prefix_count = min(prefix_count, len(task.golden_trajectory) - 1)
        if prefix_count < 1:
            raise V10ContractError("golden trajectory is too short for rollback curriculum")
        return cls(
            task_id=task.task_id,
            environment_revision_sha256=environment.revision_sha256,
            checkpoint_revision=task.checkpoint_revision,
            prefix_steps=task.golden_trajectory[:prefix_count],
            unresolved_suffix_steps=len(task.golden_trajectory) - prefix_count,
            group_rollout_ids=tuple(item.rollout_id for item in rollouts),
        )


@dataclass(frozen=True)
class CurriculumCandidate:
    task: AgentTask
    difficulty_score: float
    novelty_score: float
    coverage_gain: float
    failure_value: float
    verifier_reliability: float
    repeated_low_value_failure: bool = False
    counterfactual_variant: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "difficulty_score",
            "novelty_score",
            "coverage_gain",
            "failure_value",
            "verifier_reliability",
        ):
            value = getattr(self, field_name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise V10ContractError(f"{field_name} must be in [0, 1]")


@dataclass(frozen=True)
class FrozenCurriculum:
    round_id: str
    checkpoint_revision: str
    seed: int
    task_ids: tuple[str, ...]
    rejected_task_ids: tuple[str, ...]
    coordinate_counts: Mapping[str, int]
    digest: str


class FailureDrivenCurriculum:
    def __init__(self, *, minimum_verifier_reliability: float = 0.90) -> None:
        if not 0.0 < minimum_verifier_reliability <= 1.0:
            raise V10ContractError("minimum verifier reliability is invalid")
        self.minimum_verifier_reliability = minimum_verifier_reliability

    def freeze(
        self,
        round_id: str,
        candidates: Sequence[CurriculumCandidate],
        *,
        checkpoint_revision: str,
        seed: int,
        maximum_tasks: int,
    ) -> FrozenCurriculum:
        if not round_id.strip() or not checkpoint_revision.strip() or maximum_tasks < 1:
            raise V10ContractError("round, checkpoint, and positive task budget are required")
        admitted = [
            item
            for item in candidates
            if item.verifier_reliability >= self.minimum_verifier_reliability
            and not item.repeated_low_value_failure
        ]
        rejected = [item.task.task_id for item in candidates if item not in admitted]

        def score(item: CurriculumCandidate) -> tuple[float, str]:
            value = (
                0.25 * item.difficulty_score
                + 0.15 * item.novelty_score
                + 0.25 * item.coverage_gain
                + 0.25 * item.failure_value
                + 0.10 * float(item.counterfactual_variant)
            )
            return (-value, item.task.task_id)

        selected = sorted(admitted, key=score)[:maximum_tasks]
        coordinate_counts: dict[str, int] = {}
        for item in selected:
            key = item.task.coordinate.key
            coordinate_counts[key] = coordinate_counts.get(key, 0) + 1
        task_ids = tuple(item.task.task_id for item in selected)
        rejected_task_ids = tuple(rejected)
        payload = {
            "round_id": round_id,
            "checkpoint_revision": checkpoint_revision,
            "seed": seed,
            "task_ids": task_ids,
            "rejected_task_ids": rejected_task_ids,
            "coordinate_counts": coordinate_counts,
        }
        return FrozenCurriculum(
            **payload,
            digest=_stable_digest(payload),
        )


@dataclass(frozen=True)
class EvolutionBatch:
    batch_id: str
    source_failure_ids: tuple[str, ...]
    environments: tuple[ExecutableEnvironment, ...]
    tasks: tuple[AgentTask, ...]
    external_transfer_benchmarks: tuple[str, ...]
    status: EvolutionStatus = field(init=False)
    blockers: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        blockers: list[str] = []
        if not self.batch_id.strip() or not self.source_failure_ids:
            blockers.append("failure-grounded PRD identity is missing")
        if not self.environments or not self.tasks:
            blockers.append("evolution batch is empty")
        environment_by_id = {item.environment_id: item for item in self.environments}
        if len(environment_by_id) != len(self.environments):
            blockers.append("duplicate environment ids")
        for environment in self.environments:
            if not environment.healthcheck_passed:
                blockers.append(f"environment healthcheck failed: {environment.environment_id}")
        for task in self.tasks:
            environment = environment_by_id.get(task.environment_id)
            if environment is None or environment.revision_sha256 != task.environment_revision_sha256:
                blockers.append(f"task environment is unresolved: {task.task_id}")
        target_task_ids = {item.task_id for item in self.tasks}
        if target_task_ids & set(self.external_transfer_benchmarks):
            blockers.append("external transfer benchmark contaminated PRD targets")
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(blockers)))
        object.__setattr__(
            self,
            "status",
            EvolutionStatus.HOLD if blockers else EvolutionStatus.ADMITTED,
        )


@dataclass(frozen=True)
class FullScenarioTrainingContract:
    base_model: str
    base_revision: str
    common_policy_head: str
    benchmark_specific_adapters: tuple[str, ...]
    environments: tuple[ExecutableEnvironment, ...]
    tasks: tuple[AgentTask, ...]
    minimum_capability_dimensions: int = 10
    minimum_difficulty_dimensions: int = 8

    def audit(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.base_model.strip() or not self.base_revision.strip():
            failures.append("base model revision is not frozen")
        if not self.common_policy_head.strip():
            failures.append("common policy head is missing")
        if self.benchmark_specific_adapters:
            failures.append("benchmark-specific adapters are forbidden")
        if self.minimum_capability_dimensions != len(Capability):
            failures.append("capability taxonomy is incomplete")
        if self.minimum_difficulty_dimensions != len(AtomicDifficulty):
            failures.append("atomic difficulty taxonomy is incomplete")
        if not self.environments:
            failures.append("executable environment corpus is empty")
        if not self.tasks:
            failures.append("agent task corpus is empty")
        environment_by_id = {item.environment_id: item for item in self.environments}
        if len(environment_by_id) != len(self.environments):
            failures.append("duplicate environment ids")
        partition_hashes: dict[DatasetPartition, set[str]] = {
            item: set() for item in DatasetPartition
        }
        task_ids: set[str] = set()
        for task in self.tasks:
            if task.task_id in task_ids:
                failures.append(f"duplicate task id: {task.task_id}")
            task_ids.add(task.task_id)
            environment = environment_by_id.get(task.environment_id)
            if environment is None or environment.revision_sha256 != task.environment_revision_sha256:
                failures.append(f"unresolved task environment: {task.task_id}")
            partition_hashes[task.partition].add(task.environment_revision_sha256)
        for partition in DatasetPartition:
            if not any(task.partition == partition for task in self.tasks):
                failures.append(f"{partition.value} task partition is empty")
        training_hashes = partition_hashes[DatasetPartition.SFT] | partition_hashes[
            DatasetPartition.RL
        ]
        evaluation_hashes = partition_hashes[DatasetPartition.EVALUATION]
        if training_hashes & evaluation_hashes:
            failures.append("training/evaluation environment revision contamination")
        return tuple(dict.fromkeys(failures))

    @property
    def digest(self) -> str:
        payload = asdict(self)
        return _stable_digest(payload)
