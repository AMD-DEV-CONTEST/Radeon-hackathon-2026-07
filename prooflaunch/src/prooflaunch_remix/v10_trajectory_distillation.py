from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_agentomnia import DatasetPartition, StepTransition
from .v10_contracts import V10ContractError
from .v10_frontier_landscape import ProductLane
from .v10_gtm_environment import (
    DeterministicGTMEnvironment,
    ExecutionEvent,
    GTMAction,
    GTMSeedTask,
    IssueKind,
    IssueStatus,
    Operation,
    Planner,
    Producer,
    build_seed_episode,
    stable_digest,
)


class TrajectoryRole(str, Enum):
    PLANNER = "planner"
    WORKER = "worker"
    CRITIC = "critic"
    SUPERVISOR = "supervisor"


class OutcomeKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    FALLBACK = "fallback"
    STOP = "stop"
    HUMAN_ESCALATION = "human_escalation"


class PolicyKind(str, Enum):
    STOP = "stop"
    RETRY = "retry"
    FALLBACK = "fallback"
    HUMAN_ESCALATION = "human_escalation"


class TrainingLabel(str, Enum):
    IMITATE = "imitate"
    RECOVERY = "recovery"
    NEGATIVE = "negative_do_not_imitate"


class ExecutionSkillKind(str, Enum):
    TASK_DECOMPOSITION = "task_decomposition"
    TOOL_SELECTION = "tool_selection"
    ARGUMENT_FILLING = "argument_filling"
    OBSERVATION_COMPRESSION = "observation_compression"


@dataclass(frozen=True)
class ExecutionSkillExample:
    example_id: str
    source_trajectory_id: str
    source_trace_sha256: str
    partition: DatasetPartition
    kind: ExecutionSkillKind
    deployment_input: Mapping[str, object]
    target: Mapping[str, object]
    required_fact_sha256s: tuple[str, ...]
    output_token_budget: int
    rights_id: str = "project-owned-synthetic-v1"
    privileged_context_present: bool = False
    hidden_chain_of_thought_present: bool = False

    def __post_init__(self) -> None:
        if not self.example_id.strip() or not self.source_trajectory_id.strip():
            raise V10ContractError("execution-skill example identity is required")
        if len(self.source_trace_sha256) != 64 or not self.deployment_input or not self.target:
            raise V10ContractError("execution-skill example needs source trace input and target")
        if self.output_token_budget < 1 or self.output_token_budget > 256:
            raise V10ContractError("execution-skill target token budget must be in [1, 256]")
        if self.rights_id != "project-owned-synthetic-v1":
            raise V10ContractError("execution-skill examples must remain project-owned")
        if self.privileged_context_present or self.hidden_chain_of_thought_present:
            raise V10ContractError("execution-skill examples cannot contain privileged or hidden reasoning")
        for digest in self.required_fact_sha256s:
            if len(digest) != 64:
                raise V10ContractError("required fact digest must be a SHA-256")
        if self.kind is ExecutionSkillKind.TASK_DECOMPOSITION:
            _validate_decomposition_target(self.target)
        elif self.kind is ExecutionSkillKind.TOOL_SELECTION:
            candidates = tuple(self.target.get("candidate_tools", ()))
            if self.target.get("selected_tool") not in candidates or len(candidates) < 2:
                raise V10ContractError("tool selection target must choose from explicit candidates")
        elif self.kind is ExecutionSkillKind.ARGUMENT_FILLING:
            required = set(self.target.get("required_fields", ()))
            arguments = self.target.get("arguments", {})
            if not isinstance(arguments, Mapping) or set(arguments) != required:
                raise V10ContractError("argument target must exactly satisfy required schema")
        elif self.kind is ExecutionSkillKind.OBSERVATION_COMPRESSION:
            retained = set(self.target.get("retained_fact_sha256s", ()))
            if not set(self.required_fact_sha256s).issubset(retained):
                raise V10ContractError("observation compression dropped a required fact")
            if int(self.target.get("estimated_tokens", self.output_token_budget + 1)) > self.output_token_budget:
                raise V10ContractError("compressed observation exceeds target token budget")

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                **asdict(self),
                "partition": self.partition.value,
                "kind": self.kind.value,
            }
        )


