"""Restart-safe coordinator for the clicked AMD competition vertical slice.

This module is deliberately an orchestration boundary, not a provider factory.
Every production side effect is supplied through a narrow port.  In
particular, constructing the coordinator cannot start FLUX, H3, ComfyUI, or a
GPU process.  The first durable action is always to validate and checkpoint an
already-persisted ``h3_deferred_vertical_slice`` video-job projection created
by the user's button click.

Individual ports must be idempotent for the supplied key.  That requirement is
what closes the unavoidable process-crash window between a successful remote
side effect and the following coordinator checkpoint write.  The FLUX/H3 ports
are expected to delegate to the staged runner, whose own prompt and output
checkpoints provide the stronger no-resubmit fence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Any, Literal, Protocol
from uuid import UUID

from creative_hub.db.canonical import canonical_json_digest


_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,99}\Z")
_STAGE_ORDER = (
    "source_prepared",
    "flux_generated",
    "references_published",
    "authority_finalized",
    "workflow_materialized",
    "h3_generated",
    "delivered",
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)

WorkerStage = Literal[
    "source_prepared",
    "flux_generated",
    "references_published",
    "authority_finalized",
    "workflow_materialized",
    "h3_generated",
    "delivered",
]
CompletedStage = Literal[
    "clicked",
    "source_prepared",
    "flux_generated",
    "references_published",
    "authority_finalized",
    "workflow_materialized",
    "h3_generated",
    "delivered",
]
WorkerStatus = Literal[
    "active", "retryable_failed", "terminal_failed", "delivered"
]


class CoordinatorContractError(ValueError):
    """Persisted click or checkpoint authority is invalid; fail closed."""


class WorkerStepError(RuntimeError):
    """A safe, classified worker-port failure."""

    retryable: bool

    def __init__(self, stage: WorkerStage, safe_error_code: str) -> None:
        if stage not in _STAGE_ORDER:
            raise ValueError("worker error stage is invalid")
        if (
            type(safe_error_code) is not str
            or _ERROR_CODE_RE.fullmatch(safe_error_code) is None
        ):
            raise ValueError("worker safe error code is invalid")
        self.stage = stage
        self.safe_error_code = safe_error_code
        super().__init__(f"competition vertical-slice step failed: {safe_error_code}")


class RetryableWorkerStepError(WorkerStepError):
    retryable = True


class TerminalWorkerStepError(WorkerStepError):
    retryable = False


def _require_digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise CoordinatorContractError(f"{field} must be a lowercase SHA-256")
    return value


def _require_uuid(value: object, field: str) -> UUID:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise CoordinatorContractError(f"{field} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise CoordinatorContractError(f"{field} must be a UUID") from exc
    if str(parsed) != value:
        raise CoordinatorContractError(f"{field} must use canonical UUID text")
    return parsed


def _require_text(value: object, field: str, *, limit: int = 255) -> str:
    if type(value) is not str:
        raise CoordinatorContractError(f"{field} must be text")
    normalized = " ".join(value.split())
    if not normalized or normalized != value or len(value) > limit:
        raise CoordinatorContractError(f"{field} is invalid")
    return value


def _reject_secret_fields(value: object) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                if str(key).casefold() in _SECRET_KEYS:
                    raise CoordinatorContractError(
                        "durable worker receipt contains a secret field"
                    )
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)


def _json_object(value: object, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CoordinatorContractError(f"{field} must be a standard JSON object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoordinatorContractError(f"{field} must be standard JSON") from exc
    if type(decoded) is not dict:
        raise CoordinatorContractError(f"{field} must be a standard JSON object")
    _reject_secret_fields(decoded)
    return decoded


def _projection_value(record: object, name: str) -> object:
    if not hasattr(record, name):
        raise CoordinatorContractError(f"video-job projection is missing {name}")
    return getattr(record, name)


@dataclass(frozen=True, slots=True)
class ClickedDeferredVideoJob:
    """Immutable click identity projected from ``VideoJobProjectionRecord``.

    ``pipeline_mode`` and ``workflow_run_id`` are mutable progress fields and
    therefore are intentionally excluded from ``authority_digest``.  This lets
    the same clicked authority survive the deferred-to-materialized transition.
    """

    project_id: UUID
    book_id: UUID
    trial_script_revision_id: UUID
    direction_revision_id: UUID
    research_job_id: UUID
    external_job_id: str
    command_idempotency_key: str
    request_digest: str
    safety_decision_digest: str
    content_mode: str
    content_label: str
    content_notice: str
    prepared_reference: Mapping[str, Any] | None
    pipeline_mode: Literal["h3_deferred_vertical_slice", "h3_vertical_slice"]
    workflow_run_id: UUID | None
    authority_digest: str

    @classmethod
    def from_projection_record(cls, record: object) -> ClickedDeferredVideoJob:
        payload = _json_object(_projection_value(record, "payload"), "video-job payload")
        project_id = _require_uuid(_projection_value(record, "project_id"), "project_id")
        book_id = _require_uuid(_projection_value(record, "book_id"), "book_id")
        script_id = _require_uuid(
            _projection_value(record, "trial_script_revision_id"),
            "trial_script_revision_id",
        )
        status = _projection_value(record, "status")
        if status not in {"queued", "processing"}:
            raise CoordinatorContractError("video job is not a clicked runnable job")
        pipeline = payload.get("pipelineMode")
        if pipeline not in {"h3_deferred_vertical_slice", "h3_vertical_slice"}:
            raise CoordinatorContractError("video job is not the competition H3 pipeline")
        if type(payload.get("targetDurationSeconds")) is not float or (
            payload["targetDurationSeconds"] != 3.0
        ):
            raise CoordinatorContractError("clicked request must target 3.0 seconds")
        if type(payload.get("sequenceCount")) is not int or payload["sequenceCount"] != 1:
            raise CoordinatorContractError("clicked request must contain one sequence")
        optional_fixed = {
            "frameCount": 73,
            "fps": 24,
            "nativeAudio": True,
            "subtitles": False,
        }
        for field, expected in optional_fixed.items():
            if field in payload and (
                type(payload[field]) is not type(expected) or payload[field] != expected
            ):
                raise CoordinatorContractError(f"clicked request has invalid {field}")

        payload_book = _require_uuid(payload.get("bookId"), "payload.bookId")
        payload_script = _require_uuid(
            payload.get("trialScriptRevisionId"),
            "payload.trialScriptRevisionId",
        )
        if payload_book != book_id or payload_script != script_id:
            raise CoordinatorContractError("clicked job lineage does not match its row")
        direction_id = _require_uuid(
            payload.get("directionRevisionId"), "payload.directionRevisionId"
        )
        research_id = _require_uuid(
            payload.get("researchJobId"), "payload.researchJobId"
        )
        workflow_value = payload.get("workflowRunId")
        if pipeline == "h3_deferred_vertical_slice":
            if workflow_value is not None:
                raise CoordinatorContractError(
                    "deferred clicked job cannot already name a workflow"
                )
            workflow_id = None
        else:
            workflow_id = _require_uuid(workflow_value, "payload.workflowRunId")

        external_job_id = _require_text(
            _projection_value(record, "external_job_id"), "external_job_id", limit=200
        )
        if not external_job_id.startswith("shidu_"):
            raise CoordinatorContractError("external_job_id is not a Shidu click")
        command_key = _require_text(
            _projection_value(record, "command_idempotency_key"),
            "command_idempotency_key",
        )
        request_digest = _require_digest(payload.get("requestDigest"), "requestDigest")
        safety_digest = _require_digest(
            payload.get("safetyDecisionDigest"), "safetyDecisionDigest"
        )
        content_mode = _require_text(payload.get("contentMode"), "contentMode", limit=64)
        content_label = _require_text(payload.get("contentLabel"), "contentLabel")
        content_notice = _require_text(
            payload.get("contentNotice"), "contentNotice", limit=1000
        )
        prepared_reference_value = payload.get("competitionPreparedReference")
        if prepared_reference_value is None and pipeline == "h3_deferred_vertical_slice":
            raise CoordinatorContractError(
                "competition H3 job requires an imported reference binding"
            )
        prepared_reference: dict[str, Any] | None = None
        if prepared_reference_value is not None:
            prepared_reference = _json_object(
                prepared_reference_value, "competitionPreparedReference"
            )
            if set(prepared_reference) != {
                "requestId",
                "artifactSha256",
                "sourceMode",
                "importAuthoritySha256",
            }:
                raise CoordinatorContractError(
                    "prepared reference binding fields are invalid"
                )
            _require_uuid(prepared_reference["requestId"], "prepared requestId")
            if prepared_reference["sourceMode"] != "preuploaded_imported":
                raise CoordinatorContractError(
                    "prepared reference source mode is invalid"
                )
            for field in (
                "artifactSha256",
                "importAuthoritySha256",
            ):
                _require_digest(prepared_reference[field], f"prepared {field}")
        identity = {
            "schemaVersion": "amd.clicked-deferred-video-job.v1",
            "projectId": str(project_id),
            "bookId": str(book_id),
            "trialScriptRevisionId": str(script_id),
            "directionRevisionId": str(direction_id),
            "researchJobId": str(research_id),
            "externalJobId": external_job_id,
            "commandIdempotencyKey": command_key,
            "requestDigest": request_digest,
            "safetyDecisionDigest": safety_digest,
            "contentMode": content_mode,
            "contentLabel": content_label,
            "contentNotice": content_notice,
            "requestedDurationSeconds": 3.0,
            "frameCount": 73,
            "fps": 24,
            "nativeAudio": True,
            "subtitles": False,
        }
        if prepared_reference is not None:
            identity["preparedReference"] = prepared_reference
        return cls(
            project_id=project_id,
            book_id=book_id,
            trial_script_revision_id=script_id,
            direction_revision_id=direction_id,
            research_job_id=research_id,
            external_job_id=external_job_id,
            command_idempotency_key=command_key,
            request_digest=request_digest,
            safety_decision_digest=safety_digest,
            content_mode=content_mode,
            content_label=content_label,
            content_notice=content_notice,
            prepared_reference=prepared_reference,
            pipeline_mode=pipeline,
            workflow_run_id=workflow_id,
            authority_digest=canonical_json_digest(identity),
        )


@dataclass(frozen=True, slots=True)
class StageReceipt:
    stage: WorkerStage
    job_authority_digest: str
    payload: Mapping[str, Any]
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.stage not in _STAGE_ORDER:
            raise CoordinatorContractError("worker receipt stage is invalid")
        _require_digest(self.job_authority_digest, "job_authority_digest")
        payload = _json_object(self.payload, "worker receipt payload")
        object.__setattr__(self, "payload", payload)
        identity = {
            "schemaVersion": "amd.vertical-slice-stage-receipt.v1",
            "stage": self.stage,
            "jobAuthorityDigest": self.job_authority_digest,
            "payload": payload,
        }
        expected = canonical_json_digest(identity)
        if self.receipt_digest != expected:
            raise CoordinatorContractError("worker receipt digest mismatch")

    @classmethod
    def build(
        cls,
        *,
        stage: WorkerStage,
        job_authority_digest: str,
        payload: Mapping[str, Any],
    ) -> StageReceipt:
        normalized = _json_object(payload, "worker receipt payload")
        identity = {
            "schemaVersion": "amd.vertical-slice-stage-receipt.v1",
            "stage": stage,
            "jobAuthorityDigest": job_authority_digest,
            "payload": normalized,
        }
        return cls(
            stage=stage,
            job_authority_digest=job_authority_digest,
            payload=normalized,
            receipt_digest=canonical_json_digest(identity),
        )


@dataclass(frozen=True, slots=True)
class WorkerCheckpoint:
    schema_version: Literal["amd.vertical-slice-coordinator.v1"]
    job_authority_digest: str
    revision: int
    status: WorkerStatus
    completed_stage: CompletedStage
    receipts: tuple[StageReceipt, ...]
    error_stage: WorkerStage | None
    error_code: str | None
    checkpoint_digest: str

    def __post_init__(self) -> None:
        _require_digest(self.job_authority_digest, "checkpoint job authority")
        if type(self.revision) is not int or self.revision < 0:
            raise CoordinatorContractError("checkpoint revision is invalid")
        if self.status not in {
            "active",
            "retryable_failed",
            "terminal_failed",
            "delivered",
        }:
            raise CoordinatorContractError("checkpoint status is invalid")
        stages = tuple(receipt.stage for receipt in self.receipts)
        if stages != _STAGE_ORDER[: len(stages)]:
            raise CoordinatorContractError("checkpoint receipts are not contiguous")
        if any(
            receipt.job_authority_digest != self.job_authority_digest
            for receipt in self.receipts
        ):
            raise CoordinatorContractError("checkpoint receipt lineage mismatch")
        expected_completed = "clicked" if not stages else stages[-1]
        if self.completed_stage != expected_completed:
            raise CoordinatorContractError("checkpoint completed stage is invalid")
        if self.status == "delivered" and self.completed_stage != "delivered":
            raise CoordinatorContractError("delivered checkpoint is incomplete")
        if self.completed_stage == "delivered" and self.status != "delivered":
            raise CoordinatorContractError("completed delivery has invalid status")
        failed = self.status in {"retryable_failed", "terminal_failed"}
        if failed:
            if self.error_stage not in _STAGE_ORDER:
                raise CoordinatorContractError("failed checkpoint stage is invalid")
            if (
                type(self.error_code) is not str
                or _ERROR_CODE_RE.fullmatch(self.error_code) is None
            ):
                raise CoordinatorContractError("failed checkpoint code is invalid")
        elif self.error_stage is not None or self.error_code is not None:
            raise CoordinatorContractError("healthy checkpoint contains an error")
        expected_digest = canonical_json_digest(self._identity())
        if self.checkpoint_digest != expected_digest:
            raise CoordinatorContractError("checkpoint digest mismatch")

    def _identity(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "jobAuthorityDigest": self.job_authority_digest,
            "revision": self.revision,
            "status": self.status,
            "completedStage": self.completed_stage,
            "receipts": [
                {
                    "stage": receipt.stage,
                    "jobAuthorityDigest": receipt.job_authority_digest,
                    "payload": dict(receipt.payload),
                    "receiptDigest": receipt.receipt_digest,
                }
                for receipt in self.receipts
            ],
            "errorStage": self.error_stage,
            "errorCode": self.error_code,
        }

    def to_json_object(self) -> dict[str, Any]:
        """Return the complete standard-JSON persistence representation."""

        return {**self._identity(), "checkpointDigest": self.checkpoint_digest}

    @classmethod
    def from_json_object(cls, value: object) -> WorkerCheckpoint:
        payload = _json_object(value, "worker checkpoint")
        expected_keys = {
            "schemaVersion",
            "jobAuthorityDigest",
            "revision",
            "status",
            "completedStage",
            "receipts",
            "errorStage",
            "errorCode",
            "checkpointDigest",
        }
        if set(payload) != expected_keys or type(payload.get("receipts")) is not list:
            raise CoordinatorContractError("worker checkpoint shape is invalid")
        receipts: list[StageReceipt] = []
        for row in payload["receipts"]:
            if type(row) is not dict or set(row) != {
                "stage",
                "jobAuthorityDigest",
                "payload",
                "receiptDigest",
            }:
                raise CoordinatorContractError("worker receipt shape is invalid")
            receipts.append(
                StageReceipt(
                    stage=row["stage"],
                    job_authority_digest=row["jobAuthorityDigest"],
                    payload=row["payload"],
                    receipt_digest=row["receiptDigest"],
                )
            )
        return cls(
            schema_version=payload["schemaVersion"],
            job_authority_digest=payload["jobAuthorityDigest"],
            revision=payload["revision"],
            status=payload["status"],
            completed_stage=payload["completedStage"],
            receipts=tuple(receipts),
            error_stage=payload["errorStage"],
            error_code=payload["errorCode"],
            checkpoint_digest=payload["checkpointDigest"],
        )

    @classmethod
    def _build(
        cls,
        *,
        job_authority_digest: str,
        revision: int,
        status: WorkerStatus,
        receipts: tuple[StageReceipt, ...],
        error_stage: WorkerStage | None = None,
        error_code: str | None = None,
    ) -> WorkerCheckpoint:
        completed: CompletedStage = "clicked" if not receipts else receipts[-1].stage
        identity = {
            "schemaVersion": "amd.vertical-slice-coordinator.v1",
            "jobAuthorityDigest": job_authority_digest,
            "revision": revision,
            "status": status,
            "completedStage": completed,
            "receipts": [
                {
                    "stage": receipt.stage,
                    "jobAuthorityDigest": receipt.job_authority_digest,
                    "payload": dict(receipt.payload),
                    "receiptDigest": receipt.receipt_digest,
                }
                for receipt in receipts
            ],
            "errorStage": error_stage,
            "errorCode": error_code,
        }
        return cls(
            schema_version="amd.vertical-slice-coordinator.v1",
            job_authority_digest=job_authority_digest,
            revision=revision,
            status=status,
            completed_stage=completed,
            receipts=receipts,
            error_stage=error_stage,
            error_code=error_code,
            checkpoint_digest=canonical_json_digest(identity),
        )

    @classmethod
    def new(cls, job: ClickedDeferredVideoJob) -> WorkerCheckpoint:
        if not isinstance(job, ClickedDeferredVideoJob):
            raise CoordinatorContractError("clicked job authority is invalid")
        return cls._build(
            job_authority_digest=job.authority_digest,
            revision=0,
            status="active",
            receipts=(),
        )

    def with_revision(self, revision: int) -> WorkerCheckpoint:
        return self._build(
            job_authority_digest=self.job_authority_digest,
            revision=revision,
            status=self.status,
            receipts=self.receipts,
            error_stage=self.error_stage,
            error_code=self.error_code,
        )

    def advance(self, receipt: StageReceipt) -> WorkerCheckpoint:
        if self.status in {"terminal_failed", "delivered"}:
            raise CoordinatorContractError("terminal checkpoint cannot advance")
        expected = _STAGE_ORDER[len(self.receipts)]
        if (
            not isinstance(receipt, StageReceipt)
            or receipt.stage != expected
            or receipt.job_authority_digest != self.job_authority_digest
        ):
            raise CoordinatorContractError("worker step returned the wrong receipt")
        receipts = (*self.receipts, receipt)
        status: WorkerStatus = "delivered" if receipt.stage == "delivered" else "active"
        return self._build(
            job_authority_digest=self.job_authority_digest,
            revision=self.revision,
            status=status,
            receipts=receipts,
        )

    def fail(
        self,
        *,
        stage: WorkerStage,
        code: str,
        retryable: bool,
    ) -> WorkerCheckpoint:
        if self.status in {"terminal_failed", "delivered"}:
            raise CoordinatorContractError("terminal checkpoint cannot fail again")
        if stage != _STAGE_ORDER[len(self.receipts)]:
            raise CoordinatorContractError("worker failure stage is out of order")
        if _ERROR_CODE_RE.fullmatch(code) is None:
            raise CoordinatorContractError("worker failure code is invalid")
        return self._build(
            job_authority_digest=self.job_authority_digest,
            revision=self.revision,
            status="retryable_failed" if retryable else "terminal_failed",
            receipts=self.receipts,
            error_stage=stage,
            error_code=code,
        )


class DeferredJobPort(Protocol):
    def claim_next_clicked_deferred(self) -> object | None: ...

    def report(
        self,
        job: ClickedDeferredVideoJob,
        status: Literal["retryable_failed", "terminal_failed", "delivered"],
        code: str | None,
    ) -> None: ...


class CheckpointPort(Protocol):
    def load(self, job: ClickedDeferredVideoJob) -> WorkerCheckpoint | None: ...

    def save(
        self,
        job: ClickedDeferredVideoJob,
        checkpoint: WorkerCheckpoint,
        *,
        expected_revision: int | None,
    ) -> WorkerCheckpoint: ...


class WorkerStagePort(Protocol):
    """One idempotent step; GPU ownership is limited to the two GPU stages."""

    def execute(
        self,
        *,
        job: ClickedDeferredVideoJob,
        prior_receipts: tuple[StageReceipt, ...],
        idempotency_key: str,
    ) -> StageReceipt: ...


class CompetitionVerticalSliceCoordinator:
    """Advance at most one already-clicked competition job to delivery."""

    def __init__(
        self,
        *,
        jobs: DeferredJobPort,
        checkpoints: CheckpointPort,
        source_preparer: WorkerStagePort,
        flux_runner: WorkerStagePort,
        reference_publisher: WorkerStagePort,
        authority_finalizer: WorkerStagePort,
        workflow_materializer: WorkerStagePort,
        h3_runner: WorkerStagePort,
        delivery_publisher: WorkerStagePort,
    ) -> None:
        for owner, methods in (
            (jobs, ("claim_next_clicked_deferred", "report")),
            (checkpoints, ("load", "save")),
        ):
            if any(not callable(getattr(owner, method, None)) for method in methods):
                raise ValueError("competition coordinator port is invalid")
        ports = (
            source_preparer,
            flux_runner,
            reference_publisher,
            authority_finalizer,
            workflow_materializer,
            h3_runner,
            delivery_publisher,
        )
        if any(not callable(getattr(port, "execute", None)) for port in ports):
            raise ValueError("competition stage port is invalid")
        self._jobs = jobs
        self._checkpoints = checkpoints
        self._ports = dict(zip(_STAGE_ORDER, ports, strict=True))

    def process_one(self) -> WorkerCheckpoint | None:
        record = self._jobs.claim_next_clicked_deferred()
        if record is None:
            return None
        job = ClickedDeferredVideoJob.from_projection_record(record)
        checkpoint = self._checkpoints.load(job)
        if checkpoint is None:
            if job.pipeline_mode != "h3_deferred_vertical_slice":
                raise CoordinatorContractError(
                    "materialized workflow has no durable clicked checkpoint"
                )
            checkpoint = self._persist(job, WorkerCheckpoint.new(job), expected=None)
        else:
            if not isinstance(checkpoint, WorkerCheckpoint):
                raise CoordinatorContractError("checkpoint store returned invalid data")
            # Recompute validation even when an unsafe store mutated a frozen object.
            WorkerCheckpoint(**{
                "schema_version": checkpoint.schema_version,
                "job_authority_digest": checkpoint.job_authority_digest,
                "revision": checkpoint.revision,
                "status": checkpoint.status,
                "completed_stage": checkpoint.completed_stage,
                "receipts": checkpoint.receipts,
                "error_stage": checkpoint.error_stage,
                "error_code": checkpoint.error_code,
                "checkpoint_digest": checkpoint.checkpoint_digest,
            })
            if checkpoint.job_authority_digest != job.authority_digest:
                raise CoordinatorContractError("checkpoint belongs to another click")

        if checkpoint.status in {"terminal_failed", "delivered"}:
            return checkpoint

        while len(checkpoint.receipts) < len(_STAGE_ORDER):
            stage: WorkerStage = _STAGE_ORDER[len(checkpoint.receipts)]
            port = self._ports[stage]
            idempotency_key = (
                f"amd-three-second:{job.authority_digest[:24]}:{stage}"
            )
            try:
                receipt = port.execute(
                    job=job,
                    prior_receipts=checkpoint.receipts,
                    idempotency_key=idempotency_key,
                )
                if not isinstance(receipt, StageReceipt):
                    raise CoordinatorContractError(
                        f"{stage} returned an invalid durable receipt"
                    )
                next_checkpoint = checkpoint.advance(receipt)
            except WorkerStepError as exc:
                if exc.stage != stage:
                    raise CoordinatorContractError(
                        "worker port reported a failure for another stage"
                    ) from exc
                failed = checkpoint.fail(
                    stage=stage,
                    code=exc.safe_error_code,
                    retryable=exc.retryable,
                )
                checkpoint = self._persist(
                    job, failed, expected=checkpoint.revision
                )
                report_status = (
                    "retryable_failed" if exc.retryable else "terminal_failed"
                )
                self._jobs.report(job, report_status, exc.safe_error_code)
                return checkpoint
            except CoordinatorContractError:
                failed = checkpoint.fail(
                    stage=stage,
                    code="STAGE_CONTRACT_VIOLATION",
                    retryable=False,
                )
                checkpoint = self._persist(
                    job, failed, expected=checkpoint.revision
                )
                self._jobs.report(
                    job,
                    "terminal_failed",
                    "STAGE_CONTRACT_VIOLATION",
                )
                return checkpoint
            except Exception:
                # Dependency messages can contain provider details or secrets;
                # only a fixed safe code crosses the durable/public boundary.
                failed = checkpoint.fail(
                    stage=stage,
                    code="UNCLASSIFIED_DEPENDENCY_FAILURE",
                    retryable=True,
                )
                checkpoint = self._persist(
                    job, failed, expected=checkpoint.revision
                )
                self._jobs.report(
                    job,
                    "retryable_failed",
                    "UNCLASSIFIED_DEPENDENCY_FAILURE",
                )
                return checkpoint
            checkpoint = self._persist(
                job, next_checkpoint, expected=checkpoint.revision
            )

        self._jobs.report(job, "delivered", None)
        return checkpoint

    def _persist(
        self,
        job: ClickedDeferredVideoJob,
        checkpoint: WorkerCheckpoint,
        *,
        expected: int | None,
    ) -> WorkerCheckpoint:
        persisted = self._checkpoints.save(
            job, checkpoint, expected_revision=expected
        )
        if not isinstance(persisted, WorkerCheckpoint):
            raise CoordinatorContractError("checkpoint store returned invalid data")
        expected_revision = 1 if expected is None else expected + 1
        if (
            persisted.revision != expected_revision
            or persisted.job_authority_digest != job.authority_digest
            or persisted.status != checkpoint.status
            or persisted.completed_stage != checkpoint.completed_stage
            or persisted.receipts != checkpoint.receipts
            or persisted.error_stage != checkpoint.error_stage
            or persisted.error_code != checkpoint.error_code
        ):
            raise CoordinatorContractError("checkpoint store changed durable authority")
        return persisted


__all__ = [
    "CheckpointPort",
    "ClickedDeferredVideoJob",
    "CompetitionVerticalSliceCoordinator",
    "CompletedStage",
    "CoordinatorContractError",
    "DeferredJobPort",
    "RetryableWorkerStepError",
    "StageReceipt",
    "TerminalWorkerStepError",
    "WorkerCheckpoint",
    "WorkerStage",
    "WorkerStepError",
    "WorkerStagePort",
    "WorkerStatus",
]
