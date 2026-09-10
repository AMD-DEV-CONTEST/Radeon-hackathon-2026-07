"""Single-job production entry point rooted exclusively in file descriptors."""

from __future__ import annotations

from dataclasses import dataclass, replace
import fcntl
import os
import stat
import threading
import uuid
from types import TracebackType
from typing import Any

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.gpu_runtime_lane import (
    GpuRuntimeLaneLease,
    acquire_gpu_runtime_lane,
)
from specstyle.generation.model_approval import verify_pipeline_supply
from specstyle.observability.environment import capture_environment
from specstyle.production.context_config import (
    load_production_context_config,
    make_production_compiler_context_factory,
    require_validated_production_threshold,
)
from specstyle.production.supply_config import load_production_supply_config
from specstyle.workflow.job_models import JobState
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_export import ProductionExportResult
from specstyle.workflow.production_job_input import (
    ProductionJobInput,
    load_production_job_input_metadata,
    open_production_job_input,
)
from specstyle.workflow.production_service import (
    ProductionJobResult,
    open_production_runtime,
    production_l1_rule_bindings,
)

__all__ = (
    "ProductionRunOneCleanupError",
    "ProductionRunOneExecution",
    "ProductionRunOneFds",
    "ProductionRunOneReservation",
    "ProductionRunOneResult",
    "open_production_run_one",
    "reserve_production_run_one",
)


def _invalid() -> DomainError:
    return DomainError("invalid production run-one input")


def _unavailable() -> InfrastructureError:
    return InfrastructureError("production run-one unavailable")


@dataclass(frozen=True, slots=True)
class ProductionRunOneFds:
    config_root_fd: int
    evidence_root_fd: int
    model_root_fd: int
    state_root_fd: int
    artifact_root_fd: int
    style_asset_root_fd: int
    export_root_fd: int
    source_fd: int
    style_fd: int
    spec_fd: int
    metadata_fd: int

    def __post_init__(self) -> None:
        for descriptor in (
            self.config_root_fd,
            self.evidence_root_fd,
            self.model_root_fd,
            self.state_root_fd,
            self.artifact_root_fd,
            self.style_asset_root_fd,
            self.export_root_fd,
            self.source_fd,
            self.style_fd,
            self.spec_fd,
            self.metadata_fd,
        ):
            if type(descriptor) is not int or descriptor < 0:
                raise _invalid()


