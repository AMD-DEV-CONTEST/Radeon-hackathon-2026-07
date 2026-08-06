"""Fail-closed AMD cgroup-v2 memory admission and local GPU leasing.

The core performs no subprocess or shell work.  Cgroup reads, the clock, the
VRAM sampler, and the atomic audit writer are explicit boundaries so the same
guard can protect FLUX.2 and MiniMax H3 execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import mmap
import os
import stat
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, cast

HARD_MEMORY_MAX_BYTES = 59_055_800_320
ADMISSION_REJECT_BYTES = 47_244_640_256
DRAIN_UNLOAD_BYTES = 53_150_220_288
MIN_PERSISTENT_AVAILABLE_BYTES = 5 * 1024**3
FLUX_REQUIRED_ARGUMENTS = (
    "--highvram",
    "--cache-none",
    "--reserve-vram",
    "2",
)
FLUX_FORBIDDEN_ARGUMENTS = frozenset({"--lowvram", "--disable-mmap"})
CHARACTER_REFERENCE_VIEW_ORDER = (
    "front",
    "three_quarter_left",
    "profile_left",
)

_REQUIRED_EVENT_COUNTERS = frozenset(
    {"low", "high", "max", "oom", "oom_kill", "oom_group_kill"}
)
_RECOVERY_EVENT_COUNTERS = frozenset(
    {"max", "oom", "oom_kill", "oom_group_kill"}
)
_OOM_EVENT_COUNTERS = ("oom", "oom_kill", "oom_group_kill")
_OUTCOMES = frozenset({"completed", "failed", "cancelled"})
_FROZEN_MODEL_REVISIONS = {
    "flux": "flux2-dev-fp8mixed.v1",
    "h3": "h3-amd-local-v1",
}
_LEASE_FACTORY_SEAL = object()
_TRUSTED_REGISTRY_FACTORY_SEAL = object()
_TRUSTED_IDLE_VRAM_REGISTRY_FACTORY_SEAL = object()
_REGISTRY_DEPLOYMENT_AUTHORITY_FACTORY_SEAL = object()


def _load_amd_contract_types() -> tuple[type, type, type, type] | None:
    """Resolve the canonical shared models without creating a fallback schema."""

    try:
        from shared_contracts.amd_resource import (
            AMDAdmissionLeaseAuthorityV1,
            AMDPressureRecoveryAuthorityV1,
            AMDProvisionalResourceAdmissionDecisionV1,
            AMDResourceAdmissionRequestV1,
        )
    except (ImportError, ModuleNotFoundError):
        return None
    return (
        AMDResourceAdmissionRequestV1,
        AMDProvisionalResourceAdmissionDecisionV1,
        AMDAdmissionLeaseAuthorityV1,
        AMDPressureRecoveryAuthorityV1,
    )


def _lexically_absolute(path: Path) -> bool:
    return path.is_absolute() and Path(os.path.abspath(os.fspath(path))) == path


def _unified_cgroup_path(raw: bytes) -> PurePosixPath:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CgroupDataError("unified cgroup membership is not ASCII") from exc
    matches: list[str] = []
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            matches.append(fields[2])
    if len(matches) != 1:
        raise CgroupDataError("exactly one unified cgroup membership is required")
    value = matches[0]
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\x00" in value
    ):
        raise CgroupDataError("unified cgroup path is invalid")
    path = PurePosixPath(value)
    if not path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise CgroupDataError("unified cgroup path is not canonical")
    return path


def _open_absolute_directory_no_follow(path: Path) -> int:
    if os.name != "posix":
        raise OSError("secure directory authority requires Linux")
    if not _lexically_absolute(path):
        raise CgroupDataError("directory authority must be canonical and absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    current_fd = os.open("/", flags)
    try:
        for component in PurePosixPath(path.as_posix()).parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            try:
                value = os.fstat(next_fd)
                if not stat.S_ISDIR(value.st_mode) or value.st_nlink < 1:
                    raise CgroupDataError(
                        "directory authority contains a non-directory or unlinked inode"
                    )
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise CgroupDataError(
            "directory authority contains a link or unavailable component"
        ) from exc
    except Exception:
        os.close(current_fd)
        raise


def _cgroup_path_from_proc(
    *,
    proc_root: Path,
    cgroup_mount: Path,
    process: str,
) -> Path:
    try:
        membership = (proc_root / process / "cgroup").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        raise
    except OSError as exc:
        raise CgroupDataError("process unified cgroup membership is unavailable") from exc
    relative = _unified_cgroup_path(membership)
    return cgroup_mount.joinpath(*relative.parts[1:])


def _cgroup_generation_from_status(value: os.stat_result) -> str:
    authority = f"cgroup2:{value.st_dev}:{value.st_ino}".encode("ascii")
    return hashlib.sha256(authority).hexdigest()


def _safe_weight_path(value: str) -> bool:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\x00" in value
        or any(character in value for character in "*?[]{}")
        or any(ord(character) < 32 for character in value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        path.is_absolute()
        and path.as_posix() == value
        and "." not in path.parts
        and ".." not in path.parts
        and path.suffix == ".safetensors"
        and len(value) <= 4_096
    )


class MemoryGuardError(RuntimeError):
    """Base class for fail-closed memory guard errors."""


class CgroupDataError(MemoryGuardError):
    """Cgroup data is missing, malformed, unlimited, or from the wrong scope."""


class StaleObservation(CgroupDataError):
    """An injected observation is too old or implausibly from the future."""


class CgroupGenerationChanged(CgroupDataError):
    """The container/cgroup identity changed while this guard was live."""


class MemoryCounterRegression(CgroupDataError):
    """A monotonic cgroup memory event counter moved backwards."""


class SwapEnabled(MemoryGuardError):
    """Swap is enabled or already in use for the guarded cgroup."""


class MemoryAdmissionDenied(MemoryGuardError):
    """A generation task cannot start at the current memory level."""


class DrainUnloadRequired(MemoryAdmissionDenied):
    """Only an unload phase may run before the next generation task."""


class RecoveryRequired(DrainUnloadRequired):
    """A fresh guard/process/container is required after memory pressure."""


class LocalGpuBusy(MemoryGuardError):
    """The single local GPU lease is already held."""


class AuxiliaryWorkDenied(MemoryGuardError):
    """Memory-heavy maintenance is denied while a GPU lease is active."""


class LeaseStateError(MemoryGuardError):
    """A lease was forged, reused, or completed through the wrong guard."""


class GpuAuthorityBusy(LocalGpuBusy):
    """Another process or a retained child model owns local_gpu."""


class PageCacheReclaimDenied(MemoryGuardError):
    """A targeted weight reclaim request is not safely authorized."""


class PageCacheReclaimIneffective(MemoryGuardError):
    """Targeted advice did not reduce both file cache and cgroup usage."""


@dataclass(frozen=True, slots=True)
class LiveStartObservation:
    """Trusted resample captured inside the durable admission-consume lock."""

    captured_at_epoch_seconds: float
    cgroup_generation_id: str
    memory_current_bytes: int
    memory_peak_bytes: int
    memory_max_bytes: int
    memory_anon_bytes: int
    memory_file_bytes: int
    memory_events_source: str
    memory_events: Mapping[str, int]
    topology: object

    def to_dict(self) -> dict[str, object]:
        topology = self.topology
        if hasattr(topology, "model_dump"):
            topology = topology.model_dump(mode="json")
        return {
            "capturedAtEpochSeconds": self.captured_at_epoch_seconds,
            "cgroupGenerationId": self.cgroup_generation_id,
            "memoryCurrentBytes": self.memory_current_bytes,
            "memoryPeakBytes": self.memory_peak_bytes,
            "memoryMaxBytes": self.memory_max_bytes,
            "memoryAnonBytes": self.memory_anon_bytes,
            "memoryFileBytes": self.memory_file_bytes,
            "memoryEventsSource": self.memory_events_source,
            "memoryEvents": dict(self.memory_events),
            "topology": topology,
        }


@dataclass(frozen=True, slots=True)
class AmdGpuPreflightEvidence:
    """Go/no-go evidence sampled immediately before a GPU process launch."""

    memory: MemorySnapshot
    persistent_available_bytes: int
    running_comfyui_instances: int
    running_gpu_tasks: int
    running_flux_processes: int
    running_h3_processes: int

    def validate(self) -> None:
        counters = (
            self.running_comfyui_instances,
            self.running_gpu_tasks,
            self.running_flux_processes,
            self.running_h3_processes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counters):
            raise MemoryAdmissionDenied("GPU process topology evidence is invalid")
        if any(counters):
            raise GpuAuthorityBusy("FLUX/H3/ComfyUI residual process exists")
        if (
            self.memory.memory_max_bytes != HARD_MEMORY_MAX_BYTES
            or self.memory.swap_current_bytes != 0
            or self.memory.swap_max_bytes != 0
            or self.memory.memory_current_bytes < 0
            or self.memory.memory_current_bytes >= ADMISSION_REJECT_BYTES
            or self.memory.memory_peak_bytes < self.memory.memory_current_bytes
            or self.memory.memory_peak_bytes > HARD_MEMORY_MAX_BYTES
            or self.memory.memory_anon_bytes < 0
            or self.memory.memory_file_bytes < 0
            or self.memory.memory_anon_bytes + self.memory.memory_file_bytes
            > self.memory.memory_current_bytes
        ):
            raise MemoryAdmissionDenied("memory.current must be below 44 GiB")
        if self.memory.events_source != "memory.events.local":
            raise CgroupDataError("memory.events.local is required for GPU admission")
        if self.memory.vram.used_bytes > self.memory.idle_vram_threshold_bytes:
            raise GpuAuthorityBusy("VRAM must be at its trusted idle threshold")
        if (
            isinstance(self.persistent_available_bytes, bool)
            or not isinstance(self.persistent_available_bytes, int)
            or self.persistent_available_bytes < MIN_PERSISTENT_AVAILABLE_BYTES
        ):
            raise MemoryAdmissionDenied("persistent storage must retain 5 GiB free")


@dataclass(frozen=True, slots=True)
class DurableGpuSubmissionEvidence:
    prompt_id: str
    submission_nonce: str
    workflow_sha256: str
    asset_sha256: tuple[str, ...]
    persistent_state_path: str
    history_reconciled: bool
    compressed_database_backup_path: str
    database_backup_retention_count: int

    def validate(self) -> None:
        labels = (self.prompt_id, self.submission_nonce)
        if any(not isinstance(value, str) or not value.strip() for value in labels):
            raise LeaseStateError("persistent prompt identity is incomplete")
        digests = (self.workflow_sha256, *self.asset_sha256)
        if not digests or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in digests
        ):
            raise LeaseStateError("persistent workflow/asset SHA authority is invalid")
        for path in (
            self.persistent_state_path,
            self.compressed_database_backup_path,
        ):
            if (
                not isinstance(path, str)
                or not path.startswith("/persistent/douyin-amd/")
                or not PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
            ):
                raise LeaseStateError("recovery evidence must use the persistent root")
        if not self.compressed_database_backup_path.endswith(
            (".zst", ".gz", ".xz")
        ):
            raise LeaseStateError("database backup must be compressed")
        if self.history_reconciled is not True:
            raise LeaseStateError("ComfyUI history must be reconciled before resubmit")
        if (
            isinstance(self.database_backup_retention_count, bool)
            or not isinstance(self.database_backup_retention_count, int)
            or not 1 <= self.database_backup_retention_count <= 3
        ):
            raise LeaseStateError("database backup retention must be limited to 1..3")


def validate_flux_launch_contract(
    argv: tuple[str, ...],
    *,
    ordered_views: tuple[str, ...],
    batch_size: int,
) -> None:
    if not isinstance(argv, tuple) or any(type(value) is not str for value in argv):
        raise ValueError("FLUX arguments must be a frozen tuple of strings")
    if any(
        any(
            value == forbidden or value.startswith(f"{forbidden}=")
            for forbidden in FLUX_FORBIDDEN_ARGUMENTS
        )
        for value in argv
    ):
        raise MemoryAdmissionDenied("unsafe FLUX memory option is forbidden")
    for required in ("--highvram", "--cache-none"):
        if argv.count(required) != 1:
            raise MemoryAdmissionDenied(f"required FLUX option {required} is missing")
    reserve_positions = [index for index, value in enumerate(argv) if value == "--reserve-vram"]
    if (
        len(reserve_positions) != 1
        or reserve_positions[0] + 1 >= len(argv)
        or argv[reserve_positions[0] + 1] != "2"
    ):
        raise MemoryAdmissionDenied("FLUX reserve-vram must be exactly 2 GiB")
    if ordered_views != CHARACTER_REFERENCE_VIEW_ORDER or batch_size != 1:
        raise MemoryAdmissionDenied("three reference views must run sequentially")


class RuntimePhase(StrEnum):
    """Explicit serialized phases shared by FLUX.2 and MiniMax H3."""

    FLUX_LOAD = "flux.load"
    FLUX_T2I_SMOKE = "flux.t2i_smoke"
    FLUX_SINGLE_REFERENCE_SMOKE = "flux.single_reference_smoke"
    FLUX_DUAL_REFERENCE_SMOKE = "flux.dual_reference_smoke"
    FLUX_REFERENCE_GENERATION = "flux.reference_generation"
    FLUX_UNLOAD = "flux.unload"
    H3_LOAD = "h3.load"
    H3_REF2VA_SMOKE = "h3.ref2va_smoke"
    H3_SEQUENCE_GENERATION = "h3.sequence_generation"
    H3_UNLOAD = "h3.unload"

    @property
    def workload(self) -> str:
        return self.value.split(".", 1)[0]

    @property
    def is_unload(self) -> bool:
        return self in {RuntimePhase.FLUX_UNLOAD, RuntimePhase.H3_UNLOAD}


class AuxiliaryWork(StrEnum):
    APT = "apt"
    PIP = "pip"
    SHA256 = "sha256"
    EXTRACT = "extract"


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_time_ticks: int
    cgroup_identity: str
    model_revision: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.pid, bool)
            or not isinstance(self.pid, int)
            or self.pid <= 0
            or isinstance(self.start_time_ticks, bool)
            or not isinstance(self.start_time_ticks, int)
            or self.start_time_ticks <= 0
            or not isinstance(self.cgroup_identity, str)
            or len(self.cgroup_identity) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.cgroup_identity
            )
            or not isinstance(self.model_revision, str)
            or not self.model_revision
            or len(self.model_revision) > 200
        ):
            raise ValueError("process identity is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "startTimeTicks": self.start_time_ticks,
            "cgroupIdentity": self.cgroup_identity,
            "modelRevision": self.model_revision,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProcessIdentity:
        if not isinstance(value, Mapping) or set(value) != {
            "pid",
            "startTimeTicks",
            "cgroupIdentity",
            "modelRevision",
        }:
            raise ValueError("process identity record is invalid")
        pid = value["pid"]
        start_time = value["startTimeTicks"]
        cgroup_identity = value["cgroupIdentity"]
        model_revision = value["modelRevision"]
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(start_time, bool)
            or not isinstance(start_time, int)
            or start_time <= 0
            or not isinstance(cgroup_identity, str)
            or len(cgroup_identity) != 64
            or any(character not in "0123456789abcdef" for character in cgroup_identity)
            or not isinstance(model_revision, str)
            or not model_revision
            or len(model_revision) > 200
        ):
            raise ValueError("process identity record is invalid")
        return cls(
            pid=pid,
            start_time_ticks=start_time,
            cgroup_identity=cgroup_identity,
            model_revision=model_revision,
        )


class ProcfsProcessProbe:
    """Exact Linux PID/starttime/cgroup liveness authority."""

    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        cgroup_mount: Path = Path("/sys/fs/cgroup"),
    ) -> None:
        self.proc_root = proc_root
        self.cgroup_mount = cgroup_mount

    def identity(self, pid: int, model_revision: str) -> ProcessIdentity:
        if os.name != "posix":
            raise OSError("procfs process identity requires Linux")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("process PID is invalid")
        start_time = self._start_time(pid)

        cgroup_path = _cgroup_path_from_proc(
            proc_root=self.proc_root,
            cgroup_mount=self.cgroup_mount,
            process=str(pid),
        )
        cgroup_fd = _open_absolute_directory_no_follow(cgroup_path)
        try:
            cgroup_status = os.fstat(cgroup_fd)
            cgroup_identity = _cgroup_generation_from_status(cgroup_status)
        finally:
            os.close(cgroup_fd)
        if self._start_time(pid) != start_time:
            raise CgroupDataError(
                "process identity changed while procfs authority was sampled"
            )
        return ProcessIdentity(
            pid=pid,
            start_time_ticks=start_time,
            cgroup_identity=cgroup_identity,
            model_revision=model_revision,
        )

    def _start_time(self, pid: int) -> int:
        try:
            stat_text = (self.proc_root / str(pid) / "stat").read_text(
                encoding="ascii"
            )
        except (FileNotFoundError, ProcessLookupError):
            raise
        except OSError as exc:
            raise CgroupDataError("process stat authority is unavailable") from exc
        try:
            _head, tail_text = stat_text.rsplit(")", 1)
            tail = tail_text.split()
            if len(tail) <= 19:
                raise ValueError("truncated stat record")
            start_time = int(tail[19], 10)
            if start_time <= 0:
                raise ValueError("invalid process start time")
            return start_time
        except (IndexError, ValueError) as exc:
            raise CgroupDataError("process stat authority is malformed") from exc

    def is_alive(self, identity: ProcessIdentity) -> bool:
        pidfd: int | None = None
        if hasattr(os, "pidfd_open"):
            try:
                pidfd = os.pidfd_open(identity.pid, 0)
            except ProcessLookupError:
                return False
            except OSError as exc:
                raise CgroupDataError("process liveness is unknown") from exc
        try:
            current = self.identity(identity.pid, identity.model_revision)
        except (FileNotFoundError, ProcessLookupError):
            if pidfd is not None:
                import select

                try:
                    events = select.poll()
                    events.register(pidfd, select.POLLIN)
                    if events.poll(0):
                        return False
                except OSError as exc:
                    raise CgroupDataError("process liveness is unknown") from exc
                raise CgroupDataError(
                    "procfs disappeared while pidfd still identifies a process"
                )
            try:
                os.kill(identity.pid, 0)
            except ProcessLookupError:
                return False
            except OSError as exc:
                raise CgroupDataError("process liveness is unknown") from exc
            raise CgroupDataError(
                "procfs disappeared while the process still responds"
            )
        except CgroupDataError:
            raise
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            raise CgroupDataError("process liveness is unknown") from exc
        finally:
            if pidfd is not None:
                os.close(pidfd)
        if (
            current.pid != identity.pid
            or current.start_time_ticks != identity.start_time_ticks
        ):
            return False
        if current.cgroup_identity != identity.cgroup_identity:
            raise CgroupDataError("live process changed unified cgroup authority")
        if current.model_revision != identity.model_revision:
            raise CgroupDataError("process model revision authority changed")
        return True


@dataclass(slots=True)
class FileGpuAuthorityLease:
    fd: int
    fencing_token: int
    guard_id: str
    model_revision: str
    record: dict[str, object]
    lock_fd: int = -1


class GpuLeaseAuthority(Protocol):
    """Cross-process authority held for every GPU or reclaim critical section."""

    def acquire(
        self,
        *,
        guard_id: str,
        task_id: str,
        phase: RuntimePhase,
        model_revision: str,
    ) -> FileGpuAuthorityLease: ...

    def bind_model_process(
        self,
        lease: FileGpuAuthorityLease,
        identity: ProcessIdentity,
    ) -> None: ...

    def commit_observation_baseline(
        self,
        lease: FileGpuAuthorityLease,
        *,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None: ...

    def model_process_exited(self, lease: FileGpuAuthorityLease) -> bool: ...

    def release(
        self,
        lease: FileGpuAuthorityLease,
        *,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None: ...

    def begin_reclaim(
        self,
        *,
        guard_id: str,
        model_revision: str,
    ) -> FileGpuAuthorityLease: ...

    def finish_reclaim(
        self,
        lease: FileGpuAuthorityLease,
        *,
        success: bool,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None: ...

    def abort_reclaim(self, lease: FileGpuAuthorityLease) -> None: ...


class FileGpuLeaseAuthority:
    """Linux flock authority with durable fencing and retained-child checks."""

    def __init__(
        self,
        record_path: Path,
        *,
        process_probe: ProcfsProcessProbe | None = None,
    ) -> None:
        if not _lexically_absolute(record_path) or record_path.name in {"", ".", ".."}:
            raise ValueError("GPU authority record path must be canonical and absolute")
        self.record_path = record_path
        self.process_probe = process_probe or ProcfsProcessProbe()
        self._parent_fd = -1
        self._parent_identity: tuple[int, int] | None = None
        self._active_lease_count = 0
        if os.name == "posix":
            parent_fd = _open_absolute_directory_no_follow(record_path.parent)
            try:
                value = os.fstat(parent_fd)
                self._parent_identity = (value.st_dev, value.st_ino)
                self._validate_parent_fd(parent_fd)
            except Exception:
                os.close(parent_fd)
                self._parent_identity = None
                raise
            self._parent_fd = parent_fd

    def __enter__(self) -> FileGpuLeaseAuthority:
        if os.name == "posix" and self._parent_fd < 0:
            raise LeaseStateError("GPU authority is closed")
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._active_lease_count:
            raise LeaseStateError("cannot close GPU authority with an active lease")
        if self._parent_fd >= 0:
            os.close(self._parent_fd)
            self._parent_fd = -1
        self._parent_identity = None

    def __del__(self) -> None:
        try:
            if getattr(self, "_active_lease_count", 0) == 0:
                self.close()
        except Exception:
            pass

    def acquire(
        self,
        *,
        guard_id: str,
        task_id: str,
        phase: RuntimePhase,
        model_revision: str,
    ) -> FileGpuAuthorityLease:
        if (
            not isinstance(guard_id, str)
            or not guard_id
            or len(guard_id) > 200
            or not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 200
            or not isinstance(model_revision, str)
            or not model_revision
            or len(model_revision) > 200
        ):
            raise ValueError("GPU authority acquisition labels are invalid")
        try:
            phase = RuntimePhase(phase)
        except (TypeError, ValueError) as exc:
            raise ValueError("GPU authority phase is invalid") from exc
        lock_fd, fd = self._open_and_lock()
        try:
            previous = self._read_record(fd)
            self._reject_retained_owner(
                previous,
                guard_id=guard_id,
                phase=phase,
                model_revision=model_revision,
            )
            fencing = self._next_fencing_token(previous)
            owner = self.process_probe.identity(os.getpid(), model_revision)
            record: dict[str, object] = {
                "schemaVersion": "amd.local-gpu-authority.v1",
                "fencingToken": fencing,
                "state": "active",
                "guardId": guard_id,
                "taskId": task_id,
                "phase": phase.value,
                "modelRevision": model_revision,
                "ownerProcess": owner.to_dict(),
                "modelProcess": previous.get("modelProcess"),
                "cgroupGeneration": previous.get("cgroupGeneration"),
                "events": previous.get("events"),
                "memoryPeakBytes": previous.get("memoryPeakBytes"),
                "recoveryRequired": bool(previous.get("recoveryRequired", False)),
            }
            lease = FileGpuAuthorityLease(
                fd=fd,
                fencing_token=fencing,
                guard_id=guard_id,
                model_revision=model_revision,
                record=record,
                lock_fd=lock_fd,
            )
            self._persist_lease_record(lease, record)
            fd = lease.fd
            self._active_lease_count += 1
            return lease
        except Exception:
            self._close_record_and_unlock_parent(fd, lock_fd)
            raise

    def bind_model_process(
        self,
        lease: FileGpuAuthorityLease,
        identity: ProcessIdentity,
    ) -> None:
        record = self._locked_lease_record(lease, expected_state="active")
        if identity.model_revision != lease.model_revision:
            raise LeaseStateError("model process revision does not match GPU lease")
        raw_owner = record.get("ownerProcess")
        if not isinstance(raw_owner, Mapping):
            raise LeaseStateError("GPU lease owner process identity is unavailable")
        owner = ProcessIdentity.from_mapping(raw_owner)
        if identity.pid == owner.pid:
            raise LeaseStateError("model process must be distinct from the lease owner")
        if identity.cgroup_identity != owner.cgroup_identity:
            raise LeaseStateError("model process is outside the guarded cgroup")
        if record.get("modelProcess") is not None:
            raise LeaseStateError("model process may be bound exactly once")
        if not self.process_probe.is_alive(identity):
            raise LeaseStateError("model process identity is not live and exact")
        record["modelProcess"] = identity.to_dict()
        self._persist_lease_record(lease, record)
        lease.record.clear()
        lease.record.update(record)

    def commit_observation_baseline(
        self,
        lease: FileGpuAuthorityLease,
        *,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None:
        """Durably advance the cgroup watermark before generation is admitted."""

        record = self._locked_lease_record(lease, expected_state="active")
        self._merge_observation_baseline(
            record,
            cgroup_generation=cgroup_generation,
            events=events,
            recovery_required=recovery_required,
            reject_regression=True,
            memory_peak_bytes=memory_peak_bytes,
        )
        self._persist_lease_record(lease, record)
        lease.record.clear()
        lease.record.update(record)

    def model_process_exited(self, lease: FileGpuAuthorityLease) -> bool:
        record = self._locked_lease_record(lease, expected_state="active")
        raw_process = record.get("modelProcess")
        if raw_process is None:
            return False
        if not isinstance(raw_process, Mapping):
            raise LeaseStateError("bound model process identity is invalid")
        identity = ProcessIdentity.from_mapping(raw_process)
        return not self.process_probe.is_alive(identity)

    def release(
        self,
        lease: FileGpuAuthorityLease,
        *,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None:
        record = self._locked_lease_record(lease, expected_state="active")
        record["state"] = (
            "retained" if record.get("modelProcess") is not None else "completed"
        )
        self._merge_observation_baseline(
            record,
            cgroup_generation=cgroup_generation,
            events=events,
            recovery_required=recovery_required,
            reject_regression=False,
            memory_peak_bytes=memory_peak_bytes,
        )
        self._persist_lease_record(lease, record)
        lease.record.clear()
        lease.record.update(record)
        self._close_record_and_unlock_parent(lease.fd, lease.lock_fd)
        lease.fd = -1
        lease.lock_fd = -1
        self._active_lease_count -= 1

    def begin_reclaim(
        self,
        *,
        guard_id: str,
        model_revision: str,
    ) -> FileGpuAuthorityLease:
        if (
            not isinstance(guard_id, str)
            or not guard_id
            or len(guard_id) > 200
            or not isinstance(model_revision, str)
            or not model_revision
            or len(model_revision) > 200
        ):
            raise ValueError("reclaim authority labels are invalid")
        lock_fd, fd = self._open_and_lock()
        try:
            record = self._read_record(fd)
            if record.get("state") != "retained":
                raise PageCacheReclaimDenied(
                    "reclaim requires the exact prior retained-model lease"
                )
            raw_process = record.get("modelProcess")
            if not isinstance(raw_process, Mapping):
                raise PageCacheReclaimDenied(
                    "reclaim requires a process identity bound by the prior lease"
                )
            identity = ProcessIdentity.from_mapping(raw_process)
            if identity.model_revision != model_revision:
                raise PageCacheReclaimDenied(
                    "reclaim model revision does not match the prior lease"
                )
            reclaimer = self.process_probe.identity(os.getpid(), model_revision)
            if reclaimer.cgroup_identity != identity.cgroup_identity:
                raise PageCacheReclaimDenied(
                    "reclaimer process is outside the model cgroup"
                )
            if self.process_probe.is_alive(identity):
                raise PageCacheReclaimDenied(
                    "bound model process is still alive"
                )
            fencing = self._next_fencing_token(record)
            record.update(
                {
                    "fencingToken": fencing,
                    "state": "reclaiming",
                    "guardId": guard_id,
                }
            )
            lease = FileGpuAuthorityLease(
                fd=fd,
                fencing_token=fencing,
                guard_id=guard_id,
                model_revision=model_revision,
                record=record,
                lock_fd=lock_fd,
            )
            self._persist_lease_record(lease, record)
            fd = lease.fd
            self._active_lease_count += 1
            return lease
        except Exception:
            self._close_record_and_unlock_parent(fd, lock_fd)
            raise

    def finish_reclaim(
        self,
        lease: FileGpuAuthorityLease,
        *,
        success: bool,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        memory_peak_bytes: int | None = None,
    ) -> None:
        record = self._locked_lease_record(lease, expected_state="reclaiming")
        record["state"] = "reclaimed" if success else "reclaim_failed"
        self._merge_observation_baseline(
            record,
            cgroup_generation=cgroup_generation,
            events=events,
            recovery_required=recovery_required,
            reject_regression=False,
            memory_peak_bytes=memory_peak_bytes,
        )
        if success:
            record["modelProcess"] = None
        self._persist_lease_record(lease, record)
        lease.record.clear()
        lease.record.update(record)
        self._close_record_and_unlock_parent(lease.fd, lease.lock_fd)
        lease.fd = -1
        lease.lock_fd = -1
        self._active_lease_count -= 1

    def abort_reclaim(self, lease: FileGpuAuthorityLease) -> None:
        """Persist a fail-closed reclaim terminal state without new snapshots."""

        record = self._locked_lease_record(lease, expected_state="reclaiming")
        record["state"] = "reclaim_failed"
        record["recoveryRequired"] = True
        self._persist_lease_record(lease, record)
        lease.record.clear()
        lease.record.update(record)
        self._close_record_and_unlock_parent(lease.fd, lease.lock_fd)
        lease.fd = -1
        lease.lock_fd = -1
        self._active_lease_count -= 1

    @staticmethod
    def _normalized_events(events: Mapping[str, int]) -> dict[str, int]:
        if not isinstance(events, Mapping) or set(events) != _REQUIRED_EVENT_COUNTERS:
            raise CgroupDataError("GPU authority event watermark is invalid")
        normalized: dict[str, int] = {}
        for key in sorted(_REQUIRED_EVENT_COUNTERS):
            value = events.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CgroupDataError("GPU authority event watermark is invalid")
            normalized[key] = value
        return normalized

    @classmethod
    def _merge_observation_baseline(
        cls,
        record: dict[str, object],
        *,
        cgroup_generation: str,
        events: Mapping[str, int],
        recovery_required: bool,
        reject_regression: bool,
        memory_peak_bytes: int | None = None,
    ) -> None:
        if (
            not isinstance(cgroup_generation, str)
            or not cgroup_generation
            or len(cgroup_generation) > 200
            or not isinstance(recovery_required, bool)
        ):
            raise CgroupDataError("GPU authority cgroup baseline is invalid")
        incoming = cls._normalized_events(events)
        prior_generation = record.get("cgroupGeneration")
        prior_events = record.get("events")
        if prior_generation is None and prior_events is None:
            record["cgroupGeneration"] = cgroup_generation
            record["events"] = incoming
        elif (
            not isinstance(prior_generation, str)
            or prior_generation != cgroup_generation
            or not isinstance(prior_events, Mapping)
        ):
            raise CgroupGenerationChanged(
                "durable GPU authority belongs to a different cgroup generation"
            )
        else:
            prior = cls._normalized_events(prior_events)
            regressed = [key for key in prior if incoming[key] < prior[key]]
            if regressed and reject_regression:
                raise MemoryCounterRegression(
                    "memory event counter regressed before durable baseline commit: "
                    + ", ".join(regressed)
                )
            record["events"] = {
                key: max(prior[key], incoming[key]) for key in sorted(prior)
            }
        record["recoveryRequired"] = bool(
            record.get("recoveryRequired", False) or recovery_required
        )
        prior_peak = record.get("memoryPeakBytes")
        if memory_peak_bytes is not None:
            if (
                isinstance(memory_peak_bytes, bool)
                or not isinstance(memory_peak_bytes, int)
                or memory_peak_bytes < 0
            ):
                raise CgroupDataError("GPU authority memory.peak is invalid")
            if prior_peak is not None and (
                isinstance(prior_peak, bool)
                or not isinstance(prior_peak, int)
                or prior_peak < 0
                or memory_peak_bytes < prior_peak
            ):
                if reject_regression:
                    raise MemoryCounterRegression(
                        "memory.peak regressed before durable baseline commit"
                    )
                memory_peak_bytes = cast(int, prior_peak)
            record["memoryPeakBytes"] = memory_peak_bytes
        elif prior_peak is not None and (
            isinstance(prior_peak, bool)
            or not isinstance(prior_peak, int)
            or prior_peak < 0
        ):
            raise CgroupDataError("GPU authority memory.peak is invalid")

    def _reject_retained_owner(
        self,
        record: Mapping[str, object],
        *,
        guard_id: str,
        phase: RuntimePhase,
        model_revision: str,
    ) -> None:
        state = record.get("state")
        if bool(record.get("recoveryRequired", False)) and not phase.is_unload:
            raise RecoveryRequired(
                "durable GPU authority requires a fresh process/container recovery"
            )
        if state == "reclaim_failed":
            raise GpuAuthorityBusy("prior targeted reclaim failed")
        raw_process = record.get("modelProcess")
        if isinstance(raw_process, Mapping):
            identity = ProcessIdentity.from_mapping(raw_process)
            same_unload_owner = (
                phase.is_unload
                and record.get("guardId") == guard_id
                and identity.model_revision == model_revision
            )
            if not same_unload_owner:
                state = "live" if self.process_probe.is_alive(identity) else "exited"
                raise GpuAuthorityBusy(
                    f"retained {state} child model requires exact unload/reclaim"
                )

    @staticmethod
    def _next_fencing_token(record: Mapping[str, object]) -> int:
        previous = record.get("fencingToken", 0)
        if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0:
            raise CgroupDataError("GPU authority fencing token is invalid")
        return previous + 1

    def _open_and_lock(self) -> tuple[int, int]:
        if os.name != "posix":
            raise OSError("flock GPU authority requires Linux")
        import fcntl

        if self._parent_fd < 0 or self._parent_identity is None:
            raise CgroupDataError("GPU authority parent is not anchored")
        self._validate_anchored_parent()
        lock_fd = _open_absolute_directory_no_follow(self.record_path.parent)
        fd = -1
        try:
            self._validate_parent_fd(lock_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._validate_anchored_parent()
            self._validate_parent_fd(lock_fd)
            fd = os.open(
                self.record_path.name,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=lock_fd,
            )
            record_status = os.fstat(fd)
            if (
                not stat.S_ISREG(record_status.st_mode)
                or record_status.st_nlink != 1
                or record_status.st_uid != os.geteuid()
                or stat.S_IMODE(record_status.st_mode) != 0o600
            ):
                raise CgroupDataError(
                    "GPU authority record must be a private, single-link file"
                )
            os.fsync(lock_fd)
            self._validate_anchored_parent()
            self._validate_parent_fd(lock_fd)
            linked_status = os.stat(
                self.record_path.name,
                dir_fd=lock_fd,
                follow_symlinks=False,
            )
            opened_status = os.fstat(fd)
            if (
                (linked_status.st_dev, linked_status.st_ino)
                != (opened_status.st_dev, opened_status.st_ino)
                or linked_status.st_nlink != 1
                or opened_status.st_nlink != 1
                or not stat.S_ISREG(linked_status.st_mode)
                or opened_status.st_uid != os.geteuid()
                or stat.S_IMODE(opened_status.st_mode) != 0o600
            ):
                raise CgroupDataError(
                    "GPU authority record inode or link authority changed"
                )
        except BlockingIOError as exc:
            if fd >= 0:
                os.close(fd)
            os.close(lock_fd)
            raise GpuAuthorityBusy("local_gpu is locked by another process") from exc
        except Exception:
            if fd >= 0:
                os.close(fd)
            self._unlock_and_close(lock_fd)
            raise
        return lock_fd, fd

    def _locked_lease_record(
        self,
        lease: FileGpuAuthorityLease,
        *,
        expected_state: str,
    ) -> dict[str, object]:
        if lease.fd < 0:
            raise LeaseStateError("GPU authority lease descriptor is closed")
        try:
            record = self._read_record(lease.fd)
        except Exception as exc:
            raise LeaseStateError("GPU authority lease record is unavailable") from exc
        if (
            record.get("state") != expected_state
            or record.get("fencingToken") != lease.fencing_token
            or record.get("guardId") != lease.guard_id
            or record.get("modelRevision") != lease.model_revision
        ):
            raise LeaseStateError("GPU authority lease fencing record changed")
        return record

    def _validate_anchored_parent(self) -> None:
        if self._parent_fd < 0 or self._parent_identity is None:
            raise CgroupDataError("GPU authority parent is not anchored")
        self._validate_parent_fd(self._parent_fd)
        anchored = os.fstat(self._parent_fd)
        fresh_fd = _open_absolute_directory_no_follow(self.record_path.parent)
        try:
            self._validate_parent_fd(fresh_fd)
            fresh = os.fstat(fresh_fd)
            if (
                fresh.st_nlink != anchored.st_nlink
            ):
                raise CgroupDataError(
                    "GPU authority parent changed after it was anchored"
                )
        finally:
            os.close(fresh_fd)

    def _validate_parent_fd(self, fd: int) -> None:
        if self._parent_identity is None:
            raise CgroupDataError("GPU authority parent is not anchored")
        value = os.fstat(fd)
        if (
            not stat.S_ISDIR(value.st_mode)
            or value.st_nlink < 1
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
            or (value.st_dev, value.st_ino) != self._parent_identity
        ):
            raise CgroupDataError(
                "GPU authority parent must be private 0700, owned, and anchored"
            )

    def _persist_lease_record(
        self,
        lease: FileGpuAuthorityLease,
        record: Mapping[str, object],
    ) -> None:
        if lease.lock_fd < 0:
            # Test-only/in-memory authority adapters do not own a parent lock.
            self._write_record(lease.fd, record)
            return
        if lease.fd < 0:
            raise LeaseStateError("GPU authority lease descriptor is closed")
        new_fd = self._replace_record_atomic(lease.lock_fd, record)
        old_fd = lease.fd
        lease.fd = new_fd
        os.close(old_fd)

    def _replace_record_atomic(
        self,
        parent_fd: int,
        record: Mapping[str, object],
    ) -> int:
        self._validate_anchored_parent()
        self._validate_parent_fd(parent_fd)
        encoded = self._encode_record(record)
        temporary_name = f".amd-gpu-{uuid.uuid4().hex}.tmp"
        temporary_fd = -1
        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            self._write_bytes(temporary_fd, encoded)
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = -1
            os.replace(
                temporary_name,
                self.record_path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            self._validate_anchored_parent()
            self._validate_parent_fd(parent_fd)
            new_fd = os.open(
                self.record_path.name,
                os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                self._validate_record_fd(parent_fd, new_fd)
            except Exception:
                os.close(new_fd)
                raise
            return new_fd
        except Exception:
            if temporary_fd >= 0:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise

    def _validate_record_fd(self, parent_fd: int, fd: int) -> None:
        linked = os.stat(
            self.record_path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or opened.st_nlink != 1
            or linked.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise CgroupDataError(
                "GPU authority record must be the private canonical inode"
            )

    @staticmethod
    def _read_record(fd: int) -> dict[str, object]:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 1_000_000)
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CgroupDataError("GPU authority record is invalid") from exc
        if not isinstance(value, dict):
            raise CgroupDataError("GPU authority record is not an object")
        if value.get("schemaVersion") != "amd.local-gpu-authority.v1":
            raise CgroupDataError("GPU authority record schema is unsupported")
        fencing = value.get("fencingToken")
        if isinstance(fencing, bool) or not isinstance(fencing, int) or fencing < 1:
            raise CgroupDataError("GPU authority fencing token is invalid")
        return value

    @staticmethod
    def _write_record(fd: int, record: Mapping[str, object]) -> None:
        encoded = FileGpuLeaseAuthority._encode_record(record)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        FileGpuLeaseAuthority._write_bytes(fd, encoded)
        os.fsync(fd)

    @staticmethod
    def _encode_record(record: Mapping[str, object]) -> bytes:
        return json.dumps(
            dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _write_bytes(fd: int, encoded: bytes) -> None:
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                raise OSError("GPU authority record write made no progress")
            offset += written

    @staticmethod
    def _unlock_and_close(fd: int) -> None:
        if fd < 0:
            return
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @classmethod
    def _close_record_and_unlock_parent(
        cls,
        record_fd: int,
        lock_fd: int,
    ) -> None:
        try:
            if record_fd >= 0:
                os.close(record_fd)
        finally:
            cls._unlock_and_close(lock_fd)


class FileAmdAdmissionVerifier:
    """Exact-model verifier with a durable, indexed current-state CAS."""

    _SCHEMA_VERSION = "amd.admission-consumption-store.v4"
    _MAX_STORE_BYTES = 2_000_000
    _MAX_ACTIVE_CONSUMPTIONS = 4_096
    _MAX_SUBMISSION_TOMBSTONES = 4_096
    _CONSUMPTION_RETENTION_SECONDS = 60.0
    _RETIRED_FILTER_BYTES = 32_768
    _RETIRED_FILTER_HASHES = 7

    def __init__(
        self,
        record_path: Path,
        *,
        authority_key_id: str,
        authority_secret: bytes,
        live_start_sampler: Callable[[Any], LiveStartObservation] | None = None,
        lock_timeout_seconds: float = 0.25,
    ) -> None:
        if not _lexically_absolute(record_path) or record_path.name in {"", ".", ".."}:
            raise ValueError("admission record path must be canonical and absolute")
        if (
            not isinstance(authority_key_id, str)
            or not authority_key_id
            or len(authority_key_id) > 200
        ):
            raise ValueError("admission authority key id is invalid")
        if not isinstance(authority_secret, bytes) or len(authority_secret) < 32:
            raise ValueError("admission authority secret must contain 32 bytes")
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or not 0.01 <= float(lock_timeout_seconds) <= 5.0
        ):
            raise ValueError("admission lock timeout is invalid")
        self.record_path = record_path
        self.authority_key_id = authority_key_id
        self._authority_secret = bytes(authority_secret)
        if live_start_sampler is not None and not callable(live_start_sampler):
            raise ValueError("live start sampler must be callable")
        self._live_start_sampler = live_start_sampler
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._parent_fd = -1
        self._parent_identity: tuple[int, int] | None = None
        if os.name == "posix":
            parent_fd = _open_absolute_directory_no_follow(record_path.parent)
            try:
                value = os.fstat(parent_fd)
                self._parent_identity = (value.st_dev, value.st_ino)
                self._validate_parent_fd(parent_fd)
            except Exception:
                os.close(parent_fd)
                self._parent_identity = None
                raise
            self._parent_fd = parent_fd

    def __enter__(self) -> FileAmdAdmissionVerifier:
        if os.name == "posix" and self._parent_fd < 0:
            raise LeaseStateError("admission verifier is closed")
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._parent_fd >= 0:
            os.close(self._parent_fd)
            self._parent_fd = -1
        self._parent_identity = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def verify_admission_lease(
        self,
        receipt: Any,
        *,
        trusted_now: Any,
        expected_lease_epoch: int,
        expected_fencing_token: int,
        expected_lease_cas_version: int,
    ) -> bool:
        try:
            contract_types = _load_amd_contract_types()
            if contract_types is None or type(receipt) is not contract_types[2]:
                return False
            payload = self._checked_model_payload(receipt)
            if not self._verify_receipt_mac(
                payload,
                binding_digest_field="binding_payload_digest",
            ):
                return False
            expected_version = payload.get("expected_version")
            committed_version = payload.get("committed_version")
            if (
                isinstance(expected_version, bool)
                or not isinstance(expected_version, int)
                or expected_version < 0
                or isinstance(committed_version, bool)
                or not isinstance(committed_version, int)
            ):
                return False
            receipt_value = cast(Any, receipt)
            return bool(
                payload.get("cas_acquired") is True
                and payload.get("lease_epoch") == expected_lease_epoch
                and payload.get("fencing_token") == expected_fencing_token
                and committed_version == expected_lease_cas_version
                and payload.get("observed_version") == expected_version
                and committed_version == expected_version + 1
                and receipt_value.expires_at > trusted_now
            )
        except Exception:  # noqa: BLE001 - verifier must fail closed
            return False

    def verify_pressure_recovery(
        self,
        receipt: Any,
        *,
        trusted_now: Any,
        expected_state_version: int,
        expected_lease_epoch: int,
        expected_fencing_token: int,
        expected_lease_cas_version: int,
        expected_consumed_event_watermark: object,
    ) -> bool:
        try:
            contract_types = _load_amd_contract_types()
            if contract_types is None or type(receipt) is not contract_types[3]:
                return False
            payload = self._checked_model_payload(receipt)
            if not self._verify_receipt_mac(
                payload,
                binding_digest_field="recovery_payload_digest",
            ):
                return False
            if (
                payload.get("state_version") != expected_state_version
                or payload.get("admission_lease_epoch") != expected_lease_epoch
                or payload.get("fencing_token") != expected_fencing_token
                or payload.get("admission_lease_committed_version")
                != expected_lease_cas_version
                or payload.get("consumed_event_watermark")
                != self._json_value(expected_consumed_event_watermark)
            ):
                return False
            recovered_epoch = payload.get("recovered_epoch", 0)
            drain_epoch = payload.get("drain_epoch", 0)
            if (
                isinstance(recovered_epoch, bool)
                or not isinstance(recovered_epoch, int)
                or isinstance(drain_epoch, bool)
                or not isinstance(drain_epoch, int)
            ):
                return False
            if recovered_epoch < drain_epoch:
                for sample in getattr(receipt, "healthy_samples", ()):
                    if sample.valid_until <= trusted_now:
                        return False
            return True
        except Exception:  # noqa: BLE001 - verifier must fail closed
            return False

    def verify_and_consume_admission(
        self,
        request: Any,
        decision: Any,
        *,
        request_digest: str,
        decision_digest: str,
        cgroup_generation_id: object,
        lease_epoch: int,
        fencing_token: int,
        expected_state_version: int,
        expected_lease_cas_version: int,
        expected_consumed_event_watermark: object,
        trusted_now: Any,
    ) -> bool:
        """Authenticate every binding and commit one monotonic state transition."""

        try:
            request_value = cast(Any, request)
            decision_value = cast(Any, decision)
            lease_value = getattr(request_value, "admission_lease", None)
            recovery_value = getattr(request_value, "pressure_recovery", None)
            contract_types = _load_amd_contract_types()
            if (
                contract_types is None
                or type(request_value) is not contract_types[0]
                or type(decision_value) is not contract_types[1]
                or type(lease_value) is not contract_types[2]
                or type(recovery_value) is not contract_types[3]
            ):
                return False
            if not self._aware_datetime(trusted_now):
                return False
            for value in (
                lease_epoch,
                fencing_token,
                expected_state_version,
                expected_lease_cas_version,
            ):
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    return False

            lease = cast(Any, lease_value)
            recovery = cast(Any, recovery_value)
            request_payload = self._checked_model_payload(request_value)
            decision_payload = self._checked_model_payload(decision_value)
            lease_payload = self._checked_model_payload(lease)
            recovery_payload = self._checked_model_payload(recovery)
            expected_watermark = self._json_value(expected_consumed_event_watermark)

            if not self._valid_sha256(request_digest):
                return False
            actual_request_digest = hashlib.sha256(
                self._canonical_json(request_payload).encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(actual_request_digest, request_digest):
                return False
            if not self._valid_sha256(decision_digest):
                return False
            supplied_decision_digest = decision_payload.get("decision_digest")
            decision_identity = dict(decision_payload)
            decision_identity.pop("decision_digest", None)
            actual_decision_digest = hashlib.sha256(
                self._canonical_json(decision_identity).encode("utf-8")
            ).hexdigest()
            if (
                not isinstance(supplied_decision_digest, str)
                or not hmac.compare_digest(supplied_decision_digest, decision_digest)
                or not hmac.compare_digest(actual_decision_digest, decision_digest)
            ):
                return False

            after_snapshot = request_payload.get("after_snapshot")
            if not isinstance(after_snapshot, Mapping):
                return False
            submission_id = request_payload.get("submission_id")
            requested_model_family = request_payload.get("requested_model_family")
            if (
                decision_payload.get("submission_id") != submission_id
                or decision_payload.get("requested_model_family")
                != requested_model_family
                or decision_payload.get("provisional_admit_new_work") is not True
                or str(decision_payload.get("cgroup_generation_id"))
                != str(cgroup_generation_id)
                or request_payload.get("admission_lease") != lease_payload
                or request_payload.get("pressure_recovery") != recovery_payload
                or decision_payload.get("admission_lease") != lease_payload
                or decision_payload.get("pressure_recovery") != recovery_payload
                or str(after_snapshot.get("cgroup_generation_id"))
                != str(cgroup_generation_id)
                or lease_payload.get("lease_epoch") != lease_epoch
                or lease_payload.get("fencing_token") != fencing_token
                or recovery_payload.get("state_version") != expected_state_version
                or lease_payload.get("committed_version")
                != expected_lease_cas_version
                or recovery_payload.get("consumed_event_watermark")
                != expected_watermark
            ):
                return False
            if (
                str(lease_payload.get("reserved_submission_id"))
                != str(submission_id)
                or lease_payload.get("requested_model_family")
                != requested_model_family
                or str(lease_payload.get("cgroup_generation_id"))
                != str(cgroup_generation_id)
                or str(recovery_payload.get("admission_lease_id"))
                != str(lease_payload.get("lease_id"))
                or recovery_payload.get("admission_lease_epoch") != lease_epoch
                or recovery_payload.get("admission_lease_committed_version")
                != expected_lease_cas_version
                or str(recovery_payload.get("cgroup_generation_id"))
                != str(cgroup_generation_id)
                or recovery_payload.get("requested_model_family")
                != requested_model_family
                or recovery_payload.get("fencing_token") != fencing_token
            ):
                return False
            if not self.verify_admission_lease(
                lease,
                trusted_now=trusted_now,
                expected_lease_epoch=lease_epoch,
                expected_fencing_token=fencing_token,
                expected_lease_cas_version=expected_lease_cas_version,
            ):
                return False
            if not self.verify_pressure_recovery(
                recovery,
                trusted_now=trusted_now,
                expected_state_version=expected_state_version,
                expected_lease_epoch=lease_epoch,
                expected_fencing_token=fencing_token,
                expected_lease_cas_version=expected_lease_cas_version,
                expected_consumed_event_watermark=expected_watermark,
            ):
                return False

            lease_expiry = float(cast(Any, lease).expires_at.timestamp())
            trusted_timestamp = float(cast(Any, trusted_now).timestamp())
            evaluated_timestamp = float(
                cast(Any, request_value.evaluated_at).timestamp()
            )
            if not math.isfinite(lease_expiry) or not math.isfinite(trusted_timestamp):
                return False
            if (
                not math.isfinite(evaluated_timestamp)
                or lease_expiry - evaluated_timestamp > 4.0
                or trusted_timestamp - evaluated_timestamp > 4.0
            ):
                return False
            consumption = {
                "leaseId": str(lease_payload["lease_id"]),
                "leaseEpoch": lease_epoch,
                "submissionId": str(submission_id),
                "cgroupGenerationId": str(cgroup_generation_id),
                "fencingToken": fencing_token,
                "stateVersion": expected_state_version,
                "leaseCasVersion": expected_lease_cas_version,
                "consumedEventWatermark": expected_watermark,
                "requestDigest": request_digest,
                "decisionDigest": decision_digest,
                "leaseExpiresAtEpochSeconds": lease_expiry,
                "consumedAt": self._timestamp_text(trusted_now),
            }
            current_state = {
                "leaseEpoch": lease_epoch,
                "fencingToken": fencing_token,
                "stateVersion": expected_state_version,
                "leaseCasVersion": expected_lease_cas_version,
                "cgroupGenerationId": str(cgroup_generation_id),
                "consumedEventWatermark": expected_watermark,
            }
            consume_key = hashlib.sha256(
                self._canonical_json(
                    {
                        "leaseId": consumption["leaseId"],
                        "leaseEpoch": lease_epoch,
                        "submissionId": consumption["submissionId"],
                    }
                ).encode("utf-8")
            ).hexdigest()
            return self._consume_once(
                consume_key,
                consumption,
                current_state,
                request=request_value,
                request_payload=request_payload,
                trusted_timestamp=trusted_timestamp,
            )
        except Exception:  # noqa: BLE001 - verifier must fail closed
            return False

    def _consume_once(
        self,
        consume_key: str,
        consumption: Mapping[str, object],
        current_state: Mapping[str, object],
        *,
        request: Any,
        request_payload: Mapping[str, object],
        trusted_timestamp: float,
    ) -> bool:
        if os.name != "posix":
            return False
        import fcntl

        lock_fd = _open_absolute_directory_no_follow(self.record_path.parent)
        locked = False
        try:
            self._validate_parent_fd(lock_fd)
            deadline = time.monotonic() + self._lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    time.sleep(min(0.005, remaining))
            self._validate_anchored_parent(lock_fd)
            self._recover_stale_temporaries(lock_fd)
            record = self._read_store(lock_fd)
            self._prune_consumptions(record, trusted_timestamp=trusted_timestamp)
            live_start = self._validate_live_start_observation(
                request,
                request_payload=request_payload,
                record=record,
                trusted_timestamp=trusted_timestamp,
            )
            consumed = record["consumptions"]
            lease_index = record["leaseIndex"]
            submission_index = record["submissionIndex"]
            submission_tombstones = record["submissionTombstones"]
            if (
                not isinstance(consumed, dict)
                or not isinstance(lease_index, dict)
                or not isinstance(submission_index, dict)
                or not isinstance(submission_tombstones, dict)
            ):
                raise CgroupDataError("admission consumption ledger is invalid")
            lease_key = self._lease_index_key(consumption)
            submission_key = str(consumption["submissionId"])
            live_start_payload = live_start.to_dict()
            live_start_digest = hashlib.sha256(
                self._canonical_json(live_start_payload).encode("utf-8")
            ).hexdigest()
            consumption = dict(consumption)
            consumption["liveStartObservationDigest"] = live_start_digest
            current_state = dict(current_state)
            current_state["memoryPeakBytes"] = live_start.memory_peak_bytes
            current_state["liveStartObservationDigest"] = live_start_digest
            if (
                consume_key in consumed
                or lease_key in lease_index
                or submission_key in submission_index
                or submission_key in submission_tombstones
                or self._submission_was_retired(record, submission_key)
                or not self._state_advances(record["currentState"], current_state)
            ):
                return False
            if len(consumed) >= self._MAX_ACTIVE_CONSUMPTIONS:
                raise CgroupDataError("admission consumption ledger is full")
            self._rotate_submission_tombstones(record)
            consumed[consume_key] = dict(consumption)
            lease_index[lease_key] = consume_key
            submission_index[submission_key] = consume_key
            submission_tombstones[submission_key] = {
                "consumeKey": consume_key,
                "requestDigest": consumption["requestDigest"],
                "decisionDigest": consumption["decisionDigest"],
                "consumedAt": consumption["consumedAt"],
            }
            record["currentState"] = dict(current_state)
            self._write_store_atomic(lock_fd, record)
            return True
        finally:
            try:
                if locked:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _empty_store(self) -> dict[str, object]:
        return {
            "schemaVersion": self._SCHEMA_VERSION,
            "currentState": None,
            "consumptions": {},
            "leaseIndex": {},
            "submissionIndex": {},
            "submissionTombstones": {},
            "retiredSubmissionFilter": "00" * self._RETIRED_FILTER_BYTES,
        }

    def _validate_live_start_observation(
        self,
        request: Any,
        *,
        request_payload: Mapping[str, object],
        record: Mapping[str, object],
        trusted_timestamp: float,
    ) -> LiveStartObservation:
        if self._live_start_sampler is None:
            raise CgroupDataError("live start sampler is required")
        observation = self._live_start_sampler(request)
        if type(observation) is not LiveStartObservation:
            raise CgroupDataError("live start sampler returned the wrong type")
        if (
            isinstance(observation.captured_at_epoch_seconds, bool)
            or not isinstance(observation.captured_at_epoch_seconds, (int, float))
            or not math.isfinite(observation.captured_at_epoch_seconds)
            or abs(observation.captured_at_epoch_seconds - trusted_timestamp) > 1.0
        ):
            raise CgroupDataError("live start observation is stale")
        after = request_payload.get("after_snapshot")
        expected_topology = request_payload.get("topology")
        if not isinstance(after, Mapping) or not isinstance(expected_topology, Mapping):
            raise CgroupDataError("trusted admission request is incomplete")
        if (
            observation.cgroup_generation_id
            != str(after.get("cgroup_generation_id"))
            or observation.memory_max_bytes != HARD_MEMORY_MAX_BYTES
            or observation.memory_current_bytes < 0
            or observation.memory_current_bytes >= ADMISSION_REJECT_BYTES
            or observation.memory_peak_bytes < observation.memory_current_bytes
            or observation.memory_peak_bytes > HARD_MEMORY_MAX_BYTES
            or observation.memory_anon_bytes < 0
            or observation.memory_file_bytes < 0
            or observation.memory_anon_bytes + observation.memory_file_bytes
            > observation.memory_current_bytes
            or observation.memory_events_source != "memory.events.local"
        ):
            raise MemoryAdmissionDenied("live start cgroup memory gate failed")
        expected_peak = after.get("memory_peak_bytes")
        if (
            isinstance(expected_peak, bool)
            or not isinstance(expected_peak, int)
            or observation.memory_peak_bytes < expected_peak
        ):
            raise MemoryCounterRegression("live memory.peak regressed")
        normalized_events = FileGpuLeaseAuthority._normalized_events(
            observation.memory_events
        )
        expected_events = after.get("memory_events")
        if not isinstance(expected_events, Mapping):
            raise CgroupDataError("trusted memory.events baseline is invalid")
        for key in _REQUIRED_EVENT_COUNTERS:
            expected_value = expected_events.get(key)
            if (
                isinstance(expected_value, bool)
                or not isinstance(expected_value, int)
                or normalized_events[key] < expected_value
            ):
                raise MemoryCounterRegression(
                    f"live memory event counter {key!r} regressed"
                )
        if (
            normalized_events["max"] != expected_events.get("max")
            or any(normalized_events[key] != 0 for key in _OOM_EVENT_COUNTERS)
        ):
            raise RecoveryRequired("live memory pressure changed before start")
        topology_payload = self._json_value(observation.topology)
        if topology_payload != dict(expected_topology):
            raise GpuAuthorityBusy("live process topology changed before start")
        if (
            topology_payload.get("gpu_count") != 1
            or topology_payload.get("comfyui_instance_count") != 1
            or topology_payload.get("video_worker_count") != 1
            or topology_payload.get("single_gpu_serial_execution") is not True
            or topology_payload.get("flux_h3_mutually_exclusive") is not True
            or topology_payload.get("active_local_gpu_task_id") is not None
            or topology_payload.get("active_task_model_family") is not None
            or topology_payload.get("resident_model_family") is not None
            or topology_payload.get("resident_model_unload_confirmed") is not True
            or topology_payload.get("in_flight_delivery") is not False
        ):
            raise GpuAuthorityBusy("live process topology is not idle and serial")
        persisted = record.get("currentState")
        if isinstance(persisted, Mapping) and (
            persisted.get("cgroupGenerationId")
            == observation.cgroup_generation_id
        ):
            persisted_peak = persisted.get("memoryPeakBytes")
            if (
                isinstance(persisted_peak, bool)
                or not isinstance(persisted_peak, int)
                or observation.memory_peak_bytes < persisted_peak
            ):
                raise MemoryCounterRegression(
                    "live memory.peak regressed across verifier restart"
                )
        return observation

    @classmethod
    def _retired_filter_positions(cls, submission_key: str) -> tuple[int, ...]:
        if not isinstance(submission_key, str) or not submission_key:
            raise CgroupDataError("submission tombstone key is invalid")
        digest = hashlib.sha512(submission_key.encode("utf-8")).digest()
        bit_count = cls._RETIRED_FILTER_BYTES * 8
        return tuple(
            int.from_bytes(digest[index * 8 : index * 8 + 8], "big") % bit_count
            for index in range(cls._RETIRED_FILTER_HASHES)
        )

    @classmethod
    def _submission_was_retired(
        cls,
        record: Mapping[str, object],
        submission_key: str,
    ) -> bool:
        raw_filter = record.get("retiredSubmissionFilter")
        if (
            not isinstance(raw_filter, str)
            or len(raw_filter) != cls._RETIRED_FILTER_BYTES * 2
        ):
            raise CgroupDataError("retired submission filter is invalid")
        try:
            bitmap = bytes.fromhex(raw_filter)
        except ValueError as exc:
            raise CgroupDataError("retired submission filter is invalid") from exc
        return all(
            bitmap[position // 8] & (1 << (position % 8))
            for position in cls._retired_filter_positions(submission_key)
        )

    @classmethod
    def _rotate_submission_tombstones(
        cls,
        record: dict[str, object],
    ) -> tuple[str, ...]:
        tombstones = record.get("submissionTombstones")
        raw_filter = record.get("retiredSubmissionFilter")
        if not isinstance(tombstones, dict) or not isinstance(raw_filter, str):
            raise CgroupDataError("submission tombstone rotation state is invalid")
        try:
            bitmap = bytearray.fromhex(raw_filter)
        except ValueError as exc:
            raise CgroupDataError("retired submission filter is invalid") from exc
        if len(bitmap) != cls._RETIRED_FILTER_BYTES:
            raise CgroupDataError("retired submission filter is invalid")
        evicted: list[str] = []
        while len(tombstones) >= cls._MAX_SUBMISSION_TOMBSTONES:
            submission_key = min(
                tombstones,
                key=lambda key: (
                    str(cast(Mapping[str, object], tombstones[key]).get("consumedAt")),
                    key,
                ),
            )
            tombstone = tombstones.get(submission_key)
            if not isinstance(tombstone, Mapping):
                raise CgroupDataError("submission tombstone is invalid")
            for position in cls._retired_filter_positions(submission_key):
                bitmap[position // 8] |= 1 << (position % 8)
            tombstones.pop(submission_key)
            evicted.append(submission_key)
        record["retiredSubmissionFilter"] = bitmap.hex()
        return tuple(evicted)

    def _read_store(self, parent_fd: int) -> dict[str, object]:
        try:
            fd = os.open(
                self.record_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return self._empty_store()
        try:
            value = os.fstat(fd)
            if (
                not stat.S_ISREG(value.st_mode)
                or value.st_nlink != 1
                or value.st_uid != os.geteuid()
                or stat.S_IMODE(value.st_mode) != 0o600
            ):
                raise CgroupDataError(
                    "admission store must be a private, single-link file"
                )
            raw = os.read(fd, self._MAX_STORE_BYTES + 1)
            if len(raw) > self._MAX_STORE_BYTES:
                raise CgroupDataError("admission consumption ledger is too large")
        finally:
            os.close(fd)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CgroupDataError("admission consumption ledger is invalid") from exc
        if (
            not isinstance(record, dict)
            or set(record)
            != {
                "schemaVersion",
                "currentState",
                "consumptions",
                "leaseIndex",
                "submissionIndex",
                "submissionTombstones",
                "retiredSubmissionFilter",
            }
            or record["schemaVersion"] != self._SCHEMA_VERSION
            or not isinstance(record["consumptions"], dict)
            or not isinstance(record["leaseIndex"], dict)
            or not isinstance(record["submissionIndex"], dict)
            or not isinstance(record["submissionTombstones"], dict)
            or not isinstance(record["retiredSubmissionFilter"], str)
            or (
                record["currentState"] is not None
                and not isinstance(record["currentState"], dict)
            )
        ):
            raise CgroupDataError("admission consumption ledger schema is invalid")
        current_state = record["currentState"]
        if current_state is not None:
            peak = current_state.get("memoryPeakBytes")
            live_digest = current_state.get("liveStartObservationDigest")
            if (
                isinstance(peak, bool)
                or not isinstance(peak, int)
                or peak < 0
                or not self._valid_sha256(live_digest)
            ):
                raise CgroupDataError("admission current live-start state is invalid")
        self._validate_store_indexes(record)
        return record

    def _validate_store_indexes(self, record: Mapping[str, object]) -> None:
        consumed = record["consumptions"]
        lease_index = record["leaseIndex"]
        submission_index = record["submissionIndex"]
        submission_tombstones = record["submissionTombstones"]
        if (
            not isinstance(consumed, Mapping)
            or not isinstance(lease_index, Mapping)
            or not isinstance(submission_index, Mapping)
            or not isinstance(submission_tombstones, Mapping)
            or len(consumed) > self._MAX_ACTIVE_CONSUMPTIONS
            or len(submission_tombstones) > self._MAX_SUBMISSION_TOMBSTONES
            or len(lease_index) != len(consumed)
            or len(submission_index) != len(consumed)
        ):
            raise CgroupDataError("admission consumption indexes are invalid")
        for consume_key, entry in consumed.items():
            if (
                not self._valid_sha256(consume_key)
                or not isinstance(entry, Mapping)
                or lease_index.get(self._lease_index_key(entry)) != consume_key
                or submission_index.get(str(entry.get("submissionId"))) != consume_key
            ):
                raise CgroupDataError("admission consumption index entry is invalid")
            expiry = entry.get("leaseExpiresAtEpochSeconds")
            if (
                isinstance(expiry, bool)
                or not isinstance(expiry, (int, float))
                or not math.isfinite(expiry)
            ):
                raise CgroupDataError("admission consumption expiry is invalid")
            if not self._valid_sha256(entry.get("liveStartObservationDigest")):
                raise CgroupDataError("live start observation digest is invalid")
            submission_key = str(entry.get("submissionId"))
            tombstone = submission_tombstones.get(submission_key)
            if (
                not isinstance(tombstone, Mapping)
                or tombstone.get("consumeKey") != consume_key
                or tombstone.get("requestDigest") != entry.get("requestDigest")
                or tombstone.get("decisionDigest") != entry.get("decisionDigest")
                or tombstone.get("consumedAt") != entry.get("consumedAt")
            ):
                raise CgroupDataError("admission submission tombstone is invalid")
        raw_filter = record.get("retiredSubmissionFilter")
        if (
            not isinstance(raw_filter, str)
            or len(raw_filter) != self._RETIRED_FILTER_BYTES * 2
        ):
            raise CgroupDataError("retired submission filter is invalid")
        try:
            if len(bytes.fromhex(raw_filter)) != self._RETIRED_FILTER_BYTES:
                raise ValueError("wrong length")
        except ValueError as exc:
            raise CgroupDataError("retired submission filter is invalid") from exc
        for submission_key, tombstone in submission_tombstones.items():
            if (
                not isinstance(submission_key, str)
                or not submission_key
                or not isinstance(tombstone, Mapping)
                or set(tombstone)
                != {"consumeKey", "requestDigest", "decisionDigest", "consumedAt"}
                or not self._valid_sha256(tombstone.get("consumeKey"))
                or not self._valid_sha256(tombstone.get("requestDigest"))
                or not self._valid_sha256(tombstone.get("decisionDigest"))
                or not isinstance(tombstone.get("consumedAt"), str)
                or not tombstone.get("consumedAt")
            ):
                raise CgroupDataError("admission submission tombstone is invalid")

    def _prune_consumptions(
        self,
        record: dict[str, object],
        *,
        trusted_timestamp: float,
    ) -> None:
        consumed = record["consumptions"]
        lease_index = record["leaseIndex"]
        submission_index = record["submissionIndex"]
        if (
            not isinstance(consumed, dict)
            or not isinstance(lease_index, dict)
            or not isinstance(submission_index, dict)
        ):
            raise CgroupDataError("admission consumption ledger is invalid")
        expired = [
            key
            for key, entry in consumed.items()
            if isinstance(entry, Mapping)
            and float(entry["leaseExpiresAtEpochSeconds"])
            + self._CONSUMPTION_RETENTION_SECONDS
            < trusted_timestamp
        ]
        for consume_key in expired:
            entry = consumed.pop(consume_key)
            if not isinstance(entry, Mapping):
                raise CgroupDataError("admission consumption entry is invalid")
            lease_index.pop(self._lease_index_key(entry), None)
            submission_index.pop(str(entry["submissionId"]), None)

    @staticmethod
    def _lease_index_key(value: Mapping[str, object]) -> str:
        return f"{value.get('leaseId')}:{value.get('leaseEpoch')}"

    @classmethod
    def _state_advances(
        cls,
        persisted: object,
        incoming: Mapping[str, object],
    ) -> bool:
        if persisted is None:
            return True
        if not isinstance(persisted, Mapping):
            raise CgroupDataError("admission current state is invalid")
        for field_name in (
            "leaseEpoch",
            "fencingToken",
            "stateVersion",
            "leaseCasVersion",
        ):
            old = persisted.get(field_name)
            new = incoming.get(field_name)
            if (
                isinstance(old, bool)
                or not isinstance(old, int)
                or old < 1
                or isinstance(new, bool)
                or not isinstance(new, int)
                or new < 1
            ):
                raise CgroupDataError("admission current state version is invalid")
        if not (
            incoming["leaseEpoch"] > persisted["leaseEpoch"]
            and incoming["fencingToken"] > persisted["fencingToken"]
            and incoming["leaseCasVersion"] > persisted["leaseCasVersion"]
            and incoming["stateVersion"] >= persisted["stateVersion"]
        ):
            return False
        if (
            incoming.get("cgroupGenerationId")
            == persisted.get("cgroupGenerationId")
            and not cls._watermark_not_regressed(
                persisted.get("consumedEventWatermark"),
                incoming.get("consumedEventWatermark"),
            )
        ):
            return False
        if incoming.get("cgroupGenerationId") == persisted.get(
            "cgroupGenerationId"
        ):
            prior_peak = persisted.get("memoryPeakBytes")
            incoming_peak = incoming.get("memoryPeakBytes")
            if (
                isinstance(prior_peak, bool)
                or not isinstance(prior_peak, int)
                or prior_peak < 0
                or isinstance(incoming_peak, bool)
                or not isinstance(incoming_peak, int)
                or incoming_peak < prior_peak
            ):
                return False
        return True

    @staticmethod
    def _watermark_not_regressed(persisted: object, incoming: object) -> bool:
        if not isinstance(persisted, Mapping) or not isinstance(incoming, Mapping):
            raise CgroupDataError("admission event watermark is invalid")
        fields = (
            "snapshot_sequence",
            "memory_events_low",
            "memory_events_high",
            "memory_events_max",
            "memory_events_oom",
            "memory_events_oom_kill",
            "memory_events_oom_group_kill",
        )
        for field_name in fields:
            old = persisted.get(field_name)
            new = incoming.get(field_name)
            if (
                isinstance(old, bool)
                or not isinstance(old, int)
                or old < 0
                or isinstance(new, bool)
                or not isinstance(new, int)
                or new < old
            ):
                return False
        return True

    def _write_store_atomic(
        self,
        parent_fd: int,
        record: Mapping[str, object],
    ) -> None:
        encoded = self._canonical_json(dict(record)).encode("utf-8")
        if len(encoded) > self._MAX_STORE_BYTES:
            raise CgroupDataError("admission consumption ledger is too large")
        temporary_name = f".amd-admission-{uuid.uuid4().hex}.tmp"
        fd = -1
        try:
            fd = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            FileGpuLeaseAuthority._write_bytes(fd, encoded)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(
                temporary_name,
                self.record_path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            self._verify_published_store(parent_fd)
        except Exception:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise

    def _verify_published_store(self, parent_fd: int) -> None:
        """Reopen the canonical path and prove the published inode is unique."""

        self._validate_anchored_parent(parent_fd)
        fresh_parent_fd = _open_absolute_directory_no_follow(self.record_path.parent)
        anchored_fd = -1
        fresh_fd = -1
        try:
            self._validate_parent_fd(fresh_parent_fd)
            anchored_fd = os.open(
                self.record_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            fresh_fd = os.open(
                self.record_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=fresh_parent_fd,
            )
            anchored = os.fstat(anchored_fd)
            fresh = os.fstat(fresh_fd)
            if (
                (anchored.st_dev, anchored.st_ino) != (fresh.st_dev, fresh.st_ino)
                or not stat.S_ISREG(anchored.st_mode)
                or anchored.st_nlink != 1
                or fresh.st_nlink != 1
                or anchored.st_uid != os.geteuid()
                or stat.S_IMODE(anchored.st_mode) != 0o600
            ):
                raise CgroupDataError(
                    "canonical admission store parent or inode changed during publish"
                )
        finally:
            if anchored_fd >= 0:
                os.close(anchored_fd)
            if fresh_fd >= 0:
                os.close(fresh_fd)
            os.close(fresh_parent_fd)

    def _recover_stale_temporaries(self, parent_fd: int) -> None:
        names = [
            name
            for name in os.listdir(parent_fd)
            if name.startswith(".amd-admission-") and name.endswith(".tmp")
        ]
        if len(names) > 64:
            raise CgroupDataError("too many stale admission transaction files")
        for name in names:
            value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(value.st_mode)
                or value.st_nlink != 1
                or value.st_uid != os.geteuid()
            ):
                raise CgroupDataError("stale admission transaction is unsafe")
            os.unlink(name, dir_fd=parent_fd)
        if names:
            os.fsync(parent_fd)

    def _validate_parent_fd(self, fd: int) -> None:
        if self._parent_identity is None:
            raise CgroupDataError("admission store parent is not anchored")
        value = os.fstat(fd)
        if (
            not stat.S_ISDIR(value.st_mode)
            or value.st_nlink < 1
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
            or (value.st_dev, value.st_ino) != self._parent_identity
        ):
            raise CgroupDataError(
                "admission store parent must be private 0700, owned, and anchored"
            )

    def _validate_anchored_parent(self, lock_fd: int) -> None:
        self._validate_parent_fd(self._parent_fd)
        self._validate_parent_fd(lock_fd)
        fresh_fd = _open_absolute_directory_no_follow(self.record_path.parent)
        try:
            self._validate_parent_fd(fresh_fd)
        finally:
            os.close(fresh_fd)

    def _verify_receipt_mac(
        self,
        payload: Mapping[str, object],
        *,
        binding_digest_field: str,
    ) -> bool:
        if (
            payload.get("authority_key_id") != self.authority_key_id
            or payload.get("mac_algorithm") != "hmac-sha256"
        ):
            return False
        supplied_mac = payload.get("authority_mac")
        supplied_binding = payload.get(binding_digest_field)
        if not self._valid_sha256(supplied_mac) or not self._valid_sha256(
            supplied_binding
        ):
            return False
        supplied_mac_text = cast(str, supplied_mac)
        supplied_binding_text = cast(str, supplied_binding)
        binding_identity = dict(payload)
        binding_identity.pop(binding_digest_field, None)
        binding_identity.pop("authority_mac", None)
        expected_binding = hashlib.sha256(
            self._canonical_json(binding_identity).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(expected_binding, supplied_binding_text):
            return False
        mac_identity = dict(payload)
        mac_identity.pop("authority_mac", None)
        expected_mac = hmac.new(
            self._authority_secret,
            self._canonical_json(mac_identity).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_mac, supplied_mac_text)

    @classmethod
    def _checked_model_payload(cls, value: Any) -> dict[str, object]:
        payload = value.model_dump(mode="json")
        if not isinstance(payload, dict):
            raise TypeError("admission protocol payload must be an object")
        for field_name, serialized in payload.items():
            if not hasattr(value, field_name):
                raise TypeError("admission protocol live field is unavailable")
            live = getattr(value, field_name)
            if hasattr(live, "isoformat") and isinstance(serialized, str):
                text = live.isoformat()
                if serialized not in {text, text.replace("+00:00", "Z")}:
                    raise TypeError("admission protocol live timestamp changed")
                continue
            if cls._json_value(live) != serialized:
                raise TypeError("admission protocol live field changed")
        return payload

    @classmethod
    def _json_value(cls, value: Any) -> object:
        return json.loads(cls._canonical_json(cls._to_json_compatible(value)))

    @classmethod
    def _to_json_compatible(cls, value: Any) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(key): cls._to_json_compatible(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [cls._to_json_compatible(item) for item in value]
        if isinstance(value, StrEnum):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat().replace("+00:00", "Z")
        return value

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _valid_sha256(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _aware_datetime(value: object) -> bool:
        try:
            candidate = cast(Any, value)
            return candidate.tzinfo is not None and candidate.utcoffset() is not None
        except Exception:
            return False

    @staticmethod
    def _timestamp_text(value: Any) -> str:
        text = value.isoformat()
        return text.replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CgroupFileObservation:
    text: str
    observed_at: float
    generation: str


class CgroupFilesystem(Protocol):
    def generation(self) -> str: ...

    def read(self, name: str) -> CgroupFileObservation: ...


@dataclass(frozen=True, slots=True)
class VramSample:
    device_id: str
    total_bytes: int
    used_bytes: int
    observed_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "deviceId": self.device_id,
            "totalBytes": self.total_bytes,
            "usedBytes": self.used_bytes,
            "observedAtMonotonicSeconds": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class WeightFileManifestEntry:
    path: str
    size_bytes: int
    sha256: str
    device: int
    inode: int
    link_count: int

    def __post_init__(self) -> None:
        if not _safe_weight_path(self.path):
            raise ValueError("weight file path is not canonical and absolute")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes <= 0
        ):
            raise ValueError("weight file size is invalid")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.sha256
            )
        ):
            raise ValueError("weight file SHA-256 is invalid")
        for label, value in (
            ("device", self.device),
            ("inode", self.inode),
            ("link count", self.link_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"weight file {label} is invalid")
        if self.link_count != 1:
            raise ValueError("weight file must have exactly one hard link")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "device": self.device,
            "inode": self.inode,
            "linkCount": self.link_count,
        }


@dataclass(frozen=True, slots=True)
class WeightReclaimManifest:
    model_revision: str
    files: tuple[WeightFileManifestEntry, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_revision, str)
            or not self.model_revision
            or len(self.model_revision) > 200
        ):
            raise ValueError("weight reclaim model revision is invalid")
        if (
            not isinstance(self.files, tuple)
            or not 1 <= len(self.files) <= 32
            or any(type(item) is not WeightFileManifestEntry for item in self.files)
        ):
            raise ValueError("weight reclaim manifest file authorities are invalid")
        paths = tuple(item.path for item in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("weight file paths must be unique")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> WeightReclaimManifest:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schemaVersion",
            "modelRevision",
            "files",
        }:
            raise ValueError("weight reclaim manifest has unexpected fields")
        if payload["schemaVersion"] != "amd.weight-reclaim-manifest.v1":
            raise ValueError("weight reclaim manifest schema is unsupported")
        model_revision = payload["modelRevision"]
        raw_files = payload["files"]
        if (
            not isinstance(model_revision, str)
            or not model_revision
            or len(model_revision) > 200
        ):
            raise ValueError("weight reclaim model revision is invalid")
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= 32:
            raise ValueError("weight reclaim manifest must list 1 to 32 files")

        files: list[WeightFileManifestEntry] = []
        seen: set[str] = set()
        for raw in raw_files:
            if not isinstance(raw, Mapping) or set(raw) != {
                "path",
                "sizeBytes",
                "sha256",
                "device",
                "inode",
                "linkCount",
            }:
                raise ValueError("weight file manifest entry is not exact")
            path = raw["path"]
            size = raw["sizeBytes"]
            digest = raw["sha256"]
            device = raw["device"]
            inode = raw["inode"]
            link_count = raw["linkCount"]
            if not isinstance(path, str) or not _safe_weight_path(path):
                raise ValueError("weight file path is not a canonical absolute file")
            if path in seen:
                raise ValueError("weight file paths must be unique")
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ValueError("weight file size is invalid")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("weight file SHA-256 is invalid")
            seen.add(path)
            files.append(
                WeightFileManifestEntry(
                    path=path,
                    size_bytes=size,
                    sha256=digest,
                    device=device,
                    inode=inode,
                    link_count=link_count,
                )
            )
        return cls(model_revision=model_revision, files=tuple(files))

    @property
    def manifest_digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "amd.weight-reclaim-manifest.v1",
            "modelRevision": self.model_revision,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class WeightFileFdStatus:
    """Authority derived from the already-open descriptor used for reclaim."""

    size_bytes: int
    device: int
    inode: int
    link_count: int
    is_regular: bool
    access_read_only: bool
    file_mode_read_only: bool
    close_on_exec: bool


class WeightFileOps(Protocol):
    def open(self, path: str) -> int: ...

    def status(self, fd: int) -> WeightFileFdStatus: ...

    def sha256(self, fd: int, size_bytes: int) -> str: ...

    def cached_bytes(self, fd: int, size_bytes: int) -> int: ...

    def advise_dontneed(self, fd: int, size_bytes: int) -> None: ...

    def close(self, fd: int) -> None: ...


class PosixWeightFileOps:
    """Secure Linux openat/fstat/hash/mincore/fadvise implementation.

    Every parent and the final file are opened with ``O_NOFOLLOW``.  All file
    authority and the DONTNEED call are then derived from that same descriptor,
    eliminating the path preflight/open time-of-check/time-of-use gap.
    """

    def open(self, path: str) -> int:
        if os.name != "posix":
            raise OSError("secure weight reclaim requires Linux")
        if not _safe_weight_path(path):
            raise PageCacheReclaimDenied("weight path is not canonical")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_flags = flags | os.O_DIRECTORY
        parent_fd = os.open("/", directory_flags)
        components = PurePosixPath(path).parts[1:]
        try:
            for component in components[:-1]:
                next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                parent_status = os.fstat(next_fd)
                if not stat.S_ISDIR(parent_status.st_mode):
                    os.close(next_fd)
                    raise PageCacheReclaimDenied(
                        "weight path parent is not an exact directory"
                    )
                os.close(parent_fd)
                parent_fd = next_fd
            return os.open(components[-1], flags, dir_fd=parent_fd)
        except OSError as exc:
            raise PageCacheReclaimDenied(
                "weight path contains a link or unavailable component"
            ) from exc
        finally:
            os.close(parent_fd)

    def status(self, fd: int) -> WeightFileFdStatus:
        import fcntl

        value = os.fstat(fd)
        access_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        return WeightFileFdStatus(
            size_bytes=value.st_size,
            device=value.st_dev,
            inode=value.st_ino,
            link_count=value.st_nlink,
            is_regular=stat.S_ISREG(value.st_mode),
            access_read_only=(access_flags & os.O_ACCMODE) == os.O_RDONLY,
            file_mode_read_only=(value.st_mode & 0o222) == 0,
            close_on_exec=bool(descriptor_flags & fcntl.FD_CLOEXEC),
        )

    def sha256(self, fd: int, size_bytes: int) -> str:
        digest = hashlib.sha256()
        offset = 0
        while offset < size_bytes:
            block = os.pread(fd, min(8 * 1024 * 1024, size_bytes - offset), offset)
            if not block:
                raise PageCacheReclaimDenied("weight file ended during SHA-256")
            digest.update(block)
            offset += len(block)
        if os.pread(fd, 1, size_bytes):
            raise PageCacheReclaimDenied("weight file grew during SHA-256")
        return digest.hexdigest()

    def cached_bytes(self, fd: int, size_bytes: int) -> int:
        if size_bytes <= 0:
            return 0
        import ctypes

        page_size = mmap.PAGESIZE
        page_count = (size_bytes + page_size - 1) // page_size
        mapping = mmap.mmap(
            fd,
            size_bytes,
            flags=mmap.MAP_PRIVATE,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        view = None
        try:
            view = ctypes.c_char.from_buffer(mapping)
            residency = (ctypes.c_ubyte * page_count)()
            libc = ctypes.CDLL(None, use_errno=True)
            result = libc.mincore(
                ctypes.c_void_p(ctypes.addressof(view)),
                ctypes.c_size_t(size_bytes),
                residency,
            )
            if result != 0:
                error_number = ctypes.get_errno()
                raise OSError(error_number, os.strerror(error_number))
            resident_pages = sum(1 for value in residency if value & 1)
            if resident_pages == 0:
                return 0
            last_page_bytes = size_bytes % page_size or page_size
            cached = resident_pages * page_size
            if residency[page_count - 1] & 1:
                cached -= page_size - last_page_bytes
            return cached
        finally:
            if view is not None:
                del view
            mapping.close()

    def advise_dontneed(self, fd: int, size_bytes: int) -> None:
        if not hasattr(os, "posix_fadvise"):
            raise OSError("POSIX_FADV_DONTNEED is unavailable")
        os.posix_fadvise(fd, 0, size_bytes, os.POSIX_FADV_DONTNEED)

    def close(self, fd: int) -> None:
        os.close(fd)


class _OwnedDeploymentProof:
    __slots__ = ("canonical_payload", "authority_mac", "secret", "owner_id")

    def __init__(
        self,
        *,
        canonical_payload: bytes,
        authority_mac: str,
        secret: bytes,
    ) -> None:
        self.canonical_payload = canonical_payload
        self.authority_mac = authority_mac
        self.secret = secret
        self.owner_id: int | None = None

    def bind(self, owner: object) -> None:
        if self.owner_id is not None:
            raise TypeError("deployment authority proof cannot be replaced or cloned")
        self.owner_id = id(owner)

    def verify(self, owner: object) -> bool:
        return self.owner_id == id(owner) and hmac.compare_digest(
            hmac.new(self.secret, self.canonical_payload, hashlib.sha256).hexdigest(),
            self.authority_mac,
        )


class _OwnedRegistryProof:
    __slots__ = ("authority", "registry_kind", "registry_digest", "owner_id")

    def __init__(
        self,
        *,
        authority: RegistryDeploymentAuthority,
        registry_kind: str,
        registry_digest: str,
    ) -> None:
        self.authority = authority
        self.registry_kind = registry_kind
        self.registry_digest = registry_digest
        self.owner_id: int | None = None

    def bind(self, owner: object) -> None:
        if self.owner_id is not None:
            raise TypeError("trusted registry proof cannot be replaced or cloned")
        self.owner_id = id(owner)

    def verify(self, owner: object, registry_digest: str) -> bool:
        return (
            self.owner_id == id(owner)
            and hmac.compare_digest(self.registry_digest, registry_digest)
            and self.authority.verify_for(
                registry_kind=self.registry_kind,
                registry_digest=registry_digest,
            )
        )


@dataclass(frozen=True, slots=True)
class RegistryDeploymentAuthority:
    """Independently HMAC-authenticated digest authority for one registry kind."""

    registry_kind: str
    registry_digest: str
    authority_key_id: str
    _factory_seal: object = field(repr=False, compare=False)
    _proof: _OwnedDeploymentProof | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._factory_seal is not _REGISTRY_DEPLOYMENT_AUTHORITY_FACTORY_SEAL:
            raise TypeError("registry deployment authority must be HMAC-verified")
        if type(self._proof) is not _OwnedDeploymentProof:
            raise TypeError("registry deployment authority HMAC proof is unavailable")
        self._proof.bind(self)

    def verify_for(self, *, registry_kind: str, registry_digest: str) -> bool:
        return bool(
            self.registry_kind == registry_kind
            and hmac.compare_digest(self.registry_digest, registry_digest)
            and self._proof is not None
            and self._proof.verify(self)
        )

    @classmethod
    def from_signed_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        authority_key_id: str,
        authority_secret: bytes,
    ) -> RegistryDeploymentAuthority:
        expected_fields = {
            "schemaVersion",
            "registryKind",
            "registryDigest",
            "authorityKeyId",
            "macAlgorithm",
            "authorityMac",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_fields:
            raise ValueError("registry deployment authority has unexpected fields")
        if (
            payload.get("schemaVersion")
            != "amd.registry-deployment-authority.v1"
            or payload.get("registryKind") not in {"weight", "idle-vram"}
            or payload.get("authorityKeyId") != authority_key_id
            or payload.get("macAlgorithm") != "hmac-sha256"
            or not isinstance(authority_key_id, str)
            or not authority_key_id
            or len(authority_key_id) > 200
            or not isinstance(authority_secret, bytes)
            or len(authority_secret) < 32
        ):
            raise ValueError("registry deployment authority is invalid")
        registry_digest = payload.get("registryDigest")
        supplied_mac = payload.get("authorityMac")
        if not TrustedWeightRegistry._valid_sha256_value(
            registry_digest
        ) or not TrustedWeightRegistry._valid_sha256_value(supplied_mac):
            raise ValueError("registry deployment authority digest is invalid")
        identity = dict(payload)
        identity.pop("authorityMac")
        canonical_payload = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected_mac = hmac.new(
            authority_secret,
            canonical_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(cast(str, supplied_mac), expected_mac):
            raise ValueError("registry deployment authority HMAC is invalid")
        return cls(
            registry_kind=cast(str, payload["registryKind"]),
            registry_digest=cast(str, registry_digest),
            authority_key_id=authority_key_id,
            _proof=_OwnedDeploymentProof(
                canonical_payload=canonical_payload,
                authority_mac=cast(str, supplied_mac),
                secret=bytes(authority_secret),
            ),
            _factory_seal=_REGISTRY_DEPLOYMENT_AUTHORITY_FACTORY_SEAL,
        )


@dataclass(frozen=True, slots=True)
class TrustedWeightRegistry:
    """Deployment-anchored registry; callers can name only a manifest digest."""

    registry_digest: str
    manifests: Mapping[str, WeightReclaimManifest]
    _proof: _OwnedRegistryProof = field(repr=False, compare=False)
    _factory_seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_seal is not _TRUSTED_REGISTRY_FACTORY_SEAL:
            raise TypeError("trusted registry must be deployment-verified")
        self._proof.bind(self)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        deployment_authority: RegistryDeploymentAuthority,
    ) -> TrustedWeightRegistry:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schemaVersion",
            "manifests",
        }:
            raise ValueError("trusted weight registry has unexpected fields")
        if payload["schemaVersion"] != "amd.trusted-weight-registry.v1":
            raise ValueError("trusted weight registry schema is unsupported")
        if (
            type(deployment_authority) is not RegistryDeploymentAuthority
            or not deployment_authority.verify_for(
                registry_kind="weight",
                registry_digest=deployment_authority.registry_digest,
            )
        ):
            raise ValueError("trusted registry deployment authority is invalid")
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        actual_digest = hashlib.sha256(encoded).hexdigest()
        if not hmac.compare_digest(
            actual_digest, deployment_authority.registry_digest
        ):
            raise ValueError("trusted registry does not match deployment digest")
        raw_manifests = payload["manifests"]
        if not isinstance(raw_manifests, list) or not 1 <= len(raw_manifests) <= 32:
            raise ValueError("trusted registry manifest list is invalid")
        manifests: dict[str, WeightReclaimManifest] = {}
        for raw in raw_manifests:
            manifest = WeightReclaimManifest.from_mapping(raw)
            if manifest.manifest_digest in manifests:
                raise ValueError("trusted registry contains a duplicate manifest")
            manifests[manifest.manifest_digest] = manifest
        return cls(
            registry_digest=actual_digest,
            manifests=MappingProxyType(manifests),
            _proof=_OwnedRegistryProof(
                authority=deployment_authority,
                registry_kind="weight",
                registry_digest=actual_digest,
            ),
            _factory_seal=_TRUSTED_REGISTRY_FACTORY_SEAL,
        )

    @staticmethod
    def _valid_sha256_value(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    def resolve(self, manifest_digest: str) -> WeightReclaimManifest:
        if not self._proof.verify(self, self.registry_digest):
            raise PageCacheReclaimDenied(
                "trusted registry deployment authority HMAC is invalid"
            )
        if (
            not isinstance(manifest_digest, str)
            or len(manifest_digest) != 64
            or any(
                character not in "0123456789abcdef" for character in manifest_digest
            )
        ):
            raise PageCacheReclaimDenied("manifest digest is invalid")
        try:
            return self.manifests[manifest_digest]
        except KeyError as exc:
            raise PageCacheReclaimDenied(
                "manifest digest is not in the trusted deployment registry"
            ) from exc


@dataclass(frozen=True, slots=True)
class IdleVramThresholdAuthority:
    device_id: str
    threshold_bytes: int
    evidence_sha256: str

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
    ) -> IdleVramThresholdAuthority:
        if not isinstance(payload, Mapping) or set(payload) != {
            "deviceId",
            "thresholdBytes",
            "evidenceSha256",
        }:
            raise ValueError("idle VRAM authority has unexpected fields")
        device_id = payload["deviceId"]
        threshold_bytes = payload["thresholdBytes"]
        evidence_sha256 = payload["evidenceSha256"]
        if (
            not isinstance(device_id, str)
            or not device_id
            or len(device_id) > 200
        ):
            raise ValueError("idle VRAM authority device is invalid")
        if (
            isinstance(threshold_bytes, bool)
            or not isinstance(threshold_bytes, int)
            or threshold_bytes <= 0
        ):
            raise ValueError("idle VRAM authority threshold is invalid")
        if (
            not isinstance(evidence_sha256, str)
            or len(evidence_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in evidence_sha256
            )
        ):
            raise ValueError("idle VRAM authority evidence SHA-256 is invalid")
        return cls(
            device_id=device_id,
            threshold_bytes=threshold_bytes,
            evidence_sha256=evidence_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "deviceId": self.device_id,
            "thresholdBytes": self.threshold_bytes,
            "evidenceSha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class TrustedIdleVramRegistry:
    """Deployment digest binding the only permitted nonzero idle thresholds."""

    registry_digest: str
    authorities: Mapping[str, IdleVramThresholdAuthority]
    _proof: _OwnedRegistryProof = field(repr=False, compare=False)
    _factory_seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_seal is not _TRUSTED_IDLE_VRAM_REGISTRY_FACTORY_SEAL:
            raise TypeError("trusted idle VRAM registry must be deployment-verified")
        self._proof.bind(self)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        deployment_authority: RegistryDeploymentAuthority,
    ) -> TrustedIdleVramRegistry:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schemaVersion",
            "authorities",
        }:
            raise ValueError("trusted idle VRAM registry has unexpected fields")
        if payload["schemaVersion"] != "amd.trusted-idle-vram-registry.v1":
            raise ValueError("trusted idle VRAM registry schema is unsupported")
        if (
            type(deployment_authority) is not RegistryDeploymentAuthority
            or not deployment_authority.verify_for(
                registry_kind="idle-vram",
                registry_digest=deployment_authority.registry_digest,
            )
        ):
            raise ValueError(
                "trusted idle VRAM registry deployment authority is invalid"
            )
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        actual_digest = hashlib.sha256(encoded).hexdigest()
        if not hmac.compare_digest(
            actual_digest, deployment_authority.registry_digest
        ):
            raise ValueError(
                "trusted idle VRAM registry does not match deployment digest"
            )
        raw_authorities = payload["authorities"]
        if (
            not isinstance(raw_authorities, list)
            or not 1 <= len(raw_authorities) <= 32
        ):
            raise ValueError("trusted idle VRAM authority list is invalid")
        authorities: dict[str, IdleVramThresholdAuthority] = {}
        for raw in raw_authorities:
            authority = IdleVramThresholdAuthority.from_mapping(raw)
            if authority.device_id in authorities:
                raise ValueError(
                    "trusted idle VRAM registry contains a duplicate device"
                )
            authorities[authority.device_id] = authority
        return cls(
            registry_digest=actual_digest,
            authorities=MappingProxyType(authorities),
            _proof=_OwnedRegistryProof(
                authority=deployment_authority,
                registry_kind="idle-vram",
                registry_digest=actual_digest,
            ),
            _factory_seal=_TRUSTED_IDLE_VRAM_REGISTRY_FACTORY_SEAL,
        )

    def resolve(
        self,
        *,
        device_id: str,
        threshold_bytes: int,
        evidence_sha256: str,
    ) -> IdleVramThresholdAuthority:
        if not self._proof.verify(self, self.registry_digest):
            raise ValueError("trusted idle VRAM deployment authority HMAC is invalid")
        authority = self.authorities.get(device_id)
        if (
            authority is None
            or authority.threshold_bytes != threshold_bytes
            or not hmac.compare_digest(
                authority.evidence_sha256,
                evidence_sha256,
            )
        ):
            raise ValueError(
                "nonzero threshold lacks an exact trusted idle VRAM registry binding"
            )
        return authority


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    captured_at: float
    captured_wall_time: float
    cgroup_generation: str
    memory_current_bytes: int
    memory_peak_bytes: int
    memory_max_bytes: int
    memory_anon_bytes: int
    memory_file_bytes: int
    events_source: str
    events: Mapping[str, int]
    swap_current_bytes: int
    swap_max_bytes: int
    vram: VramSample
    idle_vram_threshold_bytes: int = 0
    idle_vram_threshold_evidence_sha256: str | None = None
    idle_vram_registry_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        vram = self.vram.to_dict()
        vram["idleAuthority"] = {
            "deviceId": self.vram.device_id,
            "thresholdBytes": self.idle_vram_threshold_bytes,
            "evidenceSha256": self.idle_vram_threshold_evidence_sha256,
            "trustedRegistrySha256": self.idle_vram_registry_digest,
        }
        return {
            "schemaVersion": "amd.memory-snapshot.v1",
            "capturedAtMonotonicSeconds": self.captured_at,
            "capturedAtEpochSeconds": self.captured_wall_time,
            "cgroupGeneration": self.cgroup_generation,
            "memory": {
                "currentBytes": self.memory_current_bytes,
                "peakBytes": self.memory_peak_bytes,
                "maxBytes": self.memory_max_bytes,
                "anonBytes": self.memory_anon_bytes,
                "fileBytes": self.memory_file_bytes,
                "eventsSource": self.events_source,
                "events": dict(self.events),
                "swapCurrentBytes": self.swap_current_bytes,
                "swapMaxBytes": self.swap_max_bytes,
            },
            "vram": vram,
        }


@dataclass(frozen=True, slots=True)
class MemoryRunRecord:
    task_id: str
    workload: str
    phase: str
    outcome: str
    before: MemorySnapshot
    after: MemorySnapshot
    drain_required: bool
    recovery_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "amd.memory-run.v1",
            "resourcePool": "local_gpu",
            "taskId": self.task_id,
            "workload": self.workload,
            "phase": self.phase,
            "outcome": self.outcome,
            "snapshots": {
                "before": self.before.to_dict(),
                "after": self.after.to_dict(),
            },
            "drainUnloadBeforeNext": self.drain_required,
            "recoveryRequired": self.recovery_required,
        }


@dataclass(frozen=True, slots=True)
class PageCacheReclaimRecord:
    model_revision: str
    process_identity: str
    manifest_digest: str
    files: tuple[WeightFileManifestEntry, ...]
    before: MemorySnapshot
    after: MemorySnapshot
    target_cached_before_bytes: int
    target_cached_after_bytes: int
    admission_restored: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "amd.page-cache-reclaim.v1",
            "resourcePool": "local_gpu",
            "modelRevision": self.model_revision,
            "processIdentity": self.process_identity,
            "manifestDigest": self.manifest_digest,
            "files": [item.to_dict() for item in self.files],
            "snapshots": {
                "before": self.before.to_dict(),
                "after": self.after.to_dict(),
            },
            "targetCachedBytes": {
                "before": self.target_cached_before_bytes,
                "after": self.target_cached_after_bytes,
            },
            "admissionRestored": self.admission_restored,
        }


class PathCgroupFilesystem:
    """Pinned no-follow reader for this process' unified cgroup-v2 scope."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        clock: Callable[[], float],
        proc_root: Path = Path("/proc"),
        cgroup_mount: Path = Path("/sys/fs/cgroup"),
    ) -> None:
        if os.name != "posix":
            raise OSError("secure cgroup filesystem requires Linux")
        self.proc_root = proc_root
        self.cgroup_mount = cgroup_mount
        self.clock = clock
        try:
            derived = _cgroup_path_from_proc(
                proc_root=proc_root,
                cgroup_mount=cgroup_mount,
                process="self",
            )
        except (FileNotFoundError, ProcessLookupError) as exc:
            raise CgroupDataError(
                "running process unified cgroup is unavailable"
            ) from exc
        if root is not None and root != derived:
            raise CgroupDataError(
                "cgroup root does not match the running process unified cgroup"
            )
        self.root = derived
        self._dir_fd = _open_absolute_directory_no_follow(derived)
        value = os.fstat(self._dir_fd)
        self._identity = (value.st_dev, value.st_ino)
        self._generation = _cgroup_generation_from_status(value)
        self._validate_running_process_scope()

    def generation(self) -> str:
        self._validate_running_process_scope()
        return self._generation

    def read(self, name: str) -> CgroupFileObservation:
        if name not in {
            "memory.current",
            "memory.peak",
            "memory.max",
            "memory.events.local",
            "memory.events",
            "memory.stat",
            "memory.swap.current",
            "memory.swap.max",
        }:
            raise CgroupDataError("unsupported cgroup file")
        before = self.generation()
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=self._dir_fd,
            )
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise CgroupDataError(f"cannot securely open cgroup file {name}") from exc
        try:
            value = os.fstat(fd)
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise CgroupDataError(
                    f"cgroup file {name} is not a single-link regular authority"
                )
            raw = os.read(fd, 1_000_001)
            if len(raw) > 1_000_000:
                raise CgroupDataError(f"cgroup file {name} is too large")
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError as exc:
                raise CgroupDataError(f"cgroup file {name} is not ASCII") from exc
            observed_at = self.clock()
        finally:
            os.close(fd)
        after = self.generation()
        if after != before:
            raise CgroupGenerationChanged(
                "unified cgroup generation changed while reading"
            )
        return CgroupFileObservation(
            text=text,
            observed_at=observed_at,
            generation=after,
        )

    def _validate_running_process_scope(self) -> None:
        pinned = os.fstat(self._dir_fd)
        if (
            not stat.S_ISDIR(pinned.st_mode)
            or pinned.st_nlink < 1
            or (pinned.st_dev, pinned.st_ino) != self._identity
            or _cgroup_generation_from_status(pinned) != self._generation
        ):
            raise CgroupGenerationChanged("pinned unified cgroup inode changed")
        try:
            current_path = _cgroup_path_from_proc(
                proc_root=self.proc_root,
                cgroup_mount=self.cgroup_mount,
                process="self",
            )
        except (FileNotFoundError, ProcessLookupError) as exc:
            raise CgroupDataError(
                "running process unified cgroup is unavailable"
            ) from exc
        if current_path != self.root:
            raise CgroupGenerationChanged(
                "running process moved to another unified cgroup"
            )
        current_fd = _open_absolute_directory_no_follow(current_path)
        try:
            current = os.fstat(current_fd)
            if (
                not stat.S_ISDIR(current.st_mode)
                or current.st_nlink < 1
                or (current.st_dev, current.st_ino) != self._identity
            ):
                raise CgroupGenerationChanged(
                    "running process unified cgroup inode changed"
                )
        finally:
            os.close(current_fd)


