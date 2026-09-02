"""Canonical dual-track record-time capture for the frozen VIO/IMU observer.

The artifact deliberately carries two different IMU tracks:

* ``exact_raw_native`` is the immediate native sensor clone.  It exists only
  for provenance and transform auditing.
* ``exact_estimator_delivered_profiled`` is the exact transformed
  ``NativeIMUSample`` delivered to the estimator.  This is the only observer
  input track.

The archive contains no sensor-origin timestamp.  Its time coordinate is an
integer logical transition-end grid derived from the frozen simulation ``dt``.
It is a deterministic, pickle-free ZIP of canonical JSON plus little-endian
raw array members.  A caller must supply the separately frozen whole-file
SHA-256 before any archive member is parsed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import struct
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import numpy.typing as npt

TRANSITION_COUNT = 300
BOUNDARY_COUNT = TRANSITION_COUNT + 1
CAPTURE_SCHEMA_VERSION = "flightguard.exact_native_observer_capture.v1"
RAW_TRACK_NAME = "exact_raw_native"
DELIVERED_TRACK_NAME = "exact_estimator_delivered_profiled"
OBSERVER_INPUT_TRACK_NAME = DELIVERED_TRACK_NAME
RAW_TRACK_PURPOSE = "provenance_and_frozen_transform_audit_only"
DELIVERED_TRACK_PURPOSE = "frozen_vio_imu_observer_input"
TIME_SOURCE = "logical_transition_end_grid_derived_from_exact_dt"
SENSOR_ORIGIN_TIMESTAMP_AVAILABLE = False

Float32Array = npt.NDArray[np.float32]
BoolArray = npt.NDArray[np.bool_]
Int32Array = npt.NDArray[np.int32]
Int64Array = npt.NDArray[np.int64]

_SHA256_HEX_LENGTH = 64
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_EXTERNAL_ATTR = (stat.S_IFREG | 0o444) << 16
_MANIFEST_MEMBER = "manifest.json"
_ARRAY_SPECS = {
    "transition_index": ("<i4", ("transition",)),
    "lane_index": ("<i4", ("lane",)),
    "logical_transition_end_time_ns": ("<i8", ("transition",)),
    "valid_transition_mask": ("|u1", ("transition", "lane")),
    "raw_specific_force_body": ("<f4", ("transition", "lane", 3)),
    "raw_angular_velocity_body": ("<f4", ("transition", "lane", 3)),
    "delivered_specific_force_body": ("<f4", ("transition", "lane", 3)),
    "delivered_angular_velocity_body": ("<f4", ("transition", "lane", 3)),
    "vio_velocity_world": ("<f4", ("boundary", "lane", 3)),
    "vio_quaternion_body_to_world_wxyz": ("<f4", ("boundary", "lane", 4)),
}
_ARRAY_MEMBER_ORDER = tuple(f"arrays/{name}.bin" for name in _ARRAY_SPECS)
_ARCHIVE_MEMBER_ORDER = (_MANIFEST_MEMBER, *_ARRAY_MEMBER_ORDER)
_TOP_LEVEL_MANIFEST_KEYS = {
    "schema_version",
    "lane_count",
    "transition_count",
    "boundary_count",
    "observer_input_track",
    "track_purposes",
    "time",
    "frozen_seeds",
    "frozen_seed_identity_sha256",
    "frozen_transform",
    "arrays",
    "track_sha256",
    "track_lane_sha256",
    "archive_member_order",
}
_ARRAY_METADATA_KEYS = {"dtype", "shape", "sha256", "lane_sha256"}
_TIME_METADATA_KEYS = {
    "source",
    "sensor_origin_timestamp_available",
    "dt_seconds_float64_le_hex",
    "dt_nanoseconds",
}
_TRANSFORM_METADATA_KEYS = {
    "name",
    "enabled",
    "implementation_sha256",
    "config_sha256",
    "error_bank_schema_version",
    "error_bank_sha256",
}


class CaptureArtifactError(ValueError):
    """Raised when capture construction or archive verification fails."""


@dataclass(frozen=True)
class FrozenSensorTransformMetadata:
    """Hash-bound description of the raw-to-delivered sensor transform."""

    name: str
    enabled: bool
    implementation_sha256: str
    config_sha256: str
    error_bank_schema_version: str
    error_bank_sha256: str

    def __post_init__(self) -> None:
        _require_nonempty_text("name", self.name)
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be exact bool")
        _require_sha256("implementation_sha256", self.implementation_sha256)
        _require_sha256("config_sha256", self.config_sha256)
        _require_nonempty_text("error_bank_schema_version", self.error_bank_schema_version)
        _require_sha256("error_bank_sha256", self.error_bank_sha256)

    def as_canonical_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "implementation_sha256": self.implementation_sha256,
            "config_sha256": self.config_sha256,
            "error_bank_schema_version": self.error_bank_schema_version,
            "error_bank_sha256": self.error_bank_sha256,
        }


@dataclass(frozen=True)
class ExactNativeObserverCapture:
    """Owned immutable CPU arrays for a fixed 300-transition capture."""

    raw_specific_force_body: Float32Array
    raw_angular_velocity_body: Float32Array
    delivered_specific_force_body: Float32Array
    delivered_angular_velocity_body: Float32Array
    vio_velocity_world: Float32Array
    vio_quaternion_body_to_world_wxyz: Float32Array
    valid_transition_mask: BoolArray
    transition_index: Int32Array
    lane_index: Int32Array
    logical_transition_end_time_ns: Int64Array
    dt_seconds: float
    frozen_seeds: tuple[tuple[str, int], ...]
    frozen_transform: FrozenSensorTransformMetadata

    @classmethod
    def from_torch(
        cls,
        *,
        raw_specific_force_body: object,
        raw_angular_velocity_body: object,
        delivered_specific_force_body: object,
        delivered_angular_velocity_body: object,
        vio_velocity_world: object,
        vio_quaternion_body_to_world_wxyz: object,
        valid_transition_mask: object,
        dt_seconds: float,
        frozen_seeds: Mapping[str, int],
        frozen_transform: FrozenSensorTransformMetadata,
    ) -> ExactNativeObserverCapture:
        """Cross the Torch/ROCm boundary into owned, immutable CPU storage."""

        raw_force = _own_torch_cpu_array(
            "raw_specific_force_body", raw_specific_force_body, expected_dtype="float32"
        )
        if raw_force.ndim != 3 or raw_force.shape[0] != TRANSITION_COUNT:
            raise CaptureArtifactError(
                "raw_specific_force_body must have shape [300, B, 3]"
            )
        lane_count = raw_force.shape[1]
        if lane_count <= 0 or raw_force.shape[2] != 3:
            raise CaptureArtifactError(
                "raw_specific_force_body must have shape [300, B, 3] with B > 0"
            )
        transition_shape = (TRANSITION_COUNT, lane_count, 3)
        boundary_velocity_shape = (BOUNDARY_COUNT, lane_count, 3)
        boundary_quaternion_shape = (BOUNDARY_COUNT, lane_count, 4)
        raw_gyro = _own_torch_cpu_array(
            "raw_angular_velocity_body",
            raw_angular_velocity_body,
            expected_dtype="float32",
            expected_shape=transition_shape,
        )
        delivered_force = _own_torch_cpu_array(
            "delivered_specific_force_body",
            delivered_specific_force_body,
            expected_dtype="float32",
            expected_shape=transition_shape,
        )
        delivered_gyro = _own_torch_cpu_array(
            "delivered_angular_velocity_body",
            delivered_angular_velocity_body,
            expected_dtype="float32",
            expected_shape=transition_shape,
        )
        vio_velocity = _own_torch_cpu_array(
            "vio_velocity_world",
            vio_velocity_world,
            expected_dtype="float32",
            expected_shape=boundary_velocity_shape,
        )
        vio_quaternion = _own_torch_cpu_array(
            "vio_quaternion_body_to_world_wxyz",
            vio_quaternion_body_to_world_wxyz,
            expected_dtype="float32",
            expected_shape=boundary_quaternion_shape,
        )
        valid_mask_u8 = _own_torch_cpu_array(
            "valid_transition_mask",
            valid_transition_mask,
            expected_dtype="bool",
            expected_shape=(TRANSITION_COUNT, lane_count),
        )
        valid_mask = np.asarray(valid_mask_u8, dtype=np.bool_).copy(order="C")
        dt_value, dt_nanoseconds = _validate_exact_dt(dt_seconds)
        seeds = _canonical_frozen_seeds(frozen_seeds)
        if not isinstance(frozen_transform, FrozenSensorTransformMetadata):
            raise TypeError("frozen_transform must be FrozenSensorTransformMetadata")
        capture = cls(
            raw_specific_force_body=_little_endian_owned(raw_force, "<f4"),
            raw_angular_velocity_body=_little_endian_owned(raw_gyro, "<f4"),
            delivered_specific_force_body=_little_endian_owned(delivered_force, "<f4"),
            delivered_angular_velocity_body=_little_endian_owned(delivered_gyro, "<f4"),
            vio_velocity_world=_little_endian_owned(vio_velocity, "<f4"),
            vio_quaternion_body_to_world_wxyz=_little_endian_owned(
                vio_quaternion, "<f4"
            ),
            valid_transition_mask=valid_mask,
            transition_index=np.arange(TRANSITION_COUNT, dtype="<i4"),
            lane_index=np.arange(lane_count, dtype="<i4"),
            logical_transition_end_time_ns=(
                np.arange(1, BOUNDARY_COUNT, dtype="<i8") * dt_nanoseconds
            ),
            dt_seconds=dt_value,
            frozen_seeds=seeds,
            frozen_transform=frozen_transform,
        )
        _validate_capture(capture)
        _freeze_capture_arrays(capture)
        return capture

    @property
    def lane_count(self) -> int:
        return int(self.lane_index.shape[0])

    @property
    def observer_specific_force_body(self) -> Float32Array:
        """Return the exact estimator-delivered observer input track."""

        return self.delivered_specific_force_body

    @property
    def observer_angular_velocity_body(self) -> Float32Array:
        """Return the exact estimator-delivered observer input track."""

        return self.delivered_angular_velocity_body

    @property
    def raw_track_is_observer_input(self) -> bool:
        return False

    @property
    def sensor_origin_timestamp_available(self) -> bool:
        return SENSOR_ORIGIN_TIMESTAMP_AVAILABLE

    def write_new(self, path: str | os.PathLike[str]) -> str:
        """Write one new canonical artifact and return its whole-file SHA-256."""

        _validate_capture(self)
        archive = _canonical_archive_bytes(self)
        _write_new_sealed_regular_file(Path(path), archive)
        return hashlib.sha256(archive).hexdigest()


class ExactNativeObserverCaptureRecorder:
    """Strict stepwise hook target for the evaluator's pre-freeze capture."""

    def __init__(
        self,
        *,
        dt_seconds: float,
        frozen_seeds: Mapping[str, int],
        frozen_transform: FrozenSensorTransformMetadata,
    ) -> None:
        self._dt_seconds, self._dt_nanoseconds = _validate_exact_dt(dt_seconds)
        self._frozen_seeds = _canonical_frozen_seeds(frozen_seeds)
        if not isinstance(frozen_transform, FrozenSensorTransformMetadata):
            raise TypeError("frozen_transform must be FrozenSensorTransformMetadata")
        self._frozen_transform = frozen_transform
        self._lane_count: int | None = None
        self._next_step = 0
        self._finalized_capture: ExactNativeObserverCapture | None = None
        self._raw_force: Float32Array | None = None
        self._raw_gyro: Float32Array | None = None
        self._delivered_force: Float32Array | None = None
        self._delivered_gyro: Float32Array | None = None
        self._vio_velocity: Float32Array | None = None
        self._vio_quaternion: Float32Array | None = None
        self._valid_mask: BoolArray | None = None

    @property
    def transition_count(self) -> int:
        return self._next_step

    @property
    def complete(self) -> bool:
        return self._next_step == TRANSITION_COUNT

    def record_initial_vio(
        self,
        *,
        quaternion_body_to_world: object,
        velocity_world: object,
    ) -> None:
        """Record boundary zero and fix the lane count before any transition."""

        if self._lane_count is not None:
            raise CaptureArtifactError("initial VIO boundary was already recorded")
        if self._finalized_capture is not None:
            raise CaptureArtifactError("capture recorder is already finalized")
        velocity = _own_torch_cpu_array(
            "velocity_world",
            velocity_world,
            expected_dtype="float32",
        )
        quaternion = _own_torch_cpu_array(
            "quaternion_body_to_world",
            quaternion_body_to_world,
            expected_dtype="float32",
        )
        if velocity.ndim != 2 or velocity.shape[1] != 3 or velocity.shape[0] <= 0:
            raise CaptureArtifactError("initial VIO velocity must have shape [B, 3]")
        lane_count = velocity.shape[0]
        if quaternion.shape != (lane_count, 4):
            raise CaptureArtifactError("initial VIO quaternion must have shape [B, 4]")
        self._lane_count = lane_count
        self._raw_force = np.empty(
            (TRANSITION_COUNT, lane_count, 3), dtype="<f4"
        )
        self._raw_gyro = np.empty(
            (TRANSITION_COUNT, lane_count, 3), dtype="<f4"
        )
        self._delivered_force = np.empty(
            (TRANSITION_COUNT, lane_count, 3), dtype="<f4"
        )
        self._delivered_gyro = np.empty(
            (TRANSITION_COUNT, lane_count, 3), dtype="<f4"
        )
        self._vio_velocity = np.empty(
            (BOUNDARY_COUNT, lane_count, 3), dtype="<f4"
        )
        self._vio_quaternion = np.empty(
            (BOUNDARY_COUNT, lane_count, 4), dtype="<f4"
        )
        self._valid_mask = np.empty(
            (TRANSITION_COUNT, lane_count), dtype=np.bool_
        )
        self._vio_velocity[0] = velocity
        self._vio_quaternion[0] = quaternion

    def append_transition(
        self,
        *,
        step_index: int,
        logical_transition_end_time_ns: int,
        raw_specific_force_body: object,
        raw_angular_velocity_body: object,
        delivered_specific_force_body: object,
        delivered_angular_velocity_body: object,
        next_quaternion_body_to_world: object,
        next_velocity_world: object,
        valid_transition_mask: object,
    ) -> None:
        """Append one exact ordered transition using only record-time values."""

        if self._lane_count is None:
            raise CaptureArtifactError("record_initial_vio must be called first")
        if self._finalized_capture is not None:
            raise CaptureArtifactError("capture recorder is already finalized")
        if self._next_step >= TRANSITION_COUNT:
            raise CaptureArtifactError("capture already contains 300 transitions")
        if type(step_index) is not int or step_index != self._next_step:
            raise CaptureArtifactError(
                f"step_index must be exact next transition {self._next_step}"
            )
        expected_time = (step_index + 1) * self._dt_nanoseconds
        if (
            type(logical_transition_end_time_ns) is not int
            or logical_transition_end_time_ns != expected_time
        ):
            raise CaptureArtifactError(
                "logical_transition_end_time_ns must equal (step_index + 1) * frozen dt"
            )
        lane_count = self._lane_count
        vector_shape = (lane_count, 3)
        raw_force = _own_torch_cpu_array(
            "raw_specific_force_body",
            raw_specific_force_body,
            expected_dtype="float32",
            expected_shape=vector_shape,
        )
        raw_gyro = _own_torch_cpu_array(
            "raw_angular_velocity_body",
            raw_angular_velocity_body,
            expected_dtype="float32",
            expected_shape=vector_shape,
        )
        delivered_force = _own_torch_cpu_array(
            "delivered_specific_force_body",
            delivered_specific_force_body,
            expected_dtype="float32",
            expected_shape=vector_shape,
        )
        delivered_gyro = _own_torch_cpu_array(
            "delivered_angular_velocity_body",
            delivered_angular_velocity_body,
            expected_dtype="float32",
            expected_shape=vector_shape,
        )
        next_velocity = _own_torch_cpu_array(
            "next_velocity_world",
            next_velocity_world,
            expected_dtype="float32",
            expected_shape=vector_shape,
        )
        next_quaternion = _own_torch_cpu_array(
            "next_quaternion_body_to_world",
            next_quaternion_body_to_world,
            expected_dtype="float32",
            expected_shape=(lane_count, 4),
        )
        valid = _own_torch_cpu_array(
            "valid_transition_mask",
            valid_transition_mask,
            expected_dtype="bool",
            expected_shape=(lane_count,),
        )
        if (
            self._raw_force is None
            or self._raw_gyro is None
            or self._delivered_force is None
            or self._delivered_gyro is None
            or self._vio_velocity is None
            or self._vio_quaternion is None
            or self._valid_mask is None
        ):
            raise AssertionError("capture buffers were not initialized")
        self._raw_force[step_index] = raw_force
        self._raw_gyro[step_index] = raw_gyro
        self._delivered_force[step_index] = delivered_force
        self._delivered_gyro[step_index] = delivered_gyro
        self._vio_velocity[step_index + 1] = next_velocity
        self._vio_quaternion[step_index + 1] = next_quaternion
        self._valid_mask[step_index] = valid
        self._next_step += 1

    def finalize(self) -> ExactNativeObserverCapture:
        """Freeze exactly 300 transitions into the canonical artifact model."""

        if self._finalized_capture is not None:
            return self._finalized_capture
        if self._lane_count is None:
            raise CaptureArtifactError("record_initial_vio must be called first")
        if self._next_step != TRANSITION_COUNT:
            raise CaptureArtifactError(
                f"capture is incomplete: {self._next_step}/300 transitions"
            )
        if (
            self._raw_force is None
            or self._raw_gyro is None
            or self._delivered_force is None
            or self._delivered_gyro is None
            or self._vio_velocity is None
            or self._vio_quaternion is None
            or self._valid_mask is None
        ):
            raise AssertionError("capture buffers were not initialized")
        capture = ExactNativeObserverCapture(
            raw_specific_force_body=self._raw_force,
            raw_angular_velocity_body=self._raw_gyro,
            delivered_specific_force_body=self._delivered_force,
            delivered_angular_velocity_body=self._delivered_gyro,
            vio_velocity_world=self._vio_velocity,
            vio_quaternion_body_to_world_wxyz=self._vio_quaternion,
            valid_transition_mask=self._valid_mask,
            transition_index=np.arange(TRANSITION_COUNT, dtype="<i4"),
            lane_index=np.arange(self._lane_count, dtype="<i4"),
            logical_transition_end_time_ns=(
                np.arange(1, BOUNDARY_COUNT, dtype="<i8") * self._dt_nanoseconds
            ),
            dt_seconds=self._dt_seconds,
            frozen_seeds=self._frozen_seeds,
            frozen_transform=self._frozen_transform,
        )
        _validate_capture(capture)
        _freeze_capture_arrays(capture)
        self._finalized_capture = capture
        return capture