def _validate_decomposition_target(target: Mapping[str, object]) -> None:
    raw_steps = target.get("steps")
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)) or not raw_steps:
        raise V10ContractError("task decomposition needs ordered steps")
    steps = tuple(raw_steps)
    if any(not isinstance(step, Mapping) for step in steps):
        raise V10ContractError("task decomposition steps must be objects")
    ids = [str(step.get("step_id", "")) for step in steps]
    if any(not step_id for step_id in ids) or len(ids) != len(set(ids)):
        raise V10ContractError("task decomposition step ids must be unique")
    position = {step_id: index for index, step_id in enumerate(ids)}
    for index, step in enumerate(steps):
        dependencies = tuple(step.get("depends_on", ()))
        if any(dependency not in position or position[dependency] >= index for dependency in dependencies):
            raise V10ContractError("task decomposition dependencies must point backward")


@dataclass(frozen=True)
class OutcomeVerification:
    expected_kind: OutcomeKind
    passed: bool
    issue_resolved: bool
    terminal_signal: str
    rejected_action_count: int
    failures: tuple[str, ...]

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                **asdict(self),
                "expected_kind": self.expected_kind.value,
            }
        )


@dataclass(frozen=True)
class OutcomeTrajectory:
    trajectory_id: str
    task_id: str
    partition: DatasetPartition
    lane: ProductLane
    issue_kind: IssueKind
    outcome_kind: OutcomeKind
    events: tuple[ExecutionEvent, ...]
    verification: OutcomeVerification
    training_label: TrainingLabel
    source_policy_revision: str = "prooflaunch-mechanical-oracle-v1"
    rights_id: str = "project-owned-synthetic-v1"
    hidden_chain_of_thought_present: bool = False

    def __post_init__(self) -> None:
        if not self.trajectory_id.strip() or not self.task_id.strip() or not self.events:
            raise V10ContractError("outcome trajectory identity and events are required")
        indices = [event.step_index for event in self.events]
        if indices != list(range(len(indices))):
            raise V10ContractError("outcome trajectory steps must be contiguous")
        if not self.events[-1].terminal or not self.events[-1].terminal_signal:
            raise V10ContractError("outcome trajectory must terminate explicitly")
        if not self.verification.passed:
            raise V10ContractError("outcome trajectory failed its kind-aware verifier")
        if self.rights_id != "project-owned-synthetic-v1":
            raise V10ContractError("trajectory seed rights must remain project-owned")
        if self.hidden_chain_of_thought_present:
            raise V10ContractError("hidden chain of thought cannot enter the trajectory corpus")

    @property
    def trace_sha256(self) -> str:
        return stable_digest([event.digest for event in self.events])


@dataclass(frozen=True)
class RoleTrajectory:
    trajectory_id: str
    parent_trajectory_id: str
    role: TrajectoryRole
    partition: DatasetPartition
    steps: tuple[StepTransition, ...]
    visible_decision_code: str
    training_label: TrainingLabel
    hidden_chain_of_thought_present: bool = False

    def __post_init__(self) -> None:
        if not self.trajectory_id.strip() or not self.parent_trajectory_id.strip():
            raise V10ContractError("role trajectory identity is required")
        if not self.steps or not self.steps[-1].terminal:
            raise V10ContractError("role trajectory needs an explicit terminal step")
        if [step.step_index for step in self.steps] != list(range(len(self.steps))):
            raise V10ContractError("role trajectory steps must be contiguous from zero")
        if not self.visible_decision_code.strip() or self.hidden_chain_of_thought_present:
            raise V10ContractError("only visible decision codes may enter role trajectories")

    @property
    def trace_sha256(self) -> str:
        return stable_digest([asdict(step) for step in self.steps])


