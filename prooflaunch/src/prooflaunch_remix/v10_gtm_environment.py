from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_agentomnia import (
    AgentCoordinate,
    AgentTask,
    ApplicationSplit,
    AtomicDifficulty,
    Capability,
    DatasetPartition,
    ExecutableEnvironment,
    ReasoningRoute,
    StepTransition,
    ToolContract,
)
from .v10_contracts import V10ContractError
from .v10_frontier_landscape import ProductLane


class AgentRole(str, Enum):
    CHALLENGER = "challenger"
    PLANNER = "planner"
    PRODUCER = "producer"
    CRITIC = "critic"
    VERIFIER = "verifier"


class IssueKind(str, Enum):
    FACT_CONFLICT = "fact_conflict"
    EVIDENCE_MISSING = "evidence_missing"
    LONG_DOCUMENT = "long_document"
    MULTI_IMAGE_CONFLICT = "multi_image_conflict"
    PRODUCT_IDENTITY = "product_identity"
    LOGO_DRIFT = "logo_drift"
    BRAND_COLOR = "brand_color"
    OCR = "ocr"
    SAFE_ZONE = "safe_zone"
    IMPLIED_CLAIM = "implied_claim"
    LOCALIZATION = "localization"
    VIDEO_FLICKER = "video_flicker"
    AV_ALIGNMENT = "av_alignment"
    TOOL_TIMEOUT = "tool_timeout"
    MODEL_OOM = "model_oom"
    STALE_MEMORY = "stale_memory"
    AGENT_CONFLICT = "agent_conflict"
    INVALID_LOOP = "invalid_loop"
    OVERTHINKING = "overthinking"


class Operation(str, Enum):
    INSPECT = "inspect"
    REQUEST_EVIDENCE = "request_evidence"
    QUARANTINE = "quarantine"
    REPAIR = "repair"
    FALLBACK = "fallback"
    ESCALATE = "escalate"
    STOP = "stop"


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


def stable_digest(payload: object) -> str:
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


EXPECTED_OPERATION: Mapping[IssueKind, Operation] = {
    IssueKind.FACT_CONFLICT: Operation.QUARANTINE,
    IssueKind.EVIDENCE_MISSING: Operation.REQUEST_EVIDENCE,
    IssueKind.LONG_DOCUMENT: Operation.REPAIR,
    IssueKind.MULTI_IMAGE_CONFLICT: Operation.QUARANTINE,
    IssueKind.PRODUCT_IDENTITY: Operation.REPAIR,
    IssueKind.LOGO_DRIFT: Operation.REPAIR,
    IssueKind.BRAND_COLOR: Operation.REPAIR,
    IssueKind.OCR: Operation.REPAIR,
    IssueKind.SAFE_ZONE: Operation.REPAIR,
    IssueKind.IMPLIED_CLAIM: Operation.REQUEST_EVIDENCE,
    IssueKind.LOCALIZATION: Operation.REPAIR,
    IssueKind.VIDEO_FLICKER: Operation.REPAIR,
    IssueKind.AV_ALIGNMENT: Operation.REPAIR,
    IssueKind.TOOL_TIMEOUT: Operation.FALLBACK,
    IssueKind.MODEL_OOM: Operation.FALLBACK,
    IssueKind.STALE_MEMORY: Operation.QUARANTINE,
    IssueKind.AGENT_CONFLICT: Operation.ESCALATE,
    IssueKind.INVALID_LOOP: Operation.STOP,
    IssueKind.OVERTHINKING: Operation.STOP,
}


