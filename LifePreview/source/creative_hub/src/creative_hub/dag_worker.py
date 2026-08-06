"""Production worker for the durable Creative Hub DAG queue.

The scheduler remains the sole lease and Attempt authority.  This module only
binds an admitted Attempt to an exact atomic request, invokes the frozen
capability registry, and reports the terminal outcome back to the scheduler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from atomic_runtime import CapabilityRegistry
from shared_contracts import (
    AtomicArtifactRef,
    EntityDomain,
    EntityRef,
    H3AttemptSelectionV1,
    H3CandidateScoreV1,
    H3DeliveryAssemblyManifestV1,
    H3DeliveryDisclosureV1,
    H3DeliverySequenceSourceV1,
    H3DeliveryV1,
    OperationRequest,
    OperationResult,
    OperationStatus,
    ResourceClass,
    RetentionClass,
    SchemaRevision,
    build_operation_input_digest,
    h3_contract_digest,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .dag_execution import (
    DagEdge,
    DagLease,
    DagNode,
    DurableDagScheduler,
)
from .dag_models import (
    RESOURCE_POOLS,
    DagReadyQueueRecord,
    OperationDependencyStateRecord,
    WorkflowRunEdgeRecord,
)
from .db.canonical import canonical_json_digest
from .db.models import (
    ArtifactLineageEdgeRecord,
    ArtifactRecordRow,
    DeliveryRevisionRecord,
    H3RuntimeAttemptRecord,
    H3SequenceRevisionRecord,
    OperationAttemptRecord,
    OperationRunRecord,
    ProviderInvocationRecord,
    QCCandidateVersionRecord,
    QCEvaluationFactRecord,
    QCGateDecisionRecord,
    QCPromptRevisionRecord,
    SelectionHeadRecord,
    SelectionRevisionRecord,
    VideoJobProjectionRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from .db.repositories import (
    OperationRepository,
    PersistenceError,
    SelectionRepository,
)
from .gpu_scheduler import (
    GpuObservation,
    GpuResourceClass,
    GpuTaskRequest,
    UnifiedGpuScheduler,
)
from .h3_repository import H3Repository


_NODE_NAMESPACE = UUID("90135ff9-11e9-4b90-ad79-8dd7b6fc93bb")
_POLICY_NAMESPACE = UUID("c09417c4-7c4b-431e-b7be-754e5dfca166")
_CONTROL_NAMESPACE = UUID("b4b26a4f-cdfa-4575-8f1f-615b190ddc39")
_RESERVED_WORKFLOW_INPUTS = frozenset(
    {"input_artifact_refs", "subject_ref", "structured_inputs"}
)


class DagWorkerError(RuntimeError):
    """A safe worker boundary failure."""


class ContextFactory(Protocol):
    def __call__(
        self,
        request: OperationRequest,
        artifact_gateway: object,
        /,
    ) -> object: ...


class ArtifactGatewayFactory(Protocol):
    def __call__(self) -> object: ...


@dataclass(frozen=True, slots=True)
class _GatewayProducedArtifact:
    payload: bytes
    mime_type: str
    logical_role: str
    retention_class: RetentionClass = RetentionClass.WORKFLOW


class GatewayEvidenceArtifactIO:
    """Bind Analysis media stages to the same publication authority."""

    def __init__(self, *, gateway: object, root: Path) -> None:
        self.gateway = gateway
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(
        self,
        project_id: UUID,
        artifact: AtomicArtifactRef,
        /,
    ) -> Path:
        if artifact.project_id != project_id:
            raise DagWorkerError("analysis artifact project mismatch")
        payload = self.gateway.read_bytes(artifact)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.content_digest or len(payload) != artifact.byte_size:
            raise DagWorkerError("analysis artifact integrity mismatch")
        project_root = self.root / project_id.hex
        project_root.mkdir(parents=True, exist_ok=True)
        target = project_root / artifact.content_digest
        if not target.exists():
            staging = project_root / f".{artifact.content_digest}.{os.getpid()}"
            try:
                with staging.open("xb") as stream:
                    stream.write(payload)
                os.replace(staging, target)
            except FileExistsError:
                pass
            finally:
                staging.unlink(missing_ok=True)
        return target

    def publish(
        self,
        request: OperationRequest,
        materialized,
        /,
        *,
        mime_type: str,
        logical_role: str,
        guard,
    ):
        guard.checkpoint()
        payload = materialized.path.read_bytes()
        if (
            hashlib.sha256(payload).hexdigest()
            != materialized.content_digest
            or len(payload) != materialized.byte_size
        ):
            raise DagWorkerError("analysis output integrity mismatch")
        return self.gateway.publish(
            _GatewayProducedArtifact(
                payload=payload,
                mime_type=mime_type,
                logical_role=logical_role,
            ),
            request=request,
            created_at=datetime.now(timezone.utc),
        )


class PostgresDurableProviderStore:
    """Transaction-per-transition adapter over the Hub provider authority."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
    ) -> None:
        self.session_factory = session_factory

    def get(self, invocation_id: UUID):
        from drama.v3.durable_provider import ProviderStateConflict

        with self.session_factory() as session:
            row = session.get(ProviderInvocationRecord, invocation_id)
            if row is None:
                raise ProviderStateConflict(
                    "provider invocation is unavailable"
                )
            return _provider_invocation(row)

    def prepare(
        self,
        *,
        invocation_id,
        project_id,
        operation_run_id,
        operation_attempt_id,
        provider,
        client_token,
        submission_nonce,
        request_payload,
        capabilities,
    ):
        from .provider_invocations import ProviderInvocationRepository

        with self.session_factory() as session, session.begin():
            attempt = session.get(
                OperationAttemptRecord, operation_attempt_id
            )
            if attempt is None or attempt.submission_nonce != submission_nonce:
                raise DagWorkerError(
                    "provider submission nonce does not match Attempt"
                )
            row = ProviderInvocationRepository(session).prepare(
                invocation_id=invocation_id,
                project_id=project_id,
                operation_run_id=operation_run_id,
                operation_attempt_id=operation_attempt_id,
                provider=provider,
                client_token=client_token,
                request_payload=request_payload,
                supports_idempotent_submit=(
                    capabilities.idempotent_submit
                ),
                supports_query_by_client_token=(
                    capabilities.query_by_client_token
                ),
                supports_query_by_task_id=capabilities.query_by_task_id,
            ).value
            return _provider_invocation(row)

    def _project_id(self, invocation_id: UUID) -> UUID:
        return self.get(invocation_id).project_id

    def mark_submission_started(
        self,
        invocation_id,
        *,
        grant,
        expected_state_version,
        occurred_at,
    ):
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(
                session
            ).mark_submission_started(
                invocation_id=invocation_id,
                project_id=project_id,
                grant_id=grant.grant_id,
                expected_state_version=expected_state_version,
                occurred_at=occurred_at,
            )
            return _provider_invocation(row)

    def record_submitted(
        self,
        invocation_id,
        *,
        provider_task_id,
        expected_state_version,
        occurred_at,
    ):
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(session).record_submitted(
                invocation_id=invocation_id,
                project_id=project_id,
                provider_task_id=provider_task_id,
                expected_state_version=expected_state_version,
                occurred_at=occurred_at,
            )
            return _provider_invocation(row)

    def record_outcome_unknown(
        self,
        invocation_id,
        *,
        expected_state_version,
        occurred_at,
    ):
        del occurred_at
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(
                session
            ).record_outcome_unknown(
                invocation_id=invocation_id,
                project_id=project_id,
                expected_state_version=expected_state_version,
            )
            return _provider_invocation(row)

    def record_observation(
        self,
        invocation_id,
        *,
        observation,
        callback_id,
        expected_state_version,
        occurred_at,
    ):
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(session).record_observation(
                invocation_id=invocation_id,
                project_id=project_id,
                observed_state=observation.state.value,
                provider_task_id=observation.provider_task_id,
                result_payload=observation.result,
                cost_micros=observation.cost_micros,
                callback_id=callback_id,
                expected_state_version=expected_state_version,
                occurred_at=occurred_at,
            )
            return _provider_invocation(row)

    def consume_reconcile_grant(
        self,
        invocation_id,
        *,
        grant,
        expected_state_version,
    ):
        from drama.v3.durable_provider import ProviderStateConflict

        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            current = session.get(
                ProviderInvocationRecord, invocation_id
            )
            if (
                current is None
                or current.state_version != expected_state_version
            ):
                raise ProviderStateConflict(
                    "provider invocation version changed"
                )
            row = ProviderInvocationRepository(
                session
            ).consume_reconcile_grant(
                invocation_id=invocation_id,
                project_id=project_id,
                grant_id=grant.grant_id,
            )
            return _provider_invocation(row)

    def require_human(
        self,
        invocation_id,
        *,
        safe_reason_code,
        expected_state_version,
        occurred_at,
    ):
        del occurred_at
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(
                session
            ).record_outcome_unknown(
                invocation_id=invocation_id,
                project_id=project_id,
                expected_state_version=expected_state_version,
                human_required=True,
                safe_reason_code=safe_reason_code,
            )
            return _provider_invocation(row)

    def begin_materialization(
        self,
        invocation_id,
        *,
        grant,
        expected_state_version,
        occurred_at,
    ):
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(
                session
            ).begin_materialization(
                invocation_id=invocation_id,
                project_id=project_id,
                grant_id=grant.grant_id,
                expected_state_version=expected_state_version,
                occurred_at=occurred_at,
            )
            return _provider_invocation(row)

    def commit(
        self,
        invocation_id,
        *,
        committed_result,
        actual_cost_micros,
        expected_state_version,
        occurred_at,
    ):
        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(session).commit(
                invocation_id=invocation_id,
                project_id=project_id,
                committed_result=committed_result,
                actual_cost_micros=actual_cost_micros or 0,
                expected_state_version=expected_state_version,
                occurred_at=occurred_at,
            )
            return _provider_invocation(row)

    def grant(self, invocation_id: UUID, action, *, reason: str):
        from drama.v3.durable_provider import ProviderActionGrant

        from .provider_invocations import ProviderInvocationRepository

        project_id = self._project_id(invocation_id)
        with self.session_factory() as session, session.begin():
            row = ProviderInvocationRepository(session).grant(
                invocation_id=invocation_id,
                project_id=project_id,
                action=action.value,
                granted_by_actor="creative-hub-video-worker",
                reason=reason,
            )
            return ProviderActionGrant(
                grant_id=row.id,
                invocation_id=row.invocation_id,
                action=action,
                granted_by_actor=row.granted_by_actor,
                reason=row.reason,
                granted_at=row.created_at,
            )


def _provider_invocation(row: ProviderInvocationRecord):
    from drama.v3.durable_provider import (
        ProviderCapabilities,
        ProviderInvocation,
        ProviderInvocationPhase,
        ProviderTerminalOutcome,
    )

    return ProviderInvocation(
        invocation_id=row.id,
        project_id=row.project_id,
        operation_run_id=row.operation_run_id,
        operation_attempt_id=row.operation_attempt_id,
        provider=row.provider,
        client_token=row.client_token,
        submission_nonce=row.submission_nonce,
        request_payload=dict(row.request_payload),
        request_digest=row.request_digest,
        capabilities=ProviderCapabilities(
            idempotent_submit=row.supports_idempotent_submit,
            query_by_client_token=row.supports_query_by_client_token,
            query_by_task_id=row.supports_query_by_task_id,
        ),
        phase=ProviderInvocationPhase(row.phase),
        state_version=row.state_version,
        provider_task_id=row.provider_task_id,
        terminal_outcome=(
            ProviderTerminalOutcome(row.terminal_outcome)
            if row.terminal_outcome
            else None
        ),
        result=dict(row.result_payload) if row.result_digest else None,
        result_digest=row.result_digest,
        committed_result=(
            dict(row.materialized_payload)
            if row.materialized_digest
            else None
        ),
        committed_result_digest=row.materialized_digest,
        cost_micros=row.cost_micros,
        submit_started_at=row.submit_started_at,
        submitted_at=row.submitted_at,
        terminal_observed_at=row.terminal_observed_at,
        materializing_at=row.materializing_at,
        committed_at=row.committed_at,
        human_required=row.human_required,
        safe_reason_code=row.safe_reason_code,
    )