class LocalGpuLease:
    """Opaque single-GPU lease; completion never preempts another task."""

    __slots__ = (
        "__guard",
        "__token",
        "__task_id",
        "__phase",
        "__model_revision",
        "__before",
        "__authority_lease",
        "__finished",
    )

    def __init__(
        self,
        *,
        factory_seal: object,
        guard: AmdMemoryGuard,
        token: object,
        task_id: str,
        phase: RuntimePhase,
        model_revision: str,
        before: MemorySnapshot,
        authority_lease: FileGpuAuthorityLease,
    ) -> None:
        if factory_seal is not _LEASE_FACTORY_SEAL:
            raise TypeError("local GPU leases are guard-created")
        object.__setattr__(self, "_LocalGpuLease__guard", guard)
        object.__setattr__(self, "_LocalGpuLease__token", token)
        object.__setattr__(self, "_LocalGpuLease__task_id", task_id)
        object.__setattr__(self, "_LocalGpuLease__phase", phase)
        object.__setattr__(
            self,
            "_LocalGpuLease__model_revision",
            model_revision,
        )
        object.__setattr__(self, "_LocalGpuLease__before", before)
        object.__setattr__(
            self,
            "_LocalGpuLease__authority_lease",
            authority_lease,
        )
        object.__setattr__(self, "_LocalGpuLease__finished", False)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("local GPU leases are immutable")

    @property
    def task_id(self) -> str:
        return self.__task_id

    @property
    def phase(self) -> RuntimePhase:
        return self.__phase

    @property
    def before(self) -> MemorySnapshot:
        return self.__before

    @property
    def model_revision(self) -> str:
        return self.__model_revision

    @property
    def active(self) -> bool:
        return not self.__finished and self.__guard._owns(self, self.__token)

    def finish(self, *, outcome: str) -> MemoryRunRecord:
        return self.__guard._finish(self, token=self.__token, outcome=outcome)

    def bind_model_process(self, identity: ProcessIdentity) -> None:
        self.__guard._bind_model_process(
            self,
            token=self.__token,
            identity=identity,
            authority_lease=self.__authority_lease,
        )

    @property
    def _authority_lease(self) -> FileGpuAuthorityLease:
        return self.__authority_lease

    def _mark_finished(self) -> None:
        object.__setattr__(self, "_LocalGpuLease__finished", True)


