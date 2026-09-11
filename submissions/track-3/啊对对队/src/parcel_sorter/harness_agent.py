"""Auditable agent layer for verified mobile-VLA self-improvement.

Agents may decompose tasks, diagnose failures, and propose bounded corrections.
They cannot emit servo actions, override the safety harness, create positive
training labels, or activate checkpoints. Those transitions are deterministic
and fail closed in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Protocol, Sequence


TASK_DIRECTIVE_PROTOCOL = "parcel-harness-task-directive-v1"
TASK_OBSERVATION_PROTOCOL = "parcel-harness-task-observation-v1"
FAILURE_PACKET_PROTOCOL = "parcel-harness-failure-packet-v1"
FAILURE_ANALYSIS_PROTOCOL = "parcel-harness-failure-analysis-v1"
CORRECTION_CANDIDATE_PROTOCOL = "parcel-harness-correction-candidate-v1"
REPLAY_VERIFICATION_PROTOCOL = "parcel-harness-replay-verification-v1"
TRAINING_ADMISSION_PROTOCOL = "parcel-harness-training-admission-v1"
CHECKPOINT_AUTHORIZATION_PROTOCOL = "parcel-harness-checkpoint-authorization-v1"

AGENT_ROLES = {"task_agent", "failure_analyst", "independent_verifier"}
ALLOWED_GRASP_MODES = {"top", "side", "cradle", "auto"}
ALLOWED_RECOVERY_STRATEGIES = {
    "hold",
    "reobserve",
    "retry_same_mode",
    "reroute_grasp_mode",
    "return_to_safe_pose",
    "abort_episode",
}
ALLOWED_CORRECTION_KINDS = {
    "task_replan",
    "grasp_mode_reroute",
    "recovery_prompt",
    "curriculum_bridge",
    "data_reweighting",
}
PURE_VLA_ATTRIBUTIONS = {"pure_vla", "autonomous_agent_vla"}
REQUIRED_SUCCESS_STAGES = (
    "grasp_success",
    "lift_success",
    "transport_success",
    "placement_success",
    "correct_destination_success",
    "release_success",
)
REQUIRED_VIDEO_MODALITIES = (
    "overhead_rgb",
    "overhead_depth",
    "wrist_left_rgb",
    "wrist_left_depth",
    "wrist_right_rgb",
    "wrist_right_depth",
)

# These fields would let an agent bypass perception, command the servo directly,
# weaken a hard gate, or promote its own output. Matching is case-insensitive.
FORBIDDEN_FIELD_NAMES = {
    "privileged_state",
    "ground_truth_state",
    "sim_state",
    "parcel_pose",
    "object_pose",
    "body_pose",
    "contact_points",
    "joint_targets",
    "joint_torques",
    "cartesian_target",
    "action",
    "actions",
    "action_chunk",
    "raw_action",
    "expert_action",
    "replacement_action",
    "servo_command",
    "tool_command",
    "safety_override",
    "force_limit_override",
    "activate_checkpoint",
    "active_checkpoint",
    "promotion_override",
    "training_label",
}
FORBIDDEN_FIELD_FRAGMENTS = (
    "privileged",
    "ground_truth",
    "joint_target",
    "joint_torque",
    "cartesian_target",
    "raw_action",
    "expert_action",
    "replacement_action",
    "safety_override",
    "force_limit_override",
    "activate_checkpoint",
    "promotion_override",
)


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    role: str
    provider: str
    model: str
    version: str

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id cannot be empty")
        if self.role not in AGENT_ROLES:
            raise ValueError(f"unsupported agent role: {self.role}")
        if any(not value.strip() for value in (self.provider, self.model, self.version)):
            raise ValueError("agent provider, model, and version must be declared")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentIdentity":
        return cls(
            agent_id=str(payload.get("agent_id") or ""),
            role=str(payload.get("role") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            version=str(payload.get("version") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessAgentConfig:
    task_agent: AgentIdentity
    failure_analyst: AgentIdentity
    independent_verifier: AgentIdentity
    force_limit_n: float = 35.0
    max_dataset_bytes: int = 25_000_000
    require_video_dataset: bool = True
    task_agent_rate_hz: tuple[float, float] = (0.1, 1.0)
    vla_executor_rate_hz: tuple[float, float] = (3.0, 10.0)
    servo_rate_hz: float = 240.0

    def __post_init__(self) -> None:
        expected_roles = (
            (self.task_agent, "task_agent"),
            (self.failure_analyst, "failure_analyst"),
            (self.independent_verifier, "independent_verifier"),
        )
        for identity, role in expected_roles:
            if identity.role != role:
                raise ValueError(f"{identity.agent_id} must declare role {role}")
        identities = {identity.agent_id for identity, _ in expected_roles}
        if len(identities) != len(expected_roles):
            raise ValueError("task, analyst, and verifier identities must be distinct")
        if not math.isfinite(self.force_limit_n) or self.force_limit_n <= 0.0:
            raise ValueError("force_limit_n must be finite and positive")
        if self.max_dataset_bytes <= 0:
            raise ValueError("max_dataset_bytes must be positive")
        for name, rate_range in (
            ("task_agent_rate_hz", self.task_agent_rate_hz),
            ("vla_executor_rate_hz", self.vla_executor_rate_hz),
        ):
            if (
                len(rate_range) != 2
                or any(not math.isfinite(value) or value <= 0.0 for value in rate_range)
                or rate_range[0] > rate_range[1]
            ):
                raise ValueError(f"{name} must be a positive ordered pair")
        if (
            not math.isfinite(self.servo_rate_hz)
            or self.servo_rate_hz <= self.vla_executor_rate_hz[1]
        ):
            raise ValueError("servo rate must exceed the VLA executor rate")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HarnessAgentConfig":
        if payload.get("protocol") != "parcel-harness-agent-config-v1":
            raise ValueError("unsupported Harness Agent config protocol")
        authority = _mapping(payload, "control_authority")
        for key in (
            "agent_may_emit_servo_actions",
            "agent_may_override_safety",
            "agent_may_activate_checkpoint",
        ):
            if authority.get(key) is not False:
                raise ValueError(f"control authority must explicitly disable {key}")
        task_rate = _rate_pair(authority.get("task_agent_hz"), "task_agent_hz")
        vla_rate = _rate_pair(authority.get("vla_executor_hz"), "vla_executor_hz")
        return cls(
            task_agent=AgentIdentity.from_dict(_mapping(payload, "task_agent")),
            failure_analyst=AgentIdentity.from_dict(_mapping(payload, "failure_analyst")),
            independent_verifier=AgentIdentity.from_dict(
                _mapping(payload, "independent_verifier")
            ),
            force_limit_n=float(payload.get("force_limit_n", 35.0)),
            max_dataset_bytes=int(payload.get("max_dataset_bytes", 25_000_000)),
            require_video_dataset=bool(payload.get("require_video_dataset", True)),
            task_agent_rate_hz=task_rate,
            vla_executor_rate_hz=vla_rate,
            servo_rate_hz=float(authority.get("servo_hz", math.nan)),
        )


class FailureAnalystAdapter(Protocol):
    """Pluggable adapter; production adapters may call a language model."""

    identity: AgentIdentity

    def analyze(self, packet: Mapping[str, Any]) -> Mapping[str, Any]: ...


class TaskAgentAdapter(Protocol):
    """Provider-neutral high-level planner with no action-space authority."""

    identity: AgentIdentity

    def plan(self, observation: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RuleBasedFailureAnalyst:
    """Deterministic local adapter used for dry runs and contract tests."""

    def __init__(self, identity: AgentIdentity) -> None:
        if identity.role != "failure_analyst":
            raise ValueError("rule-based analyst requires a failure_analyst identity")
        self.identity = identity

    def analyze(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_failure_packet(packet)
        episode_id = str(packet["episode_id"])
        failure_stage = str(packet["failure_stage"])
        peak_force_n = float(packet["telemetry"]["peak_contact_force_n"])
        if peak_force_n >= 30.0 or failure_stage == "force_safety_abort":
            failure_mode = "contact_force_margin"
            kind = "recovery_prompt"
            parameters = {"strategy": "return_to_safe_pose", "reobserve": True}
        elif failure_stage in {"grasp_success", "grasp", "suction_latch"}:
            failure_mode = "grasp_acquisition"
            kind = "grasp_mode_reroute"
            parameters = {"strategy": "reroute_grasp_mode", "mode": "auto"}
        elif failure_stage in {"lift_success", "lift"}:
            failure_mode = "lift_retention"
            kind = "curriculum_bridge"
            parameters = {"strategy": "retry_same_mode", "difficulty_scale": 0.9}
        elif failure_stage in {"placement_success", "release_success", "placement", "release"}:
            failure_mode = "placement_or_release"
            kind = "task_replan"
            parameters = {"strategy": "reobserve", "preserve_grasp_mode": True}
        else:
            failure_mode = "unclassified"
            kind = "recovery_prompt"
            parameters = {"strategy": "reobserve"}
        return {
            "schema_version": 1,
            "protocol": FAILURE_ANALYSIS_PROTOCOL,
            "analysis_id": f"analysis-{episode_id}-{self.identity.version}",
            "agent": self.identity.to_dict(),
            "episode_id": episode_id,
            "failure_packet_sha256": sha256_json(packet),
            "failure_mode": failure_mode,
            "confidence": 0.5,
            "evidence_refs": [f"failure_packet:{episode_id}"],
            "correction": {
                "correction_id": f"correction-{episode_id}-{self.identity.version}",
                "kind": kind,
                "parameters": parameters,
                "rationale": f"bounded response to {failure_mode}",
                "action_attribution": "autonomous_agent_vla",
                "expert_generated": False,
            },
        }


def validate_task_directive(
    payload: Mapping[str, Any], *, task_agent: AgentIdentity
) -> dict[str, Any]:
    """Validate a high-level directive and prove it contains no servo authority."""

    _reject_forbidden_fields(payload)
    if task_agent.role != "task_agent":
        raise ValueError("task directive signer must have task_agent role")
    if payload.get("protocol") != TASK_DIRECTIVE_PROTOCOL:
        raise ValueError("unsupported task directive protocol")
    if str(payload.get("agent_id") or "") != task_agent.agent_id:
        raise ValueError("task directive agent identity mismatch")
    directive_id = _nonempty(payload, "directive_id")
    goal = _nonempty(payload, "goal")
    grasp_mode = str(payload.get("grasp_mode") or "")
    recovery = str(payload.get("recovery_strategy") or "")
    if grasp_mode not in ALLOWED_GRASP_MODES:
        raise ValueError(f"unsupported grasp mode: {grasp_mode}")
    if recovery not in ALLOWED_RECOVERY_STRATEGIES:
        raise ValueError(f"unsupported recovery strategy: {recovery}")
    memory_refs = payload.get("memory_refs") or []
    if not isinstance(memory_refs, list) or any(not str(value).strip() for value in memory_refs):
        raise ValueError("memory_refs must be a list of non-empty evidence identifiers")
    allowed = {
        "schema_version",
        "protocol",
        "directive_id",
        "agent_id",
        "goal",
        "grasp_mode",
        "recovery_strategy",
        "memory_refs",
        "rationale",
    }
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ValueError(f"task directive contains undeclared fields: {unexpected}")
    return {
        "schema_version": 1,
        "protocol": TASK_DIRECTIVE_PROTOCOL,
        "directive_id": directive_id,
        "agent_id": task_agent.agent_id,
        "goal": goal,
        "grasp_mode": grasp_mode,
        "recovery_strategy": recovery,
        "memory_refs": [str(value) for value in memory_refs],
        "rationale": str(payload.get("rationale") or ""),
        "authority": "high_level_only",
    }


def plan_task_with_agent(
    observation: Mapping[str, Any],
    *,
    planner: TaskAgentAdapter,
    config: HarnessAgentConfig,
) -> dict[str, Any]:
    """Call a task planner through the non-privileged high-level contract."""

    if planner.identity != config.task_agent:
        raise ValueError("unregistered task Agent identity")
    _reject_forbidden_fields(observation)
    if observation.get("protocol") != TASK_OBSERVATION_PROTOCOL:
        raise ValueError("unsupported task observation protocol")
    allowed = {
        "schema_version",
        "protocol",
        "episode_id",
        "goal",
        "stage",
        "available_grasp_modes",
        "perception_summary",
        "force_margin_n",
        "memory_refs",
    }
    unexpected = sorted(set(observation) - allowed)
    if unexpected:
        raise ValueError(f"task observation contains undeclared fields: {unexpected}")
    _nonempty(observation, "episode_id")
    _nonempty(observation, "goal")
    modes = observation.get("available_grasp_modes")
    if (
        not isinstance(modes, Sequence)
        or isinstance(modes, (str, bytes))
        or not modes
        or any(str(mode) not in ALLOWED_GRASP_MODES - {"auto"} for mode in modes)
    ):
        raise ValueError("available_grasp_modes must contain supported physical modes")
    force_margin_n = float(observation.get("force_margin_n", math.nan))
    if not math.isfinite(force_margin_n) or force_margin_n < 0.0:
        raise ValueError("force_margin_n must be finite and non-negative")
    directive = validate_task_directive(
        planner.plan(dict(observation)), task_agent=config.task_agent
    )
    directive["task_observation_sha256"] = sha256_json(observation)
    return directive


def build_failure_packet(
    run: Mapping[str, Any], *, source_audit_sha256: str
) -> dict[str, Any]:
    """Extract only post-episode, non-privileged evidence for an analyst."""

    _sha(source_audit_sha256, "source_audit_sha256")
    episode_id = str(run.get("episode_id") or "").strip()
    if not episode_id:
        raise ValueError("failed run must contain episode_id")
    if bool(run.get("success")):
        raise ValueError("failure packets can only be built from failed runs")
    suction = run.get("suction") if isinstance(run.get("suction"), Mapping) else {}
    dataset = run.get("dataset") if isinstance(run.get("dataset"), Mapping) else {}
    peak_force_n = float(
        run.get("max_contact_force_n")
        or suction.get("max_contact_force_n")
        or 0.0
    )
    if not math.isfinite(peak_force_n) or peak_force_n < 0.0:
        raise ValueError("peak contact force must be finite and non-negative")
    packet = {
        "schema_version": 1,
        "protocol": FAILURE_PACKET_PROTOCOL,
        "episode_id": episode_id,
        "profile": str(run.get("profile") or "unknown"),
        "task": str(run.get("task") or "sort parcel to assigned destination"),
        "success": False,
        "failure_stage": str(run.get("failure_stage") or "unclassified"),
        "terminal_reason": str(run.get("terminal_reason") or run.get("error") or ""),
        "completed_stages": [str(value) for value in run.get("completed_stages") or []],
        "telemetry": {
            "peak_contact_force_n": peak_force_n,
            "suction_break_count": int(suction.get("break_count") or 0),
            "frame_count": int(run.get("frame_count") or dataset.get("frame_count") or 0),
            "rgbd_nonempty": bool(run.get("rgbd_nonempty") or dataset.get("rgbd_nonempty")),
            "action_attribution": str(run.get("action_attribution") or "unknown"),
        },
        "source_audit_sha256": source_audit_sha256,
        "source_run_sha256": sha256_json(run),
        "claim_boundary": "post-episode telemetry only; no privileged simulator state",
    }
    validate_failure_packet(packet)
    return packet


def validate_failure_packet(packet: Mapping[str, Any]) -> None:
    _reject_forbidden_fields(packet)
    if packet.get("protocol") != FAILURE_PACKET_PROTOCOL:
        raise ValueError("unsupported failure packet protocol")
    _nonempty(packet, "episode_id")
    if packet.get("success") is not False:
        raise ValueError("failure packet success must be false")
    _sha(packet.get("source_audit_sha256"), "source_audit_sha256")
    _sha(packet.get("source_run_sha256"), "source_run_sha256")
    telemetry = _mapping(packet, "telemetry")
    peak_force_n = float(telemetry.get("peak_contact_force_n", math.nan))
    if not math.isfinite(peak_force_n) or peak_force_n < 0.0:
        raise ValueError("failure packet force must be finite and non-negative")


def quarantine_correction(
    packet: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    analyst: AgentIdentity,
) -> dict[str, Any]:
    """Validate an analyst proposal and place it in non-executable quarantine."""

    validate_failure_packet(packet)
    _reject_forbidden_fields(analysis)
    if analyst.role != "failure_analyst":
        raise ValueError("correction proposer must have failure_analyst role")
    if analysis.get("protocol") != FAILURE_ANALYSIS_PROTOCOL:
        raise ValueError("unsupported failure analysis protocol")
    declared_agent = AgentIdentity.from_dict(_mapping(analysis, "agent"))
    if declared_agent != analyst:
        raise ValueError("failure analysis identity mismatch")
    if str(analysis.get("episode_id") or "") != str(packet["episode_id"]):
        raise ValueError("failure analysis references a different episode")
    if str(analysis.get("failure_packet_sha256") or "") != sha256_json(packet):
        raise ValueError("failure analysis packet hash mismatch")
    confidence = float(analysis.get("confidence", math.nan))
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("failure analysis confidence must be in [0, 1]")
    correction = dict(_mapping(analysis, "correction"))
    correction_id = _nonempty(correction, "correction_id")
    kind = str(correction.get("kind") or "")
    if kind not in ALLOWED_CORRECTION_KINDS:
        raise ValueError(f"unsupported correction kind: {kind}")
    if correction.get("action_attribution") != "autonomous_agent_vla":
        raise ValueError("correction must declare autonomous_agent_vla attribution")
    if correction.get("expert_generated") is not False:
        raise ValueError("expert-generated corrections cannot enter autonomous quarantine")
    parameters = _mapping(correction, "parameters")
    _reject_forbidden_fields(parameters)
    return {
        "schema_version": 1,
        "protocol": CORRECTION_CANDIDATE_PROTOCOL,
        "candidate_id": correction_id,
        "status": "quarantined_unverified",
        "episode_id": str(packet["episode_id"]),
        "proposed_by": analyst.to_dict(),
        "failure_packet_sha256": sha256_json(packet),
        "failure_analysis_sha256": sha256_json(analysis),
        "kind": kind,
        "parameters": dict(parameters),
        "rationale": str(correction.get("rationale") or ""),
        "action_attribution": "autonomous_agent_vla",
        "expert_generated": False,
        "positive_training_eligible": False,
        "executable": False,
        "claim_boundary": "proposal only; requires independent physical replay",
    }


def verify_replayed_correction(
    candidate: Mapping[str, Any],
    replay_audit: Mapping[str, Any],
    *,
    verifier: AgentIdentity,
    config: HarnessAgentConfig,
) -> dict[str, Any]:
    """Apply deterministic gates to an independently replayed correction."""

    _reject_forbidden_fields(replay_audit)
    if candidate.get("protocol") != CORRECTION_CANDIDATE_PROTOCOL:
        raise ValueError("unsupported correction candidate protocol")
    if candidate.get("status") != "quarantined_unverified":
        raise ValueError("only quarantined candidates can be verified")
    proposer = AgentIdentity.from_dict(_mapping(candidate, "proposed_by"))
    if verifier.role != "independent_verifier":
        raise ValueError("replay verifier must have independent_verifier role")
    if verifier.agent_id == proposer.agent_id:
        raise ValueError("proposal and verification identities must be distinct")
    if proposer != config.failure_analyst:
        raise ValueError("unregistered failure analyst identity")
    if verifier != config.independent_verifier:
        raise ValueError("unregistered verifier identity")
    candidate_sha = sha256_json(candidate)
    checks = {
        "candidate_hash_bound": replay_audit.get("candidate_sha256") == candidate_sha,
        "candidate_id_bound": replay_audit.get("candidate_id") == candidate.get("candidate_id"),
        "replay_audit_passed": replay_audit.get("status") == "passed",
        "task_success": replay_audit.get("success") is True,
        "pure_vla_attribution": replay_audit.get("action_attribution") in PURE_VLA_ATTRIBUTIONS,
        "no_expert_fallback": replay_audit.get("expert_fallback_used") is False,
        "no_action_replacement": replay_audit.get("action_replacement_used") is False,
        "nonempty_frames": int(replay_audit.get("frame_count") or 0) > 0,
        "nonempty_rgbd": replay_audit.get("rgbd_nonempty") is True,
    }
    for stage in REQUIRED_SUCCESS_STAGES:
        checks[stage] = replay_audit.get(stage) is True
    peak_forces = replay_audit.get("peak_forces_n")
    forces_valid = isinstance(peak_forces, Mapping) and bool(peak_forces)
    if forces_valid:
        try:
            values = [float(value) for value in peak_forces.values()]
            forces_valid = all(
                math.isfinite(value) and 0.0 <= value < config.force_limit_n
                for value in values
            )
        except (TypeError, ValueError):
            forces_valid = False
    checks["all_peak_forces_below_limit"] = forces_valid
    if config.require_video_dataset:
        modalities = replay_audit.get("video_modalities")
        checks.update(
            {
                "dataset_saved": replay_audit.get("dataset_saved") is True,
                "video_storage_format": replay_audit.get("dataset_storage_format") == "video",
                "dataset_size_gate": 0
                < int(replay_audit.get("dataset_bytes") or 0)
                <= config.max_dataset_bytes,
                "six_video_modalities": isinstance(modalities, Sequence)
                and not isinstance(modalities, (str, bytes))
                and set(str(value) for value in modalities) == set(REQUIRED_VIDEO_MODALITIES),
                "pyav_audit": replay_audit.get("pyav_audit_status") == "passed",
                "no_image_parquet": replay_audit.get("image_parquet_used") is False,
                "no_torchcodec": replay_audit.get("torchcodec_used") is False,
            }
        )
    verified = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": REPLAY_VERIFICATION_PROTOCOL,
        "candidate_id": str(candidate["candidate_id"]),
        "candidate_sha256": candidate_sha,
        "verified_by": verifier.to_dict(),
        "replay_audit_sha256": sha256_json(replay_audit),
        "status": "verified" if verified else "rejected",
        "verified": verified,
        "checks": checks,
        "rejection_reasons": sorted(name for name, passed in checks.items() if not passed),
        "claim_boundary": "deterministic admission checks over independent replay evidence",
    }


def training_admission_gate(
    candidate: Mapping[str, Any], verification: Mapping[str, Any]
) -> dict[str, Any]:
    """Admit only a hash-bound, independently verified successful correction."""

    proposer = AgentIdentity.from_dict(_mapping(candidate, "proposed_by"))
    verifier = AgentIdentity.from_dict(_mapping(verification, "verified_by"))
    checks = {
        "candidate_protocol": candidate.get("protocol") == CORRECTION_CANDIDATE_PROTOCOL,
        "verification_protocol": verification.get("protocol")
        == REPLAY_VERIFICATION_PROTOCOL,
        "candidate_quarantined": candidate.get("status") == "quarantined_unverified",
        "candidate_hash_bound": verification.get("candidate_sha256") == sha256_json(candidate),
        "candidate_id_bound": verification.get("candidate_id") == candidate.get("candidate_id"),
        "independent_identity": proposer.agent_id != verifier.agent_id,
        "verification_passed": verification.get("verified") is True
        and verification.get("status") == "verified"
        and isinstance(verification.get("checks"), Mapping)
        and bool(verification.get("checks"))
        and all(bool(value) for value in verification["checks"].values()),
        "declared_roles": proposer.role == "failure_analyst"
        and verifier.role == "independent_verifier",
        "autonomous_source": candidate.get("action_attribution") == "autonomous_agent_vla",
        "not_expert_generated": candidate.get("expert_generated") is False,
    }
    admitted = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": TRAINING_ADMISSION_PROTOCOL,
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_sha256": sha256_json(candidate),
        "verification_sha256": sha256_json(verification),
        "proposed_by": proposer.to_dict(),
        "verified_by": verifier.to_dict(),
        "status": "admitted_positive" if admitted else "quarantined",
        "admitted": admitted,
        "training_label": "verified_positive_correction" if admitted else None,
        "checks": checks,
        "claim_boundary": (
            "failed actions remain negative telemetry; only independently replayed "
            "successes may become positive training data"
        ),
    }


def authorize_agent_checkpoint_promotion(
    promotion_evidence: Mapping[str, Any],
    admissions: Sequence[Mapping[str, Any]],
    *,
    candidate_checkpoint_sha256: str,
) -> dict[str, Any]:
    """Add an agent-data provenance gate without activating any checkpoint."""

    _sha(candidate_checkpoint_sha256, "candidate_checkpoint_sha256")
    paired_sha = (_mapping(promotion_evidence, "pairing")).get(
        "candidate_checkpoint_sha256"
    )
    checks = {
        "deterministic_promotion_gate_passed": promotion_evidence.get("promoted") is True,
        "checkpoint_hash_bound": paired_sha == candidate_checkpoint_sha256,
        "has_verified_agent_correction": bool(admissions),
        "all_agent_corrections_admitted": bool(admissions)
        and all(
            item.get("protocol") == TRAINING_ADMISSION_PROTOCOL
            and item.get("admitted") is True
            and item.get("status") == "admitted_positive"
            and item.get("training_label") == "verified_positive_correction"
            and isinstance(item.get("checks"), Mapping)
            and bool(item.get("checks"))
            and all(bool(value) for value in item["checks"].values())
            and _mapping(item, "proposed_by").get("agent_id")
            != _mapping(item, "verified_by").get("agent_id")
            for item in admissions
        ),
    }
    authorized = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": CHECKPOINT_AUTHORIZATION_PROTOCOL,
        "authorized": authorized,
        "status": "authorized_for_registry_activation" if authorized else "quarantined",
        "candidate_checkpoint_sha256": candidate_checkpoint_sha256,
        "promotion_evidence_sha256": sha256_json(promotion_evidence),
        "admission_sha256": [sha256_json(item) for item in admissions],
        "checks": checks,
        "claim_boundary": (
            "this record cannot activate a checkpoint; checkpoint_registry still "
            "requires immutable paired promotion evidence and artifact hashes"
        ),
    }


def sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_forbidden_fields(payload: Mapping[str, Any]) -> None:
    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                name = str(key).strip().lower()
                child_path = f"{path}.{key}" if path else str(key)
                if name in FORBIDDEN_FIELD_NAMES or any(
                    fragment in name for fragment in FORBIDDEN_FIELD_FRAGMENTS
                ):
                    violations.append(child_path)
                visit(child, child_path)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "")
    if violations:
        raise ValueError(f"forbidden Agent authority or privileged fields: {violations}")


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _nonempty(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} cannot be empty")
    return value


def _sha(value: Any, name: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _rate_pair(value: Any, name: str) -> tuple[float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise ValueError(f"{name} must contain [minimum, maximum]")
    return float(value[0]), float(value[1])