def distill_execution_skills(
    outcome: OutcomeTrajectory,
) -> tuple[ExecutionSkillExample, ...]:
    decomposition_steps = tuple(
        {
            "step_id": f"step-{index}",
            "operation": event.action.operation.value,
            "depends_on": () if index == 0 else (f"step-{index - 1}",),
            "terminal": event.terminal,
        }
        for index, event in enumerate(outcome.events)
    )
    task_decomposition = ExecutionSkillExample(
        example_id=f"{outcome.trajectory_id}-task-decomposition",
        source_trajectory_id=outcome.trajectory_id,
        source_trace_sha256=outcome.trace_sha256,
        partition=outcome.partition,
        kind=ExecutionSkillKind.TASK_DECOMPOSITION,
        deployment_input={
            "task_id": outcome.task_id,
            "issue_kind": outcome.issue_kind.value,
            "maximum_steps": len(outcome.events),
        },
        target={"steps": decomposition_steps},
        required_fact_sha256s=(outcome.events[0].observation_sha256,),
        output_token_budget=256,
    )
    selected = outcome.events[0]
    candidate_tools = tuple(
        operation.value
        for operation in Operation
        if operation in {
            Operation.INSPECT,
            Operation.REPAIR,
            Operation.QUARANTINE,
            Operation.REQUEST_EVIDENCE,
            Operation.FALLBACK,
            Operation.ESCALATE,
            Operation.STOP,
        }
    )
    tool_selection = ExecutionSkillExample(
        example_id=f"{outcome.trajectory_id}-tool-selection",
        source_trajectory_id=outcome.trajectory_id,
        source_trace_sha256=outcome.trace_sha256,
        partition=outcome.partition,
        kind=ExecutionSkillKind.TOOL_SELECTION,
        deployment_input={
            "observation_sha256": selected.observation_sha256,
            "issue_kind": outcome.issue_kind.value,
        },
        target={
            "candidate_tools": candidate_tools,
            "selected_tool": selected.action.operation.value,
        },
        required_fact_sha256s=(selected.observation_sha256,),
        output_token_budget=32,
    )
    argument_filling = ExecutionSkillExample(
        example_id=f"{outcome.trajectory_id}-argument-filling",
        source_trajectory_id=outcome.trajectory_id,
        source_trace_sha256=outcome.trace_sha256,
        partition=outcome.partition,
        kind=ExecutionSkillKind.ARGUMENT_FILLING,
        deployment_input={
            "selected_tool": selected.action.operation.value,
            "tool_schema_revision": "gtm-operation-v1",
        },
        target={
            "required_fields": ("issue_id", "rationale_code"),
            "arguments": {
                "issue_id": selected.action.issue_id,
                "rationale_code": selected.action.rationale_code,
            },
        },
        required_fact_sha256s=(selected.observation_sha256,),
        output_token_budget=64,
    )
    required_facts = tuple(
        dict.fromkeys(
            digest
            for event in outcome.events
            for digest in (
                event.observation_sha256,
                event.tool_response_sha256,
                event.next_observation_sha256,
            )
        )
    )
    observation_compression = ExecutionSkillExample(
        example_id=f"{outcome.trajectory_id}-observation-compression",
        source_trajectory_id=outcome.trajectory_id,
        source_trace_sha256=outcome.trace_sha256,
        partition=outcome.partition,
        kind=ExecutionSkillKind.OBSERVATION_COMPRESSION,
        deployment_input={
            "visible_event_count": len(outcome.events),
            "visible_fact_sha256s": required_facts,
        },
        target={
            "summary_code": f"{outcome.issue_kind.value}:{outcome.verification.terminal_signal}",
            "retained_fact_sha256s": required_facts,
            "estimated_tokens": min(128, 12 + len(required_facts) * 3),
        },
        required_fact_sha256s=required_facts,
        output_token_budget=128,
    )
    return task_decomposition, tool_selection, argument_filling, observation_compression


