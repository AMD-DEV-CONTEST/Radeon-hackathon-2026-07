"""Qt background commands for one capability-scoped Radeon setup surface.

The runner owns only scheduling and safe UI projection.  The guided service
remains the authority for SSH enrollment, Local WSL validation, lifecycle
changes, and capability ownership.  A cancelled or closed runner suppresses
worker delivery that has not already been queued to Qt; it deliberately does
not claim to cancel an already started deployment.  Remove is the explicit
durable cancellation path owned by the deployment coordinator.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid

from ..services.amd.deployment import AmdDeploymentError, AmdRetirementRequest
from ..services.amd.guided_capability import (
    AmdCapabilityGuidedDeploymentService,
    AmdCapabilityDeploymentOption,
    AmdExistingPrivateSshInstallCommand,
    AmdGuidedCapabilityInstallation,
    AmdGuidedDeploymentError,
    AmdGuidedInputField,
    AmdGuidedPrivateTarget,
    AmdLocalWslInstallCommand,
    AmdPrivateSshInstallCommand,
    AmdSshHostTrustChallenge,
)
from ..services.amd.progress import AmdProgressEvent, AmdProgressSink
from ..services.amd.status import AmdInstallationCondition, AmdInstallationStatus


LOGGER = logging.getLogger(__name__)
_SAFE_CODE_PATTERN = re.compile(r"[a-z0-9_]{1,128}")
_RETIRE_INSTALLATION_APPEAR_RETRY_SECONDS = 0.1


class AmdCapabilityOperation(StrEnum):
    """Explicit lifecycle commands available from one capability dialog."""

    PRIVATE_INSTALL = "private_install"
    EXISTING_PRIVATE_INSTALL = "existing_private_install"
    LOCAL_WSL_INSTALL = "local_wsl_install"
    REPAIR = "repair"
    RETIRE = "retire"


@dataclass(frozen=True, slots=True)
class AmdCapabilityTaskResult:
    """One render-safe terminal result for an install or repair operation."""

    operation_id: int
    operation: AmdCapabilityOperation
    installation_id: str
    status: AmdInstallationStatus | None = field(repr=False)
    succeeded: bool = False
    error_code: str | None = None
    invalid_field: AmdGuidedInputField | None = None
    installation_available: bool | None = None
    condition: str = "unknown"
    phase: str = "unknown"

@dataclass(frozen=True, slots=True)
class AmdHostTrustTaskResult:
    """One UI-only host-trust response; the key stays opaque to logging.

    The dialog needs the original command and challenge to ask for explicit
    confirmation.  Consumers must not serialize or log either value.
    """

    operation_id: int
    command: AmdPrivateSshInstallCommand = field(repr=False)
    challenge: AmdSshHostTrustChallenge | None = field(default=None, repr=False)
    succeeded: bool = False
    error_code: str | None = None
    invalid_field: AmdGuidedInputField | None = None


@dataclass(frozen=True, slots=True)
class AmdLocalWslDiscoveryTaskResult:
    """Safe, display-ready Local WSL distribution discovery result."""

    operation_id: int
    distributions: tuple[str, ...]
    succeeded: bool = False
    error_code: str | None = None
    invalid_field: AmdGuidedInputField | None = None


@dataclass(frozen=True, slots=True)
class AmdCapabilityProgressUpdate:
    """One progress event correlated to exactly one runner operation."""

    operation_id: int
    event: AmdProgressEvent


@dataclass(frozen=True, slots=True)
class AmdRetirementAcknowledgement:
    """Durable retirement-request acknowledgement, never a cleanup status."""

    operation_id: int
    installation_id: str
    acknowledged: bool
    request_phase: str | None
    error_code: str | None = None
    invalid_field: AmdGuidedInputField | None = None


@dataclass(slots=True)
class _AmdCapabilityTaskState:
    """Session-local UI-delivery state; it is not deployment cancellation."""

    operation_id: int
    delivery_cancelled: bool = False
    pending_installation_id: str | None = None
    installation_completion: threading.Event | None = None


class _AmdCapabilityTaskError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class AmdCapabilityTaskRunner(QObject):
    """Run one capability's guided commands without blocking the Qt event loop.

    One ordinary command (install, repair, host-trust discovery, or Local WSL
    discovery) runs at a time.  Retirement acknowledgement may run alongside a
    materialization so the coordinator can commit desired absence and signal
    its own exact cancellation path.  Every ``start_*`` call returns an opaque
    operation ID; UI consumers must discard signal payloads for another ID.
    """

    finished = Signal(object)
    retirement_acknowledged = Signal(object)
    host_trust_finished = Signal(object)
    local_wsl_discovery_finished = Signal(object)
    progressed = Signal(object)

    def __init__(
        self,
        guided: AmdCapabilityGuidedDeploymentService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._guided = guided
        self._lock = threading.Lock()
        self._primary_task: _AmdCapabilityTaskState | None = None
        self._retirement_task: _AmdCapabilityTaskState | None = None
        self._next_operation_id = 0
        self._closed = False

    @property
    def active(self) -> bool:
        """Whether an ordinary command or a retirement acknowledgement is active."""

        with self._lock:
            return self._primary_task is not None or self._retirement_task is not None

    def validate_private_fields(self, command: AmdPrivateSshInstallCommand) -> None:
        """Run pure new-target validation synchronously before scheduling trust."""

        self._require_open()
        self._guided.validate_private_fields(command)

    def inventory(self) -> tuple[AmdGuidedCapabilityInstallation, ...]:
        """Read the service-owned, target-I/O-free capability inventory."""

        self._require_open()
        return self._guided.inventory()

    def deployment_options(self, placement: str | None = None) -> tuple[AmdCapabilityDeploymentOption, ...]:
        """Read adapter-owned catalog projections without probing a target."""

        self._require_open()
        return self._guided.deployment_options(placement)

    def private_targets(self) -> tuple[AmdGuidedPrivateTarget, ...]:
        """Read existing enrolled target choices without probing the network."""

        self._require_open()
        return self._guided.private_targets()

    def start_host_trust(self, command: AmdPrivateSshInstallCommand) -> int | None:
        """Discover a fresh target's host key for explicit user confirmation."""

        if not isinstance(command, AmdPrivateSshInstallCommand):
            return None
        return self._start_primary_worker(
            name="xenix-amd-capability-host-trust",
            target=lambda state: self._run_host_trust(state, command),
        )

    def start_private_install(
        self,
        command: AmdPrivateSshInstallCommand,
        accepted_trust: AmdSshHostTrustChallenge,
    ) -> int | None:
        """Install after the caller has explicitly accepted the discovered key."""

        if not isinstance(command, AmdPrivateSshInstallCommand):
            return None
        return self._start_installation_operation(
            operation=AmdCapabilityOperation.PRIVATE_INSTALL,
            installation_id=command.installation_id,
            invoke=lambda progress: self._guided.install_private(
                command,
                accepted_trust=accepted_trust,
                progress=progress,
            ),
        )

    def start_existing_private_install(
        self,
        command: AmdExistingPrivateSshInstallCommand,
    ) -> int | None:
        """Install this capability on a previously enrolled Private SSH target."""

        if not isinstance(command, AmdExistingPrivateSshInstallCommand):
            return None
        return self._start_installation_operation(
            operation=AmdCapabilityOperation.EXISTING_PRIVATE_INSTALL,
            installation_id=command.installation_id,
            invoke=lambda progress: self._guided.install_existing_private(
                command,
                progress=progress,
            ),
        )

    def start_local_wsl_discovery(self) -> int | None:
        """Discover selectable WSL distributions off the Qt event loop."""

        return self._start_primary_worker(
            name="xenix-amd-capability-wsl-discovery",
            target=self._run_local_wsl_discovery,
        )

    def start_local_wsl_install(self, command: AmdLocalWslInstallCommand) -> int | None:
        """Install this capability in one explicitly selected WSL distribution."""

        if not isinstance(command, AmdLocalWslInstallCommand):
            return None
        return self._start_installation_operation(
            operation=AmdCapabilityOperation.LOCAL_WSL_INSTALL,
            installation_id=command.installation_id,
            invoke=lambda progress: self._guided.install_local_wsl(
                command,
                progress=progress,
            ),
        )

    def start_repair(self, installation_id: str) -> int | None:
        """Run the service's fixed-capability repair command."""

        if not _is_installation_id(installation_id):
            return None
        return self._start_installation_operation(
            operation=AmdCapabilityOperation.REPAIR,
            installation_id=installation_id,
            invoke=lambda progress: self._guided.repair(installation_id, progress=progress),
        )

    def start_retire(self, installation_id: str) -> int | None:
        """Commit Remove and let the coordinator advance retirement asynchronously."""

        if not _is_installation_id(installation_id):
            return None
        return self._start_retirement_worker(
            name="xenix-amd-capability-retire",
            target=lambda state: self._run_retirement(state, installation_id),
        )

    def cancel(self, operation_id: int) -> bool:
        """Suppress only worker delivery not yet emitted for one operation.

        The service does not expose a reversible cancellation command.  A
        user-requested Remove is the only durable path that may cancel an
        in-flight materialization.  Qt may still deliver an already queued
        signal, so UI consumers must use ``operation_id`` as the final fence.
        """

        with self._lock:
            if not _is_operation_id(operation_id):
                return False
            for state in (self._primary_task, self._retirement_task):
                if state is not None and state.operation_id == operation_id:
                    state.delivery_cancelled = True
                    return True
            return False

    def shutdown(self) -> None:
        """Close the UI boundary and suppress worker delivery not already queued.

        Callers that destroy their receiving QObject must disconnect its slots
        before destruction, because Qt cannot retract an already queued signal.
        A still-queued payload remains safely distinguishable by its operation
        ID and must be ignored by a later UI operation.
        """

        with self._lock:
            self._closed = True
            for state in (self._primary_task, self._retirement_task):
                if state is not None:
                    state.delivery_cancelled = True

    def _start_installation_operation(
        self,
        *,
        operation: AmdCapabilityOperation,
        installation_id: str,
        invoke: Callable[[AmdProgressSink], AmdInstallationStatus],
    ) -> int | None:
        return self._start_primary_worker(
            name=f"xenix-amd-capability-{operation.value}",
            target=lambda state: self._run_installation_operation(
                state,
                operation=operation,
                installation_id=installation_id,
                invoke=invoke,
            ),
            pending_installation_id=(
                installation_id
                if operation
                in {
                    AmdCapabilityOperation.PRIVATE_INSTALL,
                    AmdCapabilityOperation.EXISTING_PRIVATE_INSTALL,
                    AmdCapabilityOperation.LOCAL_WSL_INSTALL,
                }
                else None
            ),
        )

    def _start_primary_worker(
        self,
        *,
        name: str,
        target: Callable[[_AmdCapabilityTaskState], None],
        pending_installation_id: str | None = None,
    ) -> int | None:
        with self._lock:
            if self._closed or self._primary_task is not None or self._retirement_task is not None:
                return None
            operation_id = self._allocate_operation_id()
            state = _AmdCapabilityTaskState(
                operation_id=operation_id,
                pending_installation_id=pending_installation_id,
                installation_completion=(
                    threading.Event()
                    if pending_installation_id is not None
                    else None
                ),
            )
            self._primary_task = state
        if self._start_worker(
            name=name,
            target=target,
            state=state,
            complete=self._complete_primary_task,
        ):
            return operation_id
        return None

    def _start_retirement_worker(
        self,
        *,
        name: str,
        target: Callable[[_AmdCapabilityTaskState], None],
    ) -> int | None:
        with self._lock:
            if self._closed or self._retirement_task is not None:
                return None
            operation_id = self._allocate_operation_id()
            state = _AmdCapabilityTaskState(operation_id=operation_id)
            self._retirement_task = state
        if self._start_worker(
            name=name,
            target=target,
            state=state,
            complete=self._complete_retirement_task,
        ):
            return operation_id
        return None

    def _start_worker(
        self,
        *,
        name: str,
        target: Callable[[_AmdCapabilityTaskState], None],
        state: _AmdCapabilityTaskState,
        complete: Callable[[_AmdCapabilityTaskState], None],
    ) -> bool:
        worker = threading.Thread(target=target, args=(state,), name=name, daemon=True)
        try:
            worker.start()
        except RuntimeError:
            complete(state)
            LOGGER.error(
                "AMD capability worker is unavailable",
                extra={
                    "event_name": "amd.capability.worker_unavailable",
                    "worker": name,
                },
            )
            return False
        return True

    def _run_installation_operation(
        self,
        state: _AmdCapabilityTaskState,
        *,
        operation: AmdCapabilityOperation,
        installation_id: str,
        invoke: Callable[[AmdProgressSink], AmdInstallationStatus],
    ) -> None:
        try:
            status = invoke(lambda event: self._report_progress(state, event))
            result = _result_from_status(state.operation_id, operation, installation_id, status)
        except Exception as exc:
            result = self._error_result(state.operation_id, operation, installation_id, exc)
            _log_operation_exception(operation, result.error_code, exc)
        self._complete_primary_task(state)
        if self._may_deliver(state) and isValid(self):
            self.finished.emit(result)

    def _run_host_trust(
        self,
        state: _AmdCapabilityTaskState,
        command: AmdPrivateSshInstallCommand,
    ) -> None:
        try:
            challenge = self._guided.discover_private_host_trust(
                command,
                progress=lambda event: self._report_progress(state, event),
            )
            result = AmdHostTrustTaskResult(
                operation_id=state.operation_id,
                command=command,
                challenge=challenge,
                succeeded=True,
            )
        except Exception as exc:
            result = AmdHostTrustTaskResult(
                operation_id=state.operation_id,
                command=command,
                succeeded=False,
                error_code=_error_code_for(exc),
                invalid_field=_invalid_field_for(exc),
            )
            _log_host_trust_exception(result.error_code, exc)
        self._complete_primary_task(state)
        if self._may_deliver(state) and isValid(self):
            self.host_trust_finished.emit(result)

    def _run_local_wsl_discovery(self, state: _AmdCapabilityTaskState) -> None:
        try:
            distributions = self._guided.local_wsl_distributions()
            result = AmdLocalWslDiscoveryTaskResult(
                operation_id=state.operation_id,
                distributions=tuple(distributions),
                succeeded=True,
            )
        except Exception as exc:
            result = AmdLocalWslDiscoveryTaskResult(
                operation_id=state.operation_id,
                distributions=(),
                succeeded=False,
                error_code=_error_code_for(exc),
                invalid_field=_invalid_field_for(exc),
            )
            _log_wsl_discovery_exception(result.error_code, exc)
        self._complete_primary_task(state)
        if self._may_deliver(state) and isValid(self):
            self.local_wsl_discovery_finished.emit(result)

    def _run_retirement(self, state: _AmdCapabilityTaskState, installation_id: str) -> None:
        try:
            request = self._request_retirement_when_installation_exists(installation_id)
            result = _result_from_retirement_request(state.operation_id, installation_id, request)
        except Exception as exc:
            result = self._retirement_error_result(state.operation_id, installation_id, exc)
            _log_operation_exception(AmdCapabilityOperation.RETIRE, result.error_code, exc)
        self._complete_retirement_task(state)
        if self._may_deliver(state) and isValid(self):
            self.retirement_acknowledged.emit(result)

    def _error_result(
        self,
        operation_id: int,
        operation: AmdCapabilityOperation,
        installation_id: str,
        exc: Exception,
    ) -> AmdCapabilityTaskResult:
        return AmdCapabilityTaskResult(
            operation_id=operation_id,
            operation=operation,
            installation_id=installation_id,
            status=None,
            succeeded=False,
            error_code=_error_code_for(exc),
            invalid_field=_invalid_field_for(exc),
            installation_available=self._known_installation_availability(installation_id),
            condition="failed",
            phase="failed",
        )

    def _retirement_error_result(
        self,
        operation_id: int,
        installation_id: str,
        exc: Exception,
    ) -> AmdRetirementAcknowledgement:
        return AmdRetirementAcknowledgement(
            operation_id=operation_id,
            installation_id=installation_id,
            acknowledged=False,
            request_phase=None,
            error_code=_error_code_for(exc),
            invalid_field=_invalid_field_for(exc),
        )

    def _known_installation_availability(self, installation_id: str) -> bool | None:
        """Return only positive knowledge; absent inventory rows are ambiguous."""

        try:
            inventory = self._guided.inventory()
        except Exception:
            return None
        for installation in inventory:
            if installation.installation_id == installation_id:
                return installation.lifecycle_state != "removed"
        return None

    def _request_retirement_when_installation_exists(
        self,
        installation_id: str,
    ) -> AmdRetirementRequest:
        """Bridge only the tiny intent-save race for this runner's new install."""

        while True:
            try:
                return self._guided.request_retirement(installation_id)
            except Exception as exc:
                if _error_code_for(exc) != "amd_installation_not_found":
                    raise
                completion = self._pending_install_completion(installation_id)
                if completion is None:
                    raise
                completion.wait(_RETIRE_INSTALLATION_APPEAR_RETRY_SECONDS)
                if completion.is_set():
                    return self._guided.request_retirement(installation_id)

    def _pending_install_completion(self, installation_id: str) -> threading.Event | None:
        with self._lock:
            state = self._primary_task
            if state is None or state.pending_installation_id != installation_id:
                return None
            return state.installation_completion

    def _report_progress(self, state: _AmdCapabilityTaskState, event: AmdProgressEvent) -> None:
        if not isinstance(event, AmdProgressEvent):
            return
        with self._lock:
            should_deliver = (
                not self._closed
                and not state.delivery_cancelled
                and self._primary_task is state
        )
        if should_deliver and isValid(self):
            self.progressed.emit(
                AmdCapabilityProgressUpdate(
                    operation_id=state.operation_id,
                    event=event,
                )
            )

    def _complete_primary_task(self, state: _AmdCapabilityTaskState) -> None:
        with self._lock:
            if state.installation_completion is not None:
                state.installation_completion.set()
            if self._primary_task is state:
                self._primary_task = None

    def _complete_retirement_task(self, state: _AmdCapabilityTaskState) -> None:
        with self._lock:
            if self._retirement_task is state:
                self._retirement_task = None

    def _may_deliver(self, state: _AmdCapabilityTaskState) -> bool:
        with self._lock:
            return not self._closed and not state.delivery_cancelled

    def _allocate_operation_id(self) -> int:
        """Allocate one monotonic opaque token while the runner lock is held."""

        self._next_operation_id += 1
        return self._next_operation_id

    def _require_open(self) -> None:
        with self._lock:
            if self._closed:
                raise AmdGuidedDeploymentError("amd_deployment_closed")