class ControlAction(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING_HUMAN = "waiting_human"


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    action: ControlAction
    reason: str = ""
    actual_cost_micros: int = 0
    metrics: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None


class ControlNodeDispatcher(Protocol):
    def __call__(
        self,
        *,
        lease: DagLease,
        operation: OperationRunRecord,
        request_payload: Mapping[str, Any],
    ) -> ControlOutcome: ...


class TickOutcome(StrEnum):
    IDLE = "idle"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_HUMAN = "waiting_human"


@dataclass(frozen=True, slots=True)
class WorkerTick:
    outcome: TickOutcome
    operation_run_id: UUID | None = None
    attempt_id: UUID | None = None


class OperationRequestBuilder:
    """Resolve late-bound artifact inputs into one strict execution envelope."""

    def __init__(
        self,
        session: Session,
        *,
        capability_registry: CapabilityRegistry,
    ) -> None:
        if not capability_registry.is_frozen:
            raise DagWorkerError(
                "capability registry must be frozen before worker execution"
            )
        self.session = session
        self.capability_registry = capability_registry

    def build(
        self,
        operation: OperationRunRecord,
        attempt_id: UUID,
    ) -> OperationRequest:
        workflow = self.session.scalar(
            select(WorkflowRunRecord).where(
                WorkflowRunRecord.id == operation.workflow_run_id,
                WorkflowRunRecord.project_id == operation.project_id,
            )
        )
        if workflow is None:
            raise DagWorkerError("workflow run is unavailable")
        template = dict(operation.request_payload)
        binding = template.get("operation_request_binding")
        if not isinstance(binding, Mapping):
            binding = {}
        node_kind = str(template.get("workflow_node_kind") or "capability")
        if node_kind == "capability":
            registration = self.capability_registry.resolve(
                op_type=operation.op_type,
                op_version=SchemaRevision.model_validate(
                    template["op_version"]
                ),
                spec_digest=str(template["operation_spec_digest"]),
                implementation_digest=str(
                    template["implementation_digest"]
                ),
            )
            op_version = registration.spec.op_version
            spec_digest = registration.spec.spec_digest
            implementation_digest = (
                registration.implementation_manifest.implementation_digest
            )
            input_schema_version = registration.spec.input_schema_version
            output_schema_version = registration.spec.output_schema_version
        else:
            op_version = SchemaRevision.model_validate(
                template.get("op_version", {"major": 1, "minor": 0})
            )
            input_schema_version = SchemaRevision()
            output_schema_version = SchemaRevision()
            spec_digest = _control_digest(operation.op_type, "spec")
            implementation_digest = _control_digest(
                operation.op_type, "implementation"
            )

        artifacts = self._input_artifacts(operation, workflow)
        structured_inputs = dict(template.get("structured_inputs") or {})
        if not template.get("input_node_keys"):
            root_inputs = workflow.input_payload.get("structured_inputs")
            if isinstance(root_inputs, Mapping):
                structured_inputs = {
                    **dict(root_inputs),
                    **structured_inputs,
                }
            else:
                structured_inputs = {
                    **{
                        key: value
                        for key, value in workflow.input_payload.items()
                        if key not in _RESERVED_WORKFLOW_INPUTS
                    },
                    **structured_inputs,
                }
        subject_ref = self._subject_ref(
            workflow=workflow,
            operation=operation,
            binding=binding,
        )
        policy_snapshot_id = UUID(
            str(
                binding.get("policy_snapshot_id")
                or uuid5(
                    _POLICY_NAMESPACE,
                    f"{workflow.id}:{workflow.policy_digest}",
                )
            )
        )
        operation_input_digest = build_operation_input_digest(
            project_id=operation.project_id,
            op_type=operation.op_type,
            op_version=op_version,
            input_schema_version=input_schema_version,
            subject_ref=subject_ref,
            input_artifact_refs=artifacts,
            structured_inputs=structured_inputs,
            parameter_snapshot=dict(
                template.get("parameter_snapshot") or {}
            ),
            policy_snapshot_id=policy_snapshot_id,
            policy_snapshot_digest=workflow.policy_digest,
        )
        node_run_id = UUID(
            str(
                binding.get("node_run_id")
                or uuid5(_NODE_NAMESPACE, str(operation.id))
            )
        )
        return OperationRequest(
            project_id=operation.project_id,
            workflow_run_id=operation.workflow_run_id,
            node_run_id=node_run_id,
            operation_run_id=operation.id,
            operation_attempt_id=attempt_id,
            op_type=operation.op_type,
            op_version=op_version,
            operation_spec_digest=spec_digest,
            implementation_digest=implementation_digest,
            input_schema_version=input_schema_version,
            required_output_schema_version=output_schema_version,
            subject_ref=subject_ref,
            input_artifact_refs=artifacts,
            structured_inputs=structured_inputs,
            parameter_snapshot=dict(
                template.get("parameter_snapshot") or {}
            ),
            policy_snapshot_id=policy_snapshot_id,
            policy_snapshot_digest=workflow.policy_digest,
            command_idempotency_key=operation.command_idempotency_key,
            operation_input_digest=operation_input_digest,
            trace_id=workflow.trace_id,
            parent_operation_run_id=operation.parent_operation_run_id,
        )

    def _subject_ref(
        self,
        *,
        workflow: WorkflowRunRecord,
        operation: OperationRunRecord,
        binding: Mapping[str, Any],
    ) -> EntityRef:
        raw = binding.get("subject_ref") or workflow.input_payload.get(
            "subject_ref"
        )
        if raw is not None:
            subject = EntityRef.model_validate(raw)
            if subject.entity_id == operation.id:
                raise DagWorkerError(
                    "subject identity cannot alias operation identity"
                )
            return subject
        domain = (
            EntityDomain.FACTORY
            if operation.op_type.startswith(
                (
                    "book.",
                    "chapter.",
                    "bible.",
                    "asset.",
                    "storyboard.",
                    "prompt.",
                    "keyframe.",
                    "video.",
                    "speech.",
                    "subtitle.",
                    "audio.mix",
                    "final.",
                )
            )
            else EntityDomain.CREATIVE
        )
        return EntityRef(
            domain=domain,
            entity_type="workflow",
            entity_id=workflow.id,
        )

    def _input_artifacts(
        self,
        operation: OperationRunRecord,
        workflow: WorkflowRunRecord,
    ) -> tuple[AtomicArtifactRef, ...]:
        raw_refs = workflow.input_payload.get("input_artifact_refs", ())
        if not isinstance(raw_refs, (list, tuple)):
            raise DagWorkerError(
                "workflow input_artifact_refs must be an array"
            )
        try:
            workflow_refs = tuple(
                AtomicArtifactRef.model_validate(item) for item in raw_refs
            )
        except ValueError as exc:
            raise DagWorkerError(
                "workflow input_artifact_refs are invalid"
            ) from exc
        if any(ref.project_id != operation.project_id for ref in workflow_refs):
            raise DagWorkerError(
                "workflow input artifact belongs to a different project"
            )
        source_refs: tuple[AtomicArtifactRef, ...] = ()
        reference_authority_refs: tuple[AtomicArtifactRef, ...] = ()
        h3_reference_input = False
        if operation.op_type == "character_reference.generate":
            h3_reference_input = (
                workflow.input_payload.get("schema_version")
                == "factory.shidu-h3-submission.v1"
            )
            if h3_reference_input:
                structured = workflow.input_payload.get("structured_inputs")
                if not isinstance(structured, Mapping):
                    raise DagWorkerError(
                        "H3 structured visual identity authority is missing"
                    )
                mode = structured.get("visual_identity_mode")
                if mode not in {
                    "historical_image_grounded",
                    "script_synthesized",
                }:
                    raise DagWorkerError("H3 visual identity mode is invalid")
                base_roles = (
                    "h3.project.authority",
                    "h3.trial-script.authority",
                    "h3.evidence-pack.authority",
                    "h3.visual-identity-resolution.authority",
                )
                expected_roles = (
                    (*base_roles, "character.source.image")
                    if mode == "historical_image_grounded"
                    else base_roles
                )
                roles = tuple(ref.logical_role for ref in workflow_refs)
                if roles != expected_roles:
                    raise DagWorkerError(
                        "H3 visual identity mode and artifact role order mismatch"
                    )
                projected_roles = structured.get("input_role_order")
                projected_refs = structured.get("input_artifact_refs")
                ref_payloads = [
                    ref.model_dump(mode="json") for ref in workflow_refs
                ]
                if (
                    not isinstance(projected_roles, (list, tuple))
                    or tuple(projected_roles) != expected_roles
                    or projected_refs != ref_payloads
                ):
                    raise DagWorkerError(
                        "H3 structured artifact authority projection mismatch"
                    )
                resolution_id = structured.get(
                    "visual_identity_resolution_id"
                )
                resolution_digest = structured.get(
                    "visual_identity_resolution_digest"
                )
                input_digest = structured.get("input_authority_digest")
                try:
                    parsed_resolution_id = UUID(str(resolution_id))
                except (TypeError, ValueError):
                    raise DagWorkerError(
                        "H3 visual identity resolution id is invalid"
                    ) from None
                if (
                    str(parsed_resolution_id) != resolution_id
                    or not isinstance(resolution_digest, str)
                    or len(resolution_digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in resolution_digest
                    )
                    or not isinstance(input_digest, str)
                ):
                    raise DagWorkerError(
                        "H3 visual identity resolution authority is invalid"
                    )
                expected_digest = canonical_json_digest(
                    {
                        "schema_version": (
                            "factory.shidu-h3-input-authority.v1"
                        ),
                        "project_id": str(operation.project_id),
                        "role_order": list(expected_roles),
                        "visual_identity_mode": mode,
                        "visual_identity_resolution_id": resolution_id,
                        "visual_identity_resolution_digest": (
                            resolution_digest
                        ),
                        "artifact_refs": ref_payloads,
                    }
                )
                if input_digest != expected_digest:
                    raise DagWorkerError(
                        "H3 input artifact authority digest mismatch"
                    )
                for ref in workflow_refs[:4]:
                    if ref.mime_type != "application/json":
                        raise DagWorkerError(
                            "H3 JSON authority artifact MIME type is invalid"
                        )
                source_refs = tuple(
                    ref
                    for ref in workflow_refs
                    if ref.logical_role == "character.source.image"
                )
                if mode == "historical_image_grounded":
                    if (
                        len(source_refs) != 1
                        or source_refs[0].mime_type
                        not in {"image/png", "image/jpeg", "image/webp"}
                    ):
                        raise DagWorkerError(
                            "historical H3 reference requires one source image"
                        )
                elif source_refs:
                    raise DagWorkerError(
                        "script-synthesized H3 reference forbids source image"
                    )
                reference_authority_refs = (
                    workflow_refs[3],
                    *source_refs,
                )
            else:
                source_refs = tuple(
                    ref
                    for ref in workflow_refs
                    if ref.logical_role == "character.source.image"
                )
                if len(source_refs) != 1:
                    raise DagWorkerError(
                        "reference generation requires one character source image"
                    )
                if source_refs[0].mime_type not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                }:
                    raise DagWorkerError(
                        "character source image MIME type is unsupported"
                    )
                reference_authority_refs = source_refs
        upstream_ids = tuple(
            self.session.scalars(
                select(
                    WorkflowRunEdgeRecord.upstream_operation_run_id
                ).where(
                    WorkflowRunEdgeRecord.project_id
                    == operation.project_id,
                    WorkflowRunEdgeRecord.workflow_run_id
                    == operation.workflow_run_id,
                    WorkflowRunEdgeRecord.downstream_operation_run_id
                    == operation.id,
                )
            )
        )
        artifacts: list[AtomicArtifactRef] = []
        if upstream_ids:
            upstream_operations = {
                item.id: item
                for item in self.session.scalars(
                    select(OperationRunRecord).where(
                        OperationRunRecord.id.in_(upstream_ids),
                        OperationRunRecord.project_id
                        == operation.project_id,
                        OperationRunRecord.status == "SUCCEEDED",
                    )
                )
            }
            accepted = {
                key: item.accepted_attempt_id
                for key, item in upstream_operations.items()
            }
            if len(accepted) != len(upstream_ids) or any(
                value is None for value in accepted.values()
            ):
                raise DagWorkerError(
                    "upstream operation has no accepted artifact authority"
                )
            for upstream_id in upstream_ids:
                upstream = upstream_operations[upstream_id]
                node_kind = str(
                    upstream.request_payload.get("workflow_node_kind")
                    or "capability"
                )
                if (
                    upstream.op_type == "h3.attempt.select"
                    and operation.op_type == "final.assemble"
                ):
                    rows = [
                        self._selected_h3_sequence_artifact(
                            operation=operation,
                            upstream=upstream,
                            workflow=workflow,
                        )
                    ]
                elif upstream.op_type == "h3.attempt.select":
                    rows = []
                elif node_kind == "quality_gate":
                    rows = [
                        self._selected_gate_artifact(
                            upstream=upstream,
                            workflow=workflow,
                        )
                    ]
                else:
                    rows = self.session.scalars(
                        select(ArtifactRecordRow)
                        .where(
                            ArtifactRecordRow.project_id
                            == operation.project_id,
                            ArtifactRecordRow.operation_run_id
                            == upstream_id,
                            ArtifactRecordRow.operation_attempt_id
                            == accepted[upstream_id],
                            ArtifactRecordRow.status == "COMMITTED",
                        )
                        .order_by(
                            ArtifactRecordRow.logical_role,
                            ArtifactRecordRow.id,
                        )
                    ).all()
                artifacts.extend(_atomic_ref(row) for row in rows)
            if reference_authority_refs:
                artifacts.extend(reference_authority_refs)
        else:
            if h3_reference_input:
                artifacts.extend(workflow_refs)
            else:
                artifacts.extend(reference_authority_refs or workflow_refs)
        unique: list[AtomicArtifactRef] = []
        by_id: dict[UUID, AtomicArtifactRef] = {}
        for artifact in artifacts:
            prior = by_id.get(artifact.artifact_id)
            if prior is not None:
                if prior != artifact:
                    raise DagWorkerError(
                        "duplicate artifact identity has conflicting metadata"
                    )
                continue
            by_id[artifact.artifact_id] = artifact
            unique.append(artifact)
        if (
            operation.op_type == "final.assemble"
            and unique
            and all(
                artifact.logical_role.startswith("h3.sequence.")
                for artifact in unique
            )
        ):
            # Dependency rows have no stable database return order.  H3 roles
            # carry a zero-padded sequence ordinal, so this also freezes the
            # input digest and the physical clip assembly order.
            unique.sort(key=lambda artifact: artifact.logical_role)
        return tuple(unique)

    def _selected_gate_artifact(
        self,
        *,
        upstream: OperationRunRecord,
        workflow: WorkflowRunRecord,
    ) -> ArtifactRecordRow:
        gate_key = str(
            upstream.request_payload.get("gate_key") or upstream.node_key
        )
        head = self.session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.project_id == upstream.project_id,
                SelectionHeadRecord.workflow_run_id == workflow.id,
                SelectionHeadRecord.selection_key == gate_key,
                SelectionHeadRecord.status == "SEALED",
                SelectionHeadRecord.current_revision.is_not(None),
            )
        )
        if head is None or head.current_revision is None:
            raise DagWorkerError(
                "quality gate has no sealed selection authority"
            )
        revision = self.session.scalar(
            select(SelectionRevisionRecord).where(
                SelectionRevisionRecord.selection_head_id == head.id,
                SelectionRevisionRecord.project_id == upstream.project_id,
                SelectionRevisionRecord.revision == head.current_revision,
                SelectionRevisionRecord.decision.in_(
                    (
                        "SELECTED",
                        "DEGRADED_ACCEPTED",
                        "HUMAN_SELECTED",
                    )
                ),
            )
        )
        if revision is None:
            raise DagWorkerError(
                "quality gate selection revision is unavailable"
            )
        artifact = self.session.scalar(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.id == revision.artifact_id,
                ArtifactRecordRow.project_id == upstream.project_id,
                ArtifactRecordRow.operation_run_id
                == revision.selected_operation_run_id,
                ArtifactRecordRow.operation_attempt_id
                == revision.selected_attempt_id,
                ArtifactRecordRow.content_digest
                == revision.artifact_digest,
                ArtifactRecordRow.status == "COMMITTED",
            )
        )
        if artifact is None:
            raise DagWorkerError(
                "quality gate selected artifact is unavailable"
            )
        return artifact

    def _selected_h3_sequence_artifact(
        self,
        *,
        operation: OperationRunRecord,
        upstream: OperationRunRecord,
        workflow: WorkflowRunRecord,
    ) -> ArtifactRecordRow:
        """Resolve one sealed H3 selection to its exact committed MP4."""
        if (
            upstream.project_id != operation.project_id
            or upstream.project_id != workflow.project_id
            or upstream.workflow_run_id != operation.workflow_run_id
            or upstream.workflow_run_id != workflow.id
            or upstream.status != "SUCCEEDED"
            or upstream.accepted_attempt_id is None
        ):
            raise DagWorkerError(
                "H3 selection is outside the downstream workflow authority"
            )
        if not isinstance(upstream.request_payload, Mapping):
            raise DagWorkerError("H3 selection request authority is invalid")
        structured_inputs = upstream.request_payload.get("structured_inputs")
        if not isinstance(structured_inputs, Mapping):
            raise DagWorkerError("H3 selection sequence ordinal is unavailable")
        ordinal = structured_inputs.get("sequence_ordinal")
        if type(ordinal) is not int or ordinal <= 0:
            raise DagWorkerError("H3 selection sequence ordinal is invalid")
        if upstream.node_key != f"sequence.{ordinal:03d}.select":
            raise DagWorkerError(
                "H3 selection node does not match the sequence ordinal"
            )
        selection_key = f"h3.sequence.{ordinal:03d}"

        head = self.session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.project_id == operation.project_id,
                SelectionHeadRecord.workflow_run_id == workflow.id,
                SelectionHeadRecord.selection_key == selection_key,
                SelectionHeadRecord.status == "SEALED",
                SelectionHeadRecord.current_revision.is_not(None),
            )
        )
        if (
            head is None
            or head.project_id != operation.project_id
            or head.workflow_run_id != workflow.id
            or head.selection_key != selection_key
            or head.status != "SEALED"
            or type(head.current_revision) is not int
            or head.current_revision <= 0
        ):
            raise DagWorkerError(
                "H3 sequence has no sealed selection authority"
            )

        sequence = self.session.scalar(
            select(H3SequenceRevisionRecord).where(
                H3SequenceRevisionRecord.project_id == operation.project_id,
                H3SequenceRevisionRecord.selection_head_id == head.id,
                H3SequenceRevisionRecord.ordinal == ordinal,
            )
        )
        if (
            sequence is None
            or sequence.project_id != operation.project_id
            or sequence.selection_head_id != head.id
            or sequence.ordinal != ordinal
        ):
            raise DagWorkerError(
                "H3 sequence revision does not match the sealed selection"
            )

        revision = self.session.scalar(
            select(SelectionRevisionRecord).where(
                SelectionRevisionRecord.selection_head_id == head.id,
                SelectionRevisionRecord.project_id == operation.project_id,
                SelectionRevisionRecord.revision == head.current_revision,
                SelectionRevisionRecord.decision.in_(
                    ("SELECTED", "DEGRADED_ACCEPTED")
                ),
            )
        )
        if (
            revision is None
            or revision.project_id != operation.project_id
            or revision.selection_head_id != head.id
            or revision.revision != head.current_revision
            or revision.decision not in {"SELECTED", "DEGRADED_ACCEPTED"}
            or revision.selected_operation_run_id is None
            or revision.selected_attempt_id is None
            or revision.artifact_id is None
        ):
            raise DagWorkerError(
                "H3 sequence selection revision is unavailable"
            )
        revision_payload = getattr(revision, "payload", None)
        if not isinstance(revision_payload, Mapping):
            raise DagWorkerError("H3 sequence selection payload is required")
        payload = dict(revision_payload)
        payload_digest = canonical_json_digest(payload)
        if getattr(revision, "payload_digest", None) != payload_digest:
            raise DagWorkerError("H3 sequence selection payload digest mismatch")
        try:
            selection = H3AttemptSelectionV1.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DagWorkerError(
                "H3 sequence selection payload is invalid"
            ) from exc
        if selection.sequence_id != sequence.sequence_id:
            raise DagWorkerError(
                "H3 selection does not match the sequence revision"
            )
        expected_decision = (
            "SELECTED"
            if selection.selected_cleanly
            else "DEGRADED_ACCEPTED"
        )
        if revision.decision != expected_decision:
            raise DagWorkerError(
                "H3 selection decision does not match its payload"
            )
        selected_attempt_ordinal = selection.selected_attempt_ordinal

        runtime_attempt = self.session.scalar(
            select(H3RuntimeAttemptRecord).where(
                H3RuntimeAttemptRecord.project_id == operation.project_id,
                H3RuntimeAttemptRecord.sequence_revision_id == sequence.id,
                H3RuntimeAttemptRecord.attempt_ordinal
                == selected_attempt_ordinal,
                H3RuntimeAttemptRecord.operation_run_id
                == revision.selected_operation_run_id,
                H3RuntimeAttemptRecord.operation_attempt_id
                == revision.selected_attempt_id,
                H3RuntimeAttemptRecord.artifact_id == revision.artifact_id,
                H3RuntimeAttemptRecord.artifact_digest
                == revision.artifact_digest,
                H3RuntimeAttemptRecord.prompt_digest
                == sequence.prompt_digest,
                H3RuntimeAttemptRecord.workflow_digest
                == sequence.workflow_digest,
            )
        )
        if (
            runtime_attempt is None
            or runtime_attempt.project_id != operation.project_id
            or runtime_attempt.sequence_revision_id != sequence.id
            or runtime_attempt.attempt_ordinal != selected_attempt_ordinal
            or runtime_attempt.operation_run_id
            != revision.selected_operation_run_id
            or runtime_attempt.operation_attempt_id
            != revision.selected_attempt_id
            or runtime_attempt.artifact_id != revision.artifact_id
            or runtime_attempt.artifact_digest != revision.artifact_digest
            or runtime_attempt.prompt_digest != sequence.prompt_digest
            or runtime_attempt.workflow_digest != sequence.workflow_digest
        ):
            raise DagWorkerError(
                "H3 selected runtime attempt lineage is unavailable"
            )

        execute = self.session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.id
                == revision.selected_operation_run_id,
                OperationRunRecord.project_id == operation.project_id,
                OperationRunRecord.workflow_run_id == workflow.id,
                OperationRunRecord.op_type == "h3.sequence.execute",
                OperationRunRecord.status == "SUCCEEDED",
                OperationRunRecord.accepted_attempt_id
                == revision.selected_attempt_id,
            )
        )
        execute_inputs = (
            execute.request_payload.get("structured_inputs")
            if execute is not None
            and isinstance(execute.request_payload, Mapping)
            else None
        )
        if (
            execute is None
            or execute.id != revision.selected_operation_run_id
            or execute.project_id != operation.project_id
            or execute.workflow_run_id != workflow.id
            or execute.op_type != "h3.sequence.execute"
            or execute.status != "SUCCEEDED"
            or execute.accepted_attempt_id != revision.selected_attempt_id
            or not isinstance(execute_inputs, Mapping)
            or execute_inputs.get("sequence_ordinal") != ordinal
            or type(execute_inputs.get("sequence_ordinal")) is not int
        ):
            raise DagWorkerError(
                "H3 selected producer or sequence ordinal is invalid"
            )

        artifact = self.session.scalar(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.id == revision.artifact_id,
                ArtifactRecordRow.project_id == operation.project_id,
                ArtifactRecordRow.operation_run_id == execute.id,
                ArtifactRecordRow.operation_attempt_id
                == revision.selected_attempt_id,
                ArtifactRecordRow.content_digest
                == revision.artifact_digest,
                ArtifactRecordRow.mime_type == "video/mp4",
                ArtifactRecordRow.status == "COMMITTED",
            )
        )
        expected_role = (
            "h3.sequence."
            f"{ordinal:03d}.attempt.{selected_attempt_ordinal}.video"
        )
        if (
            artifact is None
            or artifact.id != revision.artifact_id
            or artifact.project_id != operation.project_id
            or artifact.operation_run_id != execute.id
            or artifact.operation_attempt_id
            != revision.selected_attempt_id
            or artifact.content_digest != revision.artifact_digest
            or artifact.mime_type != "video/mp4"
            or artifact.status != "COMMITTED"
            or artifact.logical_role != expected_role
        ):
            raise DagWorkerError(
                "H3 selected sequence artifact is unavailable or invalid"
            )
        return artifact