@dataclass(frozen=True)
class StepReward:
    trajectory_id: str
    step_index: int
    correctness: int
    safety: int
    progress: int
    efficiency: float
    recovery: int
    terminal: int

    def __post_init__(self) -> None:
        for field_name in ("correctness", "safety", "progress", "recovery", "terminal"):
            if getattr(self, field_name) not in {-1, 0, 1}:
                raise V10ContractError(f"{field_name} reward must be -1, 0, or 1")
        if not 0.0 <= self.efficiency <= 1.0:
            raise V10ContractError("efficiency reward must be in [0, 1]")


@dataclass(frozen=True)
class TrajectoryReward:
    trajectory_id: str
    training_label: TrainingLabel
    terminal_success: int
    verifier_pass: int
    first_error_repaired: int
    safe_stop: int
    normalized_efficiency: float
    step_rewards_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "terminal_success",
            "verifier_pass",
            "first_error_repaired",
            "safe_stop",
        ):
            if getattr(self, field_name) not in {0, 1}:
                raise V10ContractError(f"{field_name} must be binary")
        if not 0.0 <= self.normalized_efficiency <= 1.0:
            raise V10ContractError("normalized efficiency must be in [0, 1]")
        if len(self.step_rewards_sha256) != 64:
            raise V10ContractError("step reward digest must be a SHA-256")


@dataclass(frozen=True)
class PolicyDistillationExample:
    example_id: str
    source_trajectory_id: str
    partition: DatasetPartition
    policy_kind: PolicyKind
    deployment_observation: Mapping[str, object]
    teacher_action: str
    action_arguments: Mapping[str, object]
    source_trace_sha256: str
    privileged_context_present: bool = False
    hidden_chain_of_thought_present: bool = False

    def __post_init__(self) -> None:
        if not self.example_id.strip() or not self.source_trajectory_id.strip():
            raise V10ContractError("policy example identity is required")
        if not self.teacher_action.strip() or len(self.source_trace_sha256) != 64:
            raise V10ContractError("policy example action and source digest are required")
        if self.privileged_context_present or self.hidden_chain_of_thought_present:
            raise V10ContractError(
                "deployment policy examples cannot contain privileged or hidden reasoning"
            )

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                **asdict(self),
                "partition": self.partition.value,
                "policy_kind": self.policy_kind.value,
            }
        )


def _wrong_operation(expected: Operation) -> Operation:
    for candidate in (
        Operation.REPAIR,
        Operation.QUARANTINE,
        Operation.REQUEST_EVIDENCE,
        Operation.FALLBACK,
        Operation.ESCALATE,
    ):
        if candidate != expected:
            return candidate
    raise AssertionError("operation enum unexpectedly lacks a wrong-action candidate")


def positive_outcome_kind(kind: IssueKind) -> OutcomeKind:
    expected = {
        IssueKind.TOOL_TIMEOUT: OutcomeKind.FALLBACK,
        IssueKind.MODEL_OOM: OutcomeKind.FALLBACK,
        IssueKind.INVALID_LOOP: OutcomeKind.STOP,
        IssueKind.OVERTHINKING: OutcomeKind.STOP,
        IssueKind.AGENT_CONFLICT: OutcomeKind.HUMAN_ESCALATION,
    }
    return expected.get(kind, OutcomeKind.SUCCESS)


def _actions_for(task: GTMSeedTask, outcome_kind: OutcomeKind) -> tuple[GTMAction, ...]:
    wrong = _wrong_operation(task.issue.expected_operation)
    inspect = GTMAction(Operation.INSPECT, task.issue.issue_id, "inspect_before_action")
    wrong_action = GTMAction(wrong, task.issue.issue_id, "counterfactual_wrong_action")
    if outcome_kind == OutcomeKind.FAILURE:
        return (
            inspect,
            wrong_action,
            GTMAction(wrong, task.issue.issue_id, "repeated_wrong_action_1"),
            GTMAction(wrong, task.issue.issue_id, "repeated_wrong_action_2"),
        )
    if outcome_kind == OutcomeKind.RETRY:
        recover = GTMAction(
            task.issue.expected_operation,
            task.issue.issue_id,
            "retry_with_verified_operation",
        )
        if task.issue.expected_operation == Operation.STOP:
            return (inspect, wrong_action, recover)
        return (
            inspect,
            wrong_action,
            recover,
            GTMAction(Operation.STOP, task.issue.issue_id, "stop_after_retry_success"),
        )
    return Planner.plan(task)