def _result_from_status(
    operation_id: int,
    operation: AmdCapabilityOperation,
    installation_id: str,
    status: AmdInstallationStatus,
) -> AmdCapabilityTaskResult:
    if not isinstance(status, AmdInstallationStatus) or status.installation_id != installation_id:
        raise _AmdCapabilityTaskError("amd_status_invalid")

    condition = _safe_code(status.condition.value, fallback="unknown")
    active_component = _active_component(status)
    phase = _safe_code(
        active_component.phase if active_component is not None else None,
        fallback=condition,
    )
    error_code = _status_error_code(status, active_component)
    succeeded = (
        status.condition is AmdInstallationCondition.OPERATIONAL
        and status.profile_usable
    )
    if not succeeded and error_code is None:
        error_code = {
            AmdInstallationCondition.INCOMPATIBLE: "amd_compatibility_failed",
            AmdInstallationCondition.DEGRADED: "amd_deployment_degraded",
            AmdInstallationCondition.INSTALLING: "amd_deployment_incomplete",
            AmdInstallationCondition.NOT_MATERIALIZED: "amd_not_materialized",
            AmdInstallationCondition.RETIRING: "amd_installation_retiring",
            AmdInstallationCondition.REMOVAL_BLOCKED: "amd_removal_blocked",
            AmdInstallationCondition.REMOVED: "amd_installation_removed",
        }.get(status.condition, "amd_operation_failed")
    return AmdCapabilityTaskResult(
        operation_id=operation_id,
        operation=operation,
        installation_id=installation_id,
        status=status,
        succeeded=succeeded,
        error_code=None if succeeded else error_code,
        installation_available=status.condition is not AmdInstallationCondition.REMOVED,
        condition=condition,
        phase=phase,
    )