DIFFICULTY_BY_ISSUE: Mapping[IssueKind, AtomicDifficulty] = {
    IssueKind.FACT_CONFLICT: AtomicDifficulty.SOURCE_INCONSISTENCY,
    IssueKind.EVIDENCE_MISSING: AtomicDifficulty.RISK_CLARIFICATION,
    IssueKind.LONG_DOCUMENT: AtomicDifficulty.LONG_CONTEXT,
    IssueKind.MULTI_IMAGE_CONFLICT: AtomicDifficulty.LONG_CONTEXT,
    IssueKind.PRODUCT_IDENTITY: AtomicDifficulty.STRUCTURED_INFORMATION,
    IssueKind.LOGO_DRIFT: AtomicDifficulty.STRUCTURED_INFORMATION,
    IssueKind.BRAND_COLOR: AtomicDifficulty.TOOL_GROUNDING,
    IssueKind.OCR: AtomicDifficulty.TOOL_GROUNDING,
    IssueKind.SAFE_ZONE: AtomicDifficulty.TOOL_GROUNDING,
    IssueKind.IMPLIED_CLAIM: AtomicDifficulty.AMBIGUOUS_GOAL,
    IssueKind.LOCALIZATION: AtomicDifficulty.AMBIGUOUS_GOAL,
    IssueKind.VIDEO_FLICKER: AtomicDifficulty.DYNAMIC_PLANNING,
    IssueKind.AV_ALIGNMENT: AtomicDifficulty.DYNAMIC_PLANNING,
    IssueKind.TOOL_TIMEOUT: AtomicDifficulty.RISK_CLARIFICATION,
    IssueKind.MODEL_OOM: AtomicDifficulty.RISK_CLARIFICATION,
    IssueKind.STALE_MEMORY: AtomicDifficulty.STATE_EVOLUTION,
    IssueKind.AGENT_CONFLICT: AtomicDifficulty.STATE_EVOLUTION,
    IssueKind.INVALID_LOOP: AtomicDifficulty.DYNAMIC_PLANNING,
    IssueKind.OVERTHINKING: AtomicDifficulty.DYNAMIC_PLANNING,
}


@dataclass(frozen=True)
class RoleContract:
    role: AgentRole
    allowed_operations: frozenset[Operation]
    maximum_actions: int
    output_schema: str

    def __post_init__(self) -> None:
        if not self.allowed_operations or self.maximum_actions < 1:
            raise V10ContractError("role needs bounded operations and action budget")
        if not self.output_schema.strip():
            raise V10ContractError("role output schema is required")


ROLE_CONTRACTS: Mapping[AgentRole, RoleContract] = {
    AgentRole.CHALLENGER: RoleContract(
        AgentRole.CHALLENGER,
        frozenset({Operation.INSPECT}),
        1,
        "GTMSeedTaskV1",
    ),
    AgentRole.PLANNER: RoleContract(
        AgentRole.PLANNER,
        frozenset(Operation),
        4,
        "GTMActionPlanV1",
    ),
    AgentRole.PRODUCER: RoleContract(
        AgentRole.PRODUCER,
        frozenset(Operation),
        4,
        "GTMExecutionTraceV1",
    ),
    AgentRole.CRITIC: RoleContract(
        AgentRole.CRITIC,
        frozenset({Operation.INSPECT}),
        2,
        "GTMCritiqueV1",
    ),
    AgentRole.VERIFIER: RoleContract(
        AgentRole.VERIFIER,
        frozenset({Operation.INSPECT}),
        2,
        "GTMVerificationV1",
    ),
}


@dataclass(frozen=True)
class ArtifactFixture:
    artifact_id: str
    modality: str
    content_sha256: str
    license_id: str = "project-owned-synthetic-v1"
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.modality.strip():
            raise V10ContractError("artifact id and modality are required")
        if len(self.content_sha256) != 64:
            raise V10ContractError("artifact content hash is invalid")
        if not self.synthetic or self.license_id != "project-owned-synthetic-v1":
            raise V10ContractError("seed fixtures must remain project-owned synthetic data")


@dataclass(frozen=True)
class IssueFixture:
    issue_id: str
    kind: IssueKind
    description: str
    artifacts: tuple[ArtifactFixture, ...]
    expected_operation: Operation

    def __post_init__(self) -> None:
        if not self.issue_id.strip() or not self.description.strip() or not self.artifacts:
            raise V10ContractError("issue fixture is incomplete")
        if self.expected_operation != EXPECTED_OPERATION[self.kind]:
            raise V10ContractError("issue expected operation disagrees with frozen oracle")


@dataclass(frozen=True)
class GTMAction:
    operation: Operation
    issue_id: str
    rationale_code: str

    def __post_init__(self) -> None:
        if not self.issue_id.strip() or not self.rationale_code.strip():
            raise V10ContractError("action issue and visible rationale code are required")


@dataclass(frozen=True)
class ExecutionEvent:
    step_index: int
    action: GTMAction
    observation_sha256: str
    action_sha256: str
    tool_response_sha256: str
    next_observation_sha256: str
    terminal: bool
    terminal_signal: str | None
    accepted: bool

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                **asdict(self),
                "action": {
                    "operation": self.action.operation.value,
                    "issue_id": self.action.issue_id,
                    "rationale_code": self.action.rationale_code,
                },
            }
        )