def _verify_outcome(
    task: GTMSeedTask,
    runtime: DeterministicGTMEnvironment,
    events: Sequence[ExecutionEvent],
    expected_kind: OutcomeKind,
) -> OutcomeVerification:
    failures: list[str] = []
    resolved = runtime.status[task.issue.issue_id] == IssueStatus.RESOLVED
    terminal_signal = events[-1].terminal_signal or ""
    rejected = sum(not event.accepted for event in events)
    if expected_kind == OutcomeKind.FAILURE:
        if resolved:
            failures.append("negative_trajectory_resolved_issue")
        if terminal_signal != "budget_exhausted_failure":
            failures.append("negative_trajectory_wrong_terminal")
        if rejected < 1:
            failures.append("negative_trajectory_has_no_rejected_action")
    else:
        if not resolved:
            failures.append("positive_or_recovery_trajectory_left_issue_open")
        if terminal_signal != "verified_success":
            failures.append("positive_or_recovery_trajectory_wrong_terminal")
        if expected_kind == OutcomeKind.RETRY and rejected < 1:
            failures.append("retry_trajectory_has_no_failed_attempt")
        if expected_kind != OutcomeKind.RETRY and rejected:
            failures.append("clean_positive_trajectory_contains_rejected_action")
    if not runtime.terminal or not events[-1].terminal:
        failures.append("trajectory_not_terminal")
    return OutcomeVerification(
        expected_kind=expected_kind,
        passed=not failures,
        issue_resolved=resolved,
        terminal_signal=terminal_signal,
        rejected_action_count=rejected,
        failures=tuple(failures),
    )


def build_outcome_trajectory(
    lane: ProductLane,
    kind: IssueKind,
    index: int,
    outcome_kind: OutcomeKind,
) -> OutcomeTrajectory:
    contract, task, _, _ = build_seed_episode(lane, kind, index)
    allowed = {OutcomeKind.FAILURE, OutcomeKind.RETRY, positive_outcome_kind(kind)}
    if outcome_kind not in allowed:
        raise V10ContractError(
            f"{outcome_kind.value} is not an admissible matched outcome for {kind.value}"
        )
    runtime = DeterministicGTMEnvironment(
        contract.environment_id,
        contract.revision_sha256,
        (task.issue,),
        maximum_steps=task.maximum_steps,
    )
    events = Producer.execute(runtime, _actions_for(task, outcome_kind))
    verification = _verify_outcome(task, runtime, events, outcome_kind)
    label = (
        TrainingLabel.NEGATIVE
        if outcome_kind == OutcomeKind.FAILURE
        else TrainingLabel.RECOVERY
        if outcome_kind == OutcomeKind.RETRY
        else TrainingLabel.IMITATE
    )
    return OutcomeTrajectory(
        trajectory_id=f"trajectory-{lane.value}-{kind.value}-{outcome_kind.value}",
        task_id=task.task_id,
        partition=task.partition,
        lane=lane,
        issue_kind=kind,
        outcome_kind=outcome_kind,
        events=events,
        verification=verification,
        training_label=label,
    )


def build_matched_trajectory_family(
    lane: ProductLane,
    kind: IssueKind,
    index: int,
) -> tuple[OutcomeTrajectory, ...]:
    return tuple(
        build_outcome_trajectory(lane, kind, index, outcome)
        for outcome in (
            positive_outcome_kind(kind),
            OutcomeKind.FAILURE,
            OutcomeKind.RETRY,
        )
    )