def _result_from_retirement_request(
    operation_id: int,
    installation_id: str,
    request: AmdRetirementRequest,
) -> AmdRetirementAcknowledgement:
    if not isinstance(request, AmdRetirementRequest) or request.installation_id != installation_id:
        raise _AmdCapabilityTaskError("amd_request_invalid")
    phase = _safe_code(request.phase, fallback="retirement_requested")
    return AmdRetirementAcknowledgement(
        operation_id=operation_id,
        installation_id=installation_id,
        acknowledged=True,
        request_phase=phase,
    )


def _active_component(status: AmdInstallationStatus):
    components = tuple(status.components)
    failed = next((component for component in components if component.error_code), None)
    if failed is not None:
        return failed
    unfinished = next((component for component in components if component.phase != "registered"), None)
    return unfinished or (components[0] if components else None)


def _status_error_code(status: AmdInstallationStatus, active_component: object | None) -> str | None:
    target_error = _safe_code(status.target_observation_error_code)
    if target_error is not None:
        return target_error
    component_error = _safe_code(getattr(active_component, "error_code", None))
    if component_error is not None:
        return component_error
    return next(
        (
            issue
            for candidate in status.compatibility_issues
            if (issue := _safe_code(candidate)) is not None
        ),
        None,
    )


def _error_code_for(exc: Exception) -> str:
    if isinstance(exc, (_AmdCapabilityTaskError, AmdGuidedDeploymentError, AmdDeploymentError)):
        return _safe_code(exc.error_code, fallback="amd_operation_failed") or "amd_operation_failed"
    safe_error_code = _safe_code(getattr(exc, "error_code", None))
    if safe_error_code is not None:
        return safe_error_code
    if isinstance(exc, (TypeError, ValueError)):
        return "amd_request_invalid"
    return "amd_operation_failed"