class DeterministicGTMEnvironment:
    def __init__(
        self,
        environment_id: str,
        revision_sha256: str,
        issues: Sequence[IssueFixture],
        *,
        maximum_steps: int = 4,
    ) -> None:
        if not environment_id.strip() or len(revision_sha256) != 64:
            raise V10ContractError("environment identity is invalid")
        if not issues or maximum_steps < 2:
            raise V10ContractError("environment needs issues and a viable step budget")
        ids = [item.issue_id for item in issues]
        if len(ids) != len(set(ids)):
            raise V10ContractError("environment issue ids must be unique")
        self.environment_id = environment_id
        self.revision_sha256 = revision_sha256
        self.issues = {item.issue_id: item for item in issues}
        self.maximum_steps = maximum_steps
        self.reset()

    def reset(self) -> str:
        self.status = {item: IssueStatus.OPEN for item in self.issues}
        self.events: list[ExecutionEvent] = []
        self.terminal = False
        return self.state_digest

    @property
    def state_digest(self) -> str:
        return stable_digest(
            {
                "environment_id": self.environment_id,
                "revision_sha256": self.revision_sha256,
                "status": {key: value.value for key, value in sorted(self.status.items())},
                "terminal": self.terminal,
                "event_count": len(self.events),
            }
        )

    def execute(self, action: GTMAction) -> ExecutionEvent:
        if self.terminal:
            raise V10ContractError("terminal environment cannot execute another action")
        if len(self.events) >= self.maximum_steps:
            raise V10ContractError("environment action budget exhausted")
        issue = self.issues.get(action.issue_id)
        if issue is None:
            raise V10ContractError("action references an unknown issue")
        before = self.state_digest
        accepted = action.operation == Operation.INSPECT
        signal: str | None = None
        if action.operation == issue.expected_operation:
            self.status[action.issue_id] = IssueStatus.RESOLVED
            accepted = True
        if action.operation == Operation.STOP:
            if issue.expected_operation == Operation.STOP:
                self.status[action.issue_id] = IssueStatus.RESOLVED
                accepted = True
            if all(value == IssueStatus.RESOLVED for value in self.status.values()):
                self.terminal = True
                signal = "verified_success"
                accepted = True
        if (
            not self.terminal
            and len(self.events) + 1 == self.maximum_steps
            and any(value == IssueStatus.OPEN for value in self.status.values())
        ):
            self.terminal = True
            signal = "budget_exhausted_failure"
        response = {
            "accepted": accepted,
            "issue_kind": issue.kind.value,
            "status": self.status[action.issue_id].value,
            "terminal": self.terminal,
        }
        action_payload = {
            "operation": action.operation.value,
            "issue_id": action.issue_id,
            "rationale_code": action.rationale_code,
        }
        event = ExecutionEvent(
            step_index=len(self.events),
            action=action,
            observation_sha256=before,
            action_sha256=stable_digest(action_payload),
            tool_response_sha256=stable_digest(response),
            next_observation_sha256="0" * 64,
            terminal=self.terminal,
            terminal_signal=signal,
            accepted=accepted,
        )
        self.events.append(event)
        after = self.state_digest
        event = ExecutionEvent(
            **{**asdict(event), "action": action, "next_observation_sha256": after}
        )
        self.events[-1] = event
        return event


@dataclass(frozen=True)
class GTMSeedTask:
    task_id: str
    lane: ProductLane
    partition: DatasetPartition
    issue: IssueFixture
    environment_id: str
    environment_revision_sha256: str
    coordinate: AgentCoordinate
    maximum_steps: int


@dataclass(frozen=True)
class MechanicalVerification:
    passed: bool
    failures: tuple[str, ...]
    final_state_sha256: str
    trace_sha256: str


class Challenger:
    role = ROLE_CONTRACTS[AgentRole.CHALLENGER]

    @staticmethod
    def create_issue(lane: ProductLane, kind: IssueKind) -> IssueFixture:
        payloads = artifact_payloads(lane, kind)
        artifacts = tuple(
            ArtifactFixture(
                artifact_id=f"{lane.value}-{kind.value}-{index}",
                modality=modality,
                content_sha256=stable_digest(payload),
            )
            for index, (modality, payload) in enumerate(payloads)
        )
        return IssueFixture(
            issue_id=f"issue-{lane.value}-{kind.value}",
            kind=kind,
            description=(
                f"Resolve {kind.value} in the {lane.value} GTM workflow without "
                "inventing evidence or bypassing approval."
            ),
            artifacts=artifacts,
            expected_operation=EXPECTED_OPERATION[kind],
        )