def _atomic_ref(row: ArtifactRecordRow) -> AtomicArtifactRef:
    return AtomicArtifactRef(
        artifact_id=row.id,
        project_id=row.project_id,
        content_digest=row.content_digest,
        mime_type=row.mime_type,
        byte_size=row.byte_size,
        logical_role=row.logical_role,
    )


def _control_digest(op_type: str, identity: str) -> str:
    return canonical_json_digest(
        {
            "authority": "creative_hub",
            "kind": "control_node",
            "op_type": op_type,
            "identity": identity,
        }
    )


def default_control_dispatcher(
    *,
    lease: DagLease,
    operation: OperationRunRecord,
    request_payload: Mapping[str, Any],
) -> ControlOutcome:
    del lease, request_payload
    kind = str(operation.request_payload.get("workflow_node_kind") or "")
    if kind == "quality_gate":
        return ControlOutcome(
            ControlAction.WAITING_HUMAN,
            reason="quality_gate_requires_durable_evaluation",
        )
    if kind == "delivery":
        return ControlOutcome(
            ControlAction.SUCCEEDED,
            metrics={"delivery_authority": "creative_hub"},
        )
    return ControlOutcome(
        ControlAction.FAILED,
        reason="unsupported_control_node",
        error={"error_code": "unsupported_control_node"},
    )