class AmdMemoryGuard:
    """Stateful cgroup-v2 admission guard for one ``local_gpu`` resource.

    ``memory.events`` values are cumulative only within one cgroup generation.
    The first observed ``max`` value is an explicit historical baseline, while
    any initially nonzero OOM-family value denies generation.  Every later
    max/OOM-family increment latches recovery, including increments persisted
    by a prior process in the cross-process GPU authority record.

    The recovery latch intentionally has no in-place reset.  Once pressure is
    observed, callers must unload and construct a fresh guard in the recovered
    process/container; unchanged nonzero OOM counters remain inadmissible.
    """

    def __init__(
        self,
        *,
        cgroup: CgroupFilesystem,
        clock: Callable[[], float],
        vram_sampler: Callable[[], VramSample],
        atomic_recorder: Callable[[dict[str, object]], None],
        lease_authority: GpuLeaseAuthority,
        wall_clock: Callable[[], float] = time.time,
        guard_id: str | None = None,
        max_observation_age_seconds: float = 2.0,
        idle_vram_threshold_bytes: int = 0,
        idle_vram_threshold_evidence_sha256: str | None = None,
        idle_vram_device_id: str | None = None,
        trusted_idle_vram_registry: TrustedIdleVramRegistry | None = None,
    ) -> None:
        if (
            not math.isfinite(max_observation_age_seconds)
            or max_observation_age_seconds <= 0
        ):
            raise ValueError("max observation age must be finite and positive")
        if (
            isinstance(idle_vram_threshold_bytes, bool)
            or not isinstance(idle_vram_threshold_bytes, int)
            or idle_vram_threshold_bytes < 0
        ):
            raise ValueError("idle VRAM threshold must be a non-negative integer")
        idle_vram_authority: IdleVramThresholdAuthority | None = None
        if idle_vram_threshold_bytes == 0:
            if (
                idle_vram_threshold_evidence_sha256 is not None
                or idle_vram_device_id is not None
                or trusted_idle_vram_registry is not None
            ):
                raise ValueError(
                    "zero idle VRAM threshold must not claim trusted evidence"
                )
        else:
            if (
                not isinstance(idle_vram_threshold_evidence_sha256, str)
                or len(idle_vram_threshold_evidence_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in idle_vram_threshold_evidence_sha256
                )
                or not isinstance(idle_vram_device_id, str)
                or not idle_vram_device_id
                or len(idle_vram_device_id) > 200
                or type(trusted_idle_vram_registry)
                is not TrustedIdleVramRegistry
            ):
                raise ValueError(
                    "a nonzero threshold requires an exact trusted idle VRAM "
                    "registry binding with device and evidence SHA-256"
                )
            idle_vram_authority = trusted_idle_vram_registry.resolve(
                device_id=idle_vram_device_id,
                threshold_bytes=idle_vram_threshold_bytes,
                evidence_sha256=idle_vram_threshold_evidence_sha256,
            )
        self.cgroup = cgroup
        self.clock = clock
        self.wall_clock = wall_clock
        self.vram_sampler = vram_sampler
        self.atomic_recorder = atomic_recorder
        self.lease_authority = lease_authority
        self.guard_id = guard_id or uuid.uuid4().hex
        if (
            not isinstance(self.guard_id, str)
            or not self.guard_id
            or len(self.guard_id) > 200
        ):
            raise ValueError("guard_id must contain 1 to 200 characters")
        self.max_observation_age_seconds = max_observation_age_seconds
        self.idle_vram_threshold_bytes = idle_vram_threshold_bytes
        self.idle_vram_threshold_evidence_sha256 = (
            idle_vram_threshold_evidence_sha256
        )
        self.idle_vram_device_id = idle_vram_device_id
        self.trusted_idle_vram_registry = trusted_idle_vram_registry
        self._idle_vram_authority = idle_vram_authority
        self._last_snapshot: MemorySnapshot | None = None
        self._active_lease: LocalGpuLease | None = None
        self._active_token: object | None = None
        self._drain_required = False
        self._recovery_required = False
        self._last_now: float | None = None
        self._observation_watermarks: dict[str, float] = {}

    @property
    def active_task_id(self) -> str | None:
        return None if self._active_lease is None else self._active_lease.task_id

    @property
    def drain_required(self) -> bool:
        return self._drain_required

    @property
    def recovery_required(self) -> bool:
        return self._recovery_required

    def snapshot(self) -> MemorySnapshot:
        started_at = self._now()
        generation = self._generation()
        observed_times: list[tuple[str, float]] = []
        previous = self._last_snapshot
        if previous is not None and previous.cgroup_generation != generation:
            raise CgroupGenerationChanged(
                "cgroup generation changed from "
                f"{previous.cgroup_generation!r} to {generation!r}"
            )

        current = self._read_integer(
            "memory.current",
            generation,
            observed_times,
        )
        peak = self._read_integer("memory.peak", generation, observed_times)
        maximum = self._read_limit("memory.max", generation, observed_times)
        events_source, events = self._read_events(generation, observed_times)
        memory_stat = self._read_memory_stat(generation, observed_times)
        swap_current = self._read_integer(
            "memory.swap.current",
            generation,
            observed_times,
        )
        swap_max = self._read_swap_max(generation, observed_times)
        vram = self._sample_vram(observed_times)
        finished_at = self._now()

        if self._generation() != generation:
            raise CgroupGenerationChanged(
                f"cgroup generation changed while sampling {generation!r}"
            )
        for label, observed_at in observed_times:
            self._require_fresh(
                label,
                observed_at,
                started_at=started_at,
                finished_at=finished_at,
            )
        if maximum != HARD_MEMORY_MAX_BYTES:
            raise CgroupDataError(
                "memory.max must equal the hard AMD limit "
                f"{HARD_MEMORY_MAX_BYTES}, got {maximum}"
            )
        if current > maximum:
            raise CgroupDataError("memory.current exceeds memory.max")
        if peak < current or peak > maximum:
            raise CgroupDataError("memory.peak is inconsistent with cgroup limits")
        if swap_max != 0 or swap_current != 0:
            raise SwapEnabled(
                "guarded cgroup must have memory.swap.max=0 and no swap usage"
            )
        if (
            self._idle_vram_authority is not None
            and vram.device_id != self._idle_vram_authority.device_id
        ):
            raise CgroupDataError(
                "VRAM sample does not match the trusted idle VRAM device"
            )
        if self.idle_vram_threshold_bytes >= vram.total_bytes:
            raise CgroupDataError(
                "idle VRAM threshold must be below device total VRAM"
            )

        if previous is not None:
            if peak < previous.memory_peak_bytes:
                raise MemoryCounterRegression(
                    "memory.peak regressed from "
                    f"{previous.memory_peak_bytes} to {peak}"
                )
            for key in _REQUIRED_EVENT_COUNTERS:
                if events[key] < previous.events[key]:
                    raise MemoryCounterRegression(
                        f"memory event counter {key!r} regressed from "
                        f"{previous.events[key]} to {events[key]}"
                    )
            if (
                vram.device_id != previous.vram.device_id
                or vram.total_bytes != previous.vram.total_bytes
            ):
                raise CgroupDataError("VRAM device authority changed")
            if any(
                events[key] > previous.events[key]
                for key in _RECOVERY_EVENT_COUNTERS
            ):
                self._recovery_required = True
                self._drain_required = True

        snapshot = MemorySnapshot(
            captured_at=finished_at,
            captured_wall_time=self._wall_now(),
            cgroup_generation=generation,
            memory_current_bytes=current,
            memory_peak_bytes=peak,
            memory_max_bytes=maximum,
            memory_anon_bytes=memory_stat["anon"],
            memory_file_bytes=memory_stat["file"],
            events_source=events_source,
            events=MappingProxyType(dict(sorted(events.items()))),
            swap_current_bytes=swap_current,
            swap_max_bytes=swap_max,
            vram=vram,
            idle_vram_threshold_bytes=self.idle_vram_threshold_bytes,
            idle_vram_threshold_evidence_sha256=(
                self.idle_vram_threshold_evidence_sha256
            ),
            idle_vram_registry_digest=(
                None
                if self.trusted_idle_vram_registry is None
                else self.trusted_idle_vram_registry.registry_digest
            ),
        )
        for label, observed_at in observed_times:
            self._observation_watermarks[label] = float(observed_at)
        self._last_snapshot = snapshot
        return snapshot

    def acquire(
        self,
        *,
        task_id: str,
        phase: RuntimePhase,
        model_revision: str | None = None,
    ) -> LocalGpuLease:
        if self._active_lease is not None:
            raise LocalGpuBusy(
                f"local_gpu is held by active task {self._active_lease.task_id!r}"
            )
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 200:
            raise ValueError("task_id must contain 1 to 200 characters")
        try:
            normalized_phase = RuntimePhase(phase)
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime phase is not a frozen FLUX/H3 label") from exc
        normalized_revision = (
            _FROZEN_MODEL_REVISIONS[normalized_phase.workload]
            if model_revision is None
            else model_revision
        )
        if (
            not isinstance(normalized_revision, str)
            or not normalized_revision
            or len(normalized_revision) > 200
        ):
            raise ValueError("model_revision must contain 1 to 200 characters")
        if self._recovery_required and not normalized_phase.is_unload:
            raise RecoveryRequired(
                "memory pressure requires a fresh guard/process/container recovery "
                "before another generation task"
            )
        if self._drain_required and not normalized_phase.is_unload:
            raise DrainUnloadRequired(
                "a model unload phase is required before the next GPU task"
            )

        authority_lease = self.lease_authority.acquire(
            guard_id=self.guard_id,
            task_id=task_id.strip(),
            phase=normalized_phase,
            model_revision=normalized_revision,
        )

        try:
            before = self.snapshot()
            self._reconcile_authority_baseline(authority_lease, before)
            nonzero_oom = tuple(
                key for key in _OOM_EVENT_COUNTERS if before.events[key] != 0
            )
            if nonzero_oom:
                self._recovery_required = True
                self._drain_required = True
            self.lease_authority.commit_observation_baseline(
                authority_lease,
                cgroup_generation=before.cgroup_generation,
                events=before.events,
                recovery_required=self._recovery_required,
                memory_peak_bytes=before.memory_peak_bytes,
            )
        except Exception:
            self._release_authority(authority_lease)
            raise
        if self._recovery_required and not normalized_phase.is_unload:
            detail = (
                ", ".join(nonzero_oom)
                if nonzero_oom
                else "memory pressure during a prior GPU task"
            )
            self._release_authority(authority_lease)
            raise RecoveryRequired(
                f"{detail} requires a fresh guard/process/container recovery "
                "before another generation task"
            )
        if self._drain_required and not normalized_phase.is_unload:
            self._release_authority(authority_lease)
            raise DrainUnloadRequired(
                "a model unload phase is required before the next GPU task"
            )
        if not normalized_phase.is_unload:
            if before.memory_current_bytes >= DRAIN_UNLOAD_BYTES:
                self._drain_required = True
                self._release_authority(authority_lease)
                raise DrainUnloadRequired(
                    "memory reached the drain threshold; unload before next task"
                )
            if before.memory_current_bytes >= ADMISSION_REJECT_BYTES:
                self._release_authority(authority_lease)
                raise MemoryAdmissionDenied(
                    "memory.current must be below "
                    f"{ADMISSION_REJECT_BYTES}, got "
                    f"{before.memory_current_bytes}"
                )

        token = object()
        lease = LocalGpuLease(
            factory_seal=_LEASE_FACTORY_SEAL,
            guard=self,
            token=token,
            task_id=task_id.strip(),
            phase=normalized_phase,
            model_revision=normalized_revision,
            before=before,
            authority_lease=authority_lease,
        )
        self._active_token = token
        self._active_lease = lease
        return lease

    def assert_auxiliary_allowed(self, work: AuxiliaryWork) -> None:
        try:
            normalized = AuxiliaryWork(work)
        except (TypeError, ValueError) as exc:
            raise ValueError("auxiliary work label is not frozen") from exc
        if self._active_lease is not None:
            raise AuxiliaryWorkDenied(
                f"{normalized.value} is denied while GPU task "
                f"{self._active_lease.task_id!r} is active"
            )

    def _finish(
        self,
        lease: LocalGpuLease,
        *,
        token: object,
        outcome: str,
    ) -> MemoryRunRecord:
        if not self._owns(lease, token) or not lease.active:
            raise LeaseStateError("local GPU lease is not active in this guard")
        if outcome not in _OUTCOMES:
            raise ValueError("lease outcome must be completed, failed, or cancelled")

        after = self.snapshot()
        pressure_growth = tuple(
            key
            for key in _RECOVERY_EVENT_COUNTERS
            if after.events[key] > lease.before.events[key]
        )
        recovery_required = self._recovery_required or bool(pressure_growth)
        if recovery_required:
            drain_required = True
        elif lease.phase.is_unload:
            drain_required = not (
                after.memory_current_bytes < ADMISSION_REJECT_BYTES
                and self._vram_is_idle(after)
                and self.lease_authority.model_process_exited(
                    lease._authority_lease
                )
            )
        else:
            drain_required = after.memory_current_bytes >= DRAIN_UNLOAD_BYTES
        record = MemoryRunRecord(
            task_id=lease.task_id,
            workload=lease.phase.workload,
            phase=lease.phase.value,
            outcome=outcome,
            before=lease.before,
            after=after,
            drain_required=drain_required,
            recovery_required=recovery_required,
        )

        self.atomic_recorder(record.to_dict())
        self.lease_authority.release(
            lease._authority_lease,
            cgroup_generation=after.cgroup_generation,
            events=after.events,
            recovery_required=recovery_required,
            memory_peak_bytes=after.memory_peak_bytes,
        )
        self._drain_required = drain_required
        self._recovery_required = recovery_required
        self._active_lease = None
        self._active_token = None
        lease._mark_finished()
        return record

    def _owns(self, lease: LocalGpuLease, token: object) -> bool:
        return self._active_lease is lease and self._active_token is token

    def _bind_model_process(
        self,
        lease: LocalGpuLease,
        *,
        token: object,
        identity: ProcessIdentity,
        authority_lease: FileGpuAuthorityLease,
    ) -> None:
        if not self._owns(lease, token) or not lease.active:
            raise LeaseStateError("local GPU lease is not active in this guard")
        if identity.model_revision != lease.model_revision:
            raise LeaseStateError("model process revision does not match lease")
        self.lease_authority.bind_model_process(authority_lease, identity)

    def _begin_targeted_reclaim(
        self,
        *,
        model_revision: str,
    ) -> FileGpuAuthorityLease:
        if self._active_lease is not None:
            raise PageCacheReclaimDenied(
                "targeted reclaim is denied with an active local_gpu lease"
            )
        self._drain_required = True
        return self.lease_authority.begin_reclaim(
            guard_id=self.guard_id,
            model_revision=model_revision,
        )

    def _complete_targeted_reclaim(
        self,
        authority_lease: FileGpuAuthorityLease,
        *,
        admission_restored: bool,
        success: bool,
        snapshot: MemorySnapshot,
    ) -> None:
        if self._active_lease is not None:
            raise PageCacheReclaimDenied(
                "targeted reclaim cannot complete with an active local_gpu lease"
            )
        self._drain_required = not (
            admission_restored and not self._recovery_required
        )
        self.lease_authority.finish_reclaim(
            authority_lease,
            success=success,
            cgroup_generation=snapshot.cgroup_generation,
            events=snapshot.events,
            recovery_required=self._recovery_required,
            memory_peak_bytes=snapshot.memory_peak_bytes,
        )

    def _release_authority(self, authority_lease: FileGpuAuthorityLease) -> None:
        snapshot = self._last_snapshot
        raw_generation = authority_lease.record.get("cgroupGeneration")
        raw_events = authority_lease.record.get("events")
        durable_baseline_available = isinstance(raw_generation, str) and isinstance(
            raw_events, Mapping
        )
        snapshot_advances_durable = snapshot is not None and (
            not durable_baseline_available
            or (
                snapshot.cgroup_generation == raw_generation
                and all(
                    isinstance(raw_events.get(key), int)
                    and not isinstance(raw_events.get(key), bool)
                    and snapshot.events[key] >= cast(int, raw_events.get(key))
                    for key in _REQUIRED_EVENT_COUNTERS
                )
            )
        )
        if snapshot_advances_durable:
            assert snapshot is not None
            generation = snapshot.cgroup_generation
            events = snapshot.events
        elif durable_baseline_available:
            generation = cast(str, raw_generation)
            events = cast(Mapping[str, int], raw_events)
        else:
            # Acquisition failed before the first usable observation.  This
            # establishes a non-decreasing zero watermark only so the lock can be
            # safely closed; it cannot authorize generation because acquire failed.
            generation = self._generation()
            events = {key: 0 for key in _REQUIRED_EVENT_COUNTERS}
        self.lease_authority.release(
            authority_lease,
            cgroup_generation=generation,
            events=events,
            recovery_required=self._recovery_required,
            memory_peak_bytes=(
                None if snapshot is None else snapshot.memory_peak_bytes
            ),
        )

    def _reconcile_authority_baseline(
        self,
        authority_lease: FileGpuAuthorityLease,
        snapshot: MemorySnapshot,
    ) -> None:
        record = authority_lease.record
        raw_owner = record.get("ownerProcess")
        if raw_owner is not None:
            if not isinstance(raw_owner, Mapping):
                raise CgroupDataError("durable GPU authority owner is invalid")
            try:
                owner = ProcessIdentity.from_mapping(raw_owner)
            except ValueError as exc:
                raise CgroupDataError(
                    "durable GPU authority owner is invalid"
                ) from exc
            if owner.cgroup_identity != snapshot.cgroup_generation:
                raise CgroupGenerationChanged(
                    "cgroup reader does not match the lease owner unified cgroup"
                )
        prior_generation = record.get("cgroupGeneration")
        if prior_generation is not None:
            if (
                not isinstance(prior_generation, str)
                or prior_generation != snapshot.cgroup_generation
            ):
                raise CgroupGenerationChanged(
                    "durable GPU authority belongs to a different cgroup generation"
                )
        prior_events = record.get("events")
        if prior_events is not None:
            if not isinstance(prior_events, Mapping):
                raise CgroupDataError("durable GPU authority events are invalid")
            normalized: dict[str, int] = {}
            for key in _REQUIRED_EVENT_COUNTERS:
                value = prior_events.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise CgroupDataError(
                        "durable GPU authority event counter is invalid"
                    )
                normalized[key] = value
            for key in _REQUIRED_EVENT_COUNTERS:
                if snapshot.events[key] < normalized[key]:
                    raise MemoryCounterRegression(
                        f"memory event counter {key!r} regressed across processes"
                    )
            if any(
                snapshot.events[key] > normalized[key]
                for key in _RECOVERY_EVENT_COUNTERS
            ):
                self._recovery_required = True
                self._drain_required = True
        prior_peak = record.get("memoryPeakBytes")
        if prior_peak is not None:
            if (
                isinstance(prior_peak, bool)
                or not isinstance(prior_peak, int)
                or prior_peak < 0
            ):
                raise CgroupDataError("durable GPU authority memory.peak is invalid")
            if snapshot.memory_peak_bytes < prior_peak:
                raise MemoryCounterRegression(
                    "memory.peak regressed across guard restart"
                )
        if record.get("recoveryRequired") is True:
            self._recovery_required = True
            self._drain_required = True

    def _generation(self) -> str:
        try:
            generation = self.cgroup.generation()
        except CgroupDataError:
            raise
        except Exception as exc:
            raise CgroupDataError("cgroup generation is unavailable") from exc
        if (
            not isinstance(generation, str)
            or not generation.strip()
            or len(generation) > 200
        ):
            raise CgroupDataError("cgroup generation is invalid")
        return generation

    def _now(self) -> float:
        try:
            now = float(self.clock())
        except Exception as exc:
            raise StaleObservation("snapshot clock is unavailable") from exc
        if not math.isfinite(now):
            raise StaleObservation("snapshot clock is not finite")
        if self._last_now is not None and now < self._last_now:
            raise StaleObservation("snapshot monotonic clock regressed")
        self._last_now = now
        return now

    def _wall_now(self) -> float:
        try:
            now = float(self.wall_clock())
        except Exception as exc:
            raise StaleObservation("snapshot wall clock is unavailable") from exc
        if not math.isfinite(now):
            raise StaleObservation("snapshot wall clock is not finite")
        return now

    def _read_observation(
        self,
        name: str,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> CgroupFileObservation:
        try:
            observation = self.cgroup.read(name)
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise CgroupDataError(f"cannot read {name}") from exc
        if not isinstance(observation, CgroupFileObservation):
            raise CgroupDataError(f"{name} observation has the wrong type")
        if observation.generation != generation:
            raise CgroupGenerationChanged(
                f"{name} belongs to cgroup {observation.generation!r}, "
                f"expected {generation!r}"
            )
        observed_times.append((name, observation.observed_at))
        if not isinstance(observation.text, str):
            raise CgroupDataError(f"{name} is not text")
        return observation

    def _read_integer(
        self,
        name: str,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> int:
        try:
            text = self._read_observation(
                name,
                generation,
                observed_times,
            ).text.strip()
        except FileNotFoundError as exc:
            raise CgroupDataError(f"required cgroup file {name} is missing") from exc
        if text == "max":
            raise CgroupDataError(f"{name} must not be unlimited")
        try:
            value = int(text, 10)
        except (TypeError, ValueError) as exc:
            raise CgroupDataError(f"{name} is not an integer") from exc
        if value < 0:
            raise CgroupDataError(f"{name} must be non-negative")
        return value

    def _read_limit(
        self,
        name: str,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> int:
        return self._read_integer(name, generation, observed_times)

    def _read_swap_max(
        self,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> int:
        name = "memory.swap.max"
        try:
            text = self._read_observation(
                name,
                generation,
                observed_times,
            ).text.strip()
        except FileNotFoundError as exc:
            raise CgroupDataError(f"required cgroup file {name} is missing") from exc
        if text == "max":
            raise SwapEnabled("memory.swap.max is unlimited")
        try:
            value = int(text, 10)
        except (TypeError, ValueError) as exc:
            raise CgroupDataError("memory.swap.max is not an integer") from exc
        if value < 0:
            raise CgroupDataError("memory.swap.max must be non-negative")
        return value

    def _read_events(
        self,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> tuple[str, dict[str, int]]:
        source = "memory.events.local"
        try:
            observation = self._read_observation(
                source,
                generation,
                observed_times,
            )
        except FileNotFoundError:
            source = "memory.events"
            try:
                observation = self._read_observation(
                    source,
                    generation,
                    observed_times,
                )
            except FileNotFoundError as exc:
                raise CgroupDataError("memory event counters are unavailable") from exc
        counters: dict[str, int] = {}
        for raw_line in observation.text.splitlines():
            parts = raw_line.split()
            if len(parts) != 2 or parts[0] in counters:
                raise CgroupDataError(f"{source} has malformed counters")
            try:
                value = int(parts[1], 10)
            except ValueError as exc:
                raise CgroupDataError(f"{source} has a non-integer counter") from exc
            if value < 0:
                raise CgroupDataError(f"{source} has a negative counter")
            counters[parts[0]] = value
        missing = _REQUIRED_EVENT_COUNTERS.difference(counters)
        if missing:
            raise CgroupDataError(
                f"{source} is missing counters: {', '.join(sorted(missing))}"
            )
        return source, counters

    def _read_memory_stat(
        self,
        generation: str,
        observed_times: list[tuple[str, float]],
    ) -> dict[str, int]:
        source = "memory.stat"
        try:
            observation = self._read_observation(
                source,
                generation,
                observed_times,
            )
        except FileNotFoundError as exc:
            raise CgroupDataError("memory.stat is unavailable") from exc
        counters: dict[str, int] = {}
        for raw_line in observation.text.splitlines():
            parts = raw_line.split()
            if len(parts) != 2 or parts[0] in counters:
                raise CgroupDataError("memory.stat has malformed counters")
            try:
                value = int(parts[1], 10)
            except ValueError as exc:
                raise CgroupDataError("memory.stat has a non-integer counter") from exc
            if value < 0:
                raise CgroupDataError("memory.stat has a negative counter")
            counters[parts[0]] = value
        missing = {"anon", "file"}.difference(counters)
        if missing:
            raise CgroupDataError(
                f"memory.stat is missing counters: {', '.join(sorted(missing))}"
            )
        return counters

    def _sample_vram(
        self,
        observed_times: list[tuple[str, float]],
    ) -> VramSample:
        try:
            sample = self.vram_sampler()
        except Exception as exc:
            raise CgroupDataError("VRAM sampler failed") from exc
        if not isinstance(sample, VramSample):
            raise CgroupDataError("VRAM sampler returned the wrong type")
        observed_times.append(("VRAM", sample.observed_at))
        if (
            type(sample.device_id) is not str
            or not sample.device_id
            or type(sample.total_bytes) is not int
            or sample.total_bytes <= 0
            or type(sample.used_bytes) is not int
            or sample.used_bytes < 0
            or sample.used_bytes > sample.total_bytes
        ):
            raise CgroupDataError("VRAM sample is invalid")
        return sample

    def _require_fresh(
        self,
        label: str,
        observed_at: float,
        *,
        started_at: float,
        finished_at: float,
    ) -> None:
        if (
            isinstance(observed_at, bool)
            or not isinstance(observed_at, (int, float))
            or not math.isfinite(observed_at)
        ):
            raise StaleObservation(f"{label} observation time is invalid")
        if finished_at < started_at:
            raise StaleObservation("snapshot clock regressed while sampling")
        observed = float(observed_at)
        oldest = max(
            started_at,
            finished_at - self.max_observation_age_seconds,
        )
        if observed < oldest or observed > finished_at:
            raise StaleObservation(
                f"{label} observation is outside the current sampling window"
            )
        prior = self._observation_watermarks.get(label)
        if prior is not None and observed <= prior:
            raise StaleObservation(
                f"{label} observation is not newer than its accepted watermark"
            )

    def _vram_is_idle(self, snapshot: MemorySnapshot) -> bool:
        return snapshot.vram.used_bytes <= self.idle_vram_threshold_bytes


class TargetedWeightPageCacheReclaimer:
    """Apply DONTNEED only to deployment-anchored, same-FD weight files."""

    def __init__(
        self,
        *,
        guard: AmdMemoryGuard,
        trusted_registry: TrustedWeightRegistry,
        file_ops: WeightFileOps,
    ) -> None:
        if type(trusted_registry) is not TrustedWeightRegistry:
            raise TypeError("trusted registry must be deployment-anchored")
        self.guard = guard
        self.trusted_registry = trusted_registry
        self.file_ops = file_ops

    def reclaim(
        self,
        *,
        manifest_digest: str,
    ) -> PageCacheReclaimRecord:
        if self.guard.active_task_id is not None:
            raise PageCacheReclaimDenied(
                "targeted reclaim is denied with an active local_gpu lease"
            )
        requested = self.trusted_registry.resolve(manifest_digest)
        authority_lease = self.guard._begin_targeted_reclaim(
            model_revision=requested.model_revision,
        )
        before: MemorySnapshot | None = None
        last_snapshot: MemorySnapshot | None = None
        authority_finished = False
        opened: set[int] = set()
        try:
            before = self.guard.snapshot()
            self.guard._reconcile_authority_baseline(authority_lease, before)
            last_snapshot = before
            cached_before = 0
            cached_after = 0
            for item in requested.files:
                fd = self.file_ops.open(item.path)
                if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
                    raise PageCacheReclaimDenied(
                        "weight file opener returned an invalid fd"
                    )
                opened.add(fd)
                try:
                    self._verify_open_file(fd, item)
                    cached_before += self.file_ops.cached_bytes(
                        fd,
                        item.size_bytes,
                    )
                    self.file_ops.advise_dontneed(fd, item.size_bytes)
                    cached_after += self.file_ops.cached_bytes(
                        fd,
                        item.size_bytes,
                    )
                finally:
                    self.file_ops.close(fd)
                    opened.discard(fd)
            after = self.guard.snapshot()
            last_snapshot = after

            effective = (
                cached_after < cached_before
                and after.memory_current_bytes < before.memory_current_bytes
                and after.memory_file_bytes < before.memory_file_bytes
            )
            admission_restored = (
                effective
                and after.memory_current_bytes < ADMISSION_REJECT_BYTES
                and self.guard._vram_is_idle(after)
                and not self.guard.recovery_required
            )
            raw_identity = authority_lease.record.get("modelProcess")
            process_identity = json.dumps(
                raw_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            record = PageCacheReclaimRecord(
                model_revision=requested.model_revision,
                process_identity=process_identity,
                manifest_digest=requested.manifest_digest,
                files=requested.files,
                before=before,
                after=after,
                target_cached_before_bytes=cached_before,
                target_cached_after_bytes=cached_after,
                admission_restored=admission_restored,
            )
            self.guard.atomic_recorder(record.to_dict())
            self.guard._complete_targeted_reclaim(
                authority_lease,
                admission_restored=admission_restored,
                success=effective and admission_restored,
                snapshot=after,
            )
            authority_finished = True
            if not effective:
                raise PageCacheReclaimIneffective(
                    "target file residency and cgroup file cache did not both decline"
                )
            if not admission_restored and not self.guard.recovery_required:
                raise PageCacheReclaimIneffective(
                    "targeted advice reduced cache but did not restore admission "
                    "with verified idle VRAM"
                )
            return record
        except Exception:
            for fd in tuple(opened):
                try:
                    self.file_ops.close(fd)
                finally:
                    opened.discard(fd)
            if not authority_finished:
                try:
                    failure_snapshot = self.guard.snapshot()
                except Exception:
                    failure_snapshot = last_snapshot or self.guard._last_snapshot
                if failure_snapshot is not None:
                    try:
                        self.guard._complete_targeted_reclaim(
                            authority_lease,
                            admission_restored=False,
                            success=False,
                            snapshot=failure_snapshot,
                        )
                        authority_finished = True
                    except Exception:
                        self.guard.lease_authority.abort_reclaim(authority_lease)
                        authority_finished = True
                else:
                    self.guard.lease_authority.abort_reclaim(authority_lease)
                    authority_finished = True
            raise

    def _verify_open_file(
        self,
        fd: int,
        item: WeightFileManifestEntry,
    ) -> None:
        try:
            status = self.file_ops.status(fd)
        except Exception as exc:
            raise PageCacheReclaimDenied(
                f"weight FD authority is unavailable for {item.path!r}"
            ) from exc
        if type(status) is not WeightFileFdStatus:
            raise PageCacheReclaimDenied("weight file FD status has wrong type")
        if (
            status.size_bytes != item.size_bytes
            or status.device != item.device
            or status.inode != item.inode
            or status.link_count != item.link_count
            or status.is_regular is not True
            or status.access_read_only is not True
            or status.file_mode_read_only is not True
            or status.close_on_exec is not True
        ):
            raise PageCacheReclaimDenied(
                "weight FD is not the exact read-only deployment file"
            )
        try:
            actual_digest = self.file_ops.sha256(fd, item.size_bytes)
        except Exception as exc:
            raise PageCacheReclaimDenied(
                f"weight SHA-256 is unavailable for {item.path!r}"
            ) from exc
        if not hmac.compare_digest(actual_digest, item.sha256):
            raise PageCacheReclaimDenied("weight FD SHA-256 does not match registry")


__all__ = [
    "ADMISSION_REJECT_BYTES",
    "CHARACTER_REFERENCE_VIEW_ORDER",
    "DRAIN_UNLOAD_BYTES",
    "FLUX_FORBIDDEN_ARGUMENTS",
    "FLUX_REQUIRED_ARGUMENTS",
    "HARD_MEMORY_MAX_BYTES",
    "MIN_PERSISTENT_AVAILABLE_BYTES",
    "AmdGpuPreflightEvidence",
    "AmdMemoryGuard",
    "AuxiliaryWork",
    "AuxiliaryWorkDenied",
    "CgroupDataError",
    "CgroupFileObservation",
    "CgroupFilesystem",
    "CgroupGenerationChanged",
    "DrainUnloadRequired",
    "DurableGpuSubmissionEvidence",
    "FileAmdAdmissionVerifier",
    "FileGpuAuthorityLease",
    "FileGpuLeaseAuthority",
    "GpuAuthorityBusy",
    "GpuLeaseAuthority",
    "LeaseStateError",
    "LocalGpuBusy",
    "LocalGpuLease",
    "LiveStartObservation",
    "MemoryAdmissionDenied",
    "MemoryCounterRegression",
    "MemoryGuardError",
    "MemoryRunRecord",
    "MemorySnapshot",
    "PageCacheReclaimDenied",
    "PageCacheReclaimIneffective",
    "PageCacheReclaimRecord",
    "PathCgroupFilesystem",
    "PosixWeightFileOps",
    "ProcessIdentity",
    "ProcfsProcessProbe",
    "RecoveryRequired",
    "RuntimePhase",
    "StaleObservation",
    "SwapEnabled",
    "TargetedWeightPageCacheReclaimer",
    "TrustedIdleVramRegistry",
    "TrustedWeightRegistry",
    "VramSample",
    "WeightFileManifestEntry",
    "WeightFileFdStatus",
    "WeightFileOps",
    "WeightReclaimManifest",
    "validate_flux_launch_contract",
]