def load_exact_native_observer_capture(
    path: str | os.PathLike[str],
    *,
    expected_sha256: str,
) -> ExactNativeObserverCapture:
    """Verify the whole file, then strictly decode a canonical capture."""

    _require_sha256("expected_sha256", expected_sha256)
    archive = _read_unique_regular_file(Path(path))
    actual_sha256 = hashlib.sha256(archive).hexdigest()
    if actual_sha256 != expected_sha256:
        raise CaptureArtifactError(
            "whole-file SHA-256 mismatch before archive parsing: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    capture = _decode_verified_archive(archive)
    _validate_capture(capture)
    _freeze_capture_arrays(capture)
    return capture


def capture_artifact_sha256(path: str | os.PathLike[str]) -> str:
    """Hash one stable, unique regular artifact through a no-follow FD."""

    return hashlib.sha256(_read_unique_regular_file(Path(path))).hexdigest()


def _read_unique_regular_file(source: Path) -> bytes:
    """Bind a pathname to one stable FD and reject links or identity drift."""

    try:
        path_before = os.lstat(source)
    except OSError as error:
        raise CaptureArtifactError(f"cannot lstat capture artifact: {error}") from error
    _validate_unique_regular_status(path_before, phase="before open")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise CaptureArtifactError(
            f"cannot open capture artifact with no-follow semantics: {error}"
        ) from error
    try:
        descriptor_before = os.fstat(descriptor)
        _validate_unique_regular_status(descriptor_before, phase="after open")
        if _full_file_identity(path_before) != _full_file_identity(descriptor_before):
            raise CaptureArtifactError(
                "capture artifact path identity changed between lstat and open"
            )
        payload = _read_all_from_fd(descriptor)
        descriptor_after = os.fstat(descriptor)
        _validate_unique_regular_status(descriptor_after, phase="after read")
        try:
            path_after = os.lstat(source)
        except OSError as error:
            raise CaptureArtifactError(
                f"capture artifact path disappeared during read: {error}"
            ) from error
        _validate_unique_regular_status(path_after, phase="path after read")
        identities = {
            _full_file_identity(path_before),
            _full_file_identity(descriptor_before),
            _full_file_identity(descriptor_after),
            _full_file_identity(path_after),
        }
        if len(identities) != 1:
            raise CaptureArtifactError(
                "capture artifact identity changed during stable FD read"
            )
        if len(payload) != descriptor_after.st_size:
            raise CaptureArtifactError("capture artifact read length does not match fstat size")
        return payload
    finally:
        os.close(descriptor)


def _read_all_from_fd(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_new_sealed_regular_file(destination: Path, payload: bytes) -> None:
    """Create, fsync, and seal one path without any failure-path unlink race."""

    if not destination.name or destination.name in {".", ".."}:
        raise CaptureArtifactError("capture artifact destination must name a file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        parent_path_before = os.lstat(destination.parent)
    except OSError as error:
        raise CaptureArtifactError(f"cannot lstat artifact parent directory: {error}") from error
    _validate_directory_status(parent_path_before, phase="before open")
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        parent_descriptor = os.open(destination.parent, parent_flags)
    except OSError as error:
        raise CaptureArtifactError(
            f"cannot open artifact parent directory with no-follow semantics: {error}"
        ) from error
    file_descriptor: int | None = None
    created_binding: tuple[int, int] | None = None
    sealed_identity: tuple[int, ...] | None = None
    succeeded = False
    try:
        parent_descriptor_before = os.fstat(parent_descriptor)
        _validate_directory_status(parent_descriptor_before, phase="after open")
        if _binding_identity(parent_path_before) != _binding_identity(
            parent_descriptor_before
        ):
            raise CaptureArtifactError(
                "artifact parent directory identity changed during open"
            )
        try:
            os.stat(
                destination.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except OSError as error:
            raise CaptureArtifactError(
                f"cannot inspect artifact destination: {error}"
            ) from error
        else:
            raise FileExistsError(
                f"capture artifact target already exists: {destination}"
            )
        file_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_descriptor = os.open(
            destination.name,
            file_flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        created_status = os.fstat(file_descriptor)
        _validate_unique_regular_status(created_status, phase="new file")
        created_binding = (created_status.st_dev, created_status.st_ino)
        _write_all_to_fd(file_descriptor, payload)
        os.fchmod(file_descriptor, 0o444)
        os.fsync(file_descriptor)
        final_descriptor_status = os.fstat(file_descriptor)
        _validate_unique_regular_status(final_descriptor_status, phase="sealed file")
        if final_descriptor_status.st_size != len(payload):
            raise CaptureArtifactError("sealed artifact size does not match payload")
        if (final_descriptor_status.st_dev, final_descriptor_status.st_ino) != (
            created_binding
        ):
            raise CaptureArtifactError("sealed artifact FD identity changed")
        path_via_parent = os.stat(
            destination.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _validate_unique_regular_status(path_via_parent, phase="sealed path")
        if _full_file_identity(path_via_parent) != _full_file_identity(
            final_descriptor_status
        ):
            raise CaptureArtifactError("sealed path does not reference the created FD")
        parent_descriptor_after = os.fstat(parent_descriptor)
        _validate_directory_status(parent_descriptor_after, phase="after create")
        try:
            parent_path_after = os.lstat(destination.parent)
            destination_path_after = os.lstat(destination)
        except OSError as error:
            raise CaptureArtifactError(
                f"artifact path disappeared during seal: {error}"
            ) from error
        _validate_directory_status(parent_path_after, phase="path after create")
        _validate_unique_regular_status(destination_path_after, phase="path after seal")
        if (
            _binding_identity(parent_descriptor_before)
            != _binding_identity(parent_descriptor_after)
            or _binding_identity(parent_descriptor_after)
            != _binding_identity(parent_path_after)
        ):
            raise CaptureArtifactError(
                "artifact parent directory identity changed during seal"
            )
        if _full_file_identity(destination_path_after) != _full_file_identity(
            final_descriptor_status
        ):
            raise CaptureArtifactError(
                "artifact destination path identity changed during seal"
            )
        sealed_identity = _full_file_identity(final_descriptor_status)
        os.fsync(parent_descriptor)
        succeeded = True
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(parent_descriptor)
    try:
        final_path_status = os.lstat(destination)
    except OSError as error:
        raise CaptureArtifactError(
            f"sealed artifact path disappeared after close: {error}"
        ) from error
    _validate_unique_regular_status(final_path_status, phase="final path")
    if (
        not succeeded
        or created_binding is None
        or sealed_identity is None
        or _full_file_identity(final_path_status) != sealed_identity
    ):
        raise CaptureArtifactError("sealed artifact final path identity changed")


def _write_all_to_fd(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise CaptureArtifactError("short write while sealing capture artifact")
        offset += written


def _validate_unique_regular_status(status_result: os.stat_result, *, phase: str) -> None:
    if stat.S_ISLNK(status_result.st_mode):
        raise CaptureArtifactError(f"capture artifact must not be a symlink ({phase})")
    if not stat.S_ISREG(status_result.st_mode):
        raise CaptureArtifactError(f"capture artifact must be a regular file ({phase})")
    if status_result.st_nlink != 1:
        raise CaptureArtifactError(
            f"capture artifact link count must be exactly one ({phase})"
        )


def _validate_directory_status(status_result: os.stat_result, *, phase: str) -> None:
    if stat.S_ISLNK(status_result.st_mode):
        raise CaptureArtifactError(
            f"artifact parent directory must not be a symlink ({phase})"
        )
    if not stat.S_ISDIR(status_result.st_mode):
        raise CaptureArtifactError(
            f"artifact parent path must be a directory ({phase})"
        )


def _full_file_identity(status_result: os.stat_result) -> tuple[int, ...]:
    return (
        status_result.st_dev,
        status_result.st_ino,
        status_result.st_mode,
        status_result.st_nlink,
        status_result.st_size,
        status_result.st_mtime_ns,
    )


def _binding_identity(status_result: os.stat_result) -> tuple[int, int, int]:
    return (
        status_result.st_dev,
        status_result.st_ino,
        status_result.st_mode,
    )


def _canonical_archive_bytes(capture: ExactNativeObserverCapture) -> bytes:
    arrays = _capture_arrays(capture)
    manifest = _build_manifest(capture, arrays)
    manifest_payload = _canonical_json_bytes(manifest)
    members = {name: _array_payload(array) for name, array in arrays.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        _write_canonical_member(archive, _MANIFEST_MEMBER, manifest_payload)
        for name in _ARRAY_SPECS:
            _write_canonical_member(archive, f"arrays/{name}.bin", members[name])
    return output.getvalue()


def _write_canonical_member(
    archive: zipfile.ZipFile,
    member_name: str,
    payload: bytes,
) -> None:
    info = zipfile.ZipInfo(member_name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = _ZIP_EXTERNAL_ATTR
    info.flag_bits = 0
    info.extra = b""
    info.comment = b""
    archive.writestr(info, payload)


def _decode_verified_archive(archive_bytes: bytes) -> ExactNativeObserverCapture:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            _validate_zip_members(infos, names)
            manifest_payload = archive.read(_MANIFEST_MEMBER)
            manifest = _decode_manifest(manifest_payload)
            lane_count = _manifest_lane_count(manifest)
            arrays: dict[str, np.ndarray[Any, Any]] = {}
            for name, (dtype, symbolic_shape) in _ARRAY_SPECS.items():
                shape = _resolve_shape(symbolic_shape, lane_count)
                payload = archive.read(f"arrays/{name}.bin")
                arrays[name] = _decode_array_payload(name, payload, dtype, shape)
    except CaptureArtifactError:
        raise
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        raise CaptureArtifactError(f"invalid capture ZIP: {error}") from error
    _validate_manifest_against_arrays(manifest, arrays, lane_count)
    time_metadata = _require_exact_mapping(
        "time", manifest["time"], _TIME_METADATA_KEYS
    )
    dt_seconds = struct.unpack(
        "<d", bytes.fromhex(_require_hex_bytes("dt_seconds_float64_le_hex", time_metadata))
    )[0]
    transform_payload = _require_exact_mapping(
        "frozen_transform",
        manifest["frozen_transform"],
        _TRANSFORM_METADATA_KEYS,
    )
    transform = FrozenSensorTransformMetadata(
        name=_require_manifest_text("frozen_transform.name", transform_payload["name"]),
        enabled=_require_manifest_bool(
            "frozen_transform.enabled", transform_payload["enabled"]
        ),
        implementation_sha256=_require_manifest_text(
            "frozen_transform.implementation_sha256",
            transform_payload["implementation_sha256"],
        ),
        config_sha256=_require_manifest_text(
            "frozen_transform.config_sha256", transform_payload["config_sha256"]
        ),
        error_bank_schema_version=_require_manifest_text(
            "frozen_transform.error_bank_schema_version",
            transform_payload["error_bank_schema_version"],
        ),
        error_bank_sha256=_require_manifest_text(
            "frozen_transform.error_bank_sha256",
            transform_payload["error_bank_sha256"],
        ),
    )
    seeds_payload = manifest["frozen_seeds"]
    if not isinstance(seeds_payload, dict):
        raise CaptureArtifactError("frozen_seeds must be a JSON object")
    seeds = _canonical_frozen_seeds(seeds_payload)
    capture = ExactNativeObserverCapture(
        raw_specific_force_body=arrays["raw_specific_force_body"],
        raw_angular_velocity_body=arrays["raw_angular_velocity_body"],
        delivered_specific_force_body=arrays["delivered_specific_force_body"],
        delivered_angular_velocity_body=arrays["delivered_angular_velocity_body"],
        vio_velocity_world=arrays["vio_velocity_world"],
        vio_quaternion_body_to_world_wxyz=arrays[
            "vio_quaternion_body_to_world_wxyz"
        ],
        valid_transition_mask=arrays["valid_transition_mask"].astype(
            np.bool_, copy=True
        ),
        transition_index=arrays["transition_index"],
        lane_index=arrays["lane_index"],
        logical_transition_end_time_ns=arrays[
            "logical_transition_end_time_ns"
        ],
        dt_seconds=dt_seconds,
        frozen_seeds=seeds,
        frozen_transform=transform,
    )
    return capture


def _validate_zip_members(
    infos: list[zipfile.ZipInfo],
    names: list[str],
) -> None:
    if len(names) != len(set(names)):
        raise CaptureArtifactError("duplicate ZIP members are forbidden")
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (
            not name
            or name.startswith("/")
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in name
        ):
            raise CaptureArtifactError(f"unsafe ZIP member path: {name!r}")
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK:
            raise CaptureArtifactError(f"symlink ZIP member is forbidden: {name}")
        if info.compress_type != zipfile.ZIP_STORED:
            raise CaptureArtifactError("capture ZIP members must use stored compression")
        if info.flag_bits & 0x1:
            raise CaptureArtifactError("encrypted capture ZIP members are forbidden")
        if (
            info.date_time != _ZIP_TIMESTAMP
            or info.create_system != 3
            or info.external_attr != _ZIP_EXTERNAL_ATTR
            or info.extra != b""
            or info.comment != b""
        ):
            raise CaptureArtifactError(f"noncanonical ZIP metadata for member: {name}")
    if tuple(names) != _ARCHIVE_MEMBER_ORDER:
        missing = sorted(set(_ARCHIVE_MEMBER_ORDER) - set(names))
        extra = sorted(set(names) - set(_ARCHIVE_MEMBER_ORDER))
        raise CaptureArtifactError(
            "capture ZIP member set/order mismatch: "
            f"missing={missing}, extra={extra}, order={names}"
        )


def _decode_manifest(payload: bytes) -> dict[str, object]:
    try:
        text = payload.decode("utf-8")
        decoded = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureArtifactError(f"manifest is not canonical UTF-8 JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise CaptureArtifactError("manifest root must be a JSON object")
    if set(decoded) != _TOP_LEVEL_MANIFEST_KEYS:
        raise CaptureArtifactError("manifest has missing or extra top-level fields")
    if _canonical_json_bytes(decoded) != payload:
        raise CaptureArtifactError("manifest JSON encoding is not canonical")
    return decoded


def _manifest_lane_count(manifest: dict[str, object]) -> int:
    lane_count = manifest["lane_count"]
    if (
        type(lane_count) is not int
        or lane_count <= 0
        or lane_count > np.iinfo(np.int32).max
    ):
        raise CaptureArtifactError("manifest lane_count must be a positive int32")
    return lane_count


def _validate_manifest_against_arrays(
    manifest: dict[str, object],
    arrays: dict[str, np.ndarray[Any, Any]],
    lane_count: int,
) -> None:
    if manifest["schema_version"] != CAPTURE_SCHEMA_VERSION:
        raise CaptureArtifactError("unsupported capture schema_version")
    if manifest["transition_count"] != TRANSITION_COUNT:
        raise CaptureArtifactError("manifest transition_count mismatch")
    if manifest["boundary_count"] != BOUNDARY_COUNT:
        raise CaptureArtifactError("manifest boundary_count mismatch")
    if manifest["observer_input_track"] != OBSERVER_INPUT_TRACK_NAME:
        raise CaptureArtifactError("observer input track must be estimator-delivered profiled")
    if manifest["track_purposes"] != {
        RAW_TRACK_NAME: RAW_TRACK_PURPOSE,
        DELIVERED_TRACK_NAME: DELIVERED_TRACK_PURPOSE,
    }:
        raise CaptureArtifactError("track purpose declaration mismatch")
    if manifest["archive_member_order"] != list(_ARCHIVE_MEMBER_ORDER):
        raise CaptureArtifactError("manifest archive member order mismatch")
    time_metadata = _require_exact_mapping(
        "time", manifest["time"], _TIME_METADATA_KEYS
    )
    if time_metadata["source"] != TIME_SOURCE:
        raise CaptureArtifactError("logical time source declaration mismatch")
    if time_metadata["sensor_origin_timestamp_available"] is not False:
        raise CaptureArtifactError("artifact must not claim a sensor-origin timestamp")
    dt_hex = _require_hex_bytes("dt_seconds_float64_le_hex", time_metadata)
    if len(dt_hex) != 16:
        raise CaptureArtifactError("dt_seconds_float64_le_hex must encode float64")
    dt_seconds = struct.unpack("<d", bytes.fromhex(dt_hex))[0]
    validated_dt, dt_nanoseconds = _validate_exact_dt(dt_seconds)
    if time_metadata["dt_nanoseconds"] != dt_nanoseconds:
        raise CaptureArtifactError("manifest dt_nanoseconds mismatch")
    if struct.pack("<d", validated_dt).hex() != dt_hex:
        raise CaptureArtifactError("manifest dt float64 encoding mismatch")
    seed_fingerprint = _sha256_bytes(
        _canonical_json_bytes(manifest["frozen_seeds"])
    )
    if manifest["frozen_seed_identity_sha256"] != seed_fingerprint:
        raise CaptureArtifactError("frozen seed identity digest mismatch")
    arrays_metadata = _require_exact_mapping(
        "arrays", manifest["arrays"], set(_ARRAY_SPECS)
    )
    for name, (dtype, symbolic_shape) in _ARRAY_SPECS.items():
        expected_shape = _resolve_shape(symbolic_shape, lane_count)
        metadata = _require_exact_mapping(
            f"arrays.{name}", arrays_metadata[name], _ARRAY_METADATA_KEYS
        )
        if metadata["dtype"] != dtype:
            raise CaptureArtifactError(f"manifest dtype mismatch for {name}")
        if metadata["shape"] != list(expected_shape):
            raise CaptureArtifactError(f"manifest shape mismatch for {name}")
        array = arrays[name]
        if array.shape != expected_shape or array.dtype != np.dtype(dtype):
            raise CaptureArtifactError(f"decoded dtype/shape mismatch for {name}")
        if metadata["sha256"] != _array_sha256(name, array):
            raise CaptureArtifactError(f"array digest mismatch for {name}")
        expected_lane_digests = _array_lane_sha256(name, array, lane_count)
        if metadata["lane_sha256"] != expected_lane_digests:
            raise CaptureArtifactError(f"array lane digest mismatch for {name}")
    expected_track_sha, expected_track_lane_sha = _track_digests(arrays, lane_count)
    if manifest["track_sha256"] != expected_track_sha:
        raise CaptureArtifactError("raw/delivered track array digest mismatch")
    if manifest["track_lane_sha256"] != expected_track_lane_sha:
        raise CaptureArtifactError("raw/delivered track lane digest mismatch")
    expected_transition = np.arange(TRANSITION_COUNT, dtype="<i4")
    if not np.array_equal(arrays["transition_index"], expected_transition):
        raise CaptureArtifactError("transition identity array was tampered")
    expected_lanes = np.arange(lane_count, dtype="<i4")
    if not np.array_equal(arrays["lane_index"], expected_lanes):
        raise CaptureArtifactError("lane identity array was tampered")
    expected_time = np.arange(1, BOUNDARY_COUNT, dtype="<i8") * dt_nanoseconds
    if not np.array_equal(arrays["logical_transition_end_time_ns"], expected_time):
        raise CaptureArtifactError("logical transition-end grid was tampered")
    mask = arrays["valid_transition_mask"]
    if np.any((mask != 0) & (mask != 1)):
        raise CaptureArtifactError("valid_transition_mask contains non-binary bytes")


def _build_manifest(
    capture: ExactNativeObserverCapture,
    arrays: dict[str, np.ndarray[Any, Any]],
) -> dict[str, object]:
    lane_count = capture.lane_count
    _, dt_nanoseconds = _validate_exact_dt(capture.dt_seconds)
    arrays_metadata: dict[str, object] = {}
    for name, (dtype, symbolic_shape) in _ARRAY_SPECS.items():
        array = arrays[name]
        arrays_metadata[name] = {
            "dtype": dtype,
            "shape": list(_resolve_shape(symbolic_shape, lane_count)),
            "sha256": _array_sha256(name, array),
            "lane_sha256": _array_lane_sha256(name, array, lane_count),
        }
    seeds = dict(capture.frozen_seeds)
    track_sha256, track_lane_sha256 = _track_digests(arrays, lane_count)
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "lane_count": lane_count,
        "transition_count": TRANSITION_COUNT,
        "boundary_count": BOUNDARY_COUNT,
        "observer_input_track": OBSERVER_INPUT_TRACK_NAME,
        "track_purposes": {
            RAW_TRACK_NAME: RAW_TRACK_PURPOSE,
            DELIVERED_TRACK_NAME: DELIVERED_TRACK_PURPOSE,
        },
        "time": {
            "source": TIME_SOURCE,
            "sensor_origin_timestamp_available": SENSOR_ORIGIN_TIMESTAMP_AVAILABLE,
            "dt_seconds_float64_le_hex": struct.pack("<d", capture.dt_seconds).hex(),
            "dt_nanoseconds": dt_nanoseconds,
        },
        "frozen_seeds": seeds,
        "frozen_seed_identity_sha256": _sha256_bytes(_canonical_json_bytes(seeds)),
        "frozen_transform": capture.frozen_transform.as_canonical_dict(),
        "arrays": arrays_metadata,
        "track_sha256": track_sha256,
        "track_lane_sha256": track_lane_sha256,
        "archive_member_order": list(_ARCHIVE_MEMBER_ORDER),
    }


def _capture_arrays(
    capture: ExactNativeObserverCapture,
) -> dict[str, np.ndarray[Any, Any]]:
    return {
        "transition_index": capture.transition_index,
        "lane_index": capture.lane_index,
        "logical_transition_end_time_ns": capture.logical_transition_end_time_ns,
        "valid_transition_mask": capture.valid_transition_mask.view(np.uint8),
        "raw_specific_force_body": capture.raw_specific_force_body,
        "raw_angular_velocity_body": capture.raw_angular_velocity_body,
        "delivered_specific_force_body": capture.delivered_specific_force_body,
        "delivered_angular_velocity_body": capture.delivered_angular_velocity_body,
        "vio_velocity_world": capture.vio_velocity_world,
        "vio_quaternion_body_to_world_wxyz": (
            capture.vio_quaternion_body_to_world_wxyz
        ),
    }


def _validate_capture(capture: ExactNativeObserverCapture) -> None:
    if not isinstance(capture, ExactNativeObserverCapture):
        raise TypeError("capture must be ExactNativeObserverCapture")
    if not isinstance(capture.frozen_transform, FrozenSensorTransformMetadata):
        raise TypeError("frozen_transform must be FrozenSensorTransformMetadata")
    lane_count = capture.lane_count
    if lane_count <= 0:
        raise CaptureArtifactError("capture must contain at least one lane")
    arrays = _capture_arrays(capture)
    for name, (dtype, symbolic_shape) in _ARRAY_SPECS.items():
        array = arrays[name]
        expected_shape = _resolve_shape(symbolic_shape, lane_count)
        if not isinstance(array, np.ndarray):
            raise TypeError(f"{name} must be a numpy array")
        if array.dtype != np.dtype(dtype):
            raise CaptureArtifactError(
                f"{name} must have exact canonical dtype {np.dtype(dtype).str}"
            )
        if array.shape != expected_shape:
            raise CaptureArtifactError(f"{name} must have shape {expected_shape}")
        if not array.flags.c_contiguous:
            raise CaptureArtifactError(f"{name} must be C-contiguous")
    expected_transition = np.arange(TRANSITION_COUNT, dtype="<i4")
    if not np.array_equal(capture.transition_index, expected_transition):
        raise CaptureArtifactError("transition_index must be exact range(300)")
    expected_lanes = np.arange(lane_count, dtype="<i4")
    if not np.array_equal(capture.lane_index, expected_lanes):
        raise CaptureArtifactError("lane_index must be exact range(B)")
    dt_seconds, dt_nanoseconds = _validate_exact_dt(capture.dt_seconds)
    expected_time = np.arange(1, BOUNDARY_COUNT, dtype="<i8") * dt_nanoseconds
    if not np.array_equal(capture.logical_transition_end_time_ns, expected_time):
        raise CaptureArtifactError("logical transition-end grid does not match dt")
    if dt_seconds != capture.dt_seconds:
        raise CaptureArtifactError("dt_seconds is not canonical")
    _canonical_frozen_seeds(dict(capture.frozen_seeds))
    if capture.valid_transition_mask.dtype != np.bool_:
        raise CaptureArtifactError("valid_transition_mask must have exact bool dtype")


def _freeze_capture_arrays(capture: ExactNativeObserverCapture) -> None:
    for value in vars(capture).values():
        if not isinstance(value, np.ndarray):
            continue
        array = value
        array.flags.writeable = False


def _own_torch_cpu_array(
    name: str,
    value: object,
    *,
    expected_dtype: str,
    expected_shape: tuple[int, ...] | None = None,
) -> np.ndarray[Any, Any]:
    try:
        import torch
    except ImportError as error:
        raise CaptureArtifactError("Torch is required at the capture boundary") from error
    if not isinstance(value, torch.Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    expected_torch_dtype = torch.float32 if expected_dtype == "float32" else torch.bool
    if value.dtype != expected_torch_dtype:
        raise CaptureArtifactError(f"{name} must have exact torch.{expected_dtype} dtype")
    if expected_shape is not None and tuple(value.shape) != expected_shape:
        raise CaptureArtifactError(f"{name} must have shape {expected_shape}")
    owned = value.detach().contiguous().clone().cpu()
    array = np.array(owned.numpy(), copy=True, order="C")
    if expected_shape is not None and array.shape != expected_shape:
        raise CaptureArtifactError(f"{name} changed shape across the CPU boundary")
    return array


def _little_endian_owned(
    value: np.ndarray[Any, Any],
    dtype: str,
) -> np.ndarray[Any, Any]:
    return np.array(value, dtype=np.dtype(dtype), copy=True, order="C")


def _canonical_frozen_seeds(
    frozen_seeds: Mapping[str, int],
) -> tuple[tuple[str, int], ...]:
    if not isinstance(frozen_seeds, Mapping) or not frozen_seeds:
        raise CaptureArtifactError("frozen_seeds must be a non-empty mapping")
    normalized: list[tuple[str, int]] = []
    for key, value in frozen_seeds.items():
        _require_nonempty_text("frozen seed key", key)
        if "/" in key or "\\" in key or any(ord(character) < 0x20 for character in key):
            raise CaptureArtifactError("frozen seed keys must be safe printable identifiers")
        if (
            type(value) is not int
            or value < np.iinfo(np.int64).min
            or value > np.iinfo(np.int64).max
        ):
            raise CaptureArtifactError("frozen seed values must be signed int64")
        normalized.append((key, value))
    normalized.sort()
    if len({key for key, _ in normalized}) != len(normalized):
        raise CaptureArtifactError("duplicate frozen seed keys are forbidden")
    return tuple(normalized)


def _validate_exact_dt(dt_seconds: float) -> tuple[float, int]:
    if (
        type(dt_seconds) is bool
        or not isinstance(dt_seconds, (int, float))
        or not np.isfinite(float(dt_seconds))
        or float(dt_seconds) <= 0.0
    ):
        raise CaptureArtifactError("dt_seconds must be finite and positive")
    dt_value = float(dt_seconds)
    scaled = dt_value * 1_000_000_000.0
    dt_nanoseconds = round(scaled)
    if (
        dt_nanoseconds <= 0
        or dt_nanoseconds > np.iinfo(np.int64).max // TRANSITION_COUNT
        or float(dt_nanoseconds) / 1_000_000_000.0 != dt_value
    ):
        raise CaptureArtifactError(
            "dt_seconds must be exactly representable on the int64 nanosecond grid"
        )
    return dt_value, dt_nanoseconds


def _resolve_shape(
    symbolic_shape: tuple[str | int, ...],
    lane_count: int,
) -> tuple[int, ...]:
    resolved: list[int] = []
    for extent in symbolic_shape:
        if extent == "transition":
            resolved.append(TRANSITION_COUNT)
        elif extent == "boundary":
            resolved.append(BOUNDARY_COUNT)
        elif extent == "lane":
            resolved.append(lane_count)
        elif isinstance(extent, int):
            resolved.append(extent)
        else:
            raise AssertionError(f"unknown symbolic shape extent: {extent!r}")
    return tuple(resolved)


def _array_payload(array: np.ndarray[Any, Any]) -> bytes:
    return array.tobytes(order="C")


def _decode_array_payload(
    name: str,
    payload: bytes,
    dtype: str,
    shape: tuple[int, ...],
) -> np.ndarray[Any, Any]:
    expected_size = int(np.prod(shape, dtype=np.int64)) * np.dtype(dtype).itemsize
    if len(payload) != expected_size:
        raise CaptureArtifactError(
            f"array payload size mismatch for {name}: expected {expected_size}, got {len(payload)}"
        )
    return np.frombuffer(payload, dtype=np.dtype(dtype)).copy().reshape(shape)


def _array_sha256(name: str, array: np.ndarray[Any, Any]) -> str:
    digest = hashlib.sha256()
    _update_framed(digest, b"flightguard.capture.array.v1")
    _update_framed(digest, name.encode("ascii"))
    _update_framed(digest, array.dtype.str.encode("ascii"))
    _update_framed(digest, _shape_bytes(array.shape))
    _update_framed(digest, _array_payload(array))
    return digest.hexdigest()


def _array_lane_sha256(
    name: str,
    array: np.ndarray[Any, Any],
    lane_count: int,
) -> list[str]:
    if "lane" not in _ARRAY_SPECS[name][1]:
        return []
    lane_axis = _ARRAY_SPECS[name][1].index("lane")
    digests: list[str] = []
    for lane_index in range(lane_count):
        lane = np.ascontiguousarray(np.take(array, lane_index, axis=lane_axis))
        digest = hashlib.sha256()
        _update_framed(digest, b"flightguard.capture.array_lane.v1")
        _update_framed(digest, name.encode("ascii"))
        _update_framed(digest, struct.pack("<q", lane_index))
        _update_framed(digest, array.dtype.str.encode("ascii"))
        _update_framed(digest, _shape_bytes(lane.shape))
        _update_framed(digest, _array_payload(lane))
        digests.append(digest.hexdigest())
    return digests


def _track_digests(
    arrays: dict[str, np.ndarray[Any, Any]],
    lane_count: int,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    track_fields = {
        RAW_TRACK_NAME: (
            "raw_specific_force_body",
            "raw_angular_velocity_body",
        ),
        DELIVERED_TRACK_NAME: (
            "delivered_specific_force_body",
            "delivered_angular_velocity_body",
        ),
    }
    full: dict[str, str] = {}
    lanes: dict[str, list[str]] = {}
    for track_name, fields in track_fields.items():
        digest = hashlib.sha256()
        _update_framed(digest, b"flightguard.capture.track.v1")
        _update_framed(digest, track_name.encode("ascii"))
        for field in fields:
            _update_framed(digest, field.encode("ascii"))
            _update_framed(digest, _array_payload(arrays[field]))
        full[track_name] = digest.hexdigest()
        track_lane_digests: list[str] = []
        for lane_index in range(lane_count):
            lane_digest = hashlib.sha256()
            _update_framed(lane_digest, b"flightguard.capture.track_lane.v1")
            _update_framed(lane_digest, track_name.encode("ascii"))
            _update_framed(lane_digest, struct.pack("<q", lane_index))
            for field in fields:
                lane = np.ascontiguousarray(arrays[field][:, lane_index, :])
                _update_framed(lane_digest, field.encode("ascii"))
                _update_framed(lane_digest, _array_payload(lane))
            track_lane_digests.append(lane_digest.hexdigest())
        lanes[track_name] = track_lane_digests
    return full, lanes


def _shape_bytes(shape: tuple[int, ...]) -> bytes:
    return b"".join(struct.pack("<q", int(extent)) for extent in shape)


def _update_framed(digest: Any, payload: bytes) -> None:
    digest.update(struct.pack("<Q", len(payload)))
    digest.update(payload)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise CaptureArtifactError(f"value is not canonical JSON: {error}") from error


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CaptureArtifactError(f"{name} must be lowercase SHA-256 hex")


def _require_nonempty_text(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CaptureArtifactError(f"{name} must be non-empty printable text")


def _require_exact_mapping(
    name: str,
    value: object,
    expected_keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise CaptureArtifactError(f"{name} has missing or extra fields")
    return value


def _require_manifest_text(name: str, value: object) -> str:
    _require_nonempty_text(name, value)
    assert isinstance(value, str)
    return value


def _require_manifest_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise CaptureArtifactError(f"{name} must be exact bool")
    return value


def _require_hex_bytes(name: str, mapping: dict[str, object]) -> str:
    value = mapping[name]
    if (
        not isinstance(value, str)
        or len(value) % 2
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CaptureArtifactError(f"{name} must be lowercase hexadecimal bytes")
    return value