class DurableQualityControlDispatcher:
    """Execute a frozen quality policy through registered atomic evaluators."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        capability_registry: CapabilityRegistry | None = None,
        artifact_gateway_factory: ArtifactGatewayFactory | None = None,
        context_factory: ContextFactory | None = None,
        scheduler_factory: (
            Callable[[Session], DurableDagScheduler] | None
        ) = None,
        actor_id: str = "creative-hub-quality-worker",
    ) -> None:
        if (
            capability_registry is not None
            and not capability_registry.is_frozen
        ):
            raise ValueError(
                "quality evaluator capability registry must be frozen"
            )
        self.session_factory = session_factory
        self.capability_registry = capability_registry
        self.artifact_gateway_factory = artifact_gateway_factory
        self.context_factory = context_factory
        self.scheduler_factory = scheduler_factory
        self.actor_id = actor_id

    def __call__(
        self,
        *,
        lease: DagLease,
        operation: OperationRunRecord,
        request_payload: Mapping[str, Any],
    ) -> ControlOutcome:
        kind = str(
            operation.request_payload.get("workflow_node_kind") or ""
        )
        if kind == "delivery":
            try:
                with self.session_factory() as session, session.begin():
                    current = session.get(OperationRunRecord, operation.id)
                    if current is None:
                        raise DagWorkerError("delivery operation is unavailable")
                    workflow_key = session.scalar(
                        select(WorkflowDefinitionRecord.workflow_key)
                        .join(
                            WorkflowRunRecord,
                            WorkflowRunRecord.workflow_definition_id
                            == WorkflowDefinitionRecord.id,
                        )
                        .where(
                            WorkflowRunRecord.id == current.workflow_run_id,
                            WorkflowRunRecord.project_id == current.project_id,
                            WorkflowDefinitionRecord.project_id
                            == current.project_id,
                        )
                    )
                    if workflow_key is None:
                        raise DagWorkerError(
                            "delivery workflow identity is unavailable"
                        )
                    if workflow_key == "factory.shidu-h3.v1":
                        record, artifact = _record_h3_durable_delivery(
                            session,
                            operation=current,
                            actor_id=self.actor_id,
                        )
                    elif workflow_key.startswith("factory.shidu-trial."):
                        record, artifact = _record_durable_delivery(
                            session,
                            operation=current,
                            actor_id=self.actor_id,
                        )
                    else:
                        return ControlOutcome(
                            ControlAction.SUCCEEDED,
                            metrics={
                                "delivery_authority": "creative_hub"
                            },
                        )
                return ControlOutcome(
                    ControlAction.SUCCEEDED,
                    metrics={
                        "delivery_authority": "creative_hub",
                        "delivery_revision_id": str(record.id),
                        "delivery_revision": record.revision,
                        "final_artifact_id": str(artifact.id),
                        "final_artifact_digest": artifact.content_digest,
                    },
                )
            except DagWorkerError as exc:
                return ControlOutcome(
                    ControlAction.FAILED,
                    reason="delivery_gate_authority_incomplete",
                    error={
                        "error_code": "delivery_gate_authority_incomplete",
                        "operator_detail": str(exc),
                    },
                )
        if kind != "quality_gate":
            return ControlOutcome(
                ControlAction.FAILED,
                reason="unsupported_control_node",
                error={"error_code": "unsupported_control_node"},
            )

        from shared_contracts import stable_json_sha256

        from .qc_repository import (
            DatabaseCertificationAuthority,
            PostgresSelectionSealer,
            QualityRepository,
        )
        from .quality import (
            ArtifactBinding,
            CandidateVersion,
            EvidencePackBinding,
            GateBudget,
            GateExhaustionPolicy,
            GateOutcomeKind,
            GatePolicySnapshot,
            HumanReviewMode,
            MachineJudgment,
            QCEvaluation,
            RepairProposal,
        )
        from .workflow_runtime import DurableQualityGate

        stage = _quality_stage(operation.op_type)
        gate_key = str(
            operation.request_payload.get("gate_key") or operation.node_key
        )
        with self.session_factory() as session, session.begin():
            workflow = session.scalar(
                select(WorkflowRunRecord).where(
                    WorkflowRunRecord.id == lease.workflow_run_id,
                    WorkflowRunRecord.project_id == lease.project_id,
                )
            )
            if workflow is None:
                return ControlOutcome(
                    ControlAction.FAILED,
                    reason="quality_policy_unavailable",
                    error={"error_code": "quality_policy_unavailable"},
                )
            runtime = self._runtime_policy(
                workflow=workflow,
                stage=stage,
                gate_key=gate_key,
            )
            if runtime is None:
                return ControlOutcome(
                    ControlAction.FAILED,
                    reason="quality_policy_unavailable",
                    error={"error_code": "quality_policy_unavailable"},
                )
            candidates, outcomes = self._gate_history(
                session=session,
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                gate_key=gate_key,
            )
            prior = outcomes[-1] if outcomes else None
            if prior is not None:
                if prior.kind in {
                    GateOutcomeKind.SELECTED,
                    GateOutcomeKind.DEGRADED_ACCEPTED,
                }:
                    return ControlOutcome(
                        ControlAction.SUCCEEDED,
                        metrics={"gate_outcome": prior.kind.value},
                    )
                if prior.kind is GateOutcomeKind.WAITING_HUMAN:
                    return ControlOutcome(
                        ControlAction.FAILED,
                        reason="quality_gate_human_review_disabled",
                        error={
                            "error_code": "quality_human_review_disabled"
                        },
                    )
                if (
                    prior.kind
                    is GateOutcomeKind.BLOCKED_UNCERTIFIED
                ):
                    return ControlOutcome(
                        ControlAction.FAILED,
                        reason=prior.reason,
                        error={
                            "error_code": "quality_gate_blocked"
                        },
                    )

            artifact = _quality_artifact(session, operation)
            known_candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.artifact.artifact_id == artifact.id
                ),
                None,
            )
            if (
                known_candidate is not None
                and prior is not None
                and prior.kind is GateOutcomeKind.REWORK_PLANNED
                and prior.repair_proposal is not None
            ):
                self._materialize_repair(
                    session=session,
                    operation=operation,
                    parent_artifact=artifact,
                    proposal=prior.repair_proposal,
                    ordinal=len(candidates) + 1,
                )
                return ControlOutcome(
                    ControlAction.SUCCEEDED,
                    metrics={
                        "gate_outcome": prior.kind.value,
                        "repair_plan_id": str(
                            prior.repair_proposal.repair_plan_id
                        ),
                    },
                )

            quality = QualityRepository(session)
            prompt, registration, bundle = self._evaluator_bundle(
                session=session,
                workflow=workflow,
                stage=stage,
                runtime=runtime,
                stable_json_sha256=stable_json_sha256,
            )
            head = SelectionRepository(session).create_head(
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                selection_key=gate_key,
            ).value
            binding = ArtifactBinding(
                project_id=artifact.project_id,
                artifact_id=artifact.id,
                content_digest=artifact.content_digest,
                operation_run_id=artifact.operation_run_id,
                operation_attempt_id=artifact.operation_attempt_id,
            )
            producer = session.get(
                OperationRunRecord,
                artifact.operation_run_id,
            )
            evaluated = self._evaluate(
                lease=lease,
                operation=operation,
                request_payload=request_payload,
                workflow=workflow,
                artifact=artifact,
                stage=stage,
                gate_key=gate_key,
                ordinal=len(candidates) + 1,
                runtime=runtime,
                registration=registration,
                prompt_text=prompt.prompt_text,
                responsible_node_id=(
                    producer.node_key
                    if producer is not None
                    else operation.node_key
                ),
            )
            evidence_payload = {
                "gate_key": gate_key,
                "artifact_digest": artifact.content_digest,
                "evaluator_result": evaluated.model_dump(mode="json"),
            }
            evaluation = QCEvaluation(
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                stage=stage,
                gate_key=gate_key,
                artifact=binding,
                evidence_pack=EvidencePackBinding(
                    project_id=lease.project_id,
                    evidence_pack_id=uuid5(
                        _CONTROL_NAMESPACE,
                        (
                            f"evidence:{operation.id}:"
                            f"{artifact.id}:{len(candidates) + 1}"
                        ),
                    ),
                    content_digest=stable_json_sha256(evidence_payload),
                    artifact_ids=(artifact.id,),
                ),
                expected_selection_version=head.state_version,
                evaluator=bundle,
                judgment=evaluated.judgment,
                quality_score=evaluated.quality_score,
                confidence=evaluated.confidence,
                defects=evaluated.defects,
                recommended_actions=evaluated.recommended_actions,
                repair_result=evaluated.repair_result,
                h3_qc=evaluated.h3_qc,
            )
            candidate = CandidateVersion(
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                stage=stage,
                gate_key=gate_key,
                ordinal=len(candidates) + 1,
                artifact=binding,
                evaluation=evaluation,
                generation_usage=evaluated.generation_usage,
            )
            policy = GatePolicySnapshot(
                policy_snapshot_id=uuid5(
                    _POLICY_NAMESPACE,
                    f"{lease.workflow_run_id}:{gate_key}",
                ),
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                stage=stage,
                gate_key=gate_key,
                review_mode=HumanReviewMode(runtime["review_mode"]),
                exhaustion_policy=GateExhaustionPolicy(
                    runtime["exhaustion_policy"]
                ),
                budget=GateBudget(
                    max_repair_count=runtime["max_repairs"],
                    max_cost_micros=runtime["max_cost_micros"],
                    max_gpu_seconds=runtime["max_gpu_seconds"],
                    max_wall_seconds=runtime["max_wall_seconds"],
                ),
                ranking_revision=runtime["ranking_revision"],
                ranking_weights=runtime["ranking_weights"],
                prompt_revision_id=prompt.id,
                rubric_revision_id=bundle.rubric_revision_id,
                evaluator_bundle_digest=bundle.bundle_digest,
                created_at=workflow.created_at,
            )
            proposal = None
            if (
                evaluated.judgment is MachineJudgment.FAIL
                and evaluated.repair_directive is not None
                and self.scheduler_factory is not None
                and self.capability_registry is not None
            ):
                parent = session.get(
                    OperationRunRecord,
                    artifact.operation_run_id,
                )
                if parent is not None:
                    proposal = RepairProposal(
                        repair_plan_id=uuid5(
                            _CONTROL_NAMESPACE,
                            (
                                f"repair:{operation.id}:"
                                f"{candidate.candidate_id}"
                            ),
                        ),
                        project_id=lease.project_id,
                        workflow_run_id=lease.workflow_run_id,
                        stage=stage,
                        gate_key=gate_key,
                        parent_candidate_id=candidate.candidate_id,
                        target_node_ids=(parent.node_key,),
                        target_node_stages={
                            parent.node_key: stage
                        },
                        changed_parameters=(
                            evaluated.repair_directive
                            .changed_parameters
                        ),
                        estimated_usage=(
                            evaluated.repair_directive
                            .estimated_usage
                        ),
                    )
            submission = DurableQualityGate(
                policy=policy,
                repository=quality,
                certifications=DatabaseCertificationAuthority(session),
                selection_sealer=PostgresSelectionSealer(
                    session=session,
                    project_id=lease.project_id,
                    selection_head_id=head.id,
                    actor_id=self.actor_id,
                    command_prefix=f"dag-worker:{operation.id}",
                ),
                selection_head_id=head.id,
                gate_key=gate_key,
                review_sink=None,
                created_by_actor=self.actor_id,
                restored_candidates=candidates,
                restored_outcomes=outcomes,
            ).submit(
                candidate=candidate,
                proposed_repair=proposal,
            )
            if (
                submission.outcome.kind
                is GateOutcomeKind.REWORK_PLANNED
            ):
                assert submission.outcome.repair_proposal is not None
                self._materialize_repair(
                    session=session,
                    operation=operation,
                    parent_artifact=artifact,
                    proposal=submission.outcome.repair_proposal,
                    ordinal=candidate.ordinal + 1,
                )
                return ControlOutcome(
                    ControlAction.SUCCEEDED,
                    metrics={
                        "gate_outcome": submission.outcome.kind.value,
                        "repair_plan_id": str(
                            submission.outcome
                            .repair_proposal.repair_plan_id
                        ),
                    },
            )
            if submission.outcome.kind in {
                GateOutcomeKind.SELECTED,
                GateOutcomeKind.DEGRADED_ACCEPTED,
            }:
                return ControlOutcome(
                    ControlAction.SUCCEEDED,
                    metrics={
                        "gate_outcome": submission.outcome.kind.value
                    },
                )
            if (
                submission.outcome.kind
                is GateOutcomeKind.WAITING_HUMAN
            ):
                return ControlOutcome(
                    ControlAction.FAILED,
                    reason="quality_gate_human_review_disabled",
                    error={
                        "error_code": "quality_human_review_disabled"
                    },
                )
            return ControlOutcome(
                ControlAction.FAILED,
                reason=submission.outcome.reason,
                error={
                    "error_code": (
                        f"quality_{submission.outcome.kind.value.lower()}"
                    )
                },
            )

    @staticmethod
    def _runtime_policy(*, workflow, stage, gate_key):
        raw = workflow.policy_snapshot.get("gate_policies")
        if not isinstance(raw, (list, tuple)):
            return None
        stage_items = [
            item
            for item in raw
            if isinstance(item, Mapping)
            and str(item.get("stage") or "") == stage.value
        ]
        exact = [
            item
            for item in stage_items
            if item.get("gate_key") == gate_key
        ]
        candidates = exact or [
            item for item in stage_items if item.get("gate_key") is None
        ]
        if len(candidates) != 1:
            return None
        item = dict(candidates[0])
        if item.get("machine_qc_required") is not True:
            return None
        budget = item.get("budget")
        budget = dict(budget) if isinstance(budget, Mapping) else {}
        max_repairs = item.get("max_repairs")
        budget_max_repairs = budget.get("max_repair_count")
        if (
            not isinstance(max_repairs, int)
            or isinstance(max_repairs, bool)
            or not 0 <= max_repairs <= 20
            or not isinstance(budget_max_repairs, int)
            or isinstance(budget_max_repairs, bool)
            or budget_max_repairs != max_repairs
        ):
            return None
        try:
            review_mode = str(item["review_mode"])
            exhaustion = str(item["exhaustion_policy"])
            from .quality import (
                GateExhaustionPolicy,
                HumanReviewMode,
            )

            HumanReviewMode(review_mode)
            GateExhaustionPolicy(exhaustion)
        except (KeyError, ValueError):
            return None
        max_cost_micros = budget.get("max_cost_micros")
        max_gpu_seconds = budget.get("max_gpu_seconds")
        max_wall_seconds = budget.get("max_wall_seconds")
        ranking_revision = item.get("ranking_revision")
        raw_weights = item.get("ranking_weights")
        evaluator = item.get("evaluator")
        if (
            isinstance(max_cost_micros, bool)
            or not isinstance(max_cost_micros, int)
            or isinstance(max_gpu_seconds, bool)
            or not isinstance(max_gpu_seconds, (int, float))
            or isinstance(max_wall_seconds, bool)
            or not isinstance(max_wall_seconds, (int, float))
            or not isinstance(ranking_revision, str)
            or not ranking_revision.strip()
            or not isinstance(raw_weights, Mapping)
            or not raw_weights
            or not isinstance(evaluator, Mapping)
            or not evaluator
        ):
            return None
        ranking_weights = dict(raw_weights)
        if (
            max_cost_micros < 0
            or max_gpu_seconds < 0
            or max_wall_seconds < 0
            or not math.isfinite(float(max_gpu_seconds))
            or not math.isfinite(float(max_wall_seconds))
            or not ranking_weights
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                for value in ranking_weights.values()
            )
            or not any(float(value) > 0 for value in ranking_weights.values())
            or any(
                not isinstance(evaluator.get(key), str)
                or not str(evaluator.get(key)).strip()
                for key in (
                    "provider",
                    "model_name",
                    "model_version",
                    "prompt_key",
                    "rubric_revision_id",
                    "op_type",
                )
            )
        ):
            return None
        if evaluator.get("strict_frozen") is not True:
            return None
        try:
            UUID(str(evaluator["prompt_revision_id"]))
        except (KeyError, TypeError, ValueError):
            return None
        if any(
            not isinstance(evaluator.get(key), str)
            or len(str(evaluator.get(key))) != 64
            or any(character not in "0123456789abcdef" for character in str(evaluator.get(key)))
            for key in (
                "prompt_digest",
                "rubric_digest",
                "operation_spec_digest",
                "implementation_digest",
            )
        ):
            return None
        return {
            "review_mode": review_mode,
            "exhaustion_policy": exhaustion,
            "max_repairs": max_repairs,
            "max_cost_micros": max_cost_micros,
            "max_gpu_seconds": max_gpu_seconds,
            "max_wall_seconds": max_wall_seconds,
            "ranking_revision": ranking_revision,
            "ranking_weights": ranking_weights,
            "evaluator": dict(evaluator),
        }

    def _evaluator_bundle(
        self,
        *,
        session,
        workflow,
        stage,
        runtime,
        stable_json_sha256,
    ):
        from .qc_repository import QualityRepository
        from .quality import EvaluatorBundle

        evaluator = runtime["evaluator"]
        if evaluator.get("strict_frozen") is not True:
            raise DagWorkerError("quality evaluator policy is not frozen")
        prompt = None
        raw_prompt_id = evaluator.get("prompt_revision_id")
        if raw_prompt_id is not None:
            try:
                prompt_id = UUID(str(raw_prompt_id))
            except ValueError:
                prompt_id = None
            if prompt_id is not None:
                prompt = session.scalar(
                    select(QCPromptRevisionRecord).where(
                        QCPromptRevisionRecord.id == prompt_id,
                        QCPromptRevisionRecord.project_id
                        == workflow.project_id,
                        QCPromptRevisionRecord.stage == stage.value,
                    )
                )
        prompt_key = str(evaluator.get("prompt_key") or "")
        if prompt is None:
            raise DagWorkerError("frozen quality prompt revision is unavailable")
        if prompt.prompt_digest != evaluator.get("prompt_digest"):
            raise DagWorkerError("frozen quality prompt digest mismatch")
        registration = self._evaluator_registration(
            stage=stage,
            evaluator=evaluator,
        )
        if registration is None:
            raise DagWorkerError("frozen quality evaluator capability is unavailable")
        implementation_digest = (
            registration.implementation_manifest.implementation_digest
            if registration is not None
            else stable_json_sha256(
                {
                    "evaluator": evaluator,
                    "status": "capability-unavailable",
                }
            )
        )
        # provider/model/version are the immutable scoring-backend request
        # identity carried into structured_inputs.  The capability manifest
        # separately pins the adapter code/provider boundary; these are not
        # aliases for ``provider_identity`` and therefore must not be rewritten
        # to match it.
        model_name = str(
            evaluator.get("model_name")
            or (
                registration.implementation_manifest.provider_identity
                if registration is not None
                else "unavailable-qc-evaluator"
            )
            or "registered-qc-evaluator"
        )
        model_version = str(
            evaluator.get("model_version")
            or (
                f"{registration.spec.op_version.major}."
                f"{registration.spec.op_version.minor}"
                if registration is not None
                else "1"
            )
        )
        rubric_revision = str(
            evaluator.get("rubric_revision_id")
            or f"{stage.value}-rubric-v1"
        )
        rubric_digest = str(
            evaluator.get("rubric_digest")
            or stable_json_sha256(
                {
                    "stage": stage.value,
                    "rubric_revision_id": rubric_revision,
                }
            )
        )
        bundle = EvaluatorBundle(
            project_id=workflow.project_id,
            stage=stage,
            prompt_revision_id=prompt.id,
            prompt_digest=prompt.prompt_digest,
            rubric_revision_id=rubric_revision,
            rubric_digest=rubric_digest,
            model_name=model_name,
            model_version=model_version,
            implementation_digest=implementation_digest,
        )
        return prompt, registration, bundle

    def _evaluator_registration(self, *, stage, evaluator):
        if self.capability_registry is None:
            return None
        op_type = str(
            evaluator.get("op_type") or f"qc.evaluate.{stage.value}"
        )
        matches = [
            item
            for item in self.capability_registry.registrations.values()
            if item.spec.op_type == op_type
        ]
        expected_spec = evaluator.get("operation_spec_digest")
        expected_implementation = evaluator.get("implementation_digest")
        if expected_spec is not None:
            matches = [
                item
                for item in matches
                if item.spec.spec_digest == expected_spec
            ]
        if expected_implementation is not None:
            matches = [
                item
                for item in matches
                if item.implementation_manifest.implementation_digest
                == expected_implementation
            ]
        return matches[0] if len(matches) == 1 else None

    def _evaluate(
        self,
        *,
        lease,
        operation,
        request_payload,
        workflow,
        artifact,
        stage,
        gate_key,
        ordinal,
        runtime,
        registration,
        prompt_text,
        responsible_node_id,
    ):
        from .quality import QCEvaluatorResult

        if (
            registration is None
            or self.capability_registry is None
            or self.artifact_gateway_factory is None
            or self.context_factory is None
        ):
            raise DagWorkerError(
                "quality evaluator capability is unavailable"
            )
        try:
            base = OperationRequest.model_validate(request_payload)
            structured_inputs = {
                "quality_stage": stage.value,
                "gate_key": gate_key,
                "candidate_ordinal": ordinal,
                "prompt_text": prompt_text,
                "responsible_node_id": responsible_node_id,
                "policy": runtime,
            }
            parameters = dict(runtime["evaluator"].get("parameters") or {})
            policy_snapshot_id = base.policy_snapshot_id
            input_refs = (_atomic_ref(artifact),)
            evaluator_request = OperationRequest(
                project_id=lease.project_id,
                workflow_run_id=lease.workflow_run_id,
                node_run_id=uuid5(
                    _CONTROL_NAMESPACE,
                    f"evaluator:{lease.attempt_id}:{ordinal}",
                ),
                operation_run_id=lease.operation_run_id,
                operation_attempt_id=lease.attempt_id,
                op_type=registration.spec.op_type,
                op_version=registration.spec.op_version,
                operation_spec_digest=registration.spec.spec_digest,
                implementation_digest=(
                    registration.implementation_manifest
                    .implementation_digest
                ),
                input_schema_version=(
                    registration.spec.input_schema_version
                ),
                required_output_schema_version=(
                    registration.spec.output_schema_version
                ),
                subject_ref=base.subject_ref,
                input_artifact_refs=input_refs,
                structured_inputs=structured_inputs,
                parameter_snapshot=parameters,
                policy_snapshot_id=policy_snapshot_id,
                policy_snapshot_digest=workflow.policy_digest,
                command_idempotency_key=(
                    f"qc-evaluate:{lease.attempt_id}:{ordinal}"
                ),
                operation_input_digest=build_operation_input_digest(
                    project_id=lease.project_id,
                    op_type=registration.spec.op_type,
                    op_version=registration.spec.op_version,
                    input_schema_version=(
                        registration.spec.input_schema_version
                    ),
                    subject_ref=base.subject_ref,
                    input_artifact_refs=input_refs,
                    structured_inputs=structured_inputs,
                    parameter_snapshot=parameters,
                    policy_snapshot_id=policy_snapshot_id,
                    policy_snapshot_digest=workflow.policy_digest,
                ),
                trace_id=workflow.trace_id,
                parent_operation_run_id=artifact.operation_run_id,
            )
            gateway = self.artifact_gateway_factory()
            result = self.capability_registry.invoke(
                evaluator_request,
                self.context_factory(evaluator_request, gateway),
            )
        except Exception as exc:
            raise DagWorkerError(
                "quality evaluator invocation failed"
            ) from exc
        if result.status is not OperationStatus.SUCCEEDED:
            code = (
                result.error.error_code
                if result.error is not None
                else "EXECUTION_FAILED"
            )
            safe_code = "".join(
                character
                if character.isalnum() or character in {"_", "-"}
                else "_"
                for character in str(code)
            )[:100] or "EXECUTION_FAILED"
            raise DagWorkerError(
                f"quality evaluator failed closed: {safe_code}"
            )
        try:
            return QCEvaluatorResult.model_validate(
                dict(result.structured_output)
            )
        except Exception as exc:
            raise DagWorkerError(
                "quality evaluator result failed contract validation"
            ) from exc

    @staticmethod
    def _gate_history(
        *,
        session,
        project_id,
        workflow_run_id,
        gate_key,
    ):
        from .quality import (
            ArtifactBinding,
            CandidateVersion,
            EvidencePackBinding,
            EvaluatorBundle,
            GateOutcome,
            MachineJudgment,
            QCDefect,
            QCEvaluation,
            QualityStage,
            RepairResult,
            ResourceUsage,
        )

        rows = session.scalars(
            select(QCCandidateVersionRecord)
            .where(
                QCCandidateVersionRecord.project_id == project_id,
                QCCandidateVersionRecord.workflow_run_id
                == workflow_run_id,
                QCCandidateVersionRecord.gate_key == gate_key,
            )
            .order_by(QCCandidateVersionRecord.ordinal)
        ).all()
        candidates = []
        for row in rows:
            evaluation = session.get(
                QCEvaluationFactRecord,
                row.evaluation_id,
            )
            artifact = session.get(ArtifactRecordRow, row.artifact_id)
            if evaluation is None or artifact is None:
                raise DagWorkerError(
                    "quality gate history is incomplete"
                )
            binding = ArtifactBinding(
                project_id=project_id,
                artifact_id=artifact.id,
                content_digest=artifact.content_digest,
                operation_run_id=artifact.operation_run_id,
                operation_attempt_id=artifact.operation_attempt_id,
            )
            bundle = EvaluatorBundle(
                project_id=project_id,
                stage=QualityStage(evaluation.stage),
                prompt_revision_id=evaluation.prompt_revision_id,
                prompt_digest=evaluation.prompt_digest,
                rubric_revision_id=evaluation.rubric_revision_id,
                rubric_digest=evaluation.rubric_digest,
                model_name=evaluation.model_name,
                model_version=evaluation.model_version,
                implementation_digest=evaluation.implementation_digest,
            )
            qc_evaluation = QCEvaluation(
                evaluation_id=evaluation.id,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                stage=QualityStage(evaluation.stage),
                gate_key=evaluation.gate_key,
                artifact=binding,
                evidence_pack=EvidencePackBinding(
                    project_id=project_id,
                    evidence_pack_id=evaluation.evidence_pack_id,
                    content_digest=evaluation.evidence_pack_digest,
                    artifact_ids=(artifact.id,),
                ),
                expected_selection_version=(
                    evaluation.expected_selection_version
                ),
                evaluator=bundle,
                judgment=MachineJudgment(evaluation.judgment),
                quality_score=evaluation.quality_score / 10_000,
                confidence=evaluation.confidence / 1_000_000,
                defects=tuple(
                    QCDefect.model_validate(item)
                    for item in evaluation.defects
                ),
                recommended_actions=tuple(
                    evaluation.recommended_actions
                ),
                repair_result=RepairResult.model_validate(
                    evaluation.repair_result
                ),
                h3_qc=(
                    H3CandidateScoreV1.model_validate(evaluation.h3_qc)
                    if evaluation.h3_qc is not None
                    else None
                ),
                evaluated_at=(
                    evaluation.evaluated_at.replace(tzinfo=timezone.utc)
                    if evaluation.evaluated_at.tzinfo is None
                    else evaluation.evaluated_at
                ),
                evaluation_digest=evaluation.evaluation_digest,
            )
            candidates.append(
                CandidateVersion(
                    candidate_id=row.id,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    stage=QualityStage(row.stage),
                    gate_key=row.gate_key,
                    ordinal=row.ordinal,
                    artifact=binding,
                    evaluation=qc_evaluation,
                    generation_usage=ResourceUsage.model_validate(
                        row.generation_usage
                    ),
                    created_at=(
                        row.created_at.replace(tzinfo=timezone.utc)
                        if row.created_at.tzinfo is None
                        else row.created_at
                    ),
                    candidate_digest=row.candidate_digest,
                )
            )
        decisions = session.scalars(
            select(QCGateDecisionRecord)
            .where(
                QCGateDecisionRecord.project_id == project_id,
                QCGateDecisionRecord.workflow_run_id
                == workflow_run_id,
                QCGateDecisionRecord.gate_key == gate_key,
            )
            .order_by(QCGateDecisionRecord.decision_sequence)
        ).all()
        outcomes = tuple(
            GateOutcome.model_validate(item.payload)
            for item in decisions
        )
        if len(candidates) != len(outcomes):
            raise DagWorkerError(
                "quality gate candidate/outcome history diverged"
            )
        return tuple(candidates), outcomes

    def _materialize_repair(
        self,
        *,
        session,
        operation,
        parent_artifact,
        proposal,
        ordinal,
    ) -> None:
        if (
            self.scheduler_factory is None
            or self.capability_registry is None
        ):
            raise DagWorkerError(
                "same-stage repair scheduler is unavailable"
            )
        parent = session.get(
            OperationRunRecord,
            parent_artifact.operation_run_id,
        )
        if parent is None:
            raise DagWorkerError("repair parent operation is unavailable")
        try:
            registration = self.capability_registry.resolve(
                op_type=parent.op_type,
                op_version=SchemaRevision.model_validate(
                    parent.request_payload["op_version"]
                ),
                spec_digest=str(
                    parent.request_payload["operation_spec_digest"]
                ),
                implementation_digest=str(
                    parent.request_payload["implementation_digest"]
                ),
            )
        except Exception as exc:
            raise DagWorkerError(
                "repair parent capability is unavailable"
            ) from exc
        suffix = f"repair.{ordinal}"
        repair_key = f"{parent.node_key}.{suffix}"[:200]
        gate_node_key = f"{operation.node_key}.{suffix}"[:200]
        command_prefix = (
            f"quality-repair:{proposal.repair_plan_id}"
        )
        repair_id = uuid5(
            _CONTROL_NAMESPACE,
            f"{proposal.repair_plan_id}:operation",
        )
        gate_id = uuid5(
            _CONTROL_NAMESPACE,
            f"{proposal.repair_plan_id}:gate",
        )
        repair_payload = dict(parent.request_payload)
        repair_parameters = dict(
            repair_payload.get("parameter_snapshot") or {}
        )
        repair_parameters.update(proposal.changed_parameters)
        repair_payload.update(
            {
                "parameter_snapshot": repair_parameters,
                "expected_selection_version": (
                    operation.request_payload.get(
                        "expected_selection_version", 0
                    )
                ),
            }
        )
        repair_binding = dict(
            repair_payload.get("operation_request_binding") or {}
        )
        repair_binding["node_run_id"] = str(
            uuid5(_NODE_NAMESPACE, str(repair_id))
        )
        repair_payload["operation_request_binding"] = repair_binding
        gate_payload = dict(operation.request_payload)
        gate_payload.update(
            {
                "gate_key": proposal.gate_key,
                "input_node_keys": [repair_key],
            }
        )
        gate_binding = dict(
            gate_payload.get("operation_request_binding") or {}
        )
        gate_binding["node_run_id"] = str(
            uuid5(_NODE_NAMESPACE, str(gate_id))
        )
        gate_payload["operation_request_binding"] = gate_binding
        repository = OperationRepository(session)
        repair = repository.create_operation_run(
            project_id=operation.project_id,
            workflow_run_id=operation.workflow_run_id,
            node_key=repair_key,
            op_type=parent.op_type,
            op_version=parent.op_version,
            command_idempotency_key=f"{command_prefix}:operation",
            request_payload=repair_payload,
            parent_operation_run_id=parent.id,
            operation_run_id=repair_id,
        ).value
        gate = repository.create_operation_run(
            project_id=operation.project_id,
            workflow_run_id=operation.workflow_run_id,
            node_key=gate_node_key,
            op_type=operation.op_type,
            op_version=operation.op_version,
            command_idempotency_key=f"{command_prefix}:gate",
            request_payload=gate_payload,
            parent_operation_run_id=operation.id,
            operation_run_id=gate_id,
        ).value
        projected = set(
            session.scalars(
                select(
                    OperationDependencyStateRecord.operation_run_id
                ).where(
                    OperationDependencyStateRecord.operation_run_id.in_(
                        (repair.id, gate.id)
                    )
                )
            )
        )
        parent_inputs = session.scalars(
            select(WorkflowRunEdgeRecord).where(
                WorkflowRunEdgeRecord.workflow_run_id
                == operation.workflow_run_id,
                WorkflowRunEdgeRecord.downstream_operation_run_id
                == parent.id,
            )
        ).all()
        if not projected:
            self.scheduler_factory(session).extend(
                workflow_run_id=operation.workflow_run_id,
                nodes=(
                    DagNode(
                        repair.id,
                        registration.spec.resource_class.value,
                        "interactive",
                        proposal.estimated_usage.cost_micros,
                    ),
                    DagNode(gate.id, "cpu", "interactive", 0),
                ),
                edges=(
                    *(
                        DagEdge(
                            edge.upstream_operation_run_id,
                            repair.id,
                            edge.required_status,
                        )
                        for edge in parent_inputs
                    ),
                    DagEdge(repair.id, gate.id),
                ),
            )
        elif projected != {repair.id, gate.id}:
            raise DagWorkerError(
                "repair DAG is only partially materialized"
            )
        downstream = session.scalars(
            select(WorkflowRunEdgeRecord).where(
                WorkflowRunEdgeRecord.upstream_operation_run_id
                == operation.id
            )
        ).all()
        for edge in downstream:
            exists = session.scalar(
                select(WorkflowRunEdgeRecord.id).where(
                    WorkflowRunEdgeRecord.upstream_operation_run_id
                    == gate.id,
                    WorkflowRunEdgeRecord.downstream_operation_run_id
                    == edge.downstream_operation_run_id,
                )
            )
            if exists is not None:
                continue
            projection = session.get(
                OperationDependencyStateRecord,
                edge.downstream_operation_run_id,
                with_for_update=True,
            )
            downstream_operation = session.get(
                OperationRunRecord,
                edge.downstream_operation_run_id,
                with_for_update=True,
            )
            downstream_queue = session.scalar(
                select(DagReadyQueueRecord)
                .where(
                    DagReadyQueueRecord.operation_run_id
                    == edge.downstream_operation_run_id
                )
                .with_for_update()
            )
            if (
                projection is None
                or projection.status != "WAITING"
                or downstream_operation is None
                or downstream_operation.status != "CREATED"
                or downstream_queue is None
                or downstream_queue.state != "WAITING"
            ):
                raise DagWorkerError(
                    "repair barrier cannot extend downstream authority"
                )
            projection.dependency_count += 1
            projection.state_version += 1
            projection.updated_at = datetime.now(timezone.utc)
            session.add(
                WorkflowRunEdgeRecord(
                    project_id=operation.project_id,
                    workflow_run_id=operation.workflow_run_id,
                    upstream_operation_run_id=gate.id,
                    downstream_operation_run_id=(
                        edge.downstream_operation_run_id
                    ),
                    required_status=edge.required_status,
                )
            )
        session.flush()


def _quality_stage(op_type: str):
    from .quality import QualityStage

    suffix = op_type.rsplit(".", 1)[-1]
    try:
        return QualityStage(suffix)
    except ValueError as exc:
        raise DagWorkerError(
            f"quality gate stage is invalid: {op_type}"
        ) from exc


def _sealed_gate_selection(
    session: Session,
    operation: OperationRunRecord,
) -> tuple[SelectionRevisionRecord, ArtifactRecordRow]:
    gate_key = str(
        operation.request_payload.get("gate_key") or operation.node_key
    )
    head = session.scalar(
        select(SelectionHeadRecord).where(
            SelectionHeadRecord.project_id == operation.project_id,
            SelectionHeadRecord.workflow_run_id == operation.workflow_run_id,
            SelectionHeadRecord.selection_key == gate_key,
            SelectionHeadRecord.status == "SEALED",
            SelectionHeadRecord.current_revision.is_not(None),
        )
    )
    if head is None or head.current_revision is None:
        raise DagWorkerError("quality gate has no sealed selection authority")
    revision = session.scalar(
        select(SelectionRevisionRecord).where(
            SelectionRevisionRecord.selection_head_id == head.id,
            SelectionRevisionRecord.project_id == operation.project_id,
            SelectionRevisionRecord.revision == head.current_revision,
            SelectionRevisionRecord.decision.in_(
                ("SELECTED", "DEGRADED_ACCEPTED", "HUMAN_SELECTED")
            ),
        )
    )
    if revision is None:
        raise DagWorkerError("quality gate selection revision is unavailable")
    artifact = session.scalar(
        select(ArtifactRecordRow).where(
            ArtifactRecordRow.id == revision.artifact_id,
            ArtifactRecordRow.project_id == operation.project_id,
            ArtifactRecordRow.operation_run_id
            == revision.selected_operation_run_id,
            ArtifactRecordRow.operation_attempt_id
            == revision.selected_attempt_id,
            ArtifactRecordRow.content_digest == revision.artifact_digest,
            ArtifactRecordRow.status == "COMMITTED",
        )
    )
    if artifact is None:
        raise DagWorkerError("quality gate selected artifact is unavailable")
    return revision, artifact


def _single_upstream_operation(
    session: Session,
    operation: OperationRunRecord,
) -> OperationRunRecord:
    upstream_ids = tuple(
        session.scalars(
            select(WorkflowRunEdgeRecord.upstream_operation_run_id).where(
                WorkflowRunEdgeRecord.project_id == operation.project_id,
                WorkflowRunEdgeRecord.workflow_run_id
                == operation.workflow_run_id,
                WorkflowRunEdgeRecord.downstream_operation_run_id
                == operation.id,
            )
        )
    )
    if len(upstream_ids) != 1:
        raise DagWorkerError("control boundary requires exactly one upstream gate")
    upstream = session.get(OperationRunRecord, upstream_ids[0])
    if upstream is None:
        raise DagWorkerError("upstream control operation is unavailable")
    return upstream


def _record_h3_durable_delivery(
    session: Session,
    *,
    operation: OperationRunRecord,
    actor_id: str,
) -> tuple[DeliveryRevisionRecord, ArtifactRecordRow]:
    """Publish one H3 delivery from sealed QC and selected sequence facts."""

    machine = _single_upstream_operation(session, operation)
    if (
        machine.node_key != "final-gate"
        or machine.op_type != "qc.gate.final"
        or machine.status != "SUCCEEDED"
        or str(machine.request_payload.get("workflow_node_kind") or "")
        != "quality_gate"
    ):
        raise DagWorkerError("H3 machine final gate is not complete")
    machine_revision, machine_artifact = _sealed_gate_selection(session, machine)
    if machine_revision.decision != "SELECTED":
        raise DagWorkerError("H3 final gate did not select a releasable final")
    if (
        machine_artifact.project_id != operation.project_id
        or machine_artifact.logical_role != "final_episode"
        or machine_artifact.mime_type != "video/mp4"
        or machine_artifact.status != "COMMITTED"
        or type(machine_artifact.byte_size) is not int
        or machine_artifact.byte_size <= 0
    ):
        raise DagWorkerError("H3 final gate selected an invalid final")
    try:
        evaluation_id = UUID(str(machine_revision.payload["evaluation_id"]))
        evaluation_digest = str(machine_revision.payload["evaluation_digest"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DagWorkerError("H3 final selection lacks QC authority") from exc
    evaluation = session.scalar(
        select(QCEvaluationFactRecord).where(
            QCEvaluationFactRecord.id == evaluation_id,
            QCEvaluationFactRecord.project_id == operation.project_id,
            QCEvaluationFactRecord.workflow_run_id == operation.workflow_run_id,
            QCEvaluationFactRecord.stage == "final",
            QCEvaluationFactRecord.gate_key == machine.node_key,
            QCEvaluationFactRecord.artifact_id == machine_artifact.id,
            QCEvaluationFactRecord.artifact_digest
            == machine_artifact.content_digest,
            QCEvaluationFactRecord.artifact_operation_run_id
            == machine_revision.selected_operation_run_id,
            QCEvaluationFactRecord.artifact_operation_attempt_id
            == machine_revision.selected_attempt_id,
            QCEvaluationFactRecord.evaluation_digest == evaluation_digest,
            QCEvaluationFactRecord.judgment == "PASS",
        )
    )
    if (
        evaluation is None
        or evaluation.id != evaluation_id
        or evaluation.project_id != operation.project_id
        or evaluation.workflow_run_id != operation.workflow_run_id
        or evaluation.stage != "final"
        or evaluation.gate_key != machine.node_key
        or evaluation.artifact_id != machine_artifact.id
        or evaluation.artifact_digest != machine_artifact.content_digest
        or evaluation.artifact_operation_run_id
        != machine_revision.selected_operation_run_id
        or evaluation.artifact_operation_attempt_id
        != machine_revision.selected_attempt_id
        or evaluation.evaluation_digest != evaluation_digest
        or evaluation.judgment != "PASS"
    ):
        raise DagWorkerError("H3 final QC evaluation is unavailable")

    assemble = session.get(OperationRunRecord, machine_artifact.operation_run_id)
    if (
        assemble is None
        or assemble.project_id != operation.project_id
        or assemble.workflow_run_id != operation.workflow_run_id
        or assemble.node_key != "assemble"
        or assemble.op_type != "final.assemble"
        or assemble.status != "SUCCEEDED"
        or assemble.accepted_attempt_id != machine_revision.selected_attempt_id
    ):
        raise DagWorkerError("H3 selected final producer is not the assembler")
    frozen_inputs = assemble.request_payload.get("structured_inputs")
    expected_assembly_inputs = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_source": "h3_native",
        "subtitles": False,
    }
    if (
        not isinstance(frozen_inputs, Mapping)
        or dict(frozen_inputs) != expected_assembly_inputs
    ):
        raise DagWorkerError(
            "H3 assembly must preserve native audio without subtitles"
        )
    final_edge = session.scalar(
        select(WorkflowRunEdgeRecord.id).where(
            WorkflowRunEdgeRecord.project_id == operation.project_id,
            WorkflowRunEdgeRecord.workflow_run_id == operation.workflow_run_id,
            WorkflowRunEdgeRecord.upstream_operation_run_id == assemble.id,
            WorkflowRunEdgeRecord.downstream_operation_run_id == machine.id,
        )
    )
    if final_edge is None:
        raise DagWorkerError("H3 selected final producer is outside the final gate")

    repository = H3Repository(session)
    try:
        episode_revision_id, segments = repository.load_h3_assembly_authority(
            operation.project_id,
            operation.workflow_run_id,
        )
    except (PersistenceError, ValueError) as exc:
        raise DagWorkerError("H3 selected sequence authority is incomplete") from exc
    if not segments or tuple(segment.ordinal for segment in segments) != tuple(
        range(1, len(segments) + 1)
    ):
        raise DagWorkerError("H3 selected sequence authority is not canonical")

    lineage_rows = session.execute(
        select(ArtifactLineageEdgeRecord, ArtifactRecordRow)
        .join(
            ArtifactRecordRow,
            ArtifactRecordRow.id == ArtifactLineageEdgeRecord.input_artifact_id,
        )
        .where(
            ArtifactLineageEdgeRecord.project_id == operation.project_id,
            ArtifactLineageEdgeRecord.output_artifact_id == machine_artifact.id,
            ArtifactRecordRow.status == "COMMITTED",
        )
        .order_by(ArtifactLineageEdgeRecord.ordinal)
    ).all()
    if len(lineage_rows) != len(segments):
        raise DagWorkerError("H3 final lineage does not match selected sequences")
    for index, ((edge, artifact), segment) in enumerate(
        zip(lineage_rows, segments, strict=True)
    ):
        expected_role = (
            f"h3.sequence.{segment.ordinal:03d}.attempt."
            f"{segment.selected_attempt_ordinal}.video"
        )
        if (
            edge.role != "input"
            or edge.ordinal != index
            or edge.input_artifact_id != segment.artifact_id
            or edge.output_artifact_id != machine_artifact.id
            or artifact.id != segment.artifact_id
            or artifact.project_id != operation.project_id
            or artifact.content_digest != segment.artifact_digest
            or artifact.mime_type != "video/mp4"
            or artifact.logical_role != expected_role
            or artifact.status != "COMMITTED"
            or type(artifact.byte_size) is not int
            or artifact.byte_size <= 0
        ):
            raise DagWorkerError("H3 final lineage sequence binding is invalid")

    jobs = tuple(
        job
        for job in session.scalars(
            select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.project_id == operation.project_id
            )
        ).all()
        if isinstance(job.payload, Mapping)
        and job.payload.get("workflowRunId") == str(operation.workflow_run_id)
    )
    if len(jobs) != 1:
        raise DagWorkerError("H3 delivery video job authority is unavailable")
    job = jobs[0]
    content_mode = job.payload.get("contentMode")
    code_by_mode = {
        "source_grounded": "SOURCE_GROUNDED",
        "ai_completed": "AI_COMPLETED_NON_ORIGINAL",
    }
    try:
        disclosure = H3DeliveryDisclosureV1(
            code=code_by_mode[content_mode],
            content_mode=content_mode,
            label=job.payload["contentLabel"],
            notice=job.payload["contentNotice"],
        )
        assembly_manifest = H3DeliveryAssemblyManifestV1(
            sequence_sources=tuple(
                H3DeliverySequenceSourceV1(
                    sequence_id=segment.sequence_id,
                    selected_attempt_ordinal=segment.selected_attempt_ordinal,
                    source_artifact_digest=segment.artifact_digest,
                )
                for segment in segments
            ),
            playback_asset_id=machine_artifact.id,
            download_asset_id=machine_artifact.id,
        )
        delivery_identity = {
            "episode_revision_id": str(episode_revision_id),
            "status": "succeeded",
            "assembly_manifest": assembly_manifest.model_dump(mode="json"),
            "disclosure": disclosure.model_dump(mode="json"),
        }
        delivery = H3DeliveryV1(
            **delivery_identity,
            delivery_digest=h3_contract_digest(delivery_identity),
        )
        stored = repository.store_h3_product_delivery(
            operation.project_id,
            operation.workflow_run_id,
            job.id,
            delivery,
            created_by_actor=actor_id,
        )
    except (KeyError, TypeError, ValueError, PersistenceError) as exc:
        raise DagWorkerError("H3 delivery authority is invalid") from exc
    return stored.value, machine_artifact


def _record_durable_delivery(
    session: Session,
    *,
    operation: OperationRunRecord,
    actor_id: str,
) -> tuple[DeliveryRevisionRecord, ArtifactRecordRow]:
    machine = _single_upstream_operation(session, operation)
    if (
        machine.node_key != "final-gate"
        or machine.status != "SUCCEEDED"
        or str(machine.request_payload.get("workflow_node_kind") or "")
        != "quality_gate"
    ):
        raise DagWorkerError("machine final gate is not complete")
    machine_revision, machine_artifact = _sealed_gate_selection(
        session, machine
    )
    if machine_revision.decision != "SELECTED":
        raise DagWorkerError("machine final gate did not select a releasable final")
    if (
        machine_artifact.logical_role != "final_episode"
        or machine_artifact.mime_type != "video/mp4"
    ):
        raise DagWorkerError("machine final gate selected an invalid final")
    try:
        evaluation_id = UUID(str(machine_revision.payload["evaluation_id"]))
        evaluation_digest = str(
            machine_revision.payload["evaluation_digest"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DagWorkerError(
            "machine final selection lacks QC evaluation authority"
        ) from exc
    evaluation = session.scalar(
        select(QCEvaluationFactRecord).where(
            QCEvaluationFactRecord.id == evaluation_id,
            QCEvaluationFactRecord.project_id == operation.project_id,
            QCEvaluationFactRecord.workflow_run_id
            == operation.workflow_run_id,
            QCEvaluationFactRecord.stage == "final",
            QCEvaluationFactRecord.gate_key == machine.node_key,
            QCEvaluationFactRecord.artifact_id == machine_artifact.id,
            QCEvaluationFactRecord.artifact_digest
            == machine_artifact.content_digest,
            QCEvaluationFactRecord.artifact_operation_run_id
            == machine_revision.selected_operation_run_id,
            QCEvaluationFactRecord.artifact_operation_attempt_id
            == machine_revision.selected_attempt_id,
            QCEvaluationFactRecord.evaluation_digest == evaluation_digest,
            QCEvaluationFactRecord.judgment == "PASS",
        )
    )
    if evaluation is None:
        raise DagWorkerError("machine final QC evaluation is unavailable")
    assemble = session.get(
        OperationRunRecord,
        machine_artifact.operation_run_id,
    )
    if (
        assemble is None
        or assemble.project_id != operation.project_id
        or assemble.workflow_run_id != operation.workflow_run_id
        or assemble.node_key != "assemble"
        or assemble.op_type != "final.assemble"
        or assemble.status != "SUCCEEDED"
        or assemble.accepted_attempt_id
        != machine_revision.selected_attempt_id
    ):
        raise DagWorkerError("selected final producer is not the Shidu assembler")
    final_edge = session.scalar(
        select(WorkflowRunEdgeRecord.id).where(
            WorkflowRunEdgeRecord.project_id == operation.project_id,
            WorkflowRunEdgeRecord.workflow_run_id
            == operation.workflow_run_id,
            WorkflowRunEdgeRecord.upstream_operation_run_id == assemble.id,
            WorkflowRunEdgeRecord.downstream_operation_run_id == machine.id,
        )
    )
    if final_edge is None:
        raise DagWorkerError("selected final producer is outside the final gate")
    frozen_inputs = dict(
        assemble.request_payload.get("structured_inputs") or {}
    )
    required_frozen = (
        "project_id",
        "book_id",
        "trial_script_revision_id",
        "trial_script_digest",
        "audio_alignment_policy_revision_id",
        "audio_alignment_policy_digest",
    )
    if any(not frozen_inputs.get(key) for key in required_frozen):
        raise DagWorkerError("selected final has incomplete frozen policy lineage")
    lineage_rows = session.execute(
        select(ArtifactLineageEdgeRecord, ArtifactRecordRow)
        .join(
            ArtifactRecordRow,
            ArtifactRecordRow.id
            == ArtifactLineageEdgeRecord.input_artifact_id,
        )
        .where(
            ArtifactLineageEdgeRecord.project_id == operation.project_id,
            ArtifactLineageEdgeRecord.output_artifact_id
            == machine_artifact.id,
            ArtifactRecordRow.status == "COMMITTED",
        )
        .order_by(
            ArtifactLineageEdgeRecord.role,
            ArtifactLineageEdgeRecord.ordinal,
            ArtifactLineageEdgeRecord.id,
        )
    ).all()
    sibling_rows = session.scalars(
        select(ArtifactRecordRow).where(
            ArtifactRecordRow.project_id == operation.project_id,
            ArtifactRecordRow.operation_run_id == assemble.id,
            ArtifactRecordRow.operation_attempt_id
            == machine_artifact.operation_attempt_id,
            ArtifactRecordRow.status == "COMMITTED",
        )
    ).all()

    def _single_public_artifact(
        rows: list[ArtifactRecordRow],
        *,
        role: str,
        mime_type: str,
    ) -> ArtifactRecordRow:
        matches = [
            item
            for item in rows
            if item.logical_role == role and item.mime_type == mime_type
        ]
        if len(matches) != 1:
            raise DagWorkerError(
                f"delivery requires one committed {role} artifact"
            )
        return matches[0]

    subtitle = _single_public_artifact(
        [artifact for _edge, artifact in lineage_rows],
        role="subtitle_track",
        mime_type="application/x-subrip",
    )
    cover = _single_public_artifact(
        sibling_rows,
        role="cover_image",
        mime_type="image/jpeg",
    )
    share_card = _single_public_artifact(
        sibling_rows,
        role="share_card",
        mime_type="image/jpeg",
    )

    def _public_authority(artifact: ArtifactRecordRow) -> dict[str, object]:
        return {
            "owner": "drama_factory",
            "artifact_id": str(artifact.id),
            "artifact_digest": artifact.content_digest,
            "byte_size": artifact.byte_size,
            "mime_type": artifact.mime_type,
            "logical_role": artifact.logical_role,
        }

    public_artifacts = {
        "video": _public_authority(machine_artifact),
        "subtitle": _public_authority(subtitle),
        "cover": _public_authority(cover),
        "share_card": _public_authority(share_card),
    }
    evaluation_rows = tuple(
        session.scalars(
            select(QCEvaluationFactRecord)
            .where(
                QCEvaluationFactRecord.project_id == operation.project_id,
                QCEvaluationFactRecord.workflow_run_id
                == operation.workflow_run_id,
                QCEvaluationFactRecord.stage == "final",
                QCEvaluationFactRecord.gate_key == machine.node_key,
            )
            .order_by(
                QCEvaluationFactRecord.evaluated_at,
                QCEvaluationFactRecord.id,
            )
        )
    )
    if not evaluation_rows or all(
        item.id != evaluation.id for item in evaluation_rows
    ):
        raise DagWorkerError("machine final QC repair chain is incomplete")
    repair_chain = [
        {
            "evaluation_id": str(item.id),
            "evaluation_digest": item.evaluation_digest,
            "judgment": item.judgment,
            "quality_score": item.quality_score,
            "confidence": item.confidence,
            "defects": list(item.defects),
            "recommended_actions": list(item.recommended_actions),
            "repair_result": dict(item.repair_result),
        }
        for item in evaluation_rows
    ]
    payload = {
        "schema_version": "factory.shidu-delivery.v1",
        "workflow_run_id": str(operation.workflow_run_id),
        "delivery_operation_run_id": str(operation.id),
        "final_artifact_id": str(machine_artifact.id),
        "final_artifact_digest": machine_artifact.content_digest,
        "final_artifact_byte_size": machine_artifact.byte_size,
        "machine_gate_key": machine.node_key,
        "machine_selection_revision_id": str(machine_revision.id),
        "qc_outcome": {
            "selection_decision": machine_revision.decision,
            "evaluation_id": str(evaluation.id),
            "evaluation_digest": evaluation.evaluation_digest,
            "judgment": evaluation.judgment,
            "quality_score": evaluation.quality_score,
            "confidence": evaluation.confidence,
            "unresolved_defects": list(evaluation.defects),
        },
        "repair_chain": repair_chain,
        "public_artifacts": public_artifacts,
        "frozen_authority": {
            key: frozen_inputs[key] for key in required_frozen
        },
        "input_artifact_lineage": [
            {
                "edge_role": edge.role,
                "ordinal": edge.ordinal,
                "artifact_id": str(artifact.id),
                "artifact_digest": artifact.content_digest,
                "byte_size": artifact.byte_size,
                "mime_type": artifact.mime_type,
                "logical_role": artifact.logical_role,
            }
            for edge, artifact in lineage_rows
        ],
    }
    digest = canonical_json_digest(payload)
    record_id = uuid5(
        _CONTROL_NAMESPACE,
        f"shidu-delivery:{operation.id}:{digest}",
    )
    replay = session.get(DeliveryRevisionRecord, record_id)
    if replay is not None:
        if replay.digest != digest or replay.payload != payload:
            raise DagWorkerError("delivery revision replay conflicts")
        return replay, machine_artifact
    revision = session.scalar(
        select(func.max(DeliveryRevisionRecord.revision)).where(
            DeliveryRevisionRecord.project_id == operation.project_id
        )
    ) or 0
    record = DeliveryRevisionRecord(
        id=record_id,
        project_id=operation.project_id,
        revision=revision + 1,
        digest=digest,
        created_by_actor=actor_id,
        payload=payload,
    )
    session.add(record)
    session.flush()
    return record, machine_artifact


def _quality_artifact(
    session: Session,
    operation: OperationRunRecord,
) -> ArtifactRecordRow:
    upstream_ids = tuple(
        session.scalars(
            select(
                WorkflowRunEdgeRecord.upstream_operation_run_id
            ).where(
                WorkflowRunEdgeRecord.project_id
                == operation.project_id,
                WorkflowRunEdgeRecord.workflow_run_id
                == operation.workflow_run_id,
                WorkflowRunEdgeRecord.downstream_operation_run_id
                == operation.id,
            )
        )
    )
    rows: list[ArtifactRecordRow] = []
    for upstream_id in upstream_ids:
        upstream = session.get(OperationRunRecord, upstream_id)
        if upstream is None or upstream.status != "SUCCEEDED":
            raise DagWorkerError("quality gate upstream operation is incomplete")
        kind = str(
            upstream.request_payload.get("workflow_node_kind") or "capability"
        )
        if kind == "quality_gate":
            rows.append(_sealed_gate_selection(session, upstream)[1])
        else:
            rows.extend(
                session.scalars(
                    select(ArtifactRecordRow)
                    .where(
                        ArtifactRecordRow.project_id == operation.project_id,
                        ArtifactRecordRow.operation_run_id == upstream_id,
                        ArtifactRecordRow.status == "COMMITTED",
                    )
                    .order_by(
                        ArtifactRecordRow.created_at,
                        ArtifactRecordRow.id,
                    )
                ).all()
            )
    rows = [
        row
        for row in rows
        if session.scalar(
            select(OperationRunRecord.accepted_attempt_id).where(
                OperationRunRecord.id == row.operation_run_id
            )
        )
        == row.operation_attempt_id
    ]
    if not rows:
        raise DagWorkerError(
            "quality gate has no accepted upstream artifact"
        )
    preferred_roles = {
        "qc.gate.asset": (
            "character_asset",
            "scene_asset",
            "prop_asset",
        ),
        "qc.gate.keyframe": (
            "keyframe",
            "first_frame",
            "last_frame",
        ),
        "qc.gate.final": ("final_episode",),
    }.get(operation.op_type, ())
    for role in preferred_roles:
        matches = [row for row in rows if row.logical_role == role]
        if matches:
            return matches[-1]
    if operation.op_type == "qc.gate.clip":
        matches = [
            row
            for row in rows
            if row.logical_role == "raw_video"
            or row.logical_role.startswith("clip.")
        ]
        if matches:
            return matches[-1]
    raise DagWorkerError(
        f"quality gate has no eligible {operation.op_type} artifact"
    )


@dataclass(frozen=True, slots=True)
class _InlineGpuLease:
    gpu_index: int

    @staticmethod
    def check(cancelled: Callable[[], None]) -> None:
        cancelled()


class _InlineGpuLeaseManager:
    """Expose the already-owned durable DAG GPU lease to model adapters."""

    def __init__(self, gpu_index: int) -> None:
        if gpu_index < 0:
            raise ValueError("gpu_index must be non-negative")
        self._active = _InlineGpuLease(gpu_index)

    @contextmanager
    def lease(self):
        yield self._active


def _gpu_operation_matcher(
    registry: CapabilityRegistry,
    observation: GpuObservation | None,
) -> Callable[[OperationRunRecord], bool]:
    scheduler = UnifiedGpuScheduler()

    def matches(operation: OperationRunRecord) -> bool:
        payload = operation.request_payload
        if str(payload.get("workflow_node_kind") or "capability") != (
            "capability"
        ):
            return True
        registration = registry.resolve(
            op_type=operation.op_type,
            op_version=SchemaRevision.model_validate(payload["op_version"]),
            spec_digest=str(payload["operation_spec_digest"]),
            implementation_digest=str(payload["implementation_digest"]),
        )
        if registration.spec.resource_class is not ResourceClass.LOCAL_GPU:
            return True
        requirement = registration.spec.resource_requirement
        if observation is None or requirement is None:
            return False
        request = GpuTaskRequest(
            request_id=operation.id,
            project_id=operation.project_id,
            resource_class=(
                GpuResourceClass.USER_ANALYSIS
                if operation.op_type == "speech.transcribe"
                else GpuResourceClass.INTERACTIVE_GENERATION
            ),
            model_id=(
                requirement.warm_model_affinity[0]
                if requirement.warm_model_affinity
                else operation.op_type
            ),
            estimated_vram_mib=requirement.minimum_vram_mb,
            enqueued_at=operation.created_at,
            max_runtime_seconds=requirement.estimated_duration_seconds,
            resource_requirement=requirement,
            implementation_manifest_digest=(
                registration.implementation_manifest.implementation_digest
            ),
        )
        return (
            scheduler.choose(
                (request,),
                (observation,),
                completed_dependencies=frozenset(),
                now=datetime.now(timezone.utc),
            )
            is not None
        )

    return matches


class DurableDagWorker:
    """One loop over recovery, admission, execution, and durable completion."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        scheduler_factory: Callable[[Session], DurableDagScheduler],
        capability_registry: CapabilityRegistry,
        artifact_gateway_factory: ArtifactGatewayFactory,
        context_factory: ContextFactory,
        worker_id: str,
        resource_pools: Iterable[str] | None = None,
        operation_types: Iterable[str] | None = None,
        operation_matcher: (
            Callable[[OperationRunRecord], bool] | None
        ) = None,
        control_dispatcher: ControlNodeDispatcher = (
            default_control_dispatcher
        ),
        lease_duration: timedelta = timedelta(minutes=10),
        successful_result_finalizer: (
            Callable[[Session, OperationResult], None] | None
        ) = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if (
            successful_result_finalizer is not None
            and not callable(successful_result_finalizer)
        ):
            raise ValueError(
                "successful_result_finalizer must be callable"
            )
        self.session_factory = session_factory
        self.scheduler_factory = scheduler_factory
        self.capability_registry = capability_registry
        self.artifact_gateway_factory = artifact_gateway_factory
        self.context_factory = context_factory
        self.worker_id = worker_id
        self.resource_pools = (
            tuple(resource_pools) if resource_pools is not None else None
        )
        self.operation_types = (
            tuple(operation_types)
            if operation_types is not None
            else None
        )
        self.operation_matcher = operation_matcher
        self.control_dispatcher = control_dispatcher
        self.lease_duration = lease_duration
        self.successful_result_finalizer = successful_result_finalizer

    def run_once(self) -> WorkerTick:
        with self.session_factory() as session:
            scheduler = self.scheduler_factory(session)
            scheduler.recover_expired()
            scheduler.requeue_budget_blocked()
            builder = OperationRequestBuilder(
                session,
                capability_registry=self.capability_registry,
            )
            lease = scheduler.claim(
                worker_id=self.worker_id,
                lease_duration=self.lease_duration,
                resource_pools=self.resource_pools,
                operation_types=self.operation_types,
                candidate_filter=self.operation_matcher,
                request_builder=builder.build,
            )
            session.commit()
        if lease is None:
            return WorkerTick(TickOutcome.IDLE)

        try:
            with self.session_factory() as session:
                operation = session.get(
                    OperationRunRecord, lease.operation_run_id
                )
                attempt = session.get(
                    OperationAttemptRecord, lease.attempt_id
                )
                if operation is None or attempt is None:
                    raise DagWorkerError(
                        "claimed operation attempt is unavailable"
                    )
                request = OperationRequest.model_validate(
                    attempt.request_payload
                )
                node_kind = str(
                    operation.request_payload.get("workflow_node_kind")
                    or "capability"
                )
                if node_kind != "capability":
                    control = self.control_dispatcher(
                        lease=lease,
                        operation=operation,
                        request_payload=attempt.request_payload,
                    )
                    operation_id = operation.id
                else:
                    control = None
                    operation_id = operation.id

            if control is not None:
                return self._finish_control(lease, operation_id, control)

            gateway = self.artifact_gateway_factory()
            result = None
            provider_deadline = time.monotonic() + float(
                os.getenv(
                    "CREATIVE_HUB_PROVIDER_MAX_RUNTIME_SECONDS",
                    "7200",
                )
            )
            heartbeat_interval = min(
                max(self.lease_duration.total_seconds() / 3, 1.0),
                float(
                    os.getenv(
                        "CREATIVE_HUB_DAG_HEARTBEAT_SECONDS",
                        "30",
                    )
                ),
            )
            next_heartbeat = time.monotonic() + heartbeat_interval
            while True:
                context = self.context_factory(request, gateway)
                result = self.capability_registry.invoke(request, context)
                if (
                    result.status is not OperationStatus.OUTCOME_UNKNOWN
                    or result.error is None
                    or result.error.retry_class.value
                    != "reconcile_provider"
                ):
                    break
                now = time.monotonic()
                if now >= provider_deadline:
                    break
                if now >= next_heartbeat:
                    self._renew_lease(lease)
                    next_heartbeat = now + heartbeat_interval
                time.sleep(
                    min(
                        float(
                            os.getenv(
                                "CREATIVE_HUB_PROVIDER_POLL_SECONDS",
                                "2",
                            )
                        ),
                        max(provider_deadline - now, 0.0),
                    )
                )
            if result is None:
                raise DagWorkerError(
                    "capability produced no operation result"
                )
            return self._finish_result(lease, result)
        except Exception as exc:
            return self._fail(lease, exc)

    def _renew_lease(self, lease: DagLease) -> None:
        with self.session_factory() as session:
            self.scheduler_factory(session).renew(
                lease,
                lease_duration=self.lease_duration,
            )
            session.commit()

    def _finish_control(
        self,
        lease: DagLease,
        operation_id: UUID,
        outcome: ControlOutcome,
    ) -> WorkerTick:
        with self.session_factory() as session:
            scheduler = self.scheduler_factory(session)
            if outcome.action is ControlAction.WAITING_HUMAN:
                scheduler.wait_for_human(
                    lease,
                    reason=outcome.reason or "quality_gate_waiting_human",
                )
                tick = TickOutcome.WAITING_HUMAN
            else:
                succeeded = outcome.action is ControlAction.SUCCEEDED
                scheduler.complete(
                    lease,
                    outcome="SUCCEEDED" if succeeded else "FAILED",
                    actual_cost_micros=outcome.actual_cost_micros,
                    metrics=dict(outcome.metrics or {}),
                    error=dict(outcome.error or {}),
                )
                tick = (
                    TickOutcome.SUCCEEDED
                    if succeeded
                    else TickOutcome.FAILED
                )
            session.commit()
        return WorkerTick(tick, operation_id, lease.attempt_id)

    def _finish_result(
        self,
        lease: DagLease,
        result: OperationResult,
    ) -> WorkerTick:
        if (
            result.project_id != lease.project_id
            or result.operation_run_id != lease.operation_run_id
            or result.operation_attempt_id != lease.attempt_id
        ):
            raise DagWorkerError(
                "capability result does not match the claimed attempt"
            )
        metrics = dict(result.metrics)
        raw_cost = metrics.pop("actual_cost_micros", 0)
        actual_cost = (
            raw_cost
            if isinstance(raw_cost, int)
            and not isinstance(raw_cost, bool)
            and raw_cost >= 0
            else 0
        )
        with self.session_factory() as session:
            scheduler = self.scheduler_factory(session)
            if (
                result.status is OperationStatus.SUCCEEDED
                and self.successful_result_finalizer is not None
            ):
                self.successful_result_finalizer(session, result)
            if result.status is OperationStatus.OUTCOME_UNKNOWN:
                reason = (
                    result.error.error_code
                    if result.error is not None
                    else "provider_outcome_unknown"
                )
                scheduler.wait_for_human(lease, reason=reason)
                outcome = TickOutcome.WAITING_HUMAN
            else:
                terminal = {
                    OperationStatus.SUCCEEDED: "SUCCEEDED",
                    OperationStatus.FAILED: "FAILED",
                    OperationStatus.CANCELLED: "CANCELLED",
                }[result.status]
                scheduler.complete(
                    lease,
                    outcome=terminal,
                    actual_cost_micros=actual_cost,
                    metrics=metrics,
                    error=(
                        result.error.model_dump(mode="json")
                        if result.error is not None
                        else {}
                    ),
                )
                outcome = {
                    OperationStatus.SUCCEEDED: TickOutcome.SUCCEEDED,
                    OperationStatus.FAILED: TickOutcome.FAILED,
                    OperationStatus.CANCELLED: TickOutcome.CANCELLED,
                }[result.status]
            session.commit()
        return WorkerTick(
            outcome,
            lease.operation_run_id,
            lease.attempt_id,
        )

    def _fail(self, lease: DagLease, exc: Exception) -> WorkerTick:
        with self.session_factory() as session:
            scheduler = self.scheduler_factory(session)
            scheduler.complete(
                lease,
                outcome="FAILED",
                error={
                    "error_code": "dag_worker_execution_failed",
                    "exception_type": type(exc).__name__,
                },
            )
            session.commit()
        return WorkerTick(
            TickOutcome.FAILED,
            lease.operation_run_id,
            lease.attempt_id,
        )

    def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        while True:
            tick = self.run_once()
            if tick.outcome is TickOutcome.IDLE:
                time.sleep(poll_interval_seconds)


