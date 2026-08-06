from __future__ import annotations

import json
import os
import queue
import shutil
import time
from collections.abc import Callable
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    TypeAdapter,
    ValidationError as PydanticValidationError,
    model_validator,
)

from ..config import AppPaths
from ..exceptions import ValidationError
from .knowledge_canonical import CanonicalIdentity, Canonicalizer
from .knowledge_content_store import KnowledgeContentStore
from .knowledge_pipeline import FileProbe, FormatNormalizer, ParseExecutor, ParserRouter
from .ocr.composition import build_ocr_service_from_spawn_spec
from .ocr.contracts import OcrSpawnSpec
from .storage.layout import knowledge_import_result_path, knowledge_import_task_root
from .windows_process_tree import arm_current_process_tree

_MAX_RESULT_BYTES = 256 * 1024
_DEFAULT_OPERATION_TIMEOUT_SECONDS = 15 * 60
TaskId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
EventToken = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]{1,80}$")]
BoundedWarning = Annotated[str, StringConstraints(max_length=200)]
_EVENT_TOKEN_ADAPTER = TypeAdapter(EventToken)


class _WorkerBoundaryModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class KnowledgeImportWorkerRequest(_WorkerBoundaryModel):
    paths: AppPaths
    import_id: TaskId
    source_path: str
    expected_source_sha256: Sha256
    expected_source_format: str
    expected_media_type: str | None
    identity: CanonicalIdentity
    ocr_spawn_spec: OcrSpawnSpec = Field(default_factory=lambda: OcrSpawnSpec(kind="paddle"))
    password: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _identity_is_consistent(self) -> Self:
        if (
            self.identity.import_id != self.import_id
            or self.identity.source_sha256 != self.expected_source_sha256
        ):
            raise ValueError("Knowledge import worker identity is inconsistent.")
        return self


class KnowledgeImportWorkerEvent(_WorkerBoundaryModel):
    phase: EventToken
    event_code: EventToken
    level: Literal["info", "warning", "error"] = "info"


class KnowledgeImportWorkerResult(_WorkerBoundaryModel):
    schema_version: Literal[3] = 3
    status: Literal["succeeded", "failed"]
    worker_pid: PositiveInt
    canonical_generation_id: TaskId | None = None
    media_type: str | None = None
    envelope_sha256: Sha256 | None = None
    content_ir_sha256: Sha256 | None = None
    staged_relative_path: str | None = None
    pipeline: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[BoundedWarning, ...] = ()
    error_code: EventToken | None = None
    failure_stage: EventToken | None = None
    diagnostic_code: EventToken | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def _status_fields_are_consistent(self) -> Self:
        if self.status == "succeeded":
            if (
                self.canonical_generation_id is None
                or not self.staged_relative_path
                or self.envelope_sha256 is None
                or self.content_ir_sha256 is None
                or self.error_code is not None
                or self.failure_stage is not None
                or self.diagnostic_code is not None
            ):
                raise ValueError("Knowledge import worker success result is invalid.")
            return self
        if (
            self.error_code is None
            or self.failure_stage is None
            or self.diagnostic_code is None
            or any(
                value is not None
                for value in (
                    self.canonical_generation_id,
                    self.envelope_sha256,
                    self.content_ir_sha256,
                    self.staged_relative_path,
                )
            )
        ):
            raise ValueError("Knowledge import worker failure result is invalid.")
        return self


class KnowledgeImportWorkerRunner(Protocol):
    def run(
        self,
        request: KnowledgeImportWorkerRequest,
        *,
        is_cancelled: Callable[[], bool],
        on_event: Callable[[KnowledgeImportWorkerEvent], None],
    ) -> KnowledgeImportWorkerResult: ...


