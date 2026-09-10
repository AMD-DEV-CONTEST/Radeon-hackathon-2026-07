"""Sequential Preview variation wall sharing one GPU runtime lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import threading
import time
import uuid

from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.gpu_runtime_lane import try_acquire_gpu_runtime_lane
from specstyle.workflow.preview_run_one import (
    PreviewRunOneFds,
    PreviewRunOneResult,
    PreviewRunStatus,
    _PreviewRunFailure,
    open_preview_runtime_session,
)
from specstyle.workflow.preview_wall_evidence import (
    PreviewWallEvidenceItem,
    PreviewWallEvidencePublication,
    publish_preview_wall_evidence,
)


class PreviewWallStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BUSY = "BUSY"


_RESERVATION_SEAL = object()


class PreviewWallReservation:
    __slots__ = ("_consumed", "_lock", "_run_ids", "_seal", "_wall_id")

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("preview wall reservations are issued only by reserve")

    @property
    def wall_id(self) -> str:
        _validate_reservation(self, require_open=False)
        return self._wall_id

    @property
    def run_ids(self) -> tuple[str, ...]:
        _validate_reservation(self, require_open=False)
        return self._run_ids

    def _consume(self) -> tuple[str, tuple[str, ...]]:
        with self._lock:
            _validate_reservation(self, require_open=True)
            self._consumed = True
            return self._wall_id, self._run_ids

    def __copy__(self) -> PreviewWallReservation:
        raise TypeError("preview wall reservations cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> PreviewWallReservation:
        raise TypeError("preview wall reservations cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("preview wall reservations cannot be serialized")


def _validate_reservation(value: object, *, require_open: bool) -> None:
    if (
        type(value) is not PreviewWallReservation
        or getattr(value, "_seal", None) is not _RESERVATION_SEAL
        or type(getattr(value, "_wall_id", None)) is not str
        or not value._wall_id.startswith("preview-wall-")
        or type(getattr(value, "_run_ids", None)) is not tuple
        or not 1 <= len(value._run_ids) <= 4
        or value._run_ids
        != tuple(f"{value._wall_id}-v{index}" for index in range(len(value._run_ids)))
        or type(getattr(value, "_consumed", None)) is not bool
    ):
        raise DomainError("invalid preview wall reservation")
    if require_open and value._consumed:
        raise DomainError("preview wall reservation already consumed")


def reserve_preview_wall(count: int = 4) -> PreviewWallReservation:
    if type(count) is not int or not 1 <= count <= 4:
        raise DomainError("preview wall count must be an exact int in range")
    issued = object.__new__(PreviewWallReservation)
    issued._wall_id = f"preview-wall-{uuid.uuid4().hex}"
    issued._run_ids = tuple(f"{issued._wall_id}-v{index}" for index in range(count))
    issued._consumed = False
    issued._lock = threading.Lock()
    issued._seal = _RESERVATION_SEAL
    _validate_reservation(issued, require_open=True)
    return issued


@dataclass(frozen=True, slots=True)
class PreviewWallItemResult:
    variation_index: int
    attempted: bool
    run: PreviewRunOneResult

    def __post_init__(self) -> None:
        if (
            type(self.variation_index) is not int
            or not 0 <= self.variation_index < 4
            or type(self.attempted) is not bool
            or type(self.run) is not PreviewRunOneResult
            or (self.run.status is PreviewRunStatus.COMPLETED and not self.attempted)
            or (self.run.status is PreviewRunStatus.BUSY and self.attempted)
        ):
            raise DomainError("invalid preview wall item result")
        if self.run.publication is not None:
            if self.run.publication.variation_index != self.variation_index:
                raise DomainError("preview wall variation binding mismatch")


@dataclass(frozen=True, slots=True)
class PreviewWallResult:
    wall_id: str
    status: PreviewWallStatus
    reason_code: str
    items: tuple[PreviewWallItemResult, ...]
    elapsed_seconds: float
    publication: PreviewWallEvidencePublication | None
    verification: str = "NOT_RUN"
    repair: str = "NOT_RUN"
    export: str = "NOT_RUN"

    def __post_init__(self) -> None:
        persist_failed = self.reason_code == "PERSIST_FAILED"
        if (
            type(self.wall_id) is not str
            or not self.wall_id.startswith("preview-wall-")
            or type(self.status) is not PreviewWallStatus
            or type(self.reason_code) is not str
            or not self.reason_code
            or type(self.items) is not tuple
            or not 1 <= len(self.items) <= 4
            or any(type(item) is not PreviewWallItemResult for item in self.items)
            or tuple(item.variation_index for item in self.items)
            != tuple(range(len(self.items)))
            or any(
                item.run.run_id != f"{self.wall_id}-v{item.variation_index}"
                for item in self.items
            )
            or type(self.elapsed_seconds) is not float
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
            or (
                self.publication is not None
                and (
                    type(self.publication) is not PreviewWallEvidencePublication
                    or self.publication.evidence_name != self.wall_id
                )
            )
            or (persist_failed == (self.publication is not None))
            or any(
                value != "NOT_RUN"
                for value in (self.verification, self.repair, self.export)
            )
        ):
            raise DomainError("invalid preview wall result")
        completed = sum(
            item.run.status is PreviewRunStatus.COMPLETED for item in self.items
        )
        busy = sum(item.run.status is PreviewRunStatus.BUSY for item in self.items)
        if (
            (
                self.status is PreviewWallStatus.COMPLETED
                and completed != len(self.items)
            )
            or (self.status is PreviewWallStatus.PARTIAL and completed == 0)
            or (self.status is PreviewWallStatus.BUSY and busy != len(self.items))
            or (
                self.reason_code == "OK"
                and self.status is not PreviewWallStatus.COMPLETED
            )
            or (
                self.reason_code == "GPU_BUSY"
                and self.status is not PreviewWallStatus.BUSY
            )
            or (self.status is PreviewWallStatus.COMPLETED and self.reason_code != "OK")
            or (
                self.status is PreviewWallStatus.PARTIAL
                and self.reason_code not in {"PARTIAL", "CLEANUP_FAILED"}
            )
            or (
                self.status is PreviewWallStatus.FAILED
                and self.reason_code
                not in {"ALL_FAILED", "CLEANUP_FAILED", "PERSIST_FAILED"}
            )
            or (
                self.status is PreviewWallStatus.BUSY and self.reason_code != "GPU_BUSY"
            )
        ):
            raise DomainError("invalid preview wall result status")


def _unattempted(
    run_id: str, variation_index: int, status: PreviewRunStatus, reason: str
) -> PreviewWallItemResult:
    return PreviewWallItemResult(
        variation_index,
        False,
        PreviewRunOneResult(run_id, status, reason, None),
    )


def _evidence_item(item: PreviewWallItemResult) -> PreviewWallEvidenceItem:
    return PreviewWallEvidenceItem(
        item.variation_index,
        item.attempted,
        item.run.run_id,
        item.run.status.value,
        item.run.reason_code,
        item.run.publication,
    )


def _status(
    items: tuple[PreviewWallItemResult, ...], cleanup: str
) -> PreviewWallStatus:
    completed = sum(item.run.status is PreviewRunStatus.COMPLETED for item in items)
    if all(item.run.status is PreviewRunStatus.BUSY for item in items):
        return PreviewWallStatus.BUSY
    if completed == len(items) and cleanup == "COMPLETED":
        return PreviewWallStatus.COMPLETED
    if completed:
        return PreviewWallStatus.PARTIAL
    return PreviewWallStatus.FAILED


def _reason(status: PreviewWallStatus, cleanup: str) -> str:
    if cleanup == "FAILED":
        return "CLEANUP_FAILED"
    return {
        PreviewWallStatus.COMPLETED: "OK",
        PreviewWallStatus.PARTIAL: "PARTIAL",
        PreviewWallStatus.FAILED: "ALL_FAILED",
        PreviewWallStatus.BUSY: "GPU_BUSY",
    }[status]


def _publish_result(
    fds: PreviewRunOneFds,
    wall_id: str,
    items: tuple[PreviewWallItemResult, ...],
    elapsed: float,
    cleanup: str,
) -> PreviewWallResult:
    status = _status(items, cleanup)
    reason = _reason(status, cleanup)
    try:
        publication = publish_preview_wall_evidence(
            fds.preview_evidence_root_fd,
            wall_id,
            tuple(_evidence_item(item) for item in items),
            elapsed,
            cleanup,
        )
    except (DomainError, InfrastructureError, OSError):
        return PreviewWallResult(
            wall_id,
            PreviewWallStatus.FAILED,
            "PERSIST_FAILED",
            items,
            elapsed,
            None,
        )
    return PreviewWallResult(wall_id, status, reason, items, elapsed, publication)


def _abort_remaining(
    items: list[PreviewWallItemResult], run_ids: tuple[str, ...]
) -> None:
    for variation_index in range(len(items), len(run_ids)):
        items.append(
            _unattempted(
                run_ids[variation_index],
                variation_index,
                PreviewRunStatus.FAILED,
                "WALL_ABORTED",
            )
        )


def _must_abort(result: PreviewRunOneResult) -> bool:
    return result.status is PreviewRunStatus.UNAVAILABLE or result.reason_code in {
        "PERSIST_FAILED",
        "CLEANUP_FAILED",
        "INTERNAL_FAILURE",
    }


def _run_items(
    session: object, run_ids: tuple[str, ...]
) -> list[PreviewWallItemResult]:
    items: list[PreviewWallItemResult] = []
    for variation_index, run_id in enumerate(run_ids):
        try:
            result = session.run_item(run_id, variation_index)
            if type(result) is not PreviewRunOneResult or result.run_id != run_id:
                raise DomainError("invalid preview wall runtime result")
        except (DomainError, InfrastructureError, OSError):
            result = PreviewRunOneResult(
                run_id, PreviewRunStatus.FAILED, "INTERNAL_FAILURE", None
            )
        items.append(PreviewWallItemResult(variation_index, True, result))
        if _must_abort(result):
            break
    _abort_remaining(items, run_ids)
    return items


def run_preview_wall(
    fds: PreviewRunOneFds, reservation: PreviewWallReservation, /
) -> PreviewWallResult:
    if type(fds) is not PreviewRunOneFds:
        raise DomainError("invalid preview wall input")
    _validate_reservation(reservation, require_open=True)
    wall_id, run_ids = reservation._consume()
    started = time.monotonic()
    lane = try_acquire_gpu_runtime_lane()
    if lane is None:
        items = tuple(
            _unattempted(run_id, index, PreviewRunStatus.BUSY, "GPU_BUSY")
            for index, run_id in enumerate(run_ids)
        )
        return _publish_result(
            fds, wall_id, items, time.monotonic() - started, "NOT_STARTED"
        )
    session = None
    cleanup = "COMPLETED"
    items: tuple[PreviewWallItemResult, ...]
    try:
        try:
            session = open_preview_runtime_session(fds)
            items = tuple(_run_items(session, run_ids))
        except _PreviewRunFailure as error:
            items = tuple(
                _unattempted(run_id, index, error.status, error.reason_code)
                for index, run_id in enumerate(run_ids)
            )
        except (DomainError, InfrastructureError, OSError):
            items = tuple(
                _unattempted(
                    run_id,
                    index,
                    PreviewRunStatus.FAILED,
                    "INTERNAL_FAILURE",
                )
                for index, run_id in enumerate(run_ids)
            )
    finally:
        if session is not None and session.close():
            cleanup = "FAILED"
        lane.close()
    return _publish_result(fds, wall_id, items, time.monotonic() - started, cleanup)


__all__ = (
    "PreviewWallItemResult",
    "PreviewWallReservation",
    "PreviewWallResult",
    "PreviewWallStatus",
    "reserve_preview_wall",
    "run_preview_wall",
)
