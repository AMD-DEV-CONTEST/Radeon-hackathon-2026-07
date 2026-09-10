"""One-shot Preview service isolated from Production workflow state and export."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import fcntl
import os
from pathlib import Path
import stat
import threading
import uuid

from specstyle.domain.identifiers import AttemptId, JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.gpu_runtime_lane import try_acquire_gpu_runtime_lane
from specstyle.generation.model_approval import verify_pipeline_supply
from specstyle.generation.model_registry import ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.preview_adapter_supply import verify_preview_adapter
from specstyle.generation.preview_diffusers_backend import (
    PreviewDiffusersBackend,
    _PreviewRuntimeIntegrityError,
)
from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
from specstyle.generation.protocols import build_control_input
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.environment import capture_environment, hash_environment
from specstyle.production.context_config import (
    load_production_context_config,
    make_production_compiler_context_factory,
    require_model_pipeline_support,
)
from specstyle.production.preview_supply_config import load_preview_supply_config
from specstyle.production.supply_config import load_production_supply_config
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow.preview_evidence import (
    PreviewEvidencePublication,
    publish_preview_evidence,
)
from specstyle.workflow.preview_job_input import (
    PreviewJobInput,
    load_preview_job_input_metadata,
    open_preview_job_input,
)

__all__ = (
    "PreviewRunOneFds",
    "PreviewRunOneReservation",
    "PreviewRunOneResult",
    "PreviewRunStatus",
    "reserve_preview_run_one",
    "run_preview_one",
)


class PreviewRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    BUSY = "BUSY"


@dataclass(frozen=True, slots=True)
class PreviewRunOneFds:
    production_config_root_fd: int
    production_context_evidence_root_fd: int
    preview_config_root_fd: int
    model_root_fd: int
    preview_evidence_root_fd: int
    display_root_fd: int
    style_asset_root_fd: int
    source_fd: int
    style_fd: int
    spec_fd: int
    metadata_fd: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.production_config_root_fd,
                self.production_context_evidence_root_fd,
                self.preview_config_root_fd,
                self.model_root_fd,
                self.preview_evidence_root_fd,
                self.display_root_fd,
                self.style_asset_root_fd,
                self.source_fd,
                self.style_fd,
                self.spec_fd,
                self.metadata_fd,
            )
        ):
            raise DomainError("invalid preview run-one descriptors")


_RESERVATION_SEAL = object()


class PreviewRunOneReservation:
    __slots__ = ("_consumed", "_lock", "_run_id", "_seal", "_variation_index")

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("preview run-one reservations are issued only by reserve")

    @property
    def run_id(self) -> str:
        _validate_reservation(self, require_open=False)
        return self._run_id

    def _consume(self) -> tuple[str, int]:
        with self._lock:
            _validate_reservation(self, require_open=True)
            self._consumed = True
            return self._run_id, self._variation_index

    def __copy__(self) -> PreviewRunOneReservation:
        raise TypeError("preview run-one reservations cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> PreviewRunOneReservation:
        raise TypeError("preview run-one reservations cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("preview run-one reservations cannot be serialized")


def _validate_reservation(value: object, *, require_open: bool) -> None:
    if (
        type(value) is not PreviewRunOneReservation
        or getattr(value, "_seal", None) is not _RESERVATION_SEAL
        or type(getattr(value, "_run_id", None)) is not str
        or not value._run_id.startswith("preview-")
        or type(getattr(value, "_variation_index", None)) is not int
        or not 0 <= value._variation_index < 2**31
        or type(getattr(value, "_consumed", None)) is not bool
    ):
        raise DomainError("invalid preview run-one reservation")
    if require_open and value._consumed:
        raise DomainError("preview run-one reservation already consumed")


def reserve_preview_run_one(variation_index: int = 0) -> PreviewRunOneReservation:
    if type(variation_index) is not int or not 0 <= variation_index < 2**31:
        raise DomainError("invalid preview variation index")
    issued = object.__new__(PreviewRunOneReservation)
    issued._run_id = f"preview-{uuid.uuid4().hex}"
    issued._variation_index = variation_index
    issued._consumed = False
    issued._lock = threading.Lock()
    issued._seal = _RESERVATION_SEAL
    _validate_reservation(issued, require_open=True)
    return issued


@dataclass(frozen=True, slots=True)
class PreviewRunOneResult:
    run_id: str
    status: PreviewRunStatus
    reason_code: str
    publication: PreviewEvidencePublication | None
    verification: str = "NOT_RUN"
    repair: str = "NOT_RUN"
    export: str = "NOT_RUN"

    def __post_init__(self) -> None:
        completed = self.status is PreviewRunStatus.COMPLETED
        if (
            type(self.run_id) is not str
            or not self.run_id.startswith("preview-")
            or type(self.status) is not PreviewRunStatus
            or type(self.reason_code) is not str
            or not self.reason_code
            or (completed != (type(self.publication) is PreviewEvidencePublication))
            or (completed and self.reason_code != "OK")
            or any(
                value != "NOT_RUN"
                for value in (self.verification, self.repair, self.export)
            )
        ):
            raise DomainError("invalid preview run-one result")


class _PreviewRunFailure(Exception):
    def __init__(self, status: PreviewRunStatus, reason_code: str) -> None:
        if status not in (PreviewRunStatus.FAILED, PreviewRunStatus.UNAVAILABLE):
            raise DomainError("invalid preview failure")
        super().__init__(reason_code)
        self.status = status
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _PreviewPreflight:
    context_config: object
    environment: object
    compiler_context: object
    production_supply: object
    preview_adapter: object
    preview_graph: object


def _duplicate(fd: int) -> int:
    try:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0)
    except (OSError, OverflowError):
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "DESCRIPTOR_UNAVAILABLE"
        ) from None


def _owned_descriptors(fds: PreviewRunOneFds) -> tuple[int, ...]:
    values = (
        fds.production_config_root_fd,
        fds.production_context_evidence_root_fd,
        fds.preview_config_root_fd,
        fds.model_root_fd,
        fds.preview_evidence_root_fd,
        fds.display_root_fd,
        fds.style_asset_root_fd,
        fds.source_fd,
        fds.style_fd,
        fds.spec_fd,
        fds.metadata_fd,
    )
    owned: list[int] = []
    try:
        owned.extend(_duplicate(value) for value in values)
        roots: list[tuple[int, int]] = []
        for descriptor in owned[:7]:
            info = os.fstat(descriptor)
            if not stat.S_ISDIR(info.st_mode):
                raise DomainError("invalid preview run-one root")
            roots.append((info.st_dev, info.st_ino))
        if len(set(roots)) != len(roots):
            raise DomainError("preview run-one roots must be distinct")
        if any(not stat.S_ISREG(os.fstat(item).st_mode) for item in owned[7:]):
            raise DomainError("invalid preview run-one input")
        return tuple(owned)
    except _PreviewRunFailure:
        _close_descriptors(owned)
        raise
    except (DomainError, OSError):
        _close_descriptors(owned)
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "DESCRIPTOR_INVALID"
        ) from None


def _close_descriptors(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _preview_graph(production_graph: object, preview_descriptor: object):
    descriptors = (
        production_graph.base,
        production_graph.ip_adapter,
        production_graph.controlnet,
        preview_descriptor,
    )
    registry = ModelRegistry(descriptors)
    return PipelineFactory(registry, Path("models")).build_preview(
        *(item.model_id for item in descriptors)
    )


def _call_unavailable(reason: str, callback, /):
    try:
        return callback()
    except (DomainError, InfrastructureError):
        raise _PreviewRunFailure(PreviewRunStatus.UNAVAILABLE, reason) from None


def _compiler_context(context: object, environment: object, production_graph: object):
    factory = make_production_compiler_context_factory(
        context, environment, production_graph
    )
    binding = context.l2_threshold_profile.production_binding
    preprocessing_version = (
        binding.preprocessor_pin.revision
        if binding is not None
        else "specstyle.preview.not-run."
        + production_graph.ip_adapter.expected_sha256.value
    )
    return factory(preprocessing_version)


def _open_preflight(owned: tuple[int, ...]) -> _PreviewPreflight:
    context = _call_unavailable(
        "PRODUCTION_CONFIG_INVALID",
        lambda: load_production_context_config(owned[0], owned[1]),
    )
    _call_unavailable(
        "PREVIEW_LCM_CAPABILITY_MISSING",
        lambda: require_model_pipeline_support(
            context, "lcm", ("base", "ip_adapter", "controlnet")
        ),
    )
    production_config = _call_unavailable(
        "PRODUCTION_CONFIG_INVALID", lambda: load_production_supply_config(owned[0])
    )
    preview_config = _call_unavailable(
        "PREVIEW_CONFIG_INVALID", lambda: load_preview_supply_config(owned[2])
    )
    supply = adapter = None
    try:
        supply = _call_unavailable(
            "MODEL_SUPPLY_INVALID",
            lambda: verify_pipeline_supply(
                owned[3],
                production_config.graph,
                production_config.manifests,
                production_config.approvals,
            ),
        )
        adapter = _call_unavailable(
            "PREVIEW_SUPPLY_INVALID",
            lambda: verify_preview_adapter(
                owned[3],
                preview_config.descriptor,
                preview_config.manifest,
                preview_config.approval,
            ),
        )
        graph = _call_unavailable(
            "PREVIEW_CONFIG_INVALID",
            lambda: _preview_graph(production_config.graph, preview_config.descriptor),
        )
        environment = _call_unavailable("RUNTIME_UNAVAILABLE", capture_environment)
        compiler_context = _call_unavailable(
            "RUNTIME_UNAVAILABLE",
            lambda: _compiler_context(context, environment, production_config.graph),
        )
        return _PreviewPreflight(
            context, environment, compiler_context, supply, adapter, graph
        )
    except BaseException:
        _close_resources((adapter, supply))
        raise


def _open_input(
    owned: tuple[int, ...], preflight: _PreviewPreflight, variation_index: int
) -> PreviewJobInput:
    try:
        metadata = load_preview_job_input_metadata(owned[10])
        return open_preview_job_input(
            owned[7],
            owned[8],
            owned[9],
            owned[6],
            metadata,
            preflight.context_config,
            variation_index,
        )
    except DomainError:
        raise _PreviewRunFailure(PreviewRunStatus.FAILED, "INPUT_INVALID") from None
    except InfrastructureError:
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "INPUT_UNAVAILABLE"
        ) from None


def _compile_request(
    run_id: str, job_input: PreviewJobInput, preflight: _PreviewPreflight
) -> GenerationRequest:
    from specstyle.generation.canny import CannyControlInputBuilder

    try:
        compiled = compile_style_spec(
            load_style_spec_text(job_input.spec_text), preflight.compiler_context
        )
        matched = tuple(
            graph
            for graph in compiled.preview_graphs
            if graph.output_profile == job_input.output_profile
        )
        if len(matched) != 1:
            raise DomainError("invalid preview selector")
        control = build_control_input(
            CannyControlInputBuilder(preflight.context_config.canny),
            job_input.source,
            matched[0],
        )
        return GenerationRequest(
            JobId(run_id),
            AttemptId(f"{run_id}-a0"),
            None,
            compiled,
            "preview",
            job_input.output_profile,
            job_input.source,
            job_input.style_references,
            job_input.prompt,
            control,
            job_input.variation_index,
            hash_environment(preflight.environment),
        )
    except DomainError:
        raise _PreviewRunFailure(PreviewRunStatus.FAILED, "SPEC_INVALID") from None
    except InfrastructureError:
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "PREPROCESS_UNAVAILABLE"
        ) from None


def _close_resources(resources: tuple[object | None, ...]) -> bool:
    failed = False
    for resource in resources:
        if resource is None:
            continue
        try:
            resource.close()
        except BaseException:
            failed = True
    return failed


def _load_runtime(preflight: _PreviewPreflight):
    try:
        return load_preview_pipeline(
            preflight.production_supply,
            preflight.preview_adapter,
            preflight.preview_graph,
            preflight.environment,
        )
    except DomainError:
        raise _PreviewRunFailure(
            PreviewRunStatus.FAILED, "GENERATION_REJECTED"
        ) from None
    except InfrastructureError:
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "RUNTIME_FAILED"
        ) from None


def _generate_artifact(loaded: object, job_input: PreviewJobInput, request: object):
    try:
        return PreviewDiffusersBackend(loaded, job_input.style_assets).generate(request)
    except _PreviewRuntimeIntegrityError:
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "RUNTIME_INTEGRITY_FAILED"
        ) from None
    except DomainError:
        raise _PreviewRunFailure(
            PreviewRunStatus.FAILED, "GENERATION_REJECTED"
        ) from None
    except InfrastructureError:
        raise _PreviewRunFailure(
            PreviewRunStatus.UNAVAILABLE, "RUNTIME_FAILED"
        ) from None


def _publish_artifact(
    owned: tuple[int, ...], run_id: str, artifact: object
) -> PreviewEvidencePublication:
    try:
        return publish_preview_evidence(owned[4], owned[5], run_id, artifact)
    except (DomainError, InfrastructureError):
        raise _PreviewRunFailure(PreviewRunStatus.FAILED, "PERSIST_FAILED") from None


_SESSION_SEAL = object()


class _PreviewRuntimeSession:
    __slots__ = ("_closed", "_loaded", "_lock", "_owned", "_preflight", "_seal")

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("preview runtime sessions are issued only by open")

    def run_item(self, run_id: str, variation_index: int) -> PreviewRunOneResult:
        _validate_session(self, require_open=True)
        return _execute_preview(self, run_id, variation_index)

    def close(self) -> bool:
        _validate_session(self, require_open=False)
        with self._lock:
            if self._closed:
                return False
            self._closed = True
        failed = _close_resources(
            (
                self._loaded,
                self._preflight.preview_adapter,
                self._preflight.production_supply,
            )
        )
        _close_descriptors(list(self._owned))
        return failed


def _validate_session(value: object, *, require_open: bool) -> None:
    if (
        type(value) is not _PreviewRuntimeSession
        or getattr(value, "_seal", None) is not _SESSION_SEAL
        or type(getattr(value, "_owned", None)) is not tuple
        or type(getattr(value, "_preflight", None)) is not _PreviewPreflight
        or type(getattr(value, "_closed", None)) is not bool
    ):
        raise DomainError("invalid preview runtime session")
    if require_open and value._closed:
        raise DomainError("preview runtime session is closed")


def open_preview_runtime_session(fds: PreviewRunOneFds) -> _PreviewRuntimeSession:
    if type(fds) is not PreviewRunOneFds:
        raise DomainError("invalid preview run-one input")
    owned: tuple[int, ...] = ()
    preflight = loaded = None
    try:
        owned = _owned_descriptors(fds)
        preflight = _open_preflight(owned)
        loaded = _load_runtime(preflight)
        issued = object.__new__(_PreviewRuntimeSession)
        issued._owned = owned
        issued._preflight = preflight
        issued._loaded = loaded
        issued._closed = False
        issued._lock = threading.Lock()
        issued._seal = _SESSION_SEAL
        _validate_session(issued, require_open=True)
        return issued
    except BaseException:
        resources = (
            loaded,
            None if preflight is None else preflight.preview_adapter,
            None if preflight is None else preflight.production_supply,
        )
        _close_resources(resources)
        _close_descriptors(list(owned))
        raise


def _execute_preview(
    session: _PreviewRuntimeSession, run_id: str, variation_index: int
) -> PreviewRunOneResult:
    _validate_session(session, require_open=True)
    if (
        type(run_id) is not str
        or not run_id.startswith("preview-")
        or type(variation_index) is not int
        or not 0 <= variation_index < 2**31
    ):
        raise DomainError("invalid preview runtime item")
    job_input = None
    failure: _PreviewRunFailure | None = None
    publication: PreviewEvidencePublication | None = None
    try:
        job_input = _open_input(session._owned, session._preflight, variation_index)
        request = _compile_request(run_id, job_input, session._preflight)
        artifact = _generate_artifact(session._loaded, job_input, request)
        publication = _publish_artifact(session._owned, run_id, artifact)
    except _PreviewRunFailure as error:
        failure = error
    finally:
        if _close_resources((job_input,)) and failure is None:
            failure = _PreviewRunFailure(PreviewRunStatus.FAILED, "CLEANUP_FAILED")
    if failure is not None:
        return _result(run_id, failure.status, failure.reason_code)
    if type(publication) is not PreviewEvidencePublication:
        return _result(run_id, PreviewRunStatus.FAILED, "INTERNAL_FAILURE")
    return _result(run_id, PreviewRunStatus.COMPLETED, "OK", publication)


def _result(
    run_id: str,
    status: PreviewRunStatus,
    reason_code: str,
    publication: PreviewEvidencePublication | None = None,
) -> PreviewRunOneResult:
    return PreviewRunOneResult(run_id, status, reason_code, publication)


def run_preview_one(
    fds: PreviewRunOneFds, reservation: PreviewRunOneReservation, /
) -> PreviewRunOneResult:
    if (
        type(fds) is not PreviewRunOneFds
        or type(reservation) is not PreviewRunOneReservation
    ):
        raise DomainError("invalid preview run-one input")
    _validate_reservation(reservation, require_open=True)
    lane = try_acquire_gpu_runtime_lane()
    if lane is None:
        return _result(reservation.run_id, PreviewRunStatus.BUSY, "GPU_BUSY")
    session: _PreviewRuntimeSession | None = None
    result: PreviewRunOneResult | None = None
    cleanup_failed = False
    try:
        run_id, variation_index = reservation._consume()
        try:
            session = open_preview_runtime_session(fds)
            result = session.run_item(run_id, variation_index)
        except _PreviewRunFailure as error:
            result = _result(run_id, error.status, error.reason_code)
    finally:
        if session is not None:
            cleanup_failed = session.close()
        lane.close()
    if (
        cleanup_failed
        and result is not None
        and result.status is PreviewRunStatus.COMPLETED
    ):
        return _result(result.run_id, PreviewRunStatus.FAILED, "CLEANUP_FAILED")
    if result is None:
        return _result(run_id, PreviewRunStatus.FAILED, "INTERNAL_FAILURE")
    return result