class _DurableLocalWanTransport:
    """Queryable Comfy transport with a persisted prompt id.

    Comfy prompt submission is not idempotent.  The durable provider
    coordinator commits ``submit_started_at`` before this adapter performs
    network I/O, and this adapter can recover the accepted ``prompt_id`` from
    Comfy queue/history using the already-persisted client token and
    submission nonce.  Reconciliation never submits a second prompt.
    """

    provider_name = "local-wan-comfy"

    def __init__(
        self,
        *,
        request: OperationRequest,
        gateway,
        session_factory: Callable[[], Session],
        comfy_transport: object | None = None,
        output_verifier: object | None = None,
    ) -> None:
        from drama.v3.durable_provider import ProviderCapabilities
        from drama.v3.wan_runtime import WanRequestsComfyTransport

        self.capabilities = ProviderCapabilities(
            idempotent_submit=False,
            query_by_client_token=True,
            query_by_task_id=True,
        )
        self.request = request
        self.gateway = gateway
        self.session_factory = session_factory
        gpu_shard = int(request.structured_inputs.get("gpu_shard") or 0)
        self.comfy = comfy_transport or WanRequestsComfyTransport(
            os.getenv(
                f"DRAMA_COMFY_BASE_{gpu_shard}",
                "http://127.0.0.1:8188",
            )
        )
        self.output_verifier = output_verifier
        self.submission_nonce = request.operation_attempt_id.hex

    def submit(self, request, *, client_token: str) -> str:
        del request
        recovered = self.comfy.find_submission(
            client_id=client_token,
            submission_nonce=self.submission_nonce,
        )
        if recovered is not None:
            return recovered
        workflow = self._build_workflow()
        return self.comfy.submit(
            workflow,
            client_id=client_token,
            extra_data={
                "operation_attempt_id": str(
                    self.request.operation_attempt_id
                ),
                "submission_nonce": self.submission_nonce,
            },
        )

    def query(self, *, client_token: str, provider_task_id: str | None):
        from drama.v3.durable_provider import (
            ProviderObservation,
            ProviderObservationState,
        )
        from drama.v3.durable_comfy import ComfyObservation

        prompt_id = provider_task_id
        if prompt_id is None:
            prompt_id = self.comfy.find_submission(
                client_id=client_token,
                submission_nonce=self.submission_nonce,
            )
        if prompt_id is None:
            return ProviderObservation(ProviderObservationState.ABSENT)
        state, progress = self.comfy.observe(prompt_id)
        mapped = {
            ComfyObservation.QUEUED: ProviderObservationState.PENDING,
            ComfyObservation.RUNNING: ProviderObservationState.RUNNING,
            ComfyObservation.SUCCESS: ProviderObservationState.SUCCEEDED,
            ComfyObservation.ERROR: ProviderObservationState.FAILED,
            ComfyObservation.CANCELLED: (
                ProviderObservationState.CANCELLED
            ),
            ComfyObservation.LOST: ProviderObservationState.UNKNOWN,
        }[state]
        result = None
        if mapped in {
            ProviderObservationState.SUCCEEDED,
            ProviderObservationState.FAILED,
            ProviderObservationState.CANCELLED,
        }:
            result = {
                "prompt_id": prompt_id,
                "comfy_observation": state.value,
                "progress": dict(progress),
            }
        return ProviderObservation(
            mapped,
            provider_task_id=prompt_id,
            result=result,
            cost_micros=0 if result is not None else None,
        )

    def materialize(self, invocation) -> Mapping[str, object]:
        rows = self._artifact_rows()
        if not rows:
            prompt_id = invocation.provider_task_id
            if not prompt_id:
                raise DagWorkerError(
                    "Comfy materialization requires a persisted prompt id"
                )
            from drama.atomic_factory import FactoryProducedArtifact
            from drama.v3.durable_comfy import ComfyOutputVerifier

            generation = self._generation_request()
            with tempfile.TemporaryDirectory(
                prefix="creative-hub-wan-"
            ) as raw:
                output = self.comfy.download(
                    prompt_id,
                    Path(raw) / f"{prompt_id}.mp4",
                )
                verifier = self.output_verifier or ComfyOutputVerifier()
                verified = verifier.verify(
                    output,
                    expected_resolution=generation.resolution,
                    expected_duration_seconds=(
                        generation.duration_seconds
                    ),
                )
                produced = FactoryProducedArtifact(
                    payload=output.read_bytes(),
                    mime_type=verified.mime,
                    logical_role=self._output_role(),
                )
                self.gateway.publish(
                    produced,
                    request=self.request,
                    created_at=datetime.now(timezone.utc),
                )
            rows = self._artifact_rows()
        if not rows:
            raise DagWorkerError(
                "Comfy output publication did not commit an artifact"
            )
        return {
            "provider_task_id": invocation.provider_task_id,
            "artifact_ids": [str(row.id) for row in rows],
            "artifact_digests": [row.content_digest for row in rows],
        }

    def _generation_request(self):
        from pydantic import TypeAdapter
        from shared_contracts import GenerationRequest

        return TypeAdapter(GenerationRequest).validate_python(
            self._json_artifact("generation_request")
        )

    def _build_workflow(self) -> dict[str, Any]:
        from shared_contracts import GenerationMode
        from drama.v3.prompt_compiler import CompiledWanPrompt
        from drama.v3.workflows import (
            WanQualityProfile,
            WanWorkflowBuilder,
        )

        generation = self._generation_request()
        compiled = CompiledWanPrompt.model_validate(
            self._json_artifact("compiled_prompt")
        )
        mode = str(self.request.structured_inputs["mode"])
        if generation.mode.value != mode:
            raise DagWorkerError(
                "video mode does not match generation request"
            )
        seed = int(self.request.parameter_snapshot["seed"])
        if generation.resolved_seed != seed:
            raise DagWorkerError(
                "video seed does not match generation request"
            )
        quality = WanQualityProfile(
            str(
                self.request.structured_inputs.get("quality")
                or WanQualityProfile.QUALITY.value
            )
        )
        first = None
        last = None
        if generation.mode is GenerationMode.T2V:
            pass
        elif generation.mode is GenerationMode.I2V:
            first = self._artifact_by_roles("first_frame")
            if first is None:
                raise DagWorkerError(
                    "i2v video generation requires first_frame"
                )
        elif generation.mode is GenerationMode.FIRST_LAST_FRAME:
            first = self._artifact_by_roles("first_frame")
            last = self._artifact_by_roles("last_frame")
            if first is None or last is None:
                raise DagWorkerError(
                    "first_last_frame video generation requires both frames"
                )
        with tempfile.TemporaryDirectory(
            prefix="creative-hub-wan-input-"
        ) as raw:
            staging = Path(raw)
            first_name = self._upload_frame(
                first,
                staging,
                subfolder=f"creative-hub/{self.request.operation_attempt_id}",
            )
            last_name = self._upload_frame(
                last,
                staging,
                subfolder=f"creative-hub/{self.request.operation_attempt_id}",
            )
            build = WanWorkflowBuilder().build(
                request=generation,
                compiled=compiled,
                quality=quality,
                first_image_filename=first_name,
                last_image_filename=last_name,
            )
        return build.workflow

    def _output_role(self) -> str:
        intent = self._json_artifact("generation_intent")
        role = str(intent.get("output_role") or "")
        if (
            not role.startswith("clip.")
            or len(role) > 160
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
                for character in role
            )
        ):
            raise DagWorkerError(
                "generation_intent output_role is invalid"
            )
        return role

    def _upload_frame(
        self,
        artifact: AtomicArtifactRef | None,
        staging: Path,
        *,
        subfolder: str,
    ) -> str | None:
        if artifact is None:
            return None
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(artifact.mime_type, ".bin")
        path = staging / f"{artifact.artifact_id}{suffix}"
        path.write_bytes(self.gateway.read_bytes(artifact))
        return self.comfy.upload_image(path, subfolder=subfolder)

    def _json_artifact(self, role: str) -> Mapping[str, Any]:
        artifact = self._artifact_by_roles(role)
        if artifact is None:
            raise DagWorkerError(
                f"video.generate requires {role} ArtifactRef"
            )
        try:
            payload = json.loads(
                self.gateway.read_bytes(artifact).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DagWorkerError(
                f"video.generate {role} is not UTF-8 JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise DagWorkerError(
                f"video.generate {role} must contain a JSON object"
            )
        return payload

    def _artifact_by_roles(
        self,
        *roles: str,
    ) -> AtomicArtifactRef | None:
        allowed = set(roles)
        matches = [
            item
            for item in self.request.input_artifact_refs
            if item.logical_role in allowed
        ]
        if len(matches) > 1:
            raise DagWorkerError(
                "video.generate received ambiguous ArtifactRefs for "
                + "/".join(roles)
            )
        return matches[0] if matches else None

    def _artifact_rows(self) -> list[ArtifactRecordRow]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(ArtifactRecordRow)
                    .where(
                        ArtifactRecordRow.project_id
                        == self.request.project_id,
                        ArtifactRecordRow.operation_run_id
                        == self.request.operation_run_id,
                        ArtifactRecordRow.operation_attempt_id
                        == self.request.operation_attempt_id,
                        ArtifactRecordRow.status == "COMMITTED",
                    )
                    .order_by(
                        ArtifactRecordRow.logical_role,
                        ArtifactRecordRow.id,
                    )
                )
            )


