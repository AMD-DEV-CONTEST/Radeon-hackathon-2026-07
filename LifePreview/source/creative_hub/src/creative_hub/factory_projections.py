from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from shared_contracts import (
    ModelCapability,
    ModelRegistryEntry,
    stable_json_sha256,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .gpu_scheduler import GpuObservation, GpuScheduleDecision, GpuTaskRequest
from .models import (
    DeliveryRevisionMirrorRecord,
    FactoryOutboxConsumptionRecord,
    FactoryProjectRecord,
    FactoryRevisionRecord,
    FactoryTakeIndexRecord,
    GenerationRunMirrorRecord,
    GpuLeaseMirrorRecord,
    GpuObservationRecord,
    ModelCapabilityRecord,
    ModelRegistryRecord,
    VisualCanonMirrorRecord,
)


class FactoryProjectionError(RuntimeError):
    pass


class FactoryProjectionConflict(FactoryProjectionError):
    pass


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise FactoryProjectionError(f"factory snapshot {field} is invalid") from None


def _datetime(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise FactoryProjectionError(f"factory snapshot {field} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FactoryProjectionError(f"factory snapshot {field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validated_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise FactoryProjectionError("factory snapshot must be an object")
    state_hash = snapshot.get("state_sha256")
    if not isinstance(state_hash, str) or len(state_hash) != 64:
        raise FactoryProjectionError("factory snapshot hash is missing")
    identity = dict(snapshot)
    identity.pop("state_sha256", None)
    if stable_json_sha256(identity) != state_hash:
        raise FactoryProjectionError("factory snapshot hash does not match content")
    if snapshot.get("schema_version") != "factory.project-state.v3":
        raise FactoryProjectionError("factory snapshot schema is unsupported")
    return snapshot


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    project_id: UUID
    state_version: int
    created_outbox_events: int
    replayed: bool


class FactoryProjectionRepository:
    """Idempotent Hub/Orchestration mirror of factory-authoritative state."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _identity(
        snapshot: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], UUID, UUID, int]:
        state = _validated_state(snapshot)
        revision = state.get("project_revision")
        if not isinstance(revision, dict):
            raise FactoryProjectionError("factory revision is missing")
        project_id = _uuid(revision.get("project_id"), "project_id")
        revision_id = _uuid(revision.get("revision_id"), "revision_id")
        state_version = state.get("state_version")
        if (
            isinstance(state_version, bool)
            or not isinstance(state_version, int)
            or state_version < 0
        ):
            raise FactoryProjectionError("factory state version is invalid")
        return state, revision, project_id, revision_id, state_version

    def apply_hub_snapshot(
        self,
        snapshot: dict[str, Any],
    ) -> ProjectionResult:
        (
            state,
            revision,
            project_id,
            revision_id,
            state_version,
        ) = self._identity(snapshot)
        project = self.session.get(FactoryProjectRecord, project_id)
        if project is not None:
            if project.state_version > state_version:
                raise FactoryProjectionConflict(
                    "factory mirror cannot regress to an older state"
                )
            if (
                project.state_version == state_version
                and project.state_sha256 != state["state_sha256"]
            ):
                raise FactoryProjectionConflict(
                    "factory state version conflicts with stored hash"
                )
            replayed = (
                project.state_version == state_version
                and project.state_sha256 == state["state_sha256"]
            )
        else:
            replayed = False
        self._revision(revision, project_id)
        self._project(
            project,
            project_id=project_id,
            revision_id=revision_id,
            state=state,
        )
        self._takes(state, project_id, revision_id)
        self._canon(state, project_id)
        self._deliveries(state, project_id)
        self.session.flush()
        return ProjectionResult(
            project_id=project_id,
            state_version=state_version,
            created_outbox_events=0,
            replayed=replayed,
        )

    def apply_orchestration_snapshot(
        self,
        snapshot: dict[str, Any],
    ) -> ProjectionResult:
        (
            state,
            _revision,
            project_id,
            revision_id,
            state_version,
        ) = self._identity(snapshot)
        self._runs(state, project_id, revision_id)
        created_outbox = self._outbox(state, revision_id)
        self.session.flush()
        return ProjectionResult(
            project_id=project_id,
            state_version=state_version,
            created_outbox_events=created_outbox,
            replayed=created_outbox == 0,
        )

    def apply_snapshot(self, snapshot: dict[str, Any]) -> ProjectionResult:
        hub = self.apply_hub_snapshot(snapshot)
        orchestration = self.apply_orchestration_snapshot(snapshot)
        return ProjectionResult(
            project_id=hub.project_id,
            state_version=hub.state_version,
            created_outbox_events=(
                orchestration.created_outbox_events
            ),
            replayed=hub.replayed and orchestration.replayed,
        )

    def _revision(
        self,
        payload: dict[str, Any],
        project_id: UUID,
    ) -> None:
        revision_id = _uuid(payload.get("revision_id"), "revision_id")
        existing = self.session.get(FactoryRevisionRecord, revision_id)
        if existing is not None:
            if existing.payload != payload:
                raise FactoryProjectionConflict(
                    "factory revision identity conflicts with stored content"
                )
            return
        self.session.add(
            FactoryRevisionRecord(
                id=revision_id,
                project_id=project_id,
                parent_revision_id=(
                    None
                    if payload.get("parent_revision_id") is None
                    else _uuid(
                        payload["parent_revision_id"],
                        "parent_revision_id",
                    )
                ),
                content_hash=str(payload.get("content_hash", "")),
                source_kind=str(payload.get("source_kind", "")),
                source_hash=payload.get("source_hash"),
                revision_created_at=_datetime(
                    payload.get("created_at"),
                    "revision.created_at",
                ),
                payload=payload,
            )
        )

    def _project(
        self,
        existing: FactoryProjectRecord | None,
        *,
        project_id: UUID,
        revision_id: UUID,
        state: dict[str, Any],
    ) -> None:
        summary = {
            "schema_version": state["schema_version"],
            "scene_count": len(state.get("scenes") or ()),
            "clip_count": len(state.get("clips") or ()),
            "run_count": len(state.get("runs") or ()),
            "visual_take_count": len(state.get("visual_takes") or ()),
            "delivery_take_count": len(state.get("delivery_takes") or ()),
            "updated_at": state.get("updated_at"),
        }
        if existing is None:
            self.session.add(
                FactoryProjectRecord(
                    id=project_id,
                    active_revision_id=revision_id,
                    state_version=state["state_version"],
                    state_sha256=state["state_sha256"],
                    status="active",
                    payload=summary,
                )
            )
            return
        if existing.state_version <= state["state_version"]:
            existing.active_revision_id = revision_id
            existing.state_version = state["state_version"]
            existing.state_sha256 = state["state_sha256"]
            existing.payload = summary

    def _runs(
        self,
        state: dict[str, Any],
        project_id: UUID,
        revision_id: UUID,
    ) -> None:
        checkpoints = {
            str(item.get("run_id")): item
            for item in state.get("checkpoints") or ()
            if isinstance(item, dict)
        }
        for payload in state.get("runs") or ():
            if not isinstance(payload, dict):
                raise FactoryProjectionError("factory run payload is invalid")
            request = payload.get("request")
            if not isinstance(request, dict):
                raise FactoryProjectionError("factory run request is invalid")
            run_id = _uuid(payload.get("run_id"), "run_id")
            values = {
                "project_id": project_id,
                "revision_id": revision_id,
                "scene_id": _uuid(request.get("scene_id"), "run.scene_id"),
                "clip_id": _uuid(request.get("clip_id"), "run.clip_id"),
                "mode": str(request.get("mode", "")),
                "model_id": str(request.get("model_id", "")),
                "status": str(payload.get("status", "")),
                "idempotency_key": str(request.get("idempotency_key", "")),
                "provider_checkpoint": checkpoints.get(str(run_id), {}),
                "payload": payload,
            }
            record = self.session.get(GenerationRunMirrorRecord, run_id)
            if record is None:
                self.session.add(GenerationRunMirrorRecord(id=run_id, **values))
            else:
                for key, value in values.items():
                    setattr(record, key, value)

    def _takes(
        self,
        state: dict[str, Any],
        project_id: UUID,
        revision_id: UUID,
    ) -> None:
        visuals: dict[str, dict[str, Any]] = {}
        for payload in state.get("visual_takes") or ():
            if not isinstance(payload, dict):
                raise FactoryProjectionError("visual take payload is invalid")
            take_id = _uuid(payload.get("visual_take_id"), "visual_take_id")
            visuals[str(take_id)] = payload
            self._take(
                take_id,
                project_id=project_id,
                revision_id=revision_id,
                run_id=_uuid(payload.get("run_id"), "visual_take.run_id"),
                visual_take_id=None,
                kind="visual",
                eligibility=str(payload.get("eligibility", "")),
                artifact=payload.get("raw_video_ref"),
                created_at=payload.get("created_at"),
                payload=payload,
            )
        for payload in state.get("delivery_takes") or ():
            if not isinstance(payload, dict):
                raise FactoryProjectionError("delivery take payload is invalid")
            take_id = _uuid(payload.get("delivery_take_id"), "delivery_take_id")
            visual_take_id = _uuid(
                payload.get("visual_take_id"),
                "delivery_take.visual_take_id",
            )
            visual = visuals.get(str(visual_take_id))
            run_id = (
                None
                if visual is None
                else _uuid(visual.get("run_id"), "delivery_take.run_id")
            )
            self._take(
                take_id,
                project_id=project_id,
                revision_id=revision_id,
                run_id=run_id,
                visual_take_id=visual_take_id,
                kind="delivery",
                eligibility=str(payload.get("eligibility", "")),
                artifact=payload.get("final_composite_ref"),
                created_at=payload.get("created_at"),
                payload=payload,
            )

    def _take(
        self,
        take_id: UUID,
        *,
        project_id: UUID,
        revision_id: UUID,
        run_id: UUID | None,
        visual_take_id: UUID | None,
        kind: str,
        eligibility: str,
        artifact: Any,
        created_at: Any,
        payload: dict[str, Any],
    ) -> None:
        if not isinstance(artifact, dict):
            raise FactoryProjectionError("factory take artifact is invalid")
        values = {
            "project_id": project_id,
            "revision_id": revision_id,
            "run_id": run_id,
            "visual_take_id": visual_take_id,
            "take_kind": kind,
            "eligibility": eligibility,
            "artifact_sha256": str(artifact.get("sha256", "")),
            "take_created_at": _datetime(created_at, "take.created_at"),
            "payload": payload,
        }
        record = self.session.get(FactoryTakeIndexRecord, take_id)
        if record is None:
            self.session.add(FactoryTakeIndexRecord(id=take_id, **values))
        else:
            for key, value in values.items():
                setattr(record, key, value)

    def _canon(self, state: dict[str, Any], project_id: UUID) -> None:
        for payload in state.get("visual_canon_revisions") or ():
            scene_id = _uuid(payload.get("scene_id"), "canon.scene_id")
            version = payload.get("canon_version")
            existing = self.session.scalar(
                select(VisualCanonMirrorRecord).where(
                    VisualCanonMirrorRecord.scene_id == scene_id,
                    VisualCanonMirrorRecord.canon_version == version,
                )
            )
            if existing is not None:
                if existing.payload != payload:
                    raise FactoryProjectionConflict(
                        "visual canon mirror conflicts with stored revision"
                    )
                continue
            self.session.add(
                VisualCanonMirrorRecord(
                    project_id=project_id,
                    scene_id=scene_id,
                    canon_version=version,
                    visual_take_id=_uuid(
                        payload.get("visual_take_id"),
                        "canon.visual_take_id",
                    ),
                    continuity_anchor_event_id=_uuid(
                        payload.get("continuity_anchor_event_id"),
                        "canon.continuity_anchor_event_id",
                    ),
                    payload=payload,
                )
            )

    def _deliveries(self, state: dict[str, Any], project_id: UUID) -> None:
        for payload in state.get("delivery_revisions") or ():
            version = payload.get("delivery_version")
            existing = self.session.scalar(
                select(DeliveryRevisionMirrorRecord).where(
                    DeliveryRevisionMirrorRecord.project_id == project_id,
                    DeliveryRevisionMirrorRecord.delivery_version == version,
                )
            )
            if existing is not None:
                if existing.payload != payload:
                    raise FactoryProjectionConflict(
                        "delivery mirror conflicts with stored revision"
                    )
                continue
            self.session.add(
                DeliveryRevisionMirrorRecord(
                    project_id=project_id,
                    delivery_version=version,
                    delivery_take_id=_uuid(
                        payload.get("delivery_take_id"),
                        "delivery.delivery_take_id",
                    ),
                    delivery_acceptance_event_id=_uuid(
                        payload.get("delivery_acceptance_event_id"),
                        "delivery.acceptance_event_id",
                    ),
                    payload=payload,
                )
            )

    def _outbox(self, state: dict[str, Any], revision_id: UUID) -> int:
        created = 0
        for payload in state.get("outbox_events") or ():
            payload = dict(payload)
            payload["published_at"] = None
            event_id = _uuid(payload.get("event_id"), "outbox.event_id")
            existing = self.session.get(FactoryOutboxConsumptionRecord, event_id)
            if existing is not None:
                if existing.payload != payload:
                    raise FactoryProjectionConflict(
                        "factory outbox event conflicts with consumed payload"
                    )
                continue
            self.session.add(
                FactoryOutboxConsumptionRecord(
                    event_id=event_id,
                    source_revision_id=revision_id,
                    source_sequence=payload.get("sequence"),
                    topic=str(payload.get("topic", "")),
                    source_state_sha256=state["state_sha256"],
                    payload=payload,
                )
            )
            created += 1
        return created


class OrchestrationProjectionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_model(
        self,
        entry: ModelRegistryEntry,
        capabilities: tuple[ModelCapability, ...],
    ) -> None:
        try:
            entry = ModelRegistryEntry.model_validate(
                entry.model_dump(mode="json")
            )
            capabilities = tuple(
                ModelCapability.model_validate(item.model_dump(mode="json"))
                for item in capabilities
            )
        except ValidationError:
            raise FactoryProjectionError("model registry contract is invalid") from None
        if set(entry.capability_ids) != {
            capability.capability_id for capability in capabilities
        }:
            raise FactoryProjectionError("model registry capability ids do not match")
        record = self.session.get(ModelRegistryRecord, entry.model_id)
        values = {
            "registry_entry_id": entry.registry_entry_id,
            "install_status": entry.install_status.value,
            "verification_status": entry.verification_status.value,
            "snapshot_sha256": entry.snapshot_sha256,
            "payload": entry.model_dump(mode="json"),
        }
        if record is None:
            self.session.add(ModelRegistryRecord(model_id=entry.model_id, **values))
        else:
            for key, value in values.items():
                setattr(record, key, value)
        for capability in capabilities:
            stored = self.session.get(
                ModelCapabilityRecord,
                capability.capability_id,
            )
            values = {
                "model_id": capability.model_id,
                "operation": capability.operation.value,
                "workflow_id": capability.workflow_id,
                "estimated_vram_mib": capability.estimated_vram_mib,
                "verified": capability.verified,
                "snapshot_sha256": capability.snapshot_sha256,
                "payload": capability.model_dump(mode="json"),
            }
            if stored is None:
                self.session.add(
                    ModelCapabilityRecord(
                        id=capability.capability_id,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(stored, key, value)
        self.session.flush()

    def enqueue_gpu(
        self,
        request: GpuTaskRequest,
        *,
        effective_priority: int,
    ) -> GpuLeaseMirrorRecord:
        existing = self.session.scalar(
            select(GpuLeaseMirrorRecord).where(
                GpuLeaseMirrorRecord.request_id == request.request_id
            )
        )
        payload = {
            "request_id": str(request.request_id),
            "resource_class": request.resource_class.value,
            "model_id": request.model_id,
            "estimated_vram_mib": request.estimated_vram_mib,
            "enqueued_at": request.enqueued_at.isoformat(),
            "max_runtime_seconds": request.max_runtime_seconds,
            "project_id": (
                None if request.project_id is None else str(request.project_id)
            ),
            "scene_id": (
                None if request.scene_id is None else str(request.scene_id)
            ),
            "dependency_request_ids": [
                str(value) for value in request.dependency_request_ids
            ],
            "pinned_gpu_index": request.pinned_gpu_index,
            "resource_requirement": (
                None
                if request.resource_requirement is None
                else request.resource_requirement.model_dump(mode="json")
            ),
            "implementation_manifest_digest": (
                request.implementation_manifest_digest
            ),
        }
        if existing is not None:
            if existing.payload != payload:
                raise FactoryProjectionConflict(
                    "GPU request id conflicts with stored payload"
                )
            return existing
        record = GpuLeaseMirrorRecord(
            id=request.request_id,
            request_id=request.request_id,
            resource_class=request.resource_class.value,
            model_id=request.model_id,
            estimated_vram_mib=request.estimated_vram_mib,
            effective_priority=effective_priority,
            status="queued",
            requested_at=request.enqueued_at,
            payload=payload,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def activate_gpu(
        self,
        decision: GpuScheduleDecision,
        *,
        expires_at: datetime,
    ) -> GpuLeaseMirrorRecord:
        record = self.session.scalar(
            select(GpuLeaseMirrorRecord).where(
                GpuLeaseMirrorRecord.request_id == decision.request_id
            )
        )
        if record is None or record.status != "queued":
            raise FactoryProjectionConflict("GPU request is not queued")
        record.gpu_index = decision.gpu_index
        record.effective_priority = decision.effective_priority
        record.status = "active"
        record.expires_at = expires_at
        self.session.flush()
        return record

    def append_gpu_observation(
        self,
        observation: GpuObservation,
        *,
        observed_at: datetime,
    ) -> GpuObservationRecord:
        payload = {
            "gpu_index": observation.gpu_index,
            "total_vram_mib": observation.total_vram_mib,
            "free_vram_mib": observation.free_vram_mib,
            "warm_model_id": observation.warm_model_id,
            "active_lease_id": (
                None
                if observation.active_lease_id is None
                else str(observation.active_lease_id)
            ),
            "observed_at": observed_at.isoformat(),
        }
        record = GpuObservationRecord(
            gpu_index=observation.gpu_index,
            total_vram_mib=observation.total_vram_mib,
            free_vram_mib=observation.free_vram_mib,
            warm_model_id=observation.warm_model_id,
            active_lease_id=observation.active_lease_id,
            observed_at=observed_at,
            payload=payload,
        )
        self.session.add(record)
        self.session.flush()
        return record