class LocalKnowledgeImportWorkerRunner:
    """Run one import attempt in a spawn-safe child process."""

    def __init__(
        self,
        *,
        poll_interval: float = 0.05,
        cancel_grace: float = 1.0,
        operation_timeout: float = _DEFAULT_OPERATION_TIMEOUT_SECONDS,
        entrypoint: Callable[..., None] | None = None,
    ) -> None:
        self._poll_interval = max(0.01, poll_interval)
        self._cancel_grace = max(0.1, cancel_grace)
        self._operation_timeout = max(0.1, operation_timeout)
        self._entrypoint = entrypoint or knowledge_import_worker_entry

    def run(
        self,
        request: KnowledgeImportWorkerRequest,
        *,
        is_cancelled: Callable[[], bool],
        on_event: Callable[[KnowledgeImportWorkerEvent], None],
    ) -> KnowledgeImportWorkerResult:
        _validate_request(request)
        result_path = knowledge_import_result_path(request.paths, request.import_id)
        task_root = knowledge_import_task_root(request.paths, request.import_id)
        task_root.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)
        shutil.rmtree(task_root / "canonical", ignore_errors=True)
        context = get_context("spawn")
        event_queue = context.Queue()
        process = context.Process(
            target=_managed_knowledge_import_worker_entry,
            args=(self._entrypoint, request, event_queue),
            name=f"xenix-knowledge-import-{request.import_id[:8]}",
        )
        timed_out = False
        cancelled = False
        process_started = False
        try:
            try:
                process.start()
                process_started = True
            except (OSError, RuntimeError) as exc:
                on_event(
                    KnowledgeImportWorkerEvent(
                        phase="failed",
                        event_code="worker_launch_failed",
                        level="error",
                    )
                )
                raise KnowledgeImportWorkerLaunchFailed from exc
            operation_started = time.monotonic()
            while process.is_alive():
                _drain_events(event_queue, on_event)
                if is_cancelled():
                    cancelled = True
                    _stop_process(process, grace=self._cancel_grace)
                    break
                if time.monotonic() - operation_started >= self._operation_timeout:
                    timed_out = True
                    on_event(
                        KnowledgeImportWorkerEvent(
                            phase="failed",
                            event_code="worker_operation_timed_out",
                            level="error",
                        )
                    )
                    _stop_process(process, grace=self._cancel_grace)
                    break
                process.join(self._poll_interval)
            _drain_events(event_queue, on_event)
            if timed_out:
                raise KnowledgeImportWorkerTimedOut
            if cancelled or is_cancelled():
                raise KnowledgeImportWorkerCancelled
            if process.exitcode != 0:
                on_event(
                    KnowledgeImportWorkerEvent(
                        phase="failed",
                        event_code="worker_process_crashed",
                        level="error",
                    )
                )
                raise KnowledgeImportWorkerCrashed
            try:
                return read_worker_result(result_path)
            except KnowledgeImportWorkerCrashed:
                on_event(
                    KnowledgeImportWorkerEvent(
                        phase="failed",
                        event_code="worker_result_invalid",
                        level="error",
                    )
                )
                raise
        finally:
            if process_started and process.is_alive():
                _stop_process(process, grace=self._cancel_grace)
            event_queue.close()
            event_queue.join_thread()