def _invalid_field_for(exc: Exception) -> AmdGuidedInputField | None:
    return exc.field if isinstance(exc, AmdGuidedDeploymentError) else None


def _is_installation_id(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_operation_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_code(value: object, *, fallback: str | None = None) -> str | None:
    if isinstance(value, str) and _SAFE_CODE_PATTERN.fullmatch(value):
        return value
    return fallback


def _log_operation_exception(
    operation: AmdCapabilityOperation,
    error_code: str | None,
    exc: Exception,
) -> None:
    LOGGER.warning(
        "AMD capability operation raised",
        extra={
            "event_name": "amd.capability.operation.raised",
            "operation": operation.value,
            "error_code": error_code or "amd_operation_failed",
            "exception_type": type(exc).__name__,
        },
    )


def _log_host_trust_exception(error_code: str | None, exc: Exception) -> None:
    LOGGER.warning(
        "AMD capability host-trust discovery raised",
        extra={
            "event_name": "amd.capability.host_trust.raised",
            "error_code": error_code or "amd_operation_failed",
            "exception_type": type(exc).__name__,
        },
    )


def _log_wsl_discovery_exception(error_code: str | None, exc: Exception) -> None:
    LOGGER.warning(
        "AMD capability WSL discovery raised",
        extra={
            "event_name": "amd.capability.wsl_discovery.raised",
            "error_code": error_code or "amd_operation_failed",
            "exception_type": type(exc).__name__,
        },
    )


__all__ = [
    "AmdCapabilityOperation",
    "AmdCapabilityDeploymentOption",
    "AmdCapabilityProgressUpdate",
    "AmdCapabilityTaskResult",
    "AmdCapabilityTaskRunner",
    "AmdExistingPrivateSshInstallCommand",
    "AmdGuidedCapabilityInstallation",
    "AmdGuidedDeploymentError",
    "AmdGuidedInputField",
    "AmdGuidedPrivateTarget",
    "AmdHostTrustTaskResult",
    "AmdLocalWslDiscoveryTaskResult",
    "AmdLocalWslInstallCommand",
    "AmdPrivateSshInstallCommand",
    "AmdProgressEvent",
    "AmdRetirementAcknowledgement",
    "AmdSshHostTrustChallenge",
]