def _persistent_provider_artifacts(
    session_factory: Callable[[], Session],
    request: OperationRequest,
):
    from shared_contracts import PersistentArtifactRef

    with session_factory() as session:
        rows = session.scalars(
            select(ArtifactRecordRow)
            .where(
                ArtifactRecordRow.project_id == request.project_id,
                ArtifactRecordRow.operation_run_id
                == request.operation_run_id,
                ArtifactRecordRow.operation_attempt_id
                == request.operation_attempt_id,
                ArtifactRecordRow.status == "COMMITTED",
            )
            .order_by(
                ArtifactRecordRow.logical_role, ArtifactRecordRow.id
            )
        ).all()
        return tuple(
            PersistentArtifactRef(
                artifact_id=row.id,
                project_id=row.project_id,
                content_digest=row.content_digest,
                mime_type=row.mime_type,
                byte_size=row.byte_size,
                logical_role=row.logical_role,
                storage_uri=row.storage_uri,
                produced_by_operation_run_id=row.operation_run_id,
                produced_by_operation_attempt_id=(
                    row.operation_attempt_id
                ),
                created_at=row.created_at,
                retention_class=RetentionClass(row.retention_class),
            )
            for row in rows
        )


def _video_provider_context(
    *,
    request: OperationRequest,
    artifact_gateway: object,
    session_factory: Callable[[], Session],
    comfy_transport: object | None = None,
    output_verifier: object | None = None,
):
    from drama.atomic_provider import DurableProviderAtomicExecutorContext
    from drama.v3.durable_provider import (
        DurableProviderCoordinator,
        ProviderGrantAction,
        ProviderInvocationPhase,
    )

    store = PostgresDurableProviderStore(session_factory)
    transport = _DurableLocalWanTransport(
        request=request,
        gateway=artifact_gateway,
        session_factory=session_factory,
        comfy_transport=comfy_transport,
        output_verifier=output_verifier,
    )
    coordinator = DurableProviderCoordinator(
        store=store,
        transport=transport,
    )
    invocation_id = uuid5(
        _CONTROL_NAMESPACE,
        f"provider:{request.operation_attempt_id}:local-wan-comfy",
    )
    attempt = None
    with session_factory() as session:
        attempt = session.get(
            OperationAttemptRecord, request.operation_attempt_id
        )
    if attempt is None:
        raise DagWorkerError("video Attempt is unavailable")
    invocation = coordinator.prepare(
        invocation_id=invocation_id,
        project_id=request.project_id,
        operation_run_id=request.operation_run_id,
        operation_attempt_id=request.operation_attempt_id,
        client_token=f"wan-{request.operation_attempt_id.hex}",
        submission_nonce=attempt.submission_nonce,
        request_payload=request.model_dump(mode="json"),
    )
    if invocation.phase is ProviderInvocationPhase.PREPARED:
        action = ProviderGrantAction.SUBMIT
    elif invocation.phase in {
        ProviderInvocationPhase.SUBMITTED,
        ProviderInvocationPhase.OUTCOME_UNKNOWN,
    }:
        action = ProviderGrantAction.RECONCILE
    elif invocation.phase in {
        ProviderInvocationPhase.OBSERVED_TERMINAL,
        ProviderInvocationPhase.MATERIALIZING,
        ProviderInvocationPhase.COMMITTED,
    } and (
        invocation.terminal_outcome is None
        or invocation.terminal_outcome.value == "SUCCEEDED"
    ):
        action = ProviderGrantAction.MATERIALIZE
    else:
        action = ProviderGrantAction.RECONCILE
    grant = store.grant(
        invocation_id,
        action,
        reason=f"{action.value.lower()} local Wan task",
    )
    materializer = None
    if action is ProviderGrantAction.MATERIALIZE:
        materializer = transport.materialize
    return DurableProviderAtomicExecutorContext(
        coordinator=coordinator,
        invocation_id=invocation_id,
        workflow_run_id=request.workflow_run_id,
        grant=grant,
        artifact_resolver=lambda _invocation: (
            _persistent_provider_artifacts(session_factory, request)
        ),
        materializer=materializer,
        actual_cost_micros=0 if materializer is not None else None,
    )