class InlineKnowledgeImportWorkerRunner:
    """Deterministic test seam with the same result and event contract."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        normalizer: FormatNormalizer | None = None,
        ocr_service: object | None = None,
        store: KnowledgeContentStore | None = None,
    ) -> None:
        self._paths = paths
        self._normalizer = normalizer or FormatNormalizer()
        self._parser = ParseExecutor(ocr_service)  # type: ignore[arg-type]
        self._store = store or KnowledgeContentStore(paths)

    def run(
        self,
        request: KnowledgeImportWorkerRequest,
        *,
        is_cancelled: Callable[[], bool],
        on_event: Callable[[KnowledgeImportWorkerEvent], None],
    ) -> KnowledgeImportWorkerResult:
        _validate_request(request)
        if request.paths != self._paths:
            raise ValueError("Inline Knowledge worker paths do not match the request.")
        result_path = knowledge_import_result_path(request.paths, request.import_id)
        knowledge_import_task_root(request.paths, request.import_id).mkdir(
            parents=True, exist_ok=True
        )
        result_path.unlink(missing_ok=True)
        shutil.rmtree(
            knowledge_import_task_root(request.paths, request.import_id) / "canonical",
            ignore_errors=True,
        )
        _run_worker_operation(
            request,
            on_event=on_event,
            normalizer=self._normalizer,
            parser=self._parser,
            store=self._store,
        )
        if is_cancelled():
            raise KnowledgeImportWorkerCancelled
        return read_worker_result(result_path)


class KnowledgeImportWorkerCancelled(Exception):
    pass


class KnowledgeImportWorkerCrashed(Exception):
    pass


class KnowledgeImportWorkerTimedOut(Exception):
    pass


class KnowledgeImportWorkerLaunchFailed(Exception):
    pass


def _managed_knowledge_import_worker_entry(
    entrypoint: Callable[[KnowledgeImportWorkerRequest, Any], None],
    request: KnowledgeImportWorkerRequest,
    event_queue: Any,
) -> None:
    # Keep this handle live until process exit. Closing the last handle while the
    # worker is still alive would intentionally terminate the worker itself.
    process_tree_handle = arm_current_process_tree()
    entrypoint(request, event_queue)
    _ = process_tree_handle


def knowledge_import_worker_entry(
    request: KnowledgeImportWorkerRequest,
    event_queue: Any,
) -> None:
    """Top-level entrypoint required by Windows spawn and frozen executables."""

    def on_event(event: KnowledgeImportWorkerEvent) -> None:
        try:
            event_queue.put_nowait(event)
        except Exception:
            pass

    _run_worker_operation(request, on_event=on_event)


def _run_worker_operation(
    request: KnowledgeImportWorkerRequest,
    *,
    on_event: Callable[[KnowledgeImportWorkerEvent], None],
    normalizer: FormatNormalizer | None = None,
    parser: ParseExecutor | None = None,
    store: KnowledgeContentStore | None = None,
) -> None:
    result_path = knowledge_import_result_path(request.paths, request.import_id)
    failure_stage = "probing"
    try:
        _validate_request(request)
        actual_store = store or KnowledgeContentStore(request.paths)
        actual_normalizer = normalizer or FormatNormalizer()
        actual_parser = parser or ParseExecutor(
            build_ocr_service_from_spawn_spec(request.paths, request.ocr_spawn_spec)
        )
        router = ParserRouter()
        canonicalizer = Canonicalizer()
        _emit(on_event, "probing", "worker_started")
        source = actual_store.verify_source_snapshot(
            Path(request.source_path),
            expected_sha256=request.expected_source_sha256,
        )
        probe = FileProbe().probe(source.path)
        if (
            probe.source_format != request.expected_source_format
            or probe.media_type != request.expected_media_type
        ):
            raise ValidationError(
                "Knowledge source identity changed before parsing.",
                error_code="knowledge_source_integrity_failed",
            )
        with TemporaryDirectory(prefix="xenix-knowledge-import-") as temp:
            work_dir = Path(temp)
            failure_stage = "normalizing"
            _emit(on_event, "normalizing", "normalization_started")
            normalized = actual_normalizer.normalize(
                probe,
                work_dir=work_dir,
                password=request.password,
            )
            failure_stage = "routing"
            _emit(on_event, "routing", "routing_started")
            plan = router.route(normalized, ocr_ready=actual_parser.ocr_ready)
            failure_stage = "parsing"
            _emit(on_event, "parsing", "parsing_started")
            parsed = actual_parser.parse(
                normalized,
                plan,
                probe=probe,
                work_dir=work_dir,
            )
            failure_stage = "canonicalizing"
            _emit(on_event, "canonicalizing", "canonicalization_started")
            material = canonicalizer.freeze(
                parsed.document,
                identity=request.identity,
                pipeline=parsed.pipeline,
                warnings=parsed.warnings,
                projections=parsed.projections,
            )
            failure_stage = "staging_canonical"
            _emit(on_event, "staging_canonical", "canonical_stage_started")
            stored = actual_store.stage_canonical_bundle(
                knowledge_import_task_root(request.paths, request.import_id)
                / "canonical",
                envelope=material.envelope,
                docling_document=material.docling_document,
                assets=material.assets,
            )
        result = KnowledgeImportWorkerResult(
            status="succeeded",
            worker_pid=os.getpid(),
            canonical_generation_id=request.identity.canonical_generation_id,
            media_type=probe.media_type,
            envelope_sha256=stored.envelope_sha256,
            content_ir_sha256=stored.content_ir_sha256,
            staged_relative_path=stored.relative_path,
            pipeline=dict(parsed.pipeline),
            warnings=tuple(str(item) for item in parsed.warnings),
        )
        write_worker_result(result_path, result)
        _emit(on_event, "completed", "worker_succeeded")
    except Exception as exc:
        error_code = getattr(exc, "error_code", None)
        if not isinstance(error_code, str) or not error_code.startswith("knowledge_"):
            error_code = "knowledge_import_failed"
        retryable = bool(getattr(exc, "retryable", False))
        diagnostic_code = _failure_diagnostic_code(exc)
        write_worker_result(
            result_path,
            KnowledgeImportWorkerResult(
                status="failed",
                worker_pid=os.getpid(),
                error_code=error_code,
                failure_stage=failure_stage,
                diagnostic_code=diagnostic_code,
                retryable=retryable,
            ),
        )
        _emit(on_event, "failed", f"{failure_stage}_failed", level="error")
        _emit(on_event, "failed", diagnostic_code, level="error")


def write_worker_result(path: Path, result: KnowledgeImportWorkerResult) -> None:
    payload = result.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if not encoded or len(encoded) > _MAX_RESULT_BYTES:
        raise ValidationError("Knowledge import worker result is too large.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_worker_result(path: Path) -> KnowledgeImportWorkerResult:
    try:
        size = path.stat().st_size
        if size < 1 or size > _MAX_RESULT_BYTES:
            raise ValueError("result size")
        return KnowledgeImportWorkerResult.model_validate_json(
            path.read_bytes(),
            strict=True,
        )
    except (OSError, UnicodeError, ValueError, PydanticValidationError) as exc:
        raise KnowledgeImportWorkerCrashed from exc


def _validate_request(request: KnowledgeImportWorkerRequest) -> None:
    KnowledgeImportWorkerRequest.model_validate(request, strict=True)


def _failure_diagnostic_code(exc: Exception) -> str:
    error_details = getattr(exc, "error_details", None)
    if isinstance(error_details, dict):
        candidate = error_details.get("diagnostic_code")
        try:
            return _EVENT_TOKEN_ADAPTER.validate_python(candidate, strict=True)
        except PydanticValidationError:
            pass
    if isinstance(exc, MemoryError):
        return "memory_error"
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "dependency_error"
    if isinstance(exc, OSError):
        return "os_error"
    if isinstance(exc, ValidationError):
        return "validation_error"
    return "unexpected_error"


def _drain_events(
    event_queue: Any,
    callback: Callable[[KnowledgeImportWorkerEvent], None],
) -> None:
    while True:
        try:
            event = event_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(event, KnowledgeImportWorkerEvent):
            callback(event)


def _emit(
    callback: Callable[[KnowledgeImportWorkerEvent], None],
    phase: str,
    event_code: str,
    *,
    level: Literal["info", "warning", "error"] = "info",
) -> None:
    callback(KnowledgeImportWorkerEvent(phase=phase, event_code=event_code, level=level))


def _stop_process(process: Any, *, grace: float) -> None:
    """Stop the one managed worker boundary; its Job Object owns descendants."""

    if not process.is_alive():
        return
    process.terminate()
    process.join(grace)
    if process.is_alive():
        process.kill()
        process.join()


__all__ = [
    "InlineKnowledgeImportWorkerRunner",
    "KnowledgeImportWorkerCancelled",
    "KnowledgeImportWorkerCrashed",
    "KnowledgeImportWorkerEvent",
    "KnowledgeImportWorkerLaunchFailed",
    "KnowledgeImportWorkerRequest",
    "KnowledgeImportWorkerResult",
    "KnowledgeImportWorkerRunner",
    "KnowledgeImportWorkerTimedOut",
    "LocalKnowledgeImportWorkerRunner",
    "knowledge_import_worker_entry",
    "read_worker_result",
]