class ProductionRunOneReservation:
    __slots__ = ("_token", "_consumed", "_job_id", "_variation_index", "_lock")

    def __init__(self, token: object, job_id: JobId, variation_index: int, /) -> None:
        if token is not _RESERVATION_TOKEN:
            raise TypeError(
                "production run-one reservations are issued only by reserve"
            )
        self._token, self._consumed, self._job_id = token, False, job_id
        self._variation_index = _validate_variation_index(variation_index)
        self._lock = threading.Lock()

    @property
    def job_id(self) -> JobId:
        return self._job_id

    @property
    def variation_index(self) -> int:
        return _validate_variation_index(self._variation_index)

    def _consume(self) -> tuple[JobId, int]:
        with self._lock:
            if self._consumed:
                raise _invalid()
            if type(self._job_id) is not JobId:
                raise _invalid()
            variation_index = _validate_variation_index(self._variation_index)
            self._consumed = True
            return JobId(self._job_id.value), variation_index

    def __copy__(self) -> ProductionRunOneReservation:
        raise TypeError("production run-one reservations cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> ProductionRunOneReservation:
        raise TypeError("production run-one reservations cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production run-one reservations cannot be serialized")


_RESERVATION_TOKEN = object()


def _validate_variation_index(value: object) -> int:
    if type(value) is not int or not 0 <= value < 2**31:
        raise _invalid()
    return value


def reserve_production_run_one(
    variation_index: int = 0,
) -> ProductionRunOneReservation:
    """Reserve a stable job identity before opening the heavyweight runtime."""
    variation_index = _validate_variation_index(variation_index)
    job_id = JobId(f"run-one-{uuid.uuid4().hex}")
    return ProductionRunOneReservation(
        _RESERVATION_TOKEN, JobId(job_id.value), variation_index
    )


@dataclass(frozen=True, slots=True)
class ProductionRunOneResult:
    job_result: ProductionJobResult
    export_result: ProductionExportResult

    def __post_init__(self) -> None:
        if (
            type(self.job_result) is not ProductionJobResult
            or type(self.export_result) is not ProductionExportResult
            or self.job_result.job_state != self.export_result.job_state
        ):
            raise _invalid()


class ProductionRunOneCleanupError(InfrastructureError):
    """Raised only after resource cleanup fails."""

    def __init__(self, result: ProductionRunOneResult | None = None) -> None:
        super().__init__("production run-one cleanup failed")
        self.result = result


class ProductionRunOneExecution:
    __slots__ = (
        "_asset_input",
        "_closed",
        "_export_root_fd",
        "_job_id",
        "_job_store",
        "_lock",
        "_pending_cancel",
        "_result",
        "_run_started",
        "_runtime_lane",
        "_runtime",
        "_supply",
    )

    def __init__(
        self,
        job_id: JobId,
        runtime: Any,
        asset_input: ProductionJobInput,
        supply: Any,
        job_store: JobStore,
        export_root_fd: int,
        runtime_lane: GpuRuntimeLaneLease,
        /,
    ) -> None:
        if type(runtime_lane) is not GpuRuntimeLaneLease:
            raise _invalid()
        self._job_id, self._runtime, self._asset_input = job_id, runtime, asset_input
        self._supply, self._job_store, self._export_root_fd = (
            supply,
            job_store,
            export_root_fd,
        )
        self._runtime_lane = runtime_lane
        self._lock, self._closed, self._run_started = threading.RLock(), False, False
        self._pending_cancel: str | None = None
        self._result: ProductionRunOneResult | None = None

    @property
    def job_id(self) -> JobId:
        return self._job_id

    @property
    def identity(self) -> JobId:
        return self._job_id

    def run(self) -> ProductionRunOneResult:
        with self._lock:
            if self._closed or self._run_started:
                raise _unavailable()
            self._run_started = True
            pending = self._pending_cancel
        if pending is not None:
            raise DomainError("production job cancelled")
        try:
            job_result = self._runtime.run(self._asset_input.request)
            command = self._runtime.prepare_export(
                self._asset_input.request, job_result, self._asset_input.asset_credits
            )
            export_result = self._runtime.publish_export(command, self._export_root_fd)
            expected = self._job_store.load(self._job_id)
            if export_result.job_state != expected:
                raise _unavailable()
            # run() returns pre-export job_state (APPROVED); export_result is COMPLETED.
            # Align both sides of the public result on the post-export JobStore state.
            if job_result.job_state != export_result.job_state:
                if (
                    job_result.job_state.job.job_id
                    != export_result.job_state.job.job_id
                ):
                    raise _unavailable()
                job_result = replace(job_result, job_state=export_result.job_state)
            result = ProductionRunOneResult(job_result, export_result)
            with self._lock:
                self._result = result
            return result
        except Exception:
            raise

    def cancel(self, *, reason: str = "user requested") -> JobState | None:
        if type(reason) is not str:
            raise _invalid()
        with self._lock:
            if self._closed:
                raise _unavailable()
            if not self._run_started:
                self._pending_cancel = reason
                return None
        snapshot = self._job_store.get_snapshot(self._job_id)
        if snapshot is None:
            with self._lock:
                self._pending_cancel = reason
            return None
        return self._runtime.cancel(self._job_id, reason=reason)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            failures: list[BaseException] = []
            for resource in (
                self._runtime,
                self._asset_input,
                self._supply,
                self._job_store,
            ):
                try:
                    resource.close()
                except BaseException as error:
                    failures.append(error)
            try:
                os.close(self._export_root_fd)
            except OSError as error:
                failures.append(error)
        finally:
            self._runtime_lane.close()
        if failures:
            cleanup = ProductionRunOneCleanupError(self._result)
            for error in failures:
                cleanup.add_note("production run-one cleanup failed")
            raise cleanup

    def __enter__(self) -> ProductionRunOneExecution:
        with self._lock:
            if self._closed:
                raise _unavailable()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None:
        try:
            self.close()
        except ProductionRunOneCleanupError:
            if exc is None:
                raise
            exc.add_note("production run-one cleanup failed")

    def __copy__(self) -> ProductionRunOneExecution:
        raise TypeError("production run-one executions cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> ProductionRunOneExecution:
        raise TypeError("production run-one executions cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production run-one executions cannot be serialized")


def _duplicate(fd: int) -> int:
    try:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0)
    except (OSError, OverflowError):
        raise _unavailable() from None


def _owned_descriptors(fds: ProductionRunOneFds) -> tuple[int, ...]:
    copies: list[int] = []
    try:
        for descriptor in (
            fds.config_root_fd,
            fds.evidence_root_fd,
            fds.model_root_fd,
            fds.state_root_fd,
            fds.artifact_root_fd,
            fds.style_asset_root_fd,
            fds.export_root_fd,
            fds.source_fd,
            fds.style_fd,
            fds.spec_fd,
            fds.metadata_fd,
        ):
            copies.append(_duplicate(descriptor))
        _validate_descriptor_shapes(copies)
        return tuple(copies)
    except BaseException:
        _close_descriptors(copies)
        raise


def _validate_descriptor_shapes(descriptors: list[int]) -> None:
    roots: list[tuple[int, int]] = []
    try:
        for descriptor in descriptors[:7]:
            info = os.fstat(descriptor)
            if not stat.S_ISDIR(info.st_mode):
                raise _invalid()
            roots.append((info.st_dev, info.st_ino))
        for descriptor in descriptors[7:]:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise _invalid()
    except OSError:
        raise _unavailable() from None
    if len(set(roots)) != len(roots):
        raise _invalid()


def _close_descriptors(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_resources(
    owned: tuple[int, ...], job_id: JobId, variation_index: int
) -> tuple[Any, ProductionJobInput, Any, JobStore]:
    (
        config,
        evidence,
        models,
        state,
        artifacts,
        styles,
        _export,
        source,
        style,
        spec,
        metadata,
    ) = owned
    supply = store = job_input = None
    try:
        context = load_production_context_config(config, evidence)
        require_validated_production_threshold(context)
        # Lazy: CannyControlInputBuilder pulls OpenCV; keep run_one importable without cv2.
        from specstyle.generation.canny import CannyControlInputBuilder

        input_metadata = load_production_job_input_metadata(metadata)
        supply_config = load_production_supply_config(config)
        supply = verify_pipeline_supply(
            models,
            supply_config.graph,
            supply_config.manifests,
            supply_config.approvals,
        )
        environment = capture_environment()
        factory = make_production_compiler_context_factory(
            context, environment, supply_config.graph
        )
        store = JobStore.from_root_fd(state)
        job_input = open_production_job_input(
            source,
            style,
            spec,
            styles,
            input_metadata,
            context,
            job_id,
            f"bundle-{job_id.value}",
            variation_index=variation_index,
        )
        runtime = open_production_runtime(
            supply,
            supply_config.graph,
            environment,
            factory,
            job_input.style_assets,
            CannyControlInputBuilder(context.canny),
            production_l1_rule_bindings(),
            store,
            artifacts,
        )
        return runtime, job_input, supply, store
    except BaseException:
        _close_open_failure((job_input, supply, store), None)
        raise


def _close_open_failure(resources: tuple[Any, ...], export_fd: int | None) -> None:
    for resource in resources:
        if resource is None:
            continue
        try:
            resource.close()
        except BaseException:
            pass
    if export_fd is not None:
        try:
            os.close(export_fd)
        except OSError:
            pass


def open_production_run_one(
    fds: ProductionRunOneFds, reservation: ProductionRunOneReservation, /
) -> ProductionRunOneExecution:
    if (
        type(fds) is not ProductionRunOneFds
        or type(reservation) is not ProductionRunOneReservation
    ):
        raise _invalid()
    runtime_lane = acquire_gpu_runtime_lane()
    owned: tuple[int, ...] = ()
    export_fd: int | None = None
    transferred = False
    runtime = job_input = supply = store = None
    try:
        job_id, variation_index = reservation._consume()
        owned = _owned_descriptors(fds)
        runtime, job_input, supply, store = _open_resources(
            owned, job_id, variation_index
        )
        export_fd = owned[6]
        owned = (*owned[:6], *owned[7:])
        execution = ProductionRunOneExecution(
            job_id, runtime, job_input, supply, store, export_fd, runtime_lane
        )
        transferred = True
        return execution
    except BaseException:
        _close_open_failure((runtime, job_input, supply, store), export_fd)
        raise
    finally:
        _close_descriptors(list(owned))
        if not transferred:
            runtime_lane.close()