def _single_step(
    action_name: str,
    observation: object,
    action_arguments: object,
    response: object,
    next_observation: object,
    terminal_signal: str,
) -> StepTransition:
    return StepTransition(
        step_index=0,
        observation_sha256=stable_digest(observation),
        action_name=action_name,
        action_arguments_sha256=stable_digest(action_arguments),
        tool_response_sha256=stable_digest(response),
        next_observation_sha256=stable_digest(next_observation),
        terminal=True,
        terminal_signal=terminal_signal,
    )


def decompose_role_trajectories(
    outcome: OutcomeTrajectory,
) -> tuple[RoleTrajectory, ...]:
    plan_payload = [
        {
            "operation": event.action.operation.value,
            "rationale_code": event.action.rationale_code,
        }
        for event in outcome.events
    ]
    planner = RoleTrajectory(
        trajectory_id=f"{outcome.trajectory_id}-planner",
        parent_trajectory_id=outcome.trajectory_id,
        role=TrajectoryRole.PLANNER,
        partition=outcome.partition,
        steps=(
            _single_step(
                "emit_bounded_plan",
                {"task_id": outcome.task_id, "issue": outcome.issue_kind.value},
                plan_payload,
                {"plan_length": len(plan_payload)},
                {"plan_sha256": stable_digest(plan_payload)},
                "plan_ready",
            ),
        ),
        visible_decision_code="bounded_plan_emitted",
        training_label=outcome.training_label,
    )
    worker_steps = tuple(
        StepTransition(
            step_index=index,
            observation_sha256=event.observation_sha256,
            action_name=event.action.operation.value,
            action_arguments_sha256=event.action_sha256,
            tool_response_sha256=event.tool_response_sha256,
            next_observation_sha256=event.next_observation_sha256,
            terminal=index == len(outcome.events) - 1,
            terminal_signal=(
                "worker_execution_complete"
                if index == len(outcome.events) - 1
                else None
            ),
        )
        for index, event in enumerate(outcome.events)
    )
    worker = RoleTrajectory(
        trajectory_id=f"{outcome.trajectory_id}-worker",
        parent_trajectory_id=outcome.trajectory_id,
        role=TrajectoryRole.WORKER,
        partition=outcome.partition,
        steps=worker_steps,
        visible_decision_code="typed_actions_executed",
        training_label=outcome.training_label,
    )
    critic = RoleTrajectory(
        trajectory_id=f"{outcome.trajectory_id}-critic",
        parent_trajectory_id=outcome.trajectory_id,
        role=TrajectoryRole.CRITIC,
        partition=outcome.partition,
        steps=(
            _single_step(
                "verify_outcome_kind",
                {"trace_sha256": outcome.trace_sha256},
                {"expected_kind": outcome.outcome_kind.value},
                asdict(outcome.verification),
                {"verification_sha256": outcome.verification.digest},
                "critique_complete",
            ),
        ),
        visible_decision_code="kind_aware_mechanical_verdict",
        training_label=outcome.training_label,
    )
    supervisor_decision = {
        TrainingLabel.IMITATE: "admit_positive",
        TrainingLabel.RECOVERY: "admit_recovery",
        TrainingLabel.NEGATIVE: "reject_negative",
    }[outcome.training_label]
    supervisor = RoleTrajectory(
        trajectory_id=f"{outcome.trajectory_id}-supervisor",
        parent_trajectory_id=outcome.trajectory_id,
        role=TrajectoryRole.SUPERVISOR,
        partition=outcome.partition,
        steps=(
            _single_step(
                "supervise_training_admission",
                {"verification_sha256": outcome.verification.digest},
                {"training_label": outcome.training_label.value},
                {"decision": supervisor_decision},
                {"admission": supervisor_decision},
                "supervision_complete",
            ),
        ),
        visible_decision_code=supervisor_decision,
        training_label=outcome.training_label,
    )
    return planner, worker, critic, supervisor