def _production_context_factory(
    registry: CapabilityRegistry,
    *,
    analysis_runtime_root: Path,
    session_factory: Callable[[], Session] | None = None,
    credential_resolver: Callable[[str, str], str] | None = None,
    quality_evaluator_backend_factory: Callable[..., object] | None = None,
    h3_backend_factory: Callable[..., object] | None = None,
    h3_final_assembly_runner_factory: Callable[..., object] | None = None,
    shidu_tts_provider_factory: Callable[[OperationRequest], object]
    | None = None,
    shidu_final_audio_authority_resolver_factory: Callable[
        [OperationRequest], object
    ]
    | None = None,
    gpu_index: int | None = None,
) -> ContextFactory:
    project_root = Path(
        os.getenv("FACTORY_PROJECT_ROOT", "/workspace/drama_factory")
    )
    config_dir = Path(
        os.getenv("FACTORY_CONFIG_DIR", "/workspace/drama_factory/config")
    )
    if quality_evaluator_backend_factory is None:
        from .quality_atomic import configured_quality_backend_factory

        quality_evaluator_backend_factory = (
            configured_quality_backend_factory()
        )
    audio_provider = None

    def speech_audio_provider() -> object | None:
        nonlocal audio_provider
        if gpu_index is None:
            return None
        if audio_provider is not None:
            return audio_provider
        from douyin_analysis.evidence_audio import (
            FallbackAudioAnalyzer,
            SenseVoiceFunASRAdapter,
            WhisperEvidenceAdapter,
        )
        from douyin_analysis.semantic_adapters import (
            FasterWhisperAdapter,
            run_semantic_preflight,
        )

        model_root = Path(
            os.getenv("ANALYSIS_MODEL_ROOT", "/runtime/models")
        )
        generation_root = run_semantic_preflight(model_root)
        lease_manager = _InlineGpuLeaseManager(gpu_index)
        audio_provider = FallbackAudioAnalyzer(
            primary=SenseVoiceFunASRAdapter(
                lease_manager=lease_manager,
                model_cache_root=model_root,
            ),
            fallback=WhisperEvidenceAdapter(
                transcriber=FasterWhisperAdapter(
                    lease_manager=lease_manager,
                ),
                model_cache_root=generation_root,
            ),
        )
        return audio_provider

    def context_for(
        request: OperationRequest,
        artifact_gateway: object,
    ) -> object:
        if request.op_type.startswith("qc.evaluate."):
            from .quality_atomic import (
                QualityExecutorContext,
                UnavailableQualityEvaluatorBackend,
            )

            if quality_evaluator_backend_factory is not None:
                backend = quality_evaluator_backend_factory(
                    request=request,
                    artifact_gateway=artifact_gateway,
                    credential_resolver=credential_resolver,
                )
            elif credential_resolver is not None:
                from .quality_cloud import (
                    QwenFrameAudioQualityBackend,
                )

                backend = QwenFrameAudioQualityBackend(
                    artifacts=artifact_gateway,
                    credential_provider=credential_resolver,
                    model_root=Path(
                        os.getenv(
                            "ANALYSIS_MODEL_ROOT",
                            "/runtime/models",
                        )
                    ),
                )
            else:
                backend = UnavailableQualityEvaluatorBackend()
            return QualityExecutorContext(
                backend=backend,
                clock=lambda: datetime.now(timezone.utc),
            )
        if request.op_type in {
            "source.resolve",
            "media.probe",
            "audio.extract",
            "scene.detect",
            "frame.plan",
            "frame.extract",
            "speech.transcribe",
            "audio.annotate",
            "evidence.align",
        }:
            from douyin_analysis.evidence_atomic import (
                EvidenceExecutorContext,
            )
            from douyin_analysis.evidence_cache import (
                ReusableEvidenceCache,
            )
            from douyin_analysis.media_atomic import MediaAtomicBackend

            return EvidenceExecutorContext(
                backend=MediaAtomicBackend(
                    artifacts=GatewayEvidenceArtifactIO(
                        gateway=artifact_gateway,
                        root=analysis_runtime_root / "inputs",
                    ),
                    cache=ReusableEvidenceCache(
                        analysis_runtime_root / "evidence-cache"
                    ),
                    audio_provider=(
                        speech_audio_provider()
                        if request.op_type == "speech.transcribe"
                        else None
                    ),
                ),
                clock=lambda: datetime.now(timezone.utc),
            )
        if request.op_type == "analysis.semantic_extract":
            if credential_resolver is None:
                raise DagWorkerError(
                    "semantic credential resolver is unavailable"
                )
            from douyin_analysis.atomic_adapter import (
                SemanticExecutorContext,
            )
            from douyin_analysis.cloud_vision import (
                CloudVisionAdapter,
                GlmVisionMcpClient,
                QwenVisionClient,
            )
            from douyin_analysis.semantic_atomic_backend import (
                ProductionSemanticAtomicBackend,
            )

            return SemanticExecutorContext(
                backend=ProductionSemanticAtomicBackend(
                    artifacts=artifact_gateway,
                    vision=CloudVisionAdapter(
                        QwenVisionClient(
                            credential_provider=credential_resolver
                        ),
                        GlmVisionMcpClient(
                            credential_provider=credential_resolver
                        ),
                    ),
                    workspace_root=(
                        analysis_runtime_root / "semantic-workspaces"
                    ),
                ),
                clock=lambda: datetime.now(timezone.utc),
            )
        if request.op_type == "video.generate":
            if session_factory is None:
                raise DagWorkerError(
                    "video provider persistence is not configured"
                )
            return _video_provider_context(
                request=request,
                artifact_gateway=artifact_gateway,
                session_factory=session_factory,
            )
        h3_final_profile = {
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_source": "h3_native",
            "subtitles": False,
        }
        is_h3_final_assembly = (
            request.op_type == "final.assemble"
            and dict(request.structured_inputs) == h3_final_profile
            and bool(request.input_artifact_refs)
            and all(
                re.fullmatch(
                    r"h3\.sequence\.\d{3}\.attempt\.[01]\.video",
                    ref.logical_role,
                )
                for ref in request.input_artifact_refs
            )
        )
        if is_h3_final_assembly:
            from drama.atomic_factory import FactoryAtomicExecutorContext

            registration = registry.resolve_request(request)
            provider_identity = (
                registration.implementation_manifest.provider_identity
            )
            if not provider_identity:
                raise DagWorkerError(
                    "H3 final-assembly provider identity is not pinned"
                )
            if h3_final_assembly_runner_factory is not None:
                runner = h3_final_assembly_runner_factory(
                    request=request,
                    artifact_gateway=artifact_gateway,
                )
            else:
                if session_factory is None:
                    raise DagWorkerError(
                        "H3 final-assembly persistence is not configured"
                    )
                from drama.h3.assembly import (
                    H3AssemblyAdapter,
                    H3SelectedSegment,
                )

                from .h3_final_assembly import (
                    H3AssemblyFfmpegConcatRunner,
                    H3AssemblyFfprobeBackend,
                    H3FinalAssemblyRunner,
                )
                from .h3_repository import H3Repository

                def load_authority(
                    project_id: UUID,
                    workflow_run_id: UUID,
                ) -> tuple[UUID, tuple[H3SelectedSegment, ...]]:
                    with session_factory() as session:
                        return H3Repository(session).load_h3_assembly_authority(
                            project_id,
                            workflow_run_id,
                        )

                runner = H3FinalAssemblyRunner(
                    authority_loader=load_authority,
                    assembly_adapter=H3AssemblyAdapter(
                        probe=H3AssemblyFfprobeBackend(),
                        concat_runner=H3AssemblyFfmpegConcatRunner(),
                    ),
                )
            return FactoryAtomicExecutorContext(
                op_type=request.op_type,
                project_id=request.project_id,
                workflow_run_id=request.workflow_run_id,
                operation_run_id=request.operation_run_id,
                operation_attempt_id=request.operation_attempt_id,
                operation_spec_digest=request.operation_spec_digest,
                implementation_digest=request.implementation_digest,
                runner=runner,  # type: ignore[arg-type]
                artifacts=artifact_gateway,  # type: ignore[arg-type]
                determinism_class=registration.spec.determinism_class,
                provider_identity=provider_identity,
            )
        from .h3_atomic_runtime import (
            H3AtomicExecutorContext,
            H3_OPERATION_TYPES,
        )

        if request.op_type in H3_OPERATION_TYPES:
            if h3_backend_factory is None:
                raise DagWorkerError("H3 backend is not configured")
            registration = registry.resolve_request(request)
            provider_identity = (
                registration.implementation_manifest.provider_identity
            )
            if not provider_identity:
                raise DagWorkerError("H3 provider identity is not pinned")
            backend = h3_backend_factory(
                request=request,
                artifact_gateway=artifact_gateway,
                credential_resolver=credential_resolver,
            )
            if backend is None:
                raise DagWorkerError("H3 backend factory returned no backend")
            return H3AtomicExecutorContext(
                op_type=request.op_type,
                project_id=request.project_id,
                workflow_run_id=request.workflow_run_id,
                operation_run_id=request.operation_run_id,
                operation_attempt_id=request.operation_attempt_id,
                operation_spec_digest=request.operation_spec_digest,
                implementation_digest=request.implementation_digest,
                backend=backend,  # type: ignore[arg-type]
                artifacts=artifact_gateway,  # type: ignore[arg-type]
                provider_identity=provider_identity,
                clock=lambda: datetime.now(timezone.utc),
            )
        from drama.atomic_factory import FactoryAtomicExecutorContext
        from drama.atomic_legacy import LegacyFactoryOperationRunner
        from drama.context import Context

        core = Context(
            project_root=project_root,
            config_dir=config_dir,
            dry_run=os.getenv("FACTORY_DRY_RUN", "0") == "1",
            credential_resolver=credential_resolver,
        )
        registration = registry.resolve_request(request)
        is_shidu = (
            request.structured_inputs.get("compiler_revision")
            == "shidu-episode-compiler.v2"
        )
        tts_provider = None
        if is_shidu and request.op_type == "speech.synthesize":
            if shidu_tts_provider_factory is None:
                raise DagWorkerError(
                    "Shidu Qwen CustomVoice provider is not configured"
                )
            tts_provider = shidu_tts_provider_factory(request)
        final_audio_resolver = None
        if is_shidu and request.op_type == "audio.mix":
            if shidu_final_audio_authority_resolver_factory is None:
                raise DagWorkerError(
                    "Shidu final-audio authority resolver is not configured"
                )
            final_audio_resolver = (
                shidu_final_audio_authority_resolver_factory(request)
            )
        runner = LegacyFactoryOperationRunner.create(
            core,
            shidu_tts_provider=tts_provider,  # type: ignore[arg-type]
            shidu_final_audio_authority_resolver=(
                final_audio_resolver  # type: ignore[arg-type]
            ),
        )
        return FactoryAtomicExecutorContext(
            op_type=request.op_type,
            project_id=request.project_id,
            workflow_run_id=request.workflow_run_id,
            operation_run_id=request.operation_run_id,
            operation_attempt_id=request.operation_attempt_id,
            operation_spec_digest=request.operation_spec_digest,
            implementation_digest=request.implementation_digest,
            runner=runner,
            artifacts=artifact_gateway,
            determinism_class=registration.spec.determinism_class,
            provider_identity=(
                registration.implementation_manifest.provider_identity
                or "factory-local-core"
            ),
        )

    return context_for