class Planner:
    role = ROLE_CONTRACTS[AgentRole.PLANNER]

    @staticmethod
    def plan(task: GTMSeedTask) -> tuple[GTMAction, ...]:
        inspect = GTMAction(Operation.INSPECT, task.issue.issue_id, "inspect_before_action")
        resolve = GTMAction(
            task.issue.expected_operation,
            task.issue.issue_id,
            f"oracle_{task.issue.expected_operation.value}",
        )
        if task.issue.expected_operation == Operation.STOP:
            return (inspect, resolve)
        stop = GTMAction(Operation.STOP, task.issue.issue_id, "stop_after_verified_resolution")
        return (inspect, resolve, stop)


class Producer:
    role = ROLE_CONTRACTS[AgentRole.PRODUCER]

    @staticmethod
    def execute(
        environment: DeterministicGTMEnvironment,
        plan: Sequence[GTMAction],
    ) -> tuple[ExecutionEvent, ...]:
        return tuple(environment.execute(action) for action in plan)


class Critic:
    role = ROLE_CONTRACTS[AgentRole.CRITIC]

    @staticmethod
    def critique_plan(
        task: GTMSeedTask,
        plan: Sequence[GTMAction],
    ) -> tuple[str, ...]:
        findings: list[str] = []
        if not plan or plan[0].operation != Operation.INSPECT:
            findings.append("missing_initial_inspection")
        if not any(action.operation == task.issue.expected_operation for action in plan):
            findings.append("missing_required_resolution_operation")
        if len(plan) > task.maximum_steps:
            findings.append("plan_exceeds_action_budget")
        return tuple(findings)

    @staticmethod
    def critique(task: GTMSeedTask, events: Sequence[ExecutionEvent]) -> tuple[str, ...]:
        findings = list(Critic.critique_plan(task, [event.action for event in events]))
        if any(not event.accepted for event in events):
            findings.append("rejected_action_present")
        if not events or not events[-1].terminal:
            findings.append("trajectory_not_terminal")
        return tuple(findings)


class Verifier:
    role = ROLE_CONTRACTS[AgentRole.VERIFIER]

    @staticmethod
    def verify(
        task: GTMSeedTask,
        environment: DeterministicGTMEnvironment,
        events: Sequence[ExecutionEvent],
    ) -> MechanicalVerification:
        failures = list(Critic.critique(task, events))
        if environment.status[task.issue.issue_id] != IssueStatus.RESOLVED:
            failures.append("issue_unresolved")
        if not environment.terminal:
            failures.append("environment_not_terminal")
        trace_sha256 = stable_digest([item.digest for item in events])
        return MechanicalVerification(
            passed=not failures,
            failures=tuple(dict.fromkeys(failures)),
            final_state_sha256=environment.state_digest,
            trace_sha256=trace_sha256,
        )


def artifact_payloads(
    lane: ProductLane,
    kind: IssueKind,
) -> tuple[tuple[str, object], ...]:
    base = {"lane": lane.value, "issue": kind.value, "owner": "ProofLaunch"}
    if kind == IssueKind.LONG_DOCUMENT:
        return (("text", {**base, "document": "evidence sentence. " * 512}),)
    if kind == IssueKind.MULTI_IMAGE_CONFLICT:
        return (
            ("image", {**base, "image": 1, "product_color": "blue"}),
            ("image", {**base, "image": 2, "product_color": "green"}),
        )
    if kind in {IssueKind.VIDEO_FLICKER, IssueKind.AV_ALIGNMENT}:
        return (("video", {**base, "frames": 192}), ("audio", {**base, "seconds": 8}))
    if kind in {
        IssueKind.PRODUCT_IDENTITY,
        IssueKind.LOGO_DRIFT,
        IssueKind.BRAND_COLOR,
        IssueKind.OCR,
        IssueKind.SAFE_ZONE,
    }:
        return (("image", {**base, "width": 1024, "height": 1024}),)
    return (("json", base),)


def partition_for_issue(index: int) -> DatasetPartition:
    if index < 8:
        return DatasetPartition.SFT
    if index < 13:
        return DatasetPartition.RL
    if index < 16:
        return DatasetPartition.VALIDATION
    return DatasetPartition.EVALUATION