def reward_outcome(
    outcome: OutcomeTrajectory,
) -> tuple[tuple[StepReward, ...], TrajectoryReward]:
    rejected_seen = False
    step_rewards: list[StepReward] = []
    for event in outcome.events:
        rejected_seen = rejected_seen or not event.accepted
        resolved_now = event.terminal_signal == "verified_success"
        recovery = int(rejected_seen and event.accepted and resolved_now)
        step_rewards.append(
            StepReward(
                trajectory_id=outcome.trajectory_id,
                step_index=event.step_index,
                correctness=1 if event.accepted else -1,
                safety=(
                    1
                    if event.action.operation
                    in {Operation.INSPECT, Operation.STOP, Operation.ESCALATE}
                    else 0
                    if event.accepted
                    else -1
                ),
                progress=1 if resolved_now else -1 if not event.accepted else 0,
                efficiency=max(0.0, 1.0 - event.step_index / len(outcome.events)),
                recovery=recovery,
                terminal=(
                    1
                    if event.terminal_signal == "verified_success"
                    else -1
                    if event.terminal_signal == "budget_exhausted_failure"
                    else 0
                ),
            )
        )
    rewards = tuple(step_rewards)
    success = outcome.verification.terminal_signal == "verified_success"
    trajectory_reward = TrajectoryReward(
        trajectory_id=outcome.trajectory_id,
        training_label=outcome.training_label,
        terminal_success=int(success),
        verifier_pass=int(outcome.verification.passed),
        first_error_repaired=int(
            outcome.outcome_kind == OutcomeKind.RETRY
            and outcome.verification.rejected_action_count > 0
            and success
        ),
        safe_stop=int(
            success
            and outcome.events[-1].action.operation == Operation.STOP
        ),
        normalized_efficiency=max(0.0, 1.0 - (len(outcome.events) - 1) / 4),
        step_rewards_sha256=stable_digest([asdict(item) for item in rewards]),
    )
    return rewards, trajectory_reward


POLICY_KIND_BY_OUTCOME: Mapping[OutcomeKind, PolicyKind] = {
    OutcomeKind.RETRY: PolicyKind.RETRY,
    OutcomeKind.FALLBACK: PolicyKind.FALLBACK,
    OutcomeKind.STOP: PolicyKind.STOP,
    OutcomeKind.HUMAN_ESCALATION: PolicyKind.HUMAN_ESCALATION,
}


def distill_policy_example(
    outcome: OutcomeTrajectory,
) -> PolicyDistillationExample | None:
    policy_kind = POLICY_KIND_BY_OUTCOME.get(outcome.outcome_kind)
    if policy_kind is None:
        return None
    teacher_action = {
        PolicyKind.RETRY: "retry_once_with_verified_operation",
        PolicyKind.FALLBACK: "activate_verified_fallback",
        PolicyKind.STOP: "stop_bounded_execution",
        PolicyKind.HUMAN_ESCALATION: "request_single_human_approval",
    }[policy_kind]
    observation = {
        "issue_kind": outcome.issue_kind.value,
        "rejected_action_count": outcome.verification.rejected_action_count,
        "terminal_signal": outcome.verification.terminal_signal,
        "action_budget": 4,
        "source_is_visible_trace": True,
    }
    return PolicyDistillationExample(
        example_id=f"policy-{outcome.trajectory_id}",
        source_trajectory_id=outcome.trajectory_id,
        partition=outcome.partition,
        policy_kind=policy_kind,
        deployment_observation=observation,
        teacher_action=teacher_action,
        action_arguments={
            "issue_kind": outcome.issue_kind.value,
            "bounded": True,
            "requires_confirmation": policy_kind == PolicyKind.HUMAN_ESCALATION,
        },
        source_trace_sha256=outcome.trace_sha256,
    )


def build_full_trajectory_corpus() -> tuple[OutcomeTrajectory, ...]:
    return tuple(
        trajectory
        for lane in ProductLane
        for index, kind in enumerate(IssueKind)
        for trajectory in build_matched_trajectory_family(lane, kind, index)
    )