def _worker_profile(
    name: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    h3_profiles = {
        "shidu-h3-core": (
            ("cpu",),
            (
                "project_ir.generate",
                "character_reference.qc",
                "character_reference.freeze",
                "episode_ir.generate",
                "h3.attempt.select",
            ),
        ),
        "shidu-h3-local": (
            ("local_gpu",),
            ("character_reference.generate", "h3.sequence.execute"),
        ),
    }
    try:
        return h3_profiles[name]
    except KeyError:
        pass

    from drama.atomic_factory import FACTORY_OPERATION_TYPES
    from drama.atomic_plugin import factory_operation_specs

    factory_local_gpu = tuple(
        spec.op_type
        for spec in factory_operation_specs()
        if spec.resource_class is ResourceClass.LOCAL_GPU
    )
    factory_core = tuple(
        value
        for value in FACTORY_OPERATION_TYPES
        if value not in factory_local_gpu
    )
    profiles = {
        "factory-core": (
            tuple(RESOURCE_POOLS),
            factory_core,
        ),
        "video-local": (
            ("local_gpu",),
            factory_local_gpu + ("speech.transcribe",),
        ),
        "shidu-video-local": (
            ("local_gpu",),
            ("keyframe.generate", "video.generate"),
        ),
        "quality-control": (
            ("cpu",),
            (
                "qc.gate.asset",
                "qc.gate.keyframe",
                "qc.gate.clip",
                "qc.gate.final",
                "delivery.publish",
            ),
        ),
    }
    try:
        return profiles[name]
    except KeyError as exc:
        raise DagWorkerError(f"unknown DAG worker profile: {name}") from exc


def build_production_worker(
    *,
    gpu_observation: GpuObservation | None = None,
    h3_backend_factory: Callable[..., object] | None = None,
    shidu_tts_provider_factory: Callable[[OperationRequest], object]
    | None = None,
    shidu_final_audio_authority_resolver_factory: Callable[
        [OperationRequest], object
    ]
    | None = None,
) -> DurableDagWorker:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from .artifact_publication import (
        ArtifactPublicationService,
        ContentAddressedArtifactStore,
        PostgresArtifactRepository,
    )
    from .budget_provisioning import ensure_global_budget_accounts
    from .cost_budgets import CostBudgetGuard
    from .credentials import CredentialVault
    from .lineage import PostgresArtifactLineageGraph
    from .runtime_bootstrap import (
        database_url,
        load_atomic_capability_registry,
        load_cost_budget_policy,
    )
    from .workflow_runtime import (
        PublicationArtifactGateway,
        database_attempt_identity,
    )

    orchestration_url = (
        os.getenv("CREATIVE_ORCHESTRATION_DATABASE_URL")
        or database_url("CREATIVE_ORCHESTRATION")
    )
    engine = create_engine(orchestration_url, pool_pre_ping=True)
    sessions = sessionmaker(engine, expire_on_commit=False)
    profile = os.getenv(
        "CREATIVE_HUB_DAG_WORKER_PROFILE", "factory-core"
    )
    credential_resolver = None
    if profile in {
        "factory-core",
        "video-local",
        "shidu-video-local",
        "quality-control",
    }:
        hub_engine = create_engine(
            database_url("CREATIVE_HUB"),
            pool_pre_ping=True,
        )
        hub_sessions = sessionmaker(
            hub_engine,
            expire_on_commit=False,
        )
        credential_vault = CredentialVault.from_file(
            Path(
                os.getenv(
                    "CREATIVE_HUB_CREDENTIAL_MASTER_KEY_FILE",
                    "/run/secrets/creative-hub-credential-master-key",
                )
            )
        )

        def resolve_credential(provider: str, model: str) -> str:
            with hub_sessions() as session:
                key, _revision = credential_vault.resolve(
                    session,
                    provider=provider,
                    model_name=model,
                )
                return key

        credential_resolver = resolve_credential
    registry = load_atomic_capability_registry()
    if profile in {"video-local", "shidu-video-local"} and gpu_observation is None:
        raise DagWorkerError(
            "local GPU worker requires an exact capability observation"
        )
    budget_policy = load_cost_budget_policy()
    with sessions() as session, session.begin():
        ensure_global_budget_accounts(session, budget_policy)
    budget_guard = CostBudgetGuard(budget_policy)
    store = ContentAddressedArtifactStore(
        Path(
            os.getenv(
                "CREATIVE_HUB_ARTIFACT_STORE_ROOT",
                "/runtime/creative-hub/artifacts",
            )
        )
    )
    repository = PostgresArtifactRepository(sessions)
    publication = ArtifactPublicationService(
        repository=repository,
        store=store,
    )
    lineage = PostgresArtifactLineageGraph(sessions)

    def gateway_factory() -> PublicationArtifactGateway:
        return PublicationArtifactGateway(
            publication=publication,
            repository=repository,
            store=store,
            lineage=lineage,
            attempt_identity=database_attempt_identity(sessions),
        )

    resource_pools, operation_types = _worker_profile(profile)
    context_factory = _production_context_factory(
        registry,
        analysis_runtime_root=Path(
            os.getenv(
                "ANALYSIS_ATOMIC_RUNTIME_ROOT",
                "/runtime/analysis/atomic",
            )
        ),
        session_factory=sessions,
        credential_resolver=credential_resolver,
        h3_backend_factory=h3_backend_factory,
        shidu_tts_provider_factory=shidu_tts_provider_factory,
        shidu_final_audio_authority_resolver_factory=(
            shidu_final_audio_authority_resolver_factory
        ),
        gpu_index=(
            gpu_observation.gpu_index
            if gpu_observation is not None
            else None
        ),
    )
    return DurableDagWorker(
        session_factory=sessions,
        scheduler_factory=lambda session: DurableDagScheduler(
            session,
            budget_guard=budget_guard,
        ),
        capability_registry=registry,
        artifact_gateway_factory=gateway_factory,
        context_factory=context_factory,
        worker_id=os.getenv(
            "CREATIVE_HUB_DAG_WORKER_ID",
            f"{socket.gethostname()}-{os.getpid()}",
        ),
        resource_pools=resource_pools,
        operation_types=operation_types,
        operation_matcher=_gpu_operation_matcher(
            registry, gpu_observation
        ),
        control_dispatcher=DurableQualityControlDispatcher(
            session_factory=sessions,
            capability_registry=registry,
            artifact_gateway_factory=gateway_factory,
            context_factory=context_factory,
            scheduler_factory=lambda session: DurableDagScheduler(
                session,
                budget_guard=budget_guard,
            ),
        ),
        lease_duration=timedelta(
            seconds=float(
                os.getenv(
                    "CREATIVE_HUB_DAG_LEASE_SECONDS", "3600"
                )
            )
        ),
    )


def _gpu_observation_from_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> GpuObservation | None:
    supplied = any(
        (
            args.gpu_index is not None,
            args.total_vram_mib is not None,
            args.free_vram_mib is not None,
            bool(args.model_digest),
            bool(args.workflow_digest),
            bool(args.custom_node_environment_digest),
            bool(args.implementation_manifest_digest),
        )
    )
    if not supplied:
        return None
    if (
        args.gpu_index is None
        or args.total_vram_mib is None
        or not args.model_digest
        or not args.workflow_digest
        or not args.custom_node_environment_digest
        or not args.implementation_manifest_digest
    ):
        parser.error(
            "GPU capability flags must provide index, VRAM, model, "
            "workflow, custom-node environment, and implementation digests"
        )
    return GpuObservation(
        gpu_index=args.gpu_index,
        total_vram_mib=args.total_vram_mib,
        free_vram_mib=(
            args.total_vram_mib
            if args.free_vram_mib is None
            else args.free_vram_mib
        ),
        device_type=args.device_type,
        model_digests=tuple(args.model_digest),
        workflow_digests=tuple(args.workflow_digest),
        custom_node_environment_digest=(
            args.custom_node_environment_digest[0]
        ),
        custom_node_environment_digests=tuple(
            args.custom_node_environment_digest[1:]
        ),
        implementation_manifest_digests=tuple(
            args.implementation_manifest_digest
        ),
        worker_id=os.getenv("CREATIVE_HUB_DAG_WORKER_ID"),
    )


def _build_shidu_tts_provider(
    request: OperationRequest,
    *,
    transport: object,
) -> object:
    """Bind the provider to the exact policy frozen into this speech request."""
    from drama.v3.qwen_tts_mcp import (
        DEFAULT_CHINESE_SPEAKERS,
        PHASE_TWO_CHINESE_SPEAKERS,
        Qwen3TTSMCPProvider,
    )

    raw_snapshot = request.structured_inputs.get("voice_preset_snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raise DagWorkerError(
            "Shidu speech requires a frozen TTS speaker policy"
        )
    raw_policy = raw_snapshot.get("policy_allowed_speakers")
    if (
        not isinstance(raw_policy, list)
        or not 1 <= len(raw_policy) <= 4
        or any(
            not isinstance(speaker, str)
            or not speaker
            or speaker != speaker.strip()
            for speaker in raw_policy
        )
        or len(set(raw_policy)) != len(raw_policy)
    ):
        raise DagWorkerError("Shidu frozen TTS speaker policy is invalid")
    policy_allowed_speakers = tuple(raw_policy)
    allowed = frozenset(policy_allowed_speakers)
    if (
        not DEFAULT_CHINESE_SPEAKERS.issubset(allowed)
        or not allowed.issubset(PHASE_TWO_CHINESE_SPEAKERS)
    ):
        raise DagWorkerError("Shidu frozen TTS speaker policy is invalid")
    maximum_cue_overrun_ms = request.structured_inputs.get(
        "maximum_cue_overrun_ms"
    )
    if (
        isinstance(maximum_cue_overrun_ms, bool)
        or not isinstance(maximum_cue_overrun_ms, int)
        or not 0 <= maximum_cue_overrun_ms <= 5_000
    ):
        raise DagWorkerError("Shidu frozen TTS duration policy is invalid")
    return Qwen3TTSMCPProvider(
        transport=transport,  # type: ignore[arg-type]
        policy_allowed_speakers=policy_allowed_speakers,
        maximum_duration_overrun_seconds=maximum_cue_overrun_ms / 1_000,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the unified Creative Hub durable DAG worker"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process at most one ready operation",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(
            os.getenv("CREATIVE_HUB_DAG_POLL_INTERVAL_SECONDS", "1")
        ),
    )
    parser.add_argument("--gpu-index", type=int)
    parser.add_argument("--total-vram-mib", type=int)
    parser.add_argument("--free-vram-mib", type=int)
    parser.add_argument("--device-type", default="cuda")
    parser.add_argument("--model-digest", action="append", default=[])
    parser.add_argument("--workflow-digest", action="append", default=[])
    parser.add_argument(
        "--custom-node-environment-digest",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--implementation-manifest-digest",
        action="append",
        default=[],
    )
    args = parser.parse_args()
    shidu_tts_factory = None
    shidu_audio_factory = None
    tts_endpoint = os.getenv("SHIDU_TTS_MCP_ENDPOINT", "").strip()
    audio_authority_file = os.getenv(
        "SHIDU_AUDIO_AUTHORITY_FILE", ""
    ).strip()
    project_id = os.getenv("SHIDU_PROJECT_ID", "").strip()
    if tts_endpoint:
        from .shidu.qwen_tts_transport import (
            StreamableHttpQwenTTSMCPTransport,
        )

        transport = StreamableHttpQwenTTSMCPTransport(tts_endpoint)

        def shidu_tts_factory(request: OperationRequest) -> object:
            return _build_shidu_tts_provider(
                request,
                transport=transport,
            )

    if audio_authority_file and project_id:
        from .shidu.audio_authority import (
            load_frozen_audio_authority_resolver,
        )

        resolver = load_frozen_audio_authority_resolver(
            audio_authority_file,
            expected_project_id=UUID(project_id),
        )

        def shidu_audio_factory(_request: OperationRequest) -> object:
            return resolver

    worker = build_production_worker(
        gpu_observation=_gpu_observation_from_args(args, parser),
        shidu_tts_provider_factory=shidu_tts_factory,
        shidu_final_audio_authority_resolver_factory=(
            shidu_audio_factory
        ),
    )
    if args.once:
        worker.run_once()
    else:
        worker.run_forever(poll_interval_seconds=args.poll_interval)


__all__ = [
    "ControlAction",
    "ControlOutcome",
    "DagWorkerError",
    "DurableDagWorker",
    "OperationRequestBuilder",
    "TickOutcome",
    "WorkerTick",
    "build_production_worker",
    "default_control_dispatcher",
    "main",
]


if __name__ == "__main__":
    main()