def coordinate_for(lane: ProductLane, kind: IssueKind) -> AgentCoordinate:
    lane_capability = (
        Capability.DATA_ANALYSIS
        if lane in {ProductLane.DATA, ProductLane.GEO, ProductLane.SEO}
        else Capability.OFFICE_DOCUMENTS
    )
    primary = DIFFICULTY_BY_ISSUE[kind]
    return AgentCoordinate(
        application_split=ApplicationSplit.TO_EMPLOYEE,
        domain_l1=lane.value,
        scenario_l2=kind.value,
        capabilities=frozenset(
            {
                Capability.TASK_UNDERSTANDING,
                Capability.PLANNING_DECISION,
                Capability.STATE_MANAGEMENT,
                Capability.TOOL_USE,
                Capability.RELIABILITY_SAFETY,
                lane_capability,
            }
        ),
        difficulties=frozenset({primary}),
        primary_difficulty=primary,
        route=(
            ReasoningRoute.PROGRAM
            if kind in {IssueKind.INVALID_LOOP, IssueKind.OVERTHINKING}
            else ReasoningRoute.DAG
        ),
    )


def environment_revision(lane: ProductLane, partition: DatasetPartition) -> str:
    return stable_digest(
        {
            "schema": "ProofLaunchGTMSeedEnvironmentV1",
            "lane": lane.value,
            "partition": partition.value,
        }
    )


def environment_contract(
    lane: ProductLane,
    partition: DatasetPartition,
) -> ExecutableEnvironment:
    revision = environment_revision(lane, partition)
    return ExecutableEnvironment(
        environment_id=f"env-{lane.value}-{partition.value}",
        revision_sha256=revision,
        license_id="project-owned-synthetic-v1",
        tools=tuple(
            ToolContract(
                name=operation.value,
                schema_sha256=stable_digest(
                    {"operation": operation.value, "schema": "GTMActionV1"}
                ),
                read_only=operation == Operation.INSPECT,
                requires_confirmation=operation != Operation.INSPECT,
            )
            for operation in Operation
        ),
        resettable=True,
        golden_replay_verified=True,
        healthcheck_passed=True,
        deterministic_seed=42,
    )


def build_seed_episode(
    lane: ProductLane,
    kind: IssueKind,
    index: int,
) -> tuple[ExecutableEnvironment, GTMSeedTask, AgentTask, tuple[ExecutionEvent, ...]]:
    partition = partition_for_issue(index)
    contract = environment_contract(lane, partition)
    issue = Challenger.create_issue(lane, kind)
    seed_task = GTMSeedTask(
        task_id=f"task-{lane.value}-{kind.value}",
        lane=lane,
        partition=partition,
        issue=issue,
        environment_id=contract.environment_id,
        environment_revision_sha256=contract.revision_sha256,
        coordinate=coordinate_for(lane, kind),
        maximum_steps=4,
    )
    runtime = DeterministicGTMEnvironment(
        contract.environment_id,
        contract.revision_sha256,
        (issue,),
        maximum_steps=seed_task.maximum_steps,
    )
    events = Producer.execute(runtime, Planner.plan(seed_task))
    verification = Verifier.verify(seed_task, runtime, events)
    if not verification.passed:
        raise V10ContractError(f"golden seed episode failed: {verification.failures}")
    first_digest = verification.trace_sha256
    runtime.reset()
    replay_events = Producer.execute(runtime, Planner.plan(seed_task))
    replay_verification = Verifier.verify(seed_task, runtime, replay_events)
    if replay_verification.trace_sha256 != first_digest:
        raise V10ContractError("golden replay is not deterministic")
    steps = tuple(
        StepTransition(
            step_index=event.step_index,
            observation_sha256=event.observation_sha256,
            action_name=event.action.operation.value,
            action_arguments_sha256=event.action_sha256,
            tool_response_sha256=event.tool_response_sha256,
            next_observation_sha256=event.next_observation_sha256,
            terminal=event.terminal,
            terminal_signal=event.terminal_signal,
        )
        for event in events
    )
    agent_task = AgentTask(
        task_id=seed_task.task_id,
        environment_id=contract.environment_id,
        environment_revision_sha256=contract.revision_sha256,
        partition=partition,
        coordinate=seed_task.coordinate,
        verifier_ids=("mechanical_state", "operation_oracle", "terminal_signal"),
        maximum_steps=seed_task.maximum_steps,
        task_seed=42 + index,
        checkpoint_revision="untrained-seed-policy-v1",
        golden_trajectory=steps,
    )
    return contract, seed_task, agent_task, events
