from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from shared_contracts import (
    ArtifactRef,
    CloudExecutionPolicySnapshot,
    FallbackPolicySnapshot,
    GenerationRequest,
    stable_json_sha256,
)

from ..runtime import ProjectLock, atomic_write_json
from ..seeding import derive_reroll_seed
from .domain import (
    Clip,
    ContinuityAnchorAccepted,
    DeliveryAccepted,
    DeliveryEligibility,
    DeliveryRevision,
    DeliveryTake,
    FactoryOutboxEvent,
    FactoryProjectState,
    FactoryQCEvaluation,
    FactoryQCVerdict,
    GenerationRun,
    GenerationRunStatus,
    HumanVerdict,
    HumanVerdictEvent,
    LegacyImportedTake,
    ProjectRevision,
    ProviderCheckpoint,
    Scene,
    TakeEligibility,
    VisualCanonRevision,
    VisualTake,
    with_state_hash,
)


class FactoryStateError(RuntimeError):
    pass


class FactoryStateConflict(FactoryStateError):
    pass


WriteAuthorityGuard = Callable[[str], None]


RUN_TRANSITIONS = {
    GenerationRunStatus.DRAFT: {
        GenerationRunStatus.QUEUED,
        GenerationRunStatus.CANCELLED,
    },
    GenerationRunStatus.QUEUED: {
        GenerationRunStatus.SUBMITTED,
        GenerationRunStatus.CANCELLED,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.NEEDS_HUMAN,
    },
    GenerationRunStatus.SUBMITTED: {
        GenerationRunStatus.RUNNING,
        GenerationRunStatus.MATERIALIZING,
        GenerationRunStatus.CANCELLED,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.NEEDS_HUMAN,
    },
    GenerationRunStatus.RUNNING: {
        GenerationRunStatus.MATERIALIZING,
        GenerationRunStatus.CANCELLED,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.NEEDS_HUMAN,
    },
    GenerationRunStatus.MATERIALIZING: {
        GenerationRunStatus.CANDIDATE,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.NEEDS_HUMAN,
    },
    GenerationRunStatus.CANDIDATE: {
        GenerationRunStatus.ELIGIBLE,
        GenerationRunStatus.NEEDS_HUMAN,
        GenerationRunStatus.FAILED,
    },
    GenerationRunStatus.ELIGIBLE: {
        GenerationRunStatus.ACCEPTED,
        GenerationRunStatus.REJECTED,
        GenerationRunStatus.NEEDS_HUMAN,
    },
    GenerationRunStatus.NEEDS_HUMAN: {
        GenerationRunStatus.QUEUED,
        GenerationRunStatus.REJECTED,
        GenerationRunStatus.CANCELLED,
    },
    GenerationRunStatus.ACCEPTED: set(),
    GenerationRunStatus.REJECTED: set(),
    GenerationRunStatus.FAILED: set(),
    GenerationRunStatus.CANCELLED: set(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def artifact_from_file(path: str | Path, *, mime: str) -> ArtifactRef:
    source = Path(path)
    size = source.stat().st_size
    if size <= 0:
        raise FactoryStateError("artifact file is empty")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    from shared_contracts import ComponentName

    return ArtifactRef(
        owner=ComponentName.DRAMA_FACTORY,
        artifact_id=uuid4(),
        sha256=digest.hexdigest(),
        bytes=size,
        mime=mime,
        version=1,
    )


class FactoryStateStore:
    """Single-authority immutable factory state with an atomic embedded outbox."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        write_authority_guard: WriteAuthorityGuard | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.root = self.project_root / "factory_v3"
        self.state_path = self.root / "state.json"
        self._write_authority_guard = write_authority_guard

    def assert_write_allowed(self, operation: str) -> None:
        """Enforce the externally owned authority fence at the write boundary.

        Reads and reconciliation proof loading never call this method.  A
        configured guard is invoked immediately before every state-file write,
        so API or worker checks cannot be bypassed by calling a mutator
        directly.
        """

        if not operation or len(operation) > 200:
            raise FactoryStateError("factory write operation is invalid")
        if self._write_authority_guard is not None:
            self._write_authority_guard(operation)

    def load(self) -> FactoryProjectState:
        if not self.state_path.exists():
            raise FactoryStateError("factory v3 project state is unavailable")
        raw = self.state_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if "factory_qc_evaluations" not in payload:
            stored_hash = payload.get("state_sha256")
            legacy_identity = dict(payload)
            legacy_identity.pop("state_sha256", None)
            if stored_hash != stable_json_sha256(legacy_identity):
                raise FactoryStateError(
                    "factory project state hash does not match content"
                )
            payload["factory_qc_evaluations"] = []
            return with_state_hash(payload)
        return FactoryProjectState.model_validate(payload)

    def initialize(
        self,
        *,
        project_revision: ProjectRevision,
        scenes: tuple[Scene, ...],
        clips: tuple[Clip, ...],
        legacy_imported_takes: tuple[LegacyImportedTake, ...] = (),
        initialized_at: datetime | None = None,
        outbox_event_id: UUID | None = None,
    ) -> FactoryProjectState:
        with ProjectLock(self.project_root):
            if self.state_path.exists():
                existing = self.load()
                if existing.project_revision != project_revision:
                    raise FactoryStateConflict(
                        "factory project already has a different revision"
                    )
                return existing
            scene_ids = {scene.scene_id for scene in scenes}
            if any(clip.scene_id not in scene_ids for clip in clips):
                raise FactoryStateError("clip references an unavailable scene")
            if any(
                scene.project_revision_id != project_revision.revision_id
                for scene in scenes
            ):
                raise FactoryStateError(
                    "scene references a different project revision"
                )
            clip_ids = {clip.clip_id for clip in clips}
            if any(
                take.clip_id not in clip_ids
                for take in legacy_imported_takes
            ):
                raise FactoryStateError(
                    "legacy imported take references an unavailable clip"
                )
            now = initialized_at or _now()
            event = FactoryOutboxEvent(
                event_id=outbox_event_id or uuid4(),
                sequence=1,
                topic="factory.project.initialized",
                aggregate_id=project_revision.revision_id,
                payload={
                    "project_id": str(project_revision.project_id),
                    "revision_id": str(project_revision.revision_id),
                    "content_hash": project_revision.content_hash,
                    "legacy_imported_take_count": len(legacy_imported_takes),
                },
                created_at=now,
            )
            state = with_state_hash(
                {
                    "schema_version": "factory.project-state.v3",
                    "state_version": 1,
                    "project_revision": project_revision,
                    "scenes": scenes,
                    "clips": clips,
                    "runs": (),
                    "checkpoints": (),
                    "legacy_imported_takes": legacy_imported_takes,
                    "visual_takes": (),
                    "continuity_acceptances": (),
                    "visual_canon_revisions": (),
                    "verdict_events": (),
                    "delivery_takes": (),
                    "factory_qc_evaluations": (),
                    "delivery_acceptances": (),
                    "delivery_revisions": (),
                    "outbox_events": (event,),
                    "updated_at": now,
                }
            )
            self._write(state, operation="factory.project.initialize")
            return state

    def _write(
        self,
        state: FactoryProjectState,
        *,
        operation: str,
    ) -> None:
        self.assert_write_allowed(operation)
        atomic_write_json(
            self.state_path,
            state.model_dump(mode="json"),
        )

    def _commit(
        self,
        state: FactoryProjectState,
        *,
        changes: dict[str, Any],
        topic: str,
        aggregate_id: UUID,
        event_payload: dict[str, Any],
    ) -> FactoryProjectState:
        payload = state.model_dump(mode="json", exclude={"state_sha256"})
        payload.update(changes)
        now = _now()
        sequence = max(
            (event.sequence for event in state.outbox_events),
            default=0,
        ) + 1
        outbox = list(payload["outbox_events"])
        outbox.append(
            FactoryOutboxEvent(
                event_id=uuid4(),
                sequence=sequence,
                topic=topic,
                aggregate_id=aggregate_id,
                payload=event_payload,
                created_at=now,
            ).model_dump(mode="json")
        )
        payload["outbox_events"] = outbox
        payload["state_version"] = state.state_version + 1
        payload["updated_at"] = now.isoformat()
        updated = with_state_hash(payload)
        self._write(updated, operation=topic)
        return updated

    def _mutate(
        self,
        *,
        expected_state_version: int,
        operation: Callable[
            [FactoryProjectState],
            tuple[dict[str, Any], str, UUID, dict[str, Any]],
        ],
    ) -> FactoryProjectState:
        with ProjectLock(self.project_root):
            state = self.load()
            if state.state_version != expected_state_version:
                raise FactoryStateConflict(
                    f"factory state version is {state.state_version}"
                )
            changes, topic, aggregate_id, event_payload = operation(state)
            if topic.endswith(".replayed"):
                return state
            return self._commit(
                state,
                changes=changes,
                topic=topic,
                aggregate_id=aggregate_id,
                event_payload=event_payload,
            )

    @staticmethod
    def _find_run(state: FactoryProjectState, run_id: UUID) -> GenerationRun:
        for run in state.runs:
            if run.run_id == run_id:
                return run
        raise FactoryStateError("generation run is unavailable")

    @staticmethod
    def _replace(items, identifier: str, value):
        target = getattr(value, identifier)
        replaced = False
        output = []
        for item in items:
            if getattr(item, identifier) == target:
                output.append(value)
                replaced = True
            else:
                output.append(item)
        if not replaced:
            raise FactoryStateError("factory state target is unavailable")
        return tuple(output)

    def create_run(
        self,
        *,
        request: GenerationRequest,
        fallback_policy: FallbackPolicySnapshot,
        cloud_policy: CloudExecutionPolicySnapshot,
        prompt_version: int = 1,
        changed_variable: str | None = None,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            existing = next(
                (
                    run
                    for run in state.runs
                    if run.request.idempotency_key == request.idempotency_key
                ),
                None,
            )
            if existing is not None:
                if existing.request != request:
                    raise FactoryStateConflict(
                        "generation idempotency key conflicts with existing run"
                    )
                return (
                    {},
                    "factory.generation.replayed",
                    existing.run_id,
                    {"run_id": str(existing.run_id)},
                )
            if any(run.run_id == request.run_id for run in state.runs):
                raise FactoryStateConflict("generation run id already exists")
            if request.project_revision_id != state.project_revision.revision_id:
                raise FactoryStateError(
                    "generation request targets a different project revision"
                )
            clip = next(
                (item for item in state.clips if item.clip_id == request.clip_id),
                None,
            )
            if clip is None or clip.scene_id != request.scene_id:
                raise FactoryStateError("generation request clip is unavailable")
            if request.fallback_policy_snapshot_id != fallback_policy.snapshot_id:
                raise FactoryStateError("fallback policy snapshot does not match request")
            if cloud_policy.run_id != request.run_id:
                raise FactoryStateError("cloud policy run does not match request")
            now = _now()
            run = GenerationRun(
                run_id=request.run_id,
                clip_id=request.clip_id,
                operation=request.mode.value,
                request=request,
                fallback_policy=fallback_policy,
                cloud_policy=cloud_policy,
                status=GenerationRunStatus.QUEUED,
                attempt_index=request.attempt_index,
                reroll_index=0,
                changed_variable=changed_variable,
                parent_run_id=request.parent_run_id,
                fallback_from_run_id=request.fallback_from_run_id,
                prompt_version=prompt_version,
                created_at=now,
                updated_at=now,
            )
            return (
                {"runs": (*state.runs, run)},
                "factory.generation.queued",
                run.run_id,
                {
                    "run_id": str(run.run_id),
                    "clip_id": str(run.clip_id),
                    "operation": run.operation,
                    "request": request.model_dump(mode="json"),
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def transition_run(
        self,
        run_id: UUID,
        status: GenerationRunStatus,
        *,
        expected_state_version: int,
        safe_error_code: str | None = None,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            run = self._find_run(state, run_id)
            if status not in RUN_TRANSITIONS[run.status]:
                raise FactoryStateError(
                    f"illegal generation transition {run.status.value}->{status.value}"
                )
            updated = run.model_copy(
                update={
                    "status": status,
                    "safe_error_code": safe_error_code,
                    "updated_at": _now(),
                }
            )
            return (
                {"runs": self._replace(state.runs, "run_id", updated)},
                f"factory.generation.{status.value}",
                run_id,
                {
                    "run_id": str(run_id),
                    "status": status.value,
                    "safe_error_code": safe_error_code,
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def prepare_submission(
        self,
        run_id: UUID,
        *,
        instance_id: str,
        gpu_id: str,
        gpu_lease_id: UUID,
        hub_job_lease_id: UUID,
        workflow_hash: str,
        expected_state_version: int,
        submission_nonce: str | None = None,
        client_id: str | None = None,
    ) -> FactoryProjectState:
        nonce = submission_nonce or uuid4().hex
        owner = client_id or f"drama-{uuid4().hex}"

        def operation(state: FactoryProjectState):
            run = self._find_run(state, run_id)
            if run.status is not GenerationRunStatus.QUEUED:
                raise FactoryStateError("only queued runs can prepare submission")
            existing = next(
                (
                    checkpoint
                    for checkpoint in state.checkpoints
                    if checkpoint.run_id == run_id
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.submission_nonce != nonce
                    or existing.client_id != owner
                    or existing.workflow_hash != workflow_hash
                    or existing.gpu_lease_id != gpu_lease_id
                    or existing.hub_job_lease_id != hub_job_lease_id
                ):
                    raise FactoryStateConflict(
                        "provider submission was already prepared"
                    )
                return (
                    {},
                    "factory.provider.prepare_replayed",
                    run_id,
                    {"run_id": str(run_id)},
                )
            checkpoint = ProviderCheckpoint(
                run_id=run_id,
                instance_id=instance_id,
                gpu_id=gpu_id,
                gpu_lease_id=gpu_lease_id,
                hub_job_lease_id=hub_job_lease_id,
                submission_nonce=nonce,
                client_id=owner,
                workflow_hash=workflow_hash,
                last_observed_state="prepared",
            )
            return (
                {"checkpoints": (*state.checkpoints, checkpoint)},
                "factory.provider.prepared",
                run_id,
                checkpoint.model_dump(mode="json"),
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def confirm_submission(
        self,
        run_id: UUID,
        *,
        prompt_id: str,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            run = self._find_run(state, run_id)
            if run.status is not GenerationRunStatus.QUEUED:
                raise FactoryStateError("run is not waiting for provider submission")
            checkpoint = next(
                (
                    item
                    for item in state.checkpoints
                    if item.run_id == run_id
                ),
                None,
            )
            if checkpoint is None:
                raise FactoryStateError(
                    "provider submission nonce must be persisted first"
                )
            if checkpoint.prompt_id is not None:
                if checkpoint.prompt_id != prompt_id:
                    raise FactoryStateConflict(
                        "provider prompt id conflicts with checkpoint"
                    )
                return (
                    {},
                    "factory.provider.confirm_replayed",
                    run_id,
                    {"run_id": str(run_id), "prompt_id": prompt_id},
                )
            now = _now()
            updated_checkpoint = checkpoint.model_copy(
                update={
                    "prompt_id": prompt_id,
                    "submitted_at": now,
                    "last_observed_state": "submitted",
                }
            )
            updated_run = run.model_copy(
                update={
                    "status": GenerationRunStatus.SUBMITTED,
                    "updated_at": now,
                }
            )
            return (
                {
                    "checkpoints": self._replace(
                        state.checkpoints,
                        "run_id",
                        updated_checkpoint,
                    ),
                    "runs": self._replace(state.runs, "run_id", updated_run),
                },
                "factory.provider.submitted",
                run_id,
                {
                    "run_id": str(run_id),
                    "prompt_id": prompt_id,
                    "instance_id": checkpoint.instance_id,
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def observe_provider(
        self,
        run_id: UUID,
        *,
        observed_state: str,
        progress: dict[str, Any],
        expected_state_version: int,
    ) -> FactoryProjectState:
        status_map = {
            "queued": GenerationRunStatus.SUBMITTED,
            "running": GenerationRunStatus.RUNNING,
            "success": GenerationRunStatus.MATERIALIZING,
            "error": GenerationRunStatus.FAILED,
            "lost": GenerationRunStatus.NEEDS_HUMAN,
            "cancelled": GenerationRunStatus.CANCELLED,
        }
        if observed_state not in status_map:
            raise ValueError("invalid provider observation")

        def operation(state: FactoryProjectState):
            run = self._find_run(state, run_id)
            checkpoint = next(
                (
                    item
                    for item in state.checkpoints
                    if item.run_id == run_id
                ),
                None,
            )
            if checkpoint is None or checkpoint.prompt_id is None:
                raise FactoryStateError("provider checkpoint is incomplete")
            target = status_map[observed_state]
            if target != run.status and target not in RUN_TRANSITIONS[run.status]:
                raise FactoryStateError(
                    f"illegal provider transition {run.status.value}->{target.value}"
                )
            now = _now()
            updated_checkpoint = checkpoint.model_copy(
                update={
                    "last_observed_state": observed_state,
                    "progress": progress,
                }
            )
            updated_run = run.model_copy(
                update={
                    "status": target,
                    "updated_at": now,
                    "safe_error_code": (
                        "provider_job_lost"
                        if observed_state == "lost"
                        else (
                            "provider_execution_failed"
                            if observed_state == "error"
                            else None
                        )
                    ),
                }
            )
            return (
                {
                    "checkpoints": self._replace(
                        state.checkpoints,
                        "run_id",
                        updated_checkpoint,
                    ),
                    "runs": self._replace(state.runs, "run_id", updated_run),
                },
                f"factory.provider.{observed_state}",
                run_id,
                {
                    "run_id": str(run_id),
                    "prompt_id": checkpoint.prompt_id,
                    "progress": progress,
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def record_visual_take(
        self,
        take: VisualTake,
        *,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            run = self._find_run(state, take.run_id)
            if run.status is not GenerationRunStatus.MATERIALIZING:
                raise FactoryStateError(
                    "visual take requires a materializing generation run"
                )
            if any(item.run_id == run.run_id for item in state.visual_takes):
                raise FactoryStateConflict(
                    "generation run already produced a visual take"
                )
            if take.eligibility is not TakeEligibility.CANDIDATE:
                raise FactoryStateError("new visual take must be a candidate")
            updated_run = run.model_copy(
                update={
                    "status": GenerationRunStatus.CANDIDATE,
                    "updated_at": _now(),
                }
            )
            return (
                {
                    "visual_takes": (*state.visual_takes, take),
                    "runs": self._replace(state.runs, "run_id", updated_run),
                },
                "factory.visual_take.candidate",
                take.visual_take_id,
                take.model_dump(mode="json"),
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def record_visual_qc(
        self,
        visual_take_id: UUID,
        *,
        evaluation: FactoryQCEvaluation,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            take = next(
                (
                    item
                    for item in state.visual_takes
                    if item.visual_take_id == visual_take_id
                ),
                None,
            )
            if take is None:
                raise FactoryStateError("visual take is unavailable")
            if (
                evaluation.subject_type != "visual_take"
                or evaluation.subject_id != visual_take_id
            ):
                raise FactoryStateError(
                    "visual factory QC subject does not match the take"
                )
            if take.factory_qc_evaluation_id is not None:
                if take.factory_qc_evaluation_id != evaluation.evaluation_id:
                    raise FactoryStateConflict("visual take was already evaluated")
                return (
                    {},
                    "factory.visual_qc.replayed",
                    visual_take_id,
                    {"evaluation_id": str(evaluation.evaluation_id)},
                )
            run = self._find_run(state, take.run_id)
            if run.status is not GenerationRunStatus.CANDIDATE:
                raise FactoryStateError("visual take is not awaiting factory QC")
            eligibility = (
                TakeEligibility.ELIGIBLE
                if evaluation.verdict is FactoryQCVerdict.PASS
                else (
                    TakeEligibility.NEEDS_HUMAN
                    if evaluation.verdict is FactoryQCVerdict.NEEDS_HUMAN
                    else TakeEligibility.REJECTED
                )
            )
            run_status = (
                GenerationRunStatus.ELIGIBLE
                if evaluation.verdict is FactoryQCVerdict.PASS
                else (
                    GenerationRunStatus.NEEDS_HUMAN
                    if evaluation.verdict is FactoryQCVerdict.NEEDS_HUMAN
                    else GenerationRunStatus.FAILED
                )
            )
            updated_take = take.model_copy(
                update={
                    "factory_qc_evaluation_id": evaluation.evaluation_id,
                    "eligibility": eligibility,
                }
            )
            updated_run = run.model_copy(
                update={
                    "status": run_status,
                    "safe_error_code": (
                        (
                            None
                            if evaluation.verdict is FactoryQCVerdict.PASS
                            else "factory_qc_failed"
                        )
                    ),
                    "updated_at": _now(),
                }
            )
            return (
                {
                    "visual_takes": self._replace(
                        state.visual_takes,
                        "visual_take_id",
                        updated_take,
                    ),
                    "runs": self._replace(state.runs, "run_id", updated_run),
                    "factory_qc_evaluations": (
                        *state.factory_qc_evaluations,
                        evaluation,
                    ),
                },
                (
                    "factory.visual_qc.eligible"
                    if evaluation.verdict is FactoryQCVerdict.PASS
                    else "factory.visual_qc.blocked"
                ),
                visual_take_id,
                {
                    "visual_take_id": str(visual_take_id),
                    "evaluation_id": str(evaluation.evaluation_id),
                    "eligibility": eligibility.value,
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    @staticmethod
    def _validate_derived_request(
        parent: GenerationRun,
        child: GenerationRequest,
        verdict: HumanVerdict,
        changed_variable: str | None,
        prompt_version: int,
    ) -> tuple[int, int]:
        if child.parent_run_id != parent.run_id:
            raise FactoryStateError("derived request must reference its parent run")
        if child.clip_id != parent.clip_id:
            raise FactoryStateError("derived request cannot change clip")
        if child.mode != parent.request.mode:
            raise FactoryStateError("derived request cannot change generation mode")
        if child.prompt_snapshot_id == parent.request.prompt_snapshot_id:
            raise FactoryStateError(
                "derived request requires a new immutable prompt snapshot"
            )
        if verdict is HumanVerdict.REROLL:
            reroll_index = parent.reroll_index + 1
            derived = derive_reroll_seed(
                parent_resolved_seed=parent.request.resolved_seed,
                reroll_index=reroll_index,
            )
            if (
                child.resolved_seed != derived.resolved_seed
                or child.seed_input_hash != derived.seed_input_hash
                or child.seed_derivation_version
                != derived.seed_derivation_version
                or child.attempt_index != parent.attempt_index + 1
                or prompt_version != parent.prompt_version
            ):
                raise FactoryStateError("re-roll seed or prompt inheritance is invalid")
            return child.attempt_index, reroll_index
        if verdict is HumanVerdict.REWRITE:
            if (
                child.resolved_seed != parent.request.resolved_seed
                or child.seed_input_hash != parent.request.seed_input_hash
                or child.attempt_index != parent.attempt_index
                or prompt_version != parent.prompt_version + 1
            ):
                raise FactoryStateError("rewrite must inherit seed and advance prompt")
            return child.attempt_index, parent.reroll_index
        if verdict is HumanVerdict.EDIT:
            if not changed_variable:
                raise FactoryStateError("edit requires exactly one changed variable")
            if changed_variable != "seed" and (
                child.resolved_seed != parent.request.resolved_seed
                or child.seed_input_hash != parent.request.seed_input_hash
            ):
                raise FactoryStateError("edit must inherit seed")
            if child.attempt_index != parent.attempt_index:
                raise FactoryStateError("edit must inherit attempt index")
            parent_data = parent.request.model_dump(
                mode="json",
                exclude={
                    "run_id",
                    "idempotency_key",
                    "parent_run_id",
                    "prompt_snapshot_id",
                },
            )
            child_data = child.model_dump(
                mode="json",
                exclude={
                    "run_id",
                    "idempotency_key",
                    "parent_run_id",
                    "prompt_snapshot_id",
                },
            )
            allowed_paths = {
                "duration_seconds",
                "resolution",
                "audio_intent",
                "reference_duties",
                "reference_exclusions",
                "model_id",
                "seed",
            }
            if changed_variable not in allowed_paths:
                raise FactoryStateError("edit changed variable is unsupported")
            differing = {
                key
                for key in set(parent_data) | set(child_data)
                if parent_data.get(key) != child_data.get(key)
            }
            seed_fields = {
                "resolved_seed",
                "seed_input_hash",
                "seed_derivation_version",
            }
            expected = seed_fields if changed_variable == "seed" else {changed_variable}
            if differing != expected:
                raise FactoryStateError(
                    f"edit must change one variable; observed={sorted(differing)}"
                )
            return child.attempt_index, parent.reroll_index
        raise FactoryStateError("verdict does not create a derived request")

    def apply_visual_verdict(
        self,
        visual_take_id: UUID,
        *,
        verdict: HumanVerdict,
        actor_id: str,
        idempotency_key: str,
        expected_canon_version: int,
        expected_state_version: int,
        derived_request: GenerationRequest | None = None,
        fallback_policy: FallbackPolicySnapshot | None = None,
        cloud_policy: CloudExecutionPolicySnapshot | None = None,
        changed_variable: str | None = None,
        prompt_version: int | None = None,
        reason: str | None = None,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            existing = next(
                (
                    event
                    for event in state.verdict_events
                    if event.idempotency_key == idempotency_key
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.visual_take_id != visual_take_id
                    or existing.verdict is not verdict
                ):
                    raise FactoryStateConflict(
                        "verdict idempotency key conflicts with stored command"
                    )
                return (
                    {},
                    "factory.visual_verdict.replayed",
                    visual_take_id,
                    {"event_id": str(existing.event_id)},
                )
            take = next(
                (
                    item
                    for item in state.visual_takes
                    if item.visual_take_id == visual_take_id
                ),
                None,
            )
            if take is None:
                raise FactoryStateError("visual take is unavailable")
            run = self._find_run(state, take.run_id)
            clip = next(item for item in state.clips if item.clip_id == run.clip_id)
            current_canon = max(
                (
                    revision.canon_version
                    for revision in state.visual_canon_revisions
                    if revision.scene_id == clip.scene_id
                ),
                default=0,
            )
            if current_canon != expected_canon_version:
                raise FactoryStateConflict(
                    f"visual canon version is {current_canon}"
                )
            now = _now()
            derived_run = None
            changes: dict[str, Any] = {}
            if verdict is HumanVerdict.KEEP:
                if take.eligibility is not TakeEligibility.ELIGIBLE:
                    raise FactoryStateError("only eligible visual takes can be kept")
                acceptance = ContinuityAnchorAccepted(
                    event_id=uuid4(),
                    scene_id=clip.scene_id,
                    clip_id=clip.clip_id,
                    visual_take_id=visual_take_id,
                    actor_id=actor_id,
                    observed_state=take.observed_state,
                    accepted_at=now,
                )
                canon = VisualCanonRevision(
                    scene_id=clip.scene_id,
                    canon_version=current_canon + 1,
                    visual_take_id=visual_take_id,
                    continuity_anchor_event_id=acceptance.event_id,
                    previous_version=(
                        current_canon if current_canon > 0 else None
                    ),
                    created_at=now,
                )
                changes.update(
                    {
                        "continuity_acceptances": (
                            *state.continuity_acceptances,
                            acceptance,
                        ),
                        "visual_canon_revisions": (
                            *state.visual_canon_revisions,
                            canon,
                        ),
                        "visual_takes": self._replace(
                            state.visual_takes,
                            "visual_take_id",
                            take.model_copy(
                                update={"eligibility": TakeEligibility.ACCEPTED}
                            ),
                        ),
                        "runs": self._replace(
                            state.runs,
                            "run_id",
                            run.model_copy(
                                update={
                                    "status": GenerationRunStatus.ACCEPTED,
                                    "updated_at": now,
                                }
                            ),
                        ),
                    }
                )
            elif verdict is HumanVerdict.FIX_IN_POST:
                if take.eligibility is not TakeEligibility.ELIGIBLE:
                    raise FactoryStateError(
                        "post fix can only start from an eligible visual take"
                    )
                changes.update(
                    {
                        "visual_takes": self._replace(
                            state.visual_takes,
                            "visual_take_id",
                            take.model_copy(
                                update={"eligibility": TakeEligibility.NEEDS_HUMAN}
                            ),
                        ),
                        "runs": self._replace(
                            state.runs,
                            "run_id",
                            run.model_copy(
                                update={
                                    "status": GenerationRunStatus.NEEDS_HUMAN,
                                    "updated_at": now,
                                    "safe_error_code": "post_fix_required",
                                }
                            ),
                        ),
                    }
                )
            else:
                if take.eligibility is not TakeEligibility.ELIGIBLE:
                    raise FactoryStateError(
                        "retake verdict requires an eligible visual take"
                    )
                if (
                    derived_request is None
                    or fallback_policy is None
                    or cloud_policy is None
                    or prompt_version is None
                ):
                    raise FactoryStateError(
                        "derived verdict requires a complete child run snapshot"
                    )
                attempt, reroll = self._validate_derived_request(
                    run,
                    derived_request,
                    verdict,
                    changed_variable,
                    prompt_version,
                )
                derived_run = GenerationRun(
                    run_id=derived_request.run_id,
                    clip_id=derived_request.clip_id,
                    operation=derived_request.mode.value,
                    request=derived_request,
                    fallback_policy=fallback_policy,
                    cloud_policy=cloud_policy,
                    status=GenerationRunStatus.QUEUED,
                    attempt_index=attempt,
                    reroll_index=reroll,
                    changed_variable=changed_variable,
                    parent_run_id=run.run_id,
                    fallback_from_run_id=derived_request.fallback_from_run_id,
                    prompt_version=prompt_version,
                    created_at=now,
                    updated_at=now,
                )
                changes.update(
                    {
                        "runs": (
                            *self._replace(
                                state.runs,
                                "run_id",
                                run.model_copy(
                                    update={
                                        "status": GenerationRunStatus.REJECTED,
                                        "updated_at": now,
                                        "safe_error_code": "human_retake",
                                    }
                                ),
                            ),
                            derived_run,
                        ),
                        "visual_takes": self._replace(
                            state.visual_takes,
                            "visual_take_id",
                            take.model_copy(
                                update={"eligibility": TakeEligibility.REJECTED}
                            ),
                        ),
                    }
                )
            event = HumanVerdictEvent(
                event_id=uuid4(),
                visual_take_id=visual_take_id,
                verdict=verdict,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                expected_canon_version=expected_canon_version,
                derived_run_id=(
                    None if derived_run is None else derived_run.run_id
                ),
                changed_variable=changed_variable,
                reason=reason,
                created_at=now,
            )
            changes["verdict_events"] = (*state.verdict_events, event)
            return (
                changes,
                f"factory.visual_verdict.{verdict.value}",
                visual_take_id,
                event.model_dump(mode="json"),
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def record_delivery_take(
        self,
        take: DeliveryTake,
        *,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            visual = next(
                (
                    item
                    for item in state.visual_takes
                    if item.visual_take_id == take.visual_take_id
                ),
                None,
            )
            if visual is None or visual.eligibility is not TakeEligibility.ACCEPTED:
                raise FactoryStateError(
                    "delivery take requires an accepted visual take"
                )
            if take.eligibility is not DeliveryEligibility.CANDIDATE:
                raise FactoryStateError("new delivery take must be a candidate")
            if any(
                item.delivery_take_id == take.delivery_take_id
                for item in state.delivery_takes
            ):
                raise FactoryStateConflict("delivery take already exists")
            return (
                {"delivery_takes": (*state.delivery_takes, take)},
                "factory.delivery_take.candidate",
                take.delivery_take_id,
                take.model_dump(mode="json"),
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def record_delivery_qc(
        self,
        delivery_take_id: UUID,
        *,
        evaluation: FactoryQCEvaluation,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            take = next(
                (
                    item
                    for item in state.delivery_takes
                    if item.delivery_take_id == delivery_take_id
                ),
                None,
            )
            if take is None:
                raise FactoryStateError("delivery take is unavailable")
            if (
                evaluation.subject_type != "delivery_take"
                or evaluation.subject_id != delivery_take_id
            ):
                raise FactoryStateError(
                    "delivery factory QC subject does not match the take"
                )
            if take.factory_qc_evaluation_id is not None:
                if take.factory_qc_evaluation_id != evaluation.evaluation_id:
                    raise FactoryStateConflict(
                        "delivery take was already evaluated"
                    )
                return (
                    {},
                    "factory.delivery_qc.replayed",
                    delivery_take_id,
                    {"evaluation_id": str(evaluation.evaluation_id)},
                )
            eligibility = (
                DeliveryEligibility.ELIGIBLE
                if evaluation.verdict is FactoryQCVerdict.PASS
                else (
                    DeliveryEligibility.NEEDS_HUMAN
                    if evaluation.verdict is FactoryQCVerdict.NEEDS_HUMAN
                    else DeliveryEligibility.REJECTED
                )
            )
            updated = take.model_copy(
                update={
                    "factory_qc_evaluation_id": evaluation.evaluation_id,
                    "eligibility": eligibility,
                }
            )
            return (
                {
                    "delivery_takes": self._replace(
                        state.delivery_takes,
                        "delivery_take_id",
                        updated,
                    ),
                    "factory_qc_evaluations": (
                        *state.factory_qc_evaluations,
                        evaluation,
                    ),
                },
                (
                    "factory.delivery_qc.eligible"
                    if evaluation.verdict is FactoryQCVerdict.PASS
                    else "factory.delivery_qc.blocked"
                ),
                delivery_take_id,
                {
                    "delivery_take_id": str(delivery_take_id),
                    "evaluation_id": str(evaluation.evaluation_id),
                    "eligibility": eligibility.value,
                },
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def accept_delivery(
        self,
        delivery_take_id: UUID,
        *,
        actor_id: str,
        expected_delivery_version: int,
        expected_state_version: int,
    ) -> FactoryProjectState:
        def operation(state: FactoryProjectState):
            take = next(
                (
                    item
                    for item in state.delivery_takes
                    if item.delivery_take_id == delivery_take_id
                ),
                None,
            )
            if take is None or take.eligibility is not DeliveryEligibility.ELIGIBLE:
                raise FactoryStateError(
                    "only eligible delivery takes can be accepted"
                )
            current = max(
                (
                    revision.delivery_version
                    for revision in state.delivery_revisions
                ),
                default=0,
            )
            if current != expected_delivery_version:
                raise FactoryStateConflict(
                    f"delivery revision version is {current}"
                )
            now = _now()
            acceptance = DeliveryAccepted(
                event_id=uuid4(),
                project_id=state.project_revision.project_id,
                delivery_take_id=delivery_take_id,
                actor_id=actor_id,
                accepted_at=now,
            )
            revision = DeliveryRevision(
                project_id=state.project_revision.project_id,
                delivery_version=current + 1,
                delivery_take_id=delivery_take_id,
                delivery_acceptance_event_id=acceptance.event_id,
                previous_version=current if current else None,
                created_at=now,
            )
            updated = take.model_copy(
                update={"eligibility": DeliveryEligibility.ACCEPTED}
            )
            return (
                {
                    "delivery_takes": self._replace(
                        state.delivery_takes,
                        "delivery_take_id",
                        updated,
                    ),
                    "delivery_acceptances": (
                        *state.delivery_acceptances,
                        acceptance,
                    ),
                    "delivery_revisions": (
                        *state.delivery_revisions,
                        revision,
                    ),
                },
                "factory.delivery.accepted",
                delivery_take_id,
                revision.model_dump(mode="json"),
            )

        return self._mutate(
            expected_state_version=expected_state_version,
            operation=operation,
        )

    def pending_outbox(self) -> tuple[FactoryOutboxEvent, ...]:
        return tuple(
            event
            for event in self.load().outbox_events
            if event.published_at is None
        )

    def mark_outbox_published(
        self,
        sequence: int,
        *,
        expected_state_version: int,
    ) -> FactoryProjectState:
        with ProjectLock(self.project_root):
            state = self.load()
            if state.state_version != expected_state_version:
                raise FactoryStateConflict(
                    f"factory state version is {state.state_version}"
                )
            found = False
            events = []
            for event in state.outbox_events:
                if event.sequence == sequence:
                    found = True
                    events.append(
                        event
                        if event.published_at is not None
                        else event.model_copy(update={"published_at": _now()})
                    )
                else:
                    events.append(event)
            if not found:
                raise FactoryStateError("outbox event is unavailable")
            payload = state.model_dump(mode="json", exclude={"state_sha256"})
            payload["outbox_events"] = events
            payload["state_version"] = state.state_version + 1
            payload["updated_at"] = _now()
            updated = with_state_hash(payload)
            self._write(
                updated,
                operation="factory.outbox.published",
            )
            return updated
