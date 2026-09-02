"""Development-only frozen VIO/IMU observer calibration.

The only fitted state is

``theta = [b_a(3), b_g(3), delta_roll, delta_pitch]``.

For transition ``t``, the exact estimator-delivered, profiled IMU measurements
are related to the visible VIO increments by

``R_delta @ (f_t - b_a) = R(q_{t+1})^T @ (Delta v_t / dt - g)``

and

``R_delta @ (omega_t - b_g) = Log(q_t^-1 * q_{t+1}) / dt``.

``R_delta = R_x(delta_roll) @ R_y(delta_pitch)`` maps native IMU body vectors
into the VIO body convention.  In particular, the gyro reference is always a
VIO quaternion increment; this API does not accept visible angular velocity.

The split is fixed: transitions 0--199 fit, 200--299 qualify without updates,
and the result freezes at boundary 300.  This module deliberately contains no
post-dropout update path.  It is a CPU-testable development component, not a
sim-to-real or flight-safety claim.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, fields
from os import PathLike
from typing import Any, TypeVar

import numpy as np
import numpy.typing as npt

from flightguard.exact_native_observer_capture import (
    load_exact_native_observer_capture,
)

FIT_START = 0
FIT_STOP = 200
HOLDOUT_START = 200
HOLDOUT_STOP = 300
FREEZE_STEP = 300
STATE_DIMENSION = 8
STATE_ORDER = (
    "accelerometer_bias_x_mps2",
    "accelerometer_bias_y_mps2",
    "accelerometer_bias_z_mps2",
    "gyroscope_bias_x_rad_s",
    "gyroscope_bias_y_rad_s",
    "gyroscope_bias_z_rad_s",
    "delta_roll_rad",
    "delta_pitch_rad",
)
PROVENANCE_SCHEMA_VERSION = "flightguard.frozen_vio_imu_observer.inputs.v3"
BASELINE_PROVENANCE_SCHEMA_VERSION = "flightguard.frozen_vio_imu_observer.baselines.v2"
EXACT_RAW_NATIVE_SPECIFIC_FORCE_SOURCE = "exact_raw_native.NativeIMUSample.specific_force_body"
EXACT_RAW_NATIVE_ANGULAR_VELOCITY_SOURCE = "exact_raw_native.NativeIMUSample.angular_velocity_body"
EXACT_ESTIMATOR_DELIVERED_PROFILED_SPECIFIC_FORCE_SOURCE = (
    "exact_estimator_delivered_profiled.NativeIMUSample.specific_force_body"
)
EXACT_ESTIMATOR_DELIVERED_PROFILED_ANGULAR_VELOCITY_SOURCE = (
    "exact_estimator_delivered_profiled.NativeIMUSample.angular_velocity_body"
)
# Compatibility import names now explicitly denote the delivered/profiled
# stream.  The legacy unqualified NativeIMUSample strings remain rejected.
RECORD_TIME_SPECIFIC_FORCE_SOURCE = EXACT_ESTIMATOR_DELIVERED_PROFILED_SPECIFIC_FORCE_SOURCE
RECORD_TIME_ANGULAR_VELOCITY_SOURCE = EXACT_ESTIMATOR_DELIVERED_PROFILED_ANGULAR_VELOCITY_SOURCE
LEGACY_UNQUALIFIED_NATIVE_SPECIFIC_FORCE_SOURCE = "NativeIMUSample.specific_force_body"
LEGACY_UNQUALIFIED_NATIVE_ANGULAR_VELOCITY_SOURCE = "NativeIMUSample.angular_velocity_body"
RECORD_TIME_VIO_VELOCITY_SOURCE = "record_time_vio.velocity_world"
RECORD_TIME_VIO_QUATERNION_SOURCE = "record_time_vio.quaternion_body_to_world_wxyz"
RECONSTRUCTED_SPECIFIC_FORCE_PROXY_SOURCE = "reconstructed_specific_force_proxy"
FROZEN_SENSOR_ERROR_BANK_SOURCE = "preregistered_frozen_sensor_error_bank[transition_t]"
FROZEN_APPLY_SENSOR_ERROR_SOURCE = "apply_sensor_error:frozen_source"
FROZEN_SENSOR_PROFILE_SOURCE = "FORMAL_REALISTIC_SENSOR_PROFILE:frozen"
EXACT_PROFILED_INPUT_BINDING = "exact_estimator_delivered_profiled_capture_binding"
LEGACY_UNBOUND_NATIVE_INPUT_BINDING = "legacy_unbound_native_imu"
RECONSTRUCTED_PROXY_INPUT_BINDING = "reconstructed_force_proxy_diagnostic"
ESTIMATOR_DELIVERED_PROFILED_CAUSAL_DECLARATION = (
    "For transition t, exact_estimator_delivered_profiled[t] is derived at "
    "record time only from exact_raw_native[t], the preregistered frozen sensor "
    "error bank[t], and the frozen sensor profile through the frozen "
    "apply_sensor_error source; it consumes no future observation, truth, "
    "action, or domain parameter."
)
FIT_ONLY_CALIBRATION_SOURCE = (
    "calibrate_visible_accelerometer_bias:exact_estimator_delivered_profiled_imu_vio:window[0,200)"
)
OPERATIONAL_CALIBRATION_SOURCE = (
    "calibrate_visible_accelerometer_bias:exact_estimator_delivered_profiled_imu_vio:window[0,300)"
)
VALID_TRANSITION_MASK_SOURCE = "exact_estimator_delivered_profiled_imu_vio.valid_transition_mask"
EXACT_CAL_FALLBACK_DECLARATION = (
    "On any reject or disabled lane, dispatch directly to the existing "
    "CalibratedStrapdown arm before observer arithmetic. The calibrated output "
    "object is returned unchanged; b_g and delta_roll/pitch are not applied."
)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
T = TypeVar("T")
_STRICTLY_LOADED_PROVENANCE: dict[int, tuple[object, str]] = {}
_STRICTLY_LOADED_BASELINE_PROVENANCE: dict[int, tuple[object, str, str]] = {}


@dataclass(frozen=True)
class FrozenObserverInputProvenance:
    """Exact source declaration for all calibration observations."""

    schema_version: str
    binding_kind: str
    exact_raw_native_specific_force_body_source: str
    exact_raw_native_angular_velocity_body_source: str
    specific_force_body_source: str
    angular_velocity_body_source: str
    vio_velocity_world_source: str
    vio_quaternion_body_to_world_source: str
    frozen_sensor_error_bank_source: str
    frozen_apply_sensor_error_source: str
    frozen_sensor_profile_source: str
    delivered_sample_causal_declaration: str
    native_imu_was_cloned_at_record_time: bool
    estimator_delivered_profiled_imu_was_captured_at_record_time: bool
    vio_was_captured_at_record_time: bool
    sensor_error_bank_was_preregistered_and_frozen: bool
    apply_sensor_error_source_was_frozen: bool
    sensor_profile_was_frozen: bool
    specific_force_is_reconstructed_proxy: bool
    exact_raw_native_specific_force_sha256: str
    exact_raw_native_angular_velocity_sha256: str
    estimator_delivered_profiled_specific_force_sha256: str
    estimator_delivered_profiled_angular_velocity_sha256: str
    vio_velocity_world_sha256: str
    vio_quaternion_body_to_world_sha256: str
    valid_transition_mask_sha256: str
    dt_seconds_float64_le_hex: str
    dt_seconds_float64_le_sha256: str
    frozen_sensor_error_bank_sha256: str
    apply_sensor_error_source_sha256: str
    frozen_sensor_profile_sha256: str
    capture_artifact_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "native_imu_was_cloned_at_record_time",
            "estimator_delivered_profiled_imu_was_captured_at_record_time",
            "vio_was_captured_at_record_time",
            "sensor_error_bank_was_preregistered_and_frozen",
            "apply_sensor_error_source_was_frozen",
            "sensor_profile_was_frozen",
            "specific_force_is_reconstructed_proxy",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be exact bool")

    def as_canonical_record(self) -> dict[str, bool | str]:
        """Return the exact JSON-safe record embedded in a sealed artifact."""

        record: dict[str, bool | str] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is bool or type(value) is str:
                record[field.name] = value
            else:
                raise TypeError(f"provenance field {field.name} must be exact bool or str")
        return record

    @classmethod
    def record_time_native_imu(
        cls,
        *,
        capture_artifact_path: str | PathLike[str],
        expected_sha256: str,
    ) -> FrozenObserverInputProvenance:
        """Compatibility name with the same strict artifact-only signature."""

        return cls.bind_exact_estimator_delivered_profiled_imu(
            capture_artifact_path=capture_artifact_path,
            expected_sha256=expected_sha256,
        )

    @classmethod
    def bind_exact_estimator_delivered_profiled_imu(
        cls,
        *,
        capture_artifact_path: str | PathLike[str],
        expected_sha256: str,
    ) -> FrozenObserverInputProvenance:
        """Strict-load one sealed capture and author every observer input.

        The returned record is intentionally not runtime-eligible.  A sealed
        artifact loader must persist :meth:`as_canonical_record` and later use
        :meth:`load_sealed_record` to recover a loader-bound identity.
        Caller-provided arrays and caller-invented dependency hashes are absent
        from the signature.
        """

        _require_sha256("expected_sha256", expected_sha256)
        capture = load_exact_native_observer_capture(
            capture_artifact_path,
            expected_sha256=expected_sha256,
        )
        return cls._from_strict_capture(
            capture=capture,
            expected_sha256=expected_sha256,
        )

    @classmethod
    def load_sealed_record(
        cls,
        *,
        capture_artifact_path: str | PathLike[str],
        expected_sha256: str,
        record: object,
    ) -> FrozenObserverInputProvenance:
        """Strict-load a capture and recover its exact sealed provenance record."""

        _require_sha256("expected_sha256", expected_sha256)
        if type(record) is not dict:
            raise TypeError("record must be an exact dict")
        capture = load_exact_native_observer_capture(
            capture_artifact_path,
            expected_sha256=expected_sha256,
        )
        provenance = cls._from_strict_capture(
            capture=capture,
            expected_sha256=expected_sha256,
        )
        expected_record = provenance.as_canonical_record()
        if set(record) != set(expected_record):
            raise ValueError("sealed provenance record keys mismatch")
        for name, expected_value in expected_record.items():
            actual_value = record[name]
            if type(actual_value) is not type(expected_value) or actual_value != expected_value:
                raise ValueError(f"sealed provenance record field {name} mismatch")
        _STRICTLY_LOADED_PROVENANCE[id(provenance)] = (
            provenance,
            _input_provenance_binding_fingerprint(provenance),
        )
        return provenance

    @classmethod
    def _from_strict_capture(
        cls,
        *,
        capture: object,
        expected_sha256: str,
    ) -> FrozenObserverInputProvenance:
        """Derive provenance only from one already strict-loaded capture."""

        if capture.frozen_transform.name != "apply_sensor_error":
            raise ValueError("capture frozen transform name must be exact apply_sensor_error")
        if capture.frozen_transform.enabled is not True:
            raise ValueError("capture frozen apply_sensor_error transform must be enabled")
        dt_bytes = struct.pack("<d", capture.dt_seconds)
        return cls(
            schema_version=PROVENANCE_SCHEMA_VERSION,
            binding_kind=EXACT_PROFILED_INPUT_BINDING,
            exact_raw_native_specific_force_body_source=(EXACT_RAW_NATIVE_SPECIFIC_FORCE_SOURCE),
            exact_raw_native_angular_velocity_body_source=(
                EXACT_RAW_NATIVE_ANGULAR_VELOCITY_SOURCE
            ),
            specific_force_body_source=(EXACT_ESTIMATOR_DELIVERED_PROFILED_SPECIFIC_FORCE_SOURCE),
            angular_velocity_body_source=(
                EXACT_ESTIMATOR_DELIVERED_PROFILED_ANGULAR_VELOCITY_SOURCE
            ),
            vio_velocity_world_source=RECORD_TIME_VIO_VELOCITY_SOURCE,
            vio_quaternion_body_to_world_source=RECORD_TIME_VIO_QUATERNION_SOURCE,
            frozen_sensor_error_bank_source=FROZEN_SENSOR_ERROR_BANK_SOURCE,
            frozen_apply_sensor_error_source=FROZEN_APPLY_SENSOR_ERROR_SOURCE,
            frozen_sensor_profile_source=FROZEN_SENSOR_PROFILE_SOURCE,
            delivered_sample_causal_declaration=(ESTIMATOR_DELIVERED_PROFILED_CAUSAL_DECLARATION),
            native_imu_was_cloned_at_record_time=True,
            estimator_delivered_profiled_imu_was_captured_at_record_time=True,
            vio_was_captured_at_record_time=True,
            sensor_error_bank_was_preregistered_and_frozen=True,
            apply_sensor_error_source_was_frozen=True,
            sensor_profile_was_frozen=True,
            specific_force_is_reconstructed_proxy=False,
            exact_raw_native_specific_force_sha256=canonical_observer_array_sha256(
                capture.raw_specific_force_body
            ),
            exact_raw_native_angular_velocity_sha256=(
                canonical_observer_array_sha256(capture.raw_angular_velocity_body)
            ),
            estimator_delivered_profiled_specific_force_sha256=(
                canonical_observer_array_sha256(capture.delivered_specific_force_body)
            ),
            estimator_delivered_profiled_angular_velocity_sha256=(
                canonical_observer_array_sha256(capture.delivered_angular_velocity_body)
            ),
            vio_velocity_world_sha256=canonical_observer_array_sha256(capture.vio_velocity_world),
            vio_quaternion_body_to_world_sha256=canonical_observer_array_sha256(
                capture.vio_quaternion_body_to_world_wxyz
            ),
            valid_transition_mask_sha256=canonical_observer_array_sha256(
                capture.valid_transition_mask
            ),
            dt_seconds_float64_le_hex=dt_bytes.hex(),
            dt_seconds_float64_le_sha256=hashlib.sha256(dt_bytes).hexdigest(),
            frozen_sensor_error_bank_sha256=(capture.frozen_transform.error_bank_sha256),
            apply_sensor_error_source_sha256=(capture.frozen_transform.implementation_sha256),
            frozen_sensor_profile_sha256=capture.frozen_transform.config_sha256,
            capture_artifact_sha256=expected_sha256,
        )

    @classmethod
    def reconstructed_force_proxy(cls) -> FrozenObserverInputProvenance:
        """Declare diagnostic-only reconstructed force, which can never qualify."""

        return cls(
            schema_version=PROVENANCE_SCHEMA_VERSION,
            binding_kind=RECONSTRUCTED_PROXY_INPUT_BINDING,
            exact_raw_native_specific_force_body_source=(EXACT_RAW_NATIVE_SPECIFIC_FORCE_SOURCE),
            exact_raw_native_angular_velocity_body_source=(
                EXACT_RAW_NATIVE_ANGULAR_VELOCITY_SOURCE
            ),
            specific_force_body_source=RECONSTRUCTED_SPECIFIC_FORCE_PROXY_SOURCE,
            angular_velocity_body_source=RECORD_TIME_ANGULAR_VELOCITY_SOURCE,
            vio_velocity_world_source=RECORD_TIME_VIO_VELOCITY_SOURCE,
            vio_quaternion_body_to_world_source=RECORD_TIME_VIO_QUATERNION_SOURCE,
            frozen_sensor_error_bank_source="",
            frozen_apply_sensor_error_source="",
            frozen_sensor_profile_source="",
            delivered_sample_causal_declaration="",
            native_imu_was_cloned_at_record_time=True,
            estimator_delivered_profiled_imu_was_captured_at_record_time=False,
            vio_was_captured_at_record_time=True,
            sensor_error_bank_was_preregistered_and_frozen=False,
            apply_sensor_error_source_was_frozen=False,
            sensor_profile_was_frozen=False,
            specific_force_is_reconstructed_proxy=True,
            exact_raw_native_specific_force_sha256="",
            exact_raw_native_angular_velocity_sha256="",
            estimator_delivered_profiled_specific_force_sha256="",
            estimator_delivered_profiled_angular_velocity_sha256="",
            vio_velocity_world_sha256="",
            vio_quaternion_body_to_world_sha256="",
            valid_transition_mask_sha256="",
            dt_seconds_float64_le_hex="",
            dt_seconds_float64_le_sha256="",
            frozen_sensor_error_bank_sha256="",
            apply_sensor_error_source_sha256="",
            frozen_sensor_profile_sha256="",
            capture_artifact_sha256="",
        )


@dataclass(frozen=True)
class FrozenObserverBaselineProvenance:
    """Hash-bound Cal baselines and validity mask for the fixed windows."""

    schema_version: str
    fit_only_calibration_source: str
    operational_calibration_source: str
    valid_transition_mask_source: str
    fit_only_window: tuple[int, int]
    operational_window: tuple[int, int]
    fit_only_sample_count_by_lane: tuple[int, ...]
    operational_sample_count_by_lane: tuple[int, ...]
    fit_only_bias_sha256: str
    operational_bias_sha256: str
    valid_transition_mask_sha256: str
    capture_artifact_sha256: str

    @classmethod
    def bind(
        cls,
        *,
        fit_only_bias_body_mps2: npt.ArrayLike,
        operational_bias_body_mps2: npt.ArrayLike,
        valid_transition_mask: npt.ArrayLike,
        capture_artifact_sha256: str,
    ) -> FrozenObserverBaselineProvenance:
        """Construct canonical hashes and counts without trusting caller metadata."""

        fit_bias = np.asarray(fit_only_bias_body_mps2)
        operational_bias = np.asarray(operational_bias_body_mps2)
        mask = np.asarray(valid_transition_mask)
        if (
            fit_bias.ndim != 2
            or fit_bias.shape[1] != 3
            or not np.issubdtype(fit_bias.dtype, np.floating)
        ):
            raise ValueError("fit_only_bias_body_mps2 must have floating shape [B, 3]")
        if operational_bias.shape != fit_bias.shape or not np.issubdtype(
            operational_bias.dtype, np.floating
        ):
            raise ValueError("operational_bias_body_mps2 must match fit-only bias metadata")
        if mask.shape != (FREEZE_STEP, fit_bias.shape[0]) or mask.dtype != np.bool_:
            raise ValueError("valid_transition_mask must be bool with fixed shape [300, B]")
        _require_sha256("capture_artifact_sha256", capture_artifact_sha256)
        return cls(
            schema_version=BASELINE_PROVENANCE_SCHEMA_VERSION,
            fit_only_calibration_source=FIT_ONLY_CALIBRATION_SOURCE,
            operational_calibration_source=OPERATIONAL_CALIBRATION_SOURCE,
            valid_transition_mask_source=VALID_TRANSITION_MASK_SOURCE,
            fit_only_window=(FIT_START, FIT_STOP),
            operational_window=(FIT_START, HOLDOUT_STOP),
            fit_only_sample_count_by_lane=tuple(
                int(value) for value in mask[FIT_START:FIT_STOP].sum(axis=0)
            ),
            operational_sample_count_by_lane=tuple(
                int(value) for value in mask[FIT_START:HOLDOUT_STOP].sum(axis=0)
            ),
            fit_only_bias_sha256=canonical_observer_array_sha256(fit_bias),
            operational_bias_sha256=canonical_observer_array_sha256(operational_bias),
            valid_transition_mask_sha256=canonical_observer_array_sha256(mask),
            capture_artifact_sha256=capture_artifact_sha256,
        )


def _register_strictly_loaded_baseline_provenance(
    provenance: FrozenObserverBaselineProvenance,
    *,
    baseline_artifact_sha256: str,
) -> None:
    """Register one identity only after its sealed artifact loader validates it."""

    if type(provenance) is not FrozenObserverBaselineProvenance:
        raise TypeError("provenance must be FrozenObserverBaselineProvenance")
    _require_sha256("baseline_artifact_sha256", baseline_artifact_sha256)
    if provenance.schema_version != BASELINE_PROVENANCE_SCHEMA_VERSION:
        raise ValueError("baseline provenance schema mismatch")
    if provenance.fit_only_calibration_source != FIT_ONLY_CALIBRATION_SOURCE:
        raise ValueError("baseline fit-only calibration source mismatch")
    if provenance.operational_calibration_source != OPERATIONAL_CALIBRATION_SOURCE:
        raise ValueError("baseline operational calibration source mismatch")
    if provenance.valid_transition_mask_source != VALID_TRANSITION_MASK_SOURCE:
        raise ValueError("baseline valid-transition-mask source mismatch")
    if provenance.fit_only_window != (FIT_START, FIT_STOP):
        raise ValueError("baseline fit-only window mismatch")
    if provenance.operational_window != (FIT_START, HOLDOUT_STOP):
        raise ValueError("baseline operational window mismatch")
    for name in (
        "fit_only_sample_count_by_lane",
        "operational_sample_count_by_lane",
    ):
        value = getattr(provenance, name)
        if (
            type(value) is not tuple
            or not value
            or any(type(item) is not int or item < 0 for item in value)
        ):
            raise ValueError(f"baseline {name} must be a nonempty tuple of nonnegative ints")
    if len(provenance.fit_only_sample_count_by_lane) != len(
        provenance.operational_sample_count_by_lane
    ):
        raise ValueError("baseline sample-count lane dimensions mismatch")
    for name in (
        "fit_only_bias_sha256",
        "operational_bias_sha256",
        "valid_transition_mask_sha256",
        "capture_artifact_sha256",
    ):
        _require_sha256(f"provenance.{name}", getattr(provenance, name))

    fingerprint = _baseline_provenance_binding_fingerprint(provenance)
    existing = _STRICTLY_LOADED_BASELINE_PROVENANCE.get(id(provenance))
    if existing is not None and (
        existing[0] is not provenance
        or existing[1] != fingerprint
        or existing[2] != baseline_artifact_sha256
    ):
        raise ValueError("baseline provenance identity was already registered differently")
    _STRICTLY_LOADED_BASELINE_PROVENANCE[id(provenance)] = (
        provenance,
        fingerprint,
        baseline_artifact_sha256,
    )


@dataclass(frozen=True)
class FrozenVIOIMUObserverConfig:
    """Numerical and qualification gates for the fixed split."""

    enabled: bool = True
    gravity_world_mps2: tuple[float, float, float] = (0.0, 0.0, -9.81)
    accelerometer_residual_scale_mps2: float = 1.0
    gyroscope_residual_scale_rad_s: float = 0.1
    minimum_fit_samples: int = 160
    minimum_split_half_samples: int = 75
    minimum_holdout_samples: int = 80
    minimum_normalized_sigma_ratio: float = 1.0e-3
    maximum_normalized_condition_number: float = 1.0e3
    maximum_abs_accelerometer_bias_mps2: float = 3.0
    maximum_abs_gyroscope_bias_rad_s: float = 0.25
    maximum_abs_tilt_rad: float = 0.35
    maximum_split_accelerometer_bias_l2_mps2: float = 0.15
    maximum_split_gyroscope_bias_l2_rad_s: float = 0.015
    maximum_split_tilt_geodesic_rad: float = 0.025
    minimum_cal_rmse_improvement_fraction: float = 0.10
    minimum_cal_q95_improvement_fraction: float = 0.0
    qualification_absolute_tolerance: float = 1.0e-12
    optimizer_max_iterations: int = 40
    optimizer_step_tolerance: float = 1.0e-11
    optimizer_loss_tolerance: float = 1.0e-13
    optimizer_initial_damping: float = 1.0e-8

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be exact bool")
        if (
            len(self.gravity_world_mps2) != 3
            or any(type(value) is bool for value in self.gravity_world_mps2)
            or not all(
                isinstance(value, (int, float)) and math.isfinite(float(value))
                for value in self.gravity_world_mps2
            )
        ):
            raise ValueError("gravity_world_mps2 must contain three finite values")
        positive_float_fields = (
            "accelerometer_residual_scale_mps2",
            "gyroscope_residual_scale_rad_s",
            "maximum_normalized_condition_number",
            "maximum_abs_accelerometer_bias_mps2",
            "maximum_abs_gyroscope_bias_rad_s",
            "maximum_abs_tilt_rad",
            "maximum_split_accelerometer_bias_l2_mps2",
            "maximum_split_gyroscope_bias_l2_rad_s",
            "maximum_split_tilt_geodesic_rad",
            "optimizer_step_tolerance",
            "optimizer_loss_tolerance",
            "optimizer_initial_damping",
        )
        for name in positive_float_fields:
            value = getattr(self, name)
            if (
                type(value) is bool
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f"{name} must be finite and positive")
        if (
            type(self.minimum_normalized_sigma_ratio) is bool
            or not isinstance(self.minimum_normalized_sigma_ratio, (int, float))
            or not math.isfinite(self.minimum_normalized_sigma_ratio)
            or not 0.0 < self.minimum_normalized_sigma_ratio <= 1.0
        ):
            raise ValueError("minimum_normalized_sigma_ratio must lie in (0, 1]")
        for name, lower_inclusive in (
            ("minimum_cal_rmse_improvement_fraction", False),
            ("minimum_cal_q95_improvement_fraction", True),
        ):
            value = getattr(self, name)
            lower_ok = value >= 0.0 if lower_inclusive else value > 0.0
            if (
                type(value) is bool
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lower_ok
                or value >= 1.0
            ):
                interval = "[0, 1)" if lower_inclusive else "(0, 1)"
                raise ValueError(f"{name} must lie in {interval}")
        if (
            type(self.qualification_absolute_tolerance) is bool
            or not isinstance(self.qualification_absolute_tolerance, (int, float))
            or not math.isfinite(self.qualification_absolute_tolerance)
            or self.qualification_absolute_tolerance < 0.0
        ):
            raise ValueError("qualification_absolute_tolerance must be finite and nonnegative")
        for name, upper_bound in (
            ("minimum_fit_samples", FIT_STOP - FIT_START),
            ("minimum_split_half_samples", (FIT_STOP - FIT_START) // 2),
            ("minimum_holdout_samples", HOLDOUT_STOP - HOLDOUT_START),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > upper_bound
            ):
                raise ValueError(f"{name} must be an integer in [1, {upper_bound}]")
        if (
            isinstance(self.optimizer_max_iterations, bool)
            or not isinstance(self.optimizer_max_iterations, int)
            or self.optimizer_max_iterations <= 0
        ):
            raise ValueError("optimizer_max_iterations must be a positive integer")
        implied_condition = 1.0 / self.minimum_normalized_sigma_ratio
        if self.maximum_normalized_condition_number + 1.0e-12 < implied_condition:
            raise ValueError(
                "maximum_normalized_condition_number conflicts with minimum_normalized_sigma_ratio"
            )


@dataclass(frozen=True)
class FrozenObserverState:
    """Immutable scalar representation of the eight fitted parameters."""

    accelerometer_bias_body_mps2: tuple[float, float, float]
    gyroscope_bias_body_rad_s: tuple[float, float, float]
    delta_roll_pitch_rad: tuple[float, float]

    def as_tuple(self) -> tuple[float, ...]:
        return (
            *self.accelerometer_bias_body_mps2,
            *self.gyroscope_bias_body_rad_s,
            *self.delta_roll_pitch_rad,
        )


@dataclass(frozen=True)
class NormalizedJacobianCertificate:
    """Explicit SVD certificate for the column-normalized fit Jacobian."""

    state_order: tuple[str, ...]
    residual_row_count: int
    state_dimension: int
    column_l2_norms: tuple[float, ...]
    normalized_singular_values_descending: tuple[float, ...]
    numerical_rank: int
    required_rank: int
    rank_tolerance: float
    normalized_sigma_ratio: float
    minimum_normalized_sigma_ratio: float
    normalized_condition_number: float
    maximum_normalized_condition_number: float
    passed: bool


@dataclass(frozen=True)
class SplitHalfStability:
    """Independent 0--99 versus 100--199 refit stability."""

    first_half_state: FrozenObserverState | None
    second_half_state: FrozenObserverState | None
    first_half_certificate: NormalizedJacobianCertificate | None
    second_half_certificate: NormalizedJacobianCertificate | None
    accelerometer_bias_l2_mps2: float
    gyroscope_bias_l2_rad_s: float
    tilt_geodesic_rad: float
    passed: bool
    reject_reasons: tuple[str, ...]


@dataclass(frozen=True)
class CalRelativeMetric:
    """Candidate and Cal error summaries for one holdout observable."""

    candidate_rmse: float
    calibrated_rmse: float
    candidate_q95: float
    calibrated_q95: float
    rmse_ratio_to_calibrated: float
    q95_ratio_to_calibrated: float
    all_finite: bool
    rmse_passed: bool
    q95_passed: bool


@dataclass(frozen=True)
class HoldoutQualification:
    """Zero-update transition 200--299 qualification metrics."""

    sample_count: int
    delta_velocity_error_mps: CalRelativeMetric
    rotation_geodesic_error_rad: CalRelativeMetric
    passed: bool
    reject_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FrozenObserverLaneResult:
    """All immutable evidence and the selected deployment state for one lane."""

    lane_index: int
    diagnostic_candidate_state: FrozenObserverState | None
    exact_cal_fallback_state: FrozenObserverState
    deployment_state: FrozenObserverState
    full_fit_certificate: NormalizedJacobianCertificate | None
    split_half_stability: SplitHalfStability | None
    holdout_qualification: HoldoutQualification | None
    fit_sample_count: int
    holdout_sample_count: int
    provenance_eligible: bool
    qualified: bool
    deployment_mode: str
    reject_reasons: tuple[str, ...]
    frozen_at_step: int
    exact_cal_fallback_declaration: str


@dataclass(frozen=True)
class FrozenVIOIMUObserverResult:
    """Immutable batched result; no post-freeze mutation API exists."""

    schema_version: str
    development_only: bool
    fit_window: tuple[int, int]
    holdout_window: tuple[int, int]
    frozen_at_step: int
    provenance: FrozenObserverInputProvenance
    provenance_eligible: bool
    provenance_reject_reasons: tuple[str, ...]
    baseline_provenance: FrozenObserverBaselineProvenance
    baseline_provenance_eligible: bool
    baseline_provenance_reject_reasons: tuple[str, ...]
    lanes: tuple[FrozenObserverLaneResult, ...]
    all_lanes_qualified: bool


@dataclass(frozen=True)
class _PreparedHistory:
    specific_force_body: FloatArray
    angular_velocity_body: FloatArray
    target_specific_force_vio: FloatArray
    target_angular_velocity_vio: FloatArray
    valid: BoolArray
    invalid_requested: BoolArray


@dataclass(frozen=True)
class _FitOutcome:
    state: FrozenObserverState | None
    theta: FloatArray | None
    certificate: NormalizedJacobianCertificate | None
    sample_count: int
    converged: bool
    reject_reasons: tuple[str, ...]


def fit_frozen_vio_imu_observer(
    *,
    specific_force_body_history: npt.ArrayLike,
    angular_velocity_body_history: npt.ArrayLike,
    vio_velocity_world_history: npt.ArrayLike,
    vio_quaternion_body_to_world_history: npt.ArrayLike,
    valid_transition_mask: npt.ArrayLike,
    fit_only_calibrated_accelerometer_bias_body_mps2: npt.ArrayLike,
    operational_calibrated_accelerometer_bias_body_mps2: npt.ArrayLike,
    dt: float,
    provenance: FrozenObserverInputProvenance,
    baseline_provenance: FrozenObserverBaselineProvenance,
    exact_raw_native_specific_force_body_history: npt.ArrayLike | None = None,
    exact_raw_native_angular_velocity_body_history: npt.ArrayLike | None = None,
    config: FrozenVIOIMUObserverConfig | None = None,
) -> FrozenVIOIMUObserverResult:
    """Fit on 0--199, qualify without updates on 200--299, then freeze.

    The fitted IMU histories are the exact estimator-delivered/profiled stream,
    never the raw native sensor stream.  Both streams must be supplied as exact
    fixed-boundary arrays ``[300,B,3]`` so their frozen provenance hashes can be
    verified.  VIO velocity is ``[301,B,3]``, VIO quaternion ``[301,B,4]``, and
    the transition mask ``[300,B]``.  Requiring exact lengths removes any API
    path by which post-freeze observations could enter the fit.

    Reconstructed specific force is accepted only with
    :meth:`FrozenObserverInputProvenance.reconstructed_force_proxy`; its
    diagnostics are permanently ineligible for qualification.
    """

    if config is None:
        settings = FrozenVIOIMUObserverConfig()
    elif type(config) is FrozenVIOIMUObserverConfig:
        settings = config
    else:
        raise TypeError("config must be None or FrozenVIOIMUObserverConfig")
    time_step = _validate_dt(dt)

    specific_force = _float_array(
        "specific_force_body_history",
        specific_force_body_history,
        (FREEZE_STEP, None, 3),
    )
    batch = specific_force.shape[1]
    angular_velocity = _float_array(
        "angular_velocity_body_history",
        angular_velocity_body_history,
        (FREEZE_STEP, batch, 3),
    )
    raw_specific_force: FloatArray | None = None
    raw_angular_velocity: FloatArray | None = None
    if exact_raw_native_specific_force_body_history is not None:
        raw_specific_force = _float_array(
            "exact_raw_native_specific_force_body_history",
            exact_raw_native_specific_force_body_history,
            (FREEZE_STEP, batch, 3),
        )
    if exact_raw_native_angular_velocity_body_history is not None:
        raw_angular_velocity = _float_array(
            "exact_raw_native_angular_velocity_body_history",
            exact_raw_native_angular_velocity_body_history,
            (FREEZE_STEP, batch, 3),
        )
    velocity = _float_array(
        "vio_velocity_world_history",
        vio_velocity_world_history,
        (FREEZE_STEP + 1, batch, 3),
    )
    quaternion = _float_array(
        "vio_quaternion_body_to_world_history",
        vio_quaternion_body_to_world_history,
        (FREEZE_STEP + 1, batch, 4),
    )
    valid_mask = np.asarray(valid_transition_mask)
    if valid_mask.shape != (FREEZE_STEP, batch) or valid_mask.dtype != np.bool_:
        raise ValueError(
            f"valid_transition_mask must be a bool array with shape {(FREEZE_STEP, batch)}"
        )
    provenance_reasons = _validate_provenance(
        provenance,
        exact_raw_native_specific_force=raw_specific_force,
        exact_raw_native_angular_velocity=raw_angular_velocity,
        estimator_delivered_profiled_specific_force=specific_force,
        estimator_delivered_profiled_angular_velocity=angular_velocity,
        vio_velocity_world=velocity,
        vio_quaternion_body_to_world=quaternion,
        valid_transition_mask=valid_mask,
        dt=time_step,
    )
    fit_only_calibrated_bias = _float_array(
        "fit_only_calibrated_accelerometer_bias_body_mps2",
        fit_only_calibrated_accelerometer_bias_body_mps2,
        (batch, 3),
    )
    operational_calibrated_bias = _float_array(
        "operational_calibrated_accelerometer_bias_body_mps2",
        operational_calibrated_accelerometer_bias_body_mps2,
        (batch, 3),
    )
    if not np.isfinite(fit_only_calibrated_bias).all():
        raise ValueError("fit_only_calibrated_accelerometer_bias_body_mps2 must be finite")
    if not np.isfinite(operational_calibrated_bias).all():
        raise ValueError("operational_calibrated_accelerometer_bias_body_mps2 must be finite")
    baseline_provenance_reasons = _validate_baseline_provenance(
        baseline_provenance,
        fit_only_bias=fit_only_calibrated_bias,
        operational_bias=operational_calibrated_bias,
        valid_mask=valid_mask,
    )
    if (
        provenance.binding_kind == EXACT_PROFILED_INPUT_BINDING
        and provenance.capture_artifact_sha256 != baseline_provenance.capture_artifact_sha256
    ):
        provenance_reasons = _unique(
            (
                *provenance_reasons,
                "input_baseline_capture_artifact_sha256_mismatch",
            )
        )
    provenance_eligible = not provenance_reasons
    baseline_provenance_eligible = not baseline_provenance_reasons
    combined_provenance_reasons = _unique((*provenance_reasons, *baseline_provenance_reasons))
    combined_provenance_eligible = provenance_eligible and baseline_provenance_eligible

    prepared = _prepare_history(
        specific_force=specific_force,
        angular_velocity=angular_velocity,
        velocity=velocity,
        quaternion=quaternion,
        valid_mask=valid_mask,
        dt=time_step,
        gravity_world=np.asarray(settings.gravity_world_mps2, dtype=np.float64),
    )

    lanes = tuple(
        _fit_lane(
            lane_index=lane,
            history=prepared,
            fit_only_calibrated_bias=fit_only_calibrated_bias[lane],
            operational_calibrated_bias=operational_calibrated_bias[lane],
            dt=time_step,
            provenance_eligible=combined_provenance_eligible,
            provenance_reasons=combined_provenance_reasons,
            config=settings,
        )
        for lane in range(batch)
    )
    return FrozenVIOIMUObserverResult(
        schema_version="flightguard.frozen_vio_imu_observer.result.v3",
        development_only=True,
        fit_window=(FIT_START, FIT_STOP),
        holdout_window=(HOLDOUT_START, HOLDOUT_STOP),
        frozen_at_step=FREEZE_STEP,
        provenance=provenance,
        provenance_eligible=provenance_eligible,
        provenance_reject_reasons=provenance_reasons,
        baseline_provenance=baseline_provenance,
        baseline_provenance_eligible=baseline_provenance_eligible,
        baseline_provenance_reject_reasons=baseline_provenance_reasons,
        lanes=lanes,
        all_lanes_qualified=bool(lanes) and all(lane.qualified for lane in lanes),
    )


def select_qualified_or_exact_cal(
    *,
    lane_result: FrozenObserverLaneResult,
    candidate_factory: Callable[[], T],
    calibrated: T,
) -> T:
    """Return ``calibrated`` by identity on every non-qualified path.

    The candidate is constructed lazily only for a qualified lane.  Every
    fallback executes the factory zero times and returns the original Cal
    object, not a copy.
    """

    if not callable(candidate_factory):
        raise TypeError("candidate_factory must be callable")
    if lane_result.qualified:
        return candidate_factory()
    return calibrated


def _fit_lane(
    *,
    lane_index: int,
    history: _PreparedHistory,
    fit_only_calibrated_bias: FloatArray,
    operational_calibrated_bias: FloatArray,
    dt: float,
    provenance_eligible: bool,
    provenance_reasons: tuple[str, ...],
    config: FrozenVIOIMUObserverConfig,
) -> FrozenObserverLaneResult:
    fallback_state = FrozenObserverState(
        accelerometer_bias_body_mps2=_tuple3(operational_calibrated_bias),
        gyroscope_bias_body_rad_s=(0.0, 0.0, 0.0),
        delta_roll_pitch_rad=(0.0, 0.0),
    )
    fit_requested = history.valid[FIT_START:FIT_STOP, lane_index]
    holdout_requested = history.valid[HOLDOUT_START:HOLDOUT_STOP, lane_index]
    fit_sample_count = int(fit_requested.sum())
    holdout_sample_count = int(holdout_requested.sum())

    if not config.enabled:
        return _fallback_lane(
            lane_index=lane_index,
            fallback_state=fallback_state,
            fit_sample_count=fit_sample_count,
            holdout_sample_count=holdout_sample_count,
            provenance_eligible=provenance_eligible,
            reasons=("disabled_by_config", *provenance_reasons),
        )

    reasons = list(provenance_reasons)
    if bool(history.invalid_requested[FIT_START:FIT_STOP, lane_index].any()):
        reasons.append("nonfinite_or_invalid_fit_observation")
    if bool(history.invalid_requested[HOLDOUT_START:HOLDOUT_STOP, lane_index].any()):
        reasons.append("nonfinite_or_invalid_holdout_observation")

    full_fit = _fit_indices(
        history=history,
        lane_index=lane_index,
        start=FIT_START,
        stop=FIT_STOP,
        calibrated_bias=fit_only_calibrated_bias,
        minimum_samples=config.minimum_fit_samples,
        config=config,
    )
    reasons.extend(full_fit.reject_reasons)
    if full_fit.state is None or full_fit.theta is None or full_fit.certificate is None:
        return _fallback_lane(
            lane_index=lane_index,
            fallback_state=fallback_state,
            fit_sample_count=fit_sample_count,
            holdout_sample_count=holdout_sample_count,
            provenance_eligible=provenance_eligible,
            reasons=tuple(reasons),
            certificate=full_fit.certificate,
        )

    split = _split_half_stability(
        history=history,
        lane_index=lane_index,
        calibrated_bias=fit_only_calibrated_bias,
        config=config,
    )
    reasons.extend(split.reject_reasons)
    holdout = _qualify_holdout(
        history=history,
        lane_index=lane_index,
        theta=full_fit.theta,
        calibrated_bias=fit_only_calibrated_bias,
        dt=dt,
        config=config,
    )
    reasons.extend(holdout.reject_reasons)
    bounded_reasons = _state_bound_reasons(full_fit.theta, config)
    reasons.extend(bounded_reasons)
    unique_reasons = _unique(reasons)
    qualified = (
        provenance_eligible
        and full_fit.certificate.passed
        and split.passed
        and holdout.passed
        and full_fit.converged
        and not unique_reasons
    )
    deployment_state = full_fit.state if qualified else fallback_state
    return FrozenObserverLaneResult(
        lane_index=lane_index,
        diagnostic_candidate_state=full_fit.state,
        exact_cal_fallback_state=fallback_state,
        deployment_state=deployment_state,
        full_fit_certificate=full_fit.certificate,
        split_half_stability=split,
        holdout_qualification=holdout,
        fit_sample_count=fit_sample_count,
        holdout_sample_count=holdout_sample_count,
        provenance_eligible=provenance_eligible,
        qualified=qualified,
        deployment_mode="frozen_observer" if qualified else "exact_cal_fallback",
        reject_reasons=unique_reasons,
        frozen_at_step=FREEZE_STEP,
        exact_cal_fallback_declaration=EXACT_CAL_FALLBACK_DECLARATION,
    )


def _fallback_lane(
    *,
    lane_index: int,
    fallback_state: FrozenObserverState,
    fit_sample_count: int,
    holdout_sample_count: int,
    provenance_eligible: bool,
    reasons: tuple[str, ...],
    certificate: NormalizedJacobianCertificate | None = None,
) -> FrozenObserverLaneResult:
    return FrozenObserverLaneResult(
        lane_index=lane_index,
        diagnostic_candidate_state=None,
        exact_cal_fallback_state=fallback_state,
        deployment_state=fallback_state,
        full_fit_certificate=certificate,
        split_half_stability=None,
        holdout_qualification=None,
        fit_sample_count=fit_sample_count,
        holdout_sample_count=holdout_sample_count,
        provenance_eligible=provenance_eligible,
        qualified=False,
        deployment_mode="exact_cal_fallback",
        reject_reasons=_unique(reasons),
        frozen_at_step=FREEZE_STEP,
        exact_cal_fallback_declaration=EXACT_CAL_FALLBACK_DECLARATION,
    )


def _prepare_history(
    *,
    specific_force: FloatArray,
    angular_velocity: FloatArray,
    velocity: FloatArray,
    quaternion: FloatArray,
    valid_mask: BoolArray,
    dt: float,
    gravity_world: FloatArray,
) -> _PreparedHistory:
    quaternion_norm = _finite_scaled_norm(quaternion, axis=2)
    quaternion_valid = np.isfinite(quaternion).all(axis=2) & np.isfinite(quaternion_norm)
    quaternion_valid &= quaternion_norm > np.finfo(np.float64).eps
    safe_quaternion = np.zeros_like(quaternion)
    safe_quaternion[:, :, 0] = 1.0
    safe_quaternion[quaternion_valid] = (
        quaternion[quaternion_valid] / quaternion_norm[quaternion_valid, None]
    )
    rotations = _quaternion_to_rotation_matrix(safe_quaternion.reshape(-1, 4)).reshape(
        FREEZE_STEP + 1,
        specific_force.shape[1],
        3,
        3,
    )
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        acceleration_world = (velocity[1:] - velocity[:-1]) / dt
        target_specific_force = np.einsum(
            "tbij,tbj->tbi",
            rotations[1:].transpose(0, 1, 3, 2),
            acceleration_world - gravity_world.reshape(1, 1, 3),
        )
    target_angular_velocity = (
        _relative_quaternion_rotvec(
            safe_quaternion[:-1],
            safe_quaternion[1:],
        )
        / dt
    )
    finite = (
        np.isfinite(specific_force).all(axis=2)
        & np.isfinite(angular_velocity).all(axis=2)
        & np.isfinite(velocity[:-1]).all(axis=2)
        & np.isfinite(velocity[1:]).all(axis=2)
        & quaternion_valid[:-1]
        & quaternion_valid[1:]
        & np.isfinite(target_specific_force).all(axis=2)
        & np.isfinite(target_angular_velocity).all(axis=2)
    )
    invalid_requested = valid_mask & ~finite
    valid = valid_mask & finite
    return _PreparedHistory(
        specific_force_body=specific_force,
        angular_velocity_body=angular_velocity,
        target_specific_force_vio=target_specific_force,
        target_angular_velocity_vio=target_angular_velocity,
        valid=valid,
        invalid_requested=invalid_requested,
    )


def _fit_indices(
    *,
    history: _PreparedHistory,
    lane_index: int,
    start: int,
    stop: int,
    calibrated_bias: FloatArray,
    minimum_samples: int,
    config: FrozenVIOIMUObserverConfig,
) -> _FitOutcome:
    mask = history.valid[start:stop, lane_index]
    sample_count = int(mask.sum())
    label = _window_label(start, stop)
    if sample_count < minimum_samples:
        return _FitOutcome(
            state=None,
            theta=None,
            certificate=None,
            sample_count=sample_count,
            converged=False,
            reject_reasons=(f"insufficient_{label}_samples",),
        )
    force = history.specific_force_body[start:stop, lane_index][mask]
    gyro = history.angular_velocity_body[start:stop, lane_index][mask]
    target_force = history.target_specific_force_vio[start:stop, lane_index][mask]
    target_gyro = history.target_angular_velocity_vio[start:stop, lane_index][mask]
    initial = np.zeros(STATE_DIMENSION, dtype=np.float64)
    initial[:3] = np.mean(force - target_force, axis=0)
    if not np.isfinite(initial[:3]).all():
        initial[:3] = calibrated_bias
    initial[3:6] = np.mean(gyro - target_gyro, axis=0)

    theta, converged = _gauss_newton(
        force=force,
        gyro=gyro,
        target_force=target_force,
        target_gyro=target_gyro,
        initial=initial,
        config=config,
    )
    residual, jacobian = _residual_and_jacobian(
        theta,
        force=force,
        gyro=gyro,
        target_force=target_force,
        target_gyro=target_gyro,
        config=config,
    )
    certificate = _jacobian_certificate(jacobian, config)
    reasons: list[str] = []
    if not converged:
        reasons.append(f"{label}_optimizer_not_converged")
    if not np.isfinite(theta).all() or not np.isfinite(residual).all():
        reasons.append(f"{label}_fit_nonfinite")
    if certificate.numerical_rank != STATE_DIMENSION:
        reasons.append(f"{label}_normalized_jacobian_rank_below_8")
    if certificate.normalized_sigma_ratio < config.minimum_normalized_sigma_ratio:
        reasons.append(f"{label}_normalized_sigma_ratio_below_minimum")
    if certificate.normalized_condition_number > config.maximum_normalized_condition_number:
        reasons.append(f"{label}_normalized_condition_number_above_maximum")
    return _FitOutcome(
        state=_state_from_theta(theta) if np.isfinite(theta).all() else None,
        theta=theta if np.isfinite(theta).all() else None,
        certificate=certificate,
        sample_count=sample_count,
        converged=converged,
        reject_reasons=_unique(reasons),
    )


def _gauss_newton(
    *,
    force: FloatArray,
    gyro: FloatArray,
    target_force: FloatArray,
    target_gyro: FloatArray,
    initial: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> tuple[FloatArray, bool]:
    theta = initial.copy()
    damping = config.optimizer_initial_damping
    previous_loss = math.inf
    converged = False
    for _ in range(config.optimizer_max_iterations):
        residual, jacobian = _residual_and_jacobian(
            theta,
            force=force,
            gyro=gyro,
            target_force=target_force,
            target_gyro=target_gyro,
            config=config,
        )
        loss = _finite_scaled_rmse(residual)
        if not math.isfinite(loss) or not np.isfinite(jacobian).all():
            break
        # Some BLAS builds leak benign floating-point status flags from the
        # masked quaternion log into the following matmul.  Suppress the flag,
        # then make the actual finite result an explicit fail-closed gate.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            normal = jacobian.T @ jacobian
            gradient = jacobian.T @ residual
        if not np.isfinite(normal).all() or not np.isfinite(gradient).all():
            break
        diagonal = np.maximum(np.diag(normal), 1.0)
        damped = normal + damping * np.diag(diagonal)
        try:
            step = np.linalg.solve(damped, -gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(damped, -gradient, rcond=None)[0]
        if not np.isfinite(step).all():
            break
        accepted = False
        accepted_loss = loss
        accepted_theta = theta
        for exponent in range(12):
            scale = 0.5**exponent
            candidate = theta + scale * step
            if (
                bool(np.abs(candidate[:3]).max() > config.maximum_abs_accelerometer_bias_mps2)
                or bool(np.abs(candidate[3:6]).max() > config.maximum_abs_gyroscope_bias_rad_s)
                or bool(np.abs(candidate[6:8]).max() > config.maximum_abs_tilt_rad)
            ):
                continue
            candidate_residual, _ = _residual_and_jacobian(
                candidate,
                force=force,
                gyro=gyro,
                target_force=target_force,
                target_gyro=target_gyro,
                config=config,
            )
            candidate_loss = _finite_scaled_rmse(candidate_residual)
            if math.isfinite(candidate_loss) and candidate_loss <= loss:
                accepted = True
                accepted_loss = candidate_loss
                accepted_theta = candidate
                break
        if not accepted:
            if _finite_scaled_norm(step) <= config.optimizer_step_tolerance:
                converged = True
            break
        theta = accepted_theta
        improvement = loss - accepted_loss
        if (
            _finite_scaled_norm(scale * step) <= config.optimizer_step_tolerance
            or improvement <= config.optimizer_loss_tolerance
            or abs(previous_loss - accepted_loss) <= config.optimizer_loss_tolerance
        ):
            converged = True
            break
        previous_loss = accepted_loss
        damping = max(damping * 0.3, np.finfo(np.float64).eps)
    return theta, converged


def _residual_and_jacobian(
    theta: FloatArray,
    *,
    force: FloatArray,
    gyro: FloatArray,
    target_force: FloatArray,
    target_gyro: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> tuple[FloatArray, FloatArray]:
    bias_acc = theta[:3]
    bias_gyro = theta[3:6]
    rotation, derivative_roll, derivative_pitch = _tilt_rotation_and_derivatives(
        theta[6],
        theta[7],
    )
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        unbiased_force = force - bias_acc
        unbiased_gyro = gyro - bias_gyro
        predicted_force = np.einsum("ij,nj->ni", rotation, unbiased_force)
        predicted_gyro = np.einsum("ij,nj->ni", rotation, unbiased_gyro)
        residual_force = (predicted_force - target_force) / config.accelerometer_residual_scale_mps2
        residual_gyro = (predicted_gyro - target_gyro) / config.gyroscope_residual_scale_rad_s
    count = force.shape[0]
    jacobian_force = np.zeros((count, 3, STATE_DIMENSION), dtype=np.float64)
    jacobian_gyro = np.zeros((count, 3, STATE_DIMENSION), dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        jacobian_force[:, :, :3] = -rotation / config.accelerometer_residual_scale_mps2
        jacobian_gyro[:, :, 3:6] = -rotation / config.gyroscope_residual_scale_rad_s
        jacobian_force[:, :, 6] = (
            np.einsum(
                "ij,nj->ni",
                derivative_roll,
                unbiased_force,
            )
            / config.accelerometer_residual_scale_mps2
        )
        jacobian_force[:, :, 7] = (
            np.einsum(
                "ij,nj->ni",
                derivative_pitch,
                unbiased_force,
            )
            / config.accelerometer_residual_scale_mps2
        )
        jacobian_gyro[:, :, 6] = (
            np.einsum(
                "ij,nj->ni",
                derivative_roll,
                unbiased_gyro,
            )
            / config.gyroscope_residual_scale_rad_s
        )
        jacobian_gyro[:, :, 7] = (
            np.einsum(
                "ij,nj->ni",
                derivative_pitch,
                unbiased_gyro,
            )
            / config.gyroscope_residual_scale_rad_s
        )
    residual = np.concatenate((residual_force.reshape(-1), residual_gyro.reshape(-1)))
    jacobian = np.concatenate(
        (jacobian_force.reshape(-1, STATE_DIMENSION), jacobian_gyro.reshape(-1, STATE_DIMENSION)),
        axis=0,
    )
    return residual, jacobian


def _jacobian_certificate(
    jacobian: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> NormalizedJacobianCertificate:
    column_norm = _finite_scaled_norm(jacobian, axis=0)
    finite_columns = np.isfinite(column_norm)
    nonzero_columns = column_norm > np.finfo(np.float64).tiny
    valid_columns = finite_columns & nonzero_columns
    normalized = np.zeros_like(jacobian)
    normalized[:, valid_columns] = jacobian[:, valid_columns] / column_norm[valid_columns]
    if np.isfinite(normalized).all():
        singular_values = np.linalg.svd(normalized, compute_uv=False)
    else:
        singular_values = np.zeros(STATE_DIMENSION, dtype=np.float64)
    largest = float(singular_values[0]) if singular_values.size else 0.0
    tolerance = (
        max(normalized.shape) * np.finfo(np.float64).eps * largest if largest > 0.0 else math.inf
    )
    rank = int(np.sum(singular_values > tolerance)) if math.isfinite(tolerance) else 0
    smallest = (
        float(singular_values[STATE_DIMENSION - 1])
        if singular_values.size >= STATE_DIMENSION
        else 0.0
    )
    ratio = smallest / largest if largest > 0.0 else 0.0
    condition = largest / smallest if smallest > 0.0 else math.inf
    passed = (
        bool(valid_columns.all())
        and rank == STATE_DIMENSION
        and ratio >= config.minimum_normalized_sigma_ratio
        and condition <= config.maximum_normalized_condition_number
    )
    return NormalizedJacobianCertificate(
        state_order=STATE_ORDER,
        residual_row_count=int(jacobian.shape[0]),
        state_dimension=STATE_DIMENSION,
        column_l2_norms=tuple(float(value) for value in column_norm),
        normalized_singular_values_descending=tuple(
            float(value) for value in singular_values[:STATE_DIMENSION]
        ),
        numerical_rank=rank,
        required_rank=STATE_DIMENSION,
        rank_tolerance=float(tolerance),
        normalized_sigma_ratio=float(ratio),
        minimum_normalized_sigma_ratio=config.minimum_normalized_sigma_ratio,
        normalized_condition_number=float(condition),
        maximum_normalized_condition_number=config.maximum_normalized_condition_number,
        passed=passed,
    )


def _split_half_stability(
    *,
    history: _PreparedHistory,
    lane_index: int,
    calibrated_bias: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> SplitHalfStability:
    first = _fit_indices(
        history=history,
        lane_index=lane_index,
        start=FIT_START,
        stop=(FIT_START + FIT_STOP) // 2,
        calibrated_bias=calibrated_bias,
        minimum_samples=config.minimum_split_half_samples,
        config=config,
    )
    second = _fit_indices(
        history=history,
        lane_index=lane_index,
        start=(FIT_START + FIT_STOP) // 2,
        stop=FIT_STOP,
        calibrated_bias=calibrated_bias,
        minimum_samples=config.minimum_split_half_samples,
        config=config,
    )
    reasons = list(first.reject_reasons) + list(second.reject_reasons)
    if first.theta is None or second.theta is None:
        return SplitHalfStability(
            first_half_state=first.state,
            second_half_state=second.state,
            first_half_certificate=first.certificate,
            second_half_certificate=second.certificate,
            accelerometer_bias_l2_mps2=math.inf,
            gyroscope_bias_l2_rad_s=math.inf,
            tilt_geodesic_rad=math.inf,
            passed=False,
            reject_reasons=_unique(reasons),
        )
    acc_difference = float(_finite_scaled_norm(first.theta[:3] - second.theta[:3]))
    gyro_difference = float(_finite_scaled_norm(first.theta[3:6] - second.theta[3:6]))
    first_rotation = _tilt_rotation_and_derivatives(first.theta[6], first.theta[7])[0]
    second_rotation = _tilt_rotation_and_derivatives(second.theta[6], second.theta[7])[0]
    tilt_difference = _rotation_geodesic(first_rotation, second_rotation)
    if acc_difference > config.maximum_split_accelerometer_bias_l2_mps2:
        reasons.append("split_half_accelerometer_bias_instability")
    if gyro_difference > config.maximum_split_gyroscope_bias_l2_rad_s:
        reasons.append("split_half_gyroscope_bias_instability")
    if tilt_difference > config.maximum_split_tilt_geodesic_rad:
        reasons.append("split_half_tilt_instability")
    if first.certificate is None or not first.certificate.passed:
        reasons.append("first_fit_half_unobservable")
    if second.certificate is None or not second.certificate.passed:
        reasons.append("second_fit_half_unobservable")
    if not first.converged:
        reasons.append("first_fit_half_optimizer_not_converged")
    if not second.converged:
        reasons.append("second_fit_half_optimizer_not_converged")
    unique_reasons = _unique(reasons)
    return SplitHalfStability(
        first_half_state=first.state,
        second_half_state=second.state,
        first_half_certificate=first.certificate,
        second_half_certificate=second.certificate,
        accelerometer_bias_l2_mps2=acc_difference,
        gyroscope_bias_l2_rad_s=gyro_difference,
        tilt_geodesic_rad=tilt_difference,
        passed=not unique_reasons,
        reject_reasons=unique_reasons,
    )


def _qualify_holdout(
    *,
    history: _PreparedHistory,
    lane_index: int,
    theta: FloatArray,
    calibrated_bias: FloatArray,
    dt: float,
    config: FrozenVIOIMUObserverConfig,
) -> HoldoutQualification:
    mask = history.valid[HOLDOUT_START:HOLDOUT_STOP, lane_index]
    sample_count = int(mask.sum())
    force = history.specific_force_body[HOLDOUT_START:HOLDOUT_STOP, lane_index][mask]
    gyro = history.angular_velocity_body[HOLDOUT_START:HOLDOUT_STOP, lane_index][mask]
    target_force = history.target_specific_force_vio[
        HOLDOUT_START:HOLDOUT_STOP,
        lane_index,
    ][mask]
    target_gyro = history.target_angular_velocity_vio[
        HOLDOUT_START:HOLDOUT_STOP,
        lane_index,
    ][mask]
    reasons: list[str] = []
    if sample_count < config.minimum_holdout_samples:
        reasons.append("insufficient_holdout_samples")
    if not sample_count:
        nan_metric = CalRelativeMetric(
            candidate_rmse=math.inf,
            calibrated_rmse=math.inf,
            candidate_q95=math.inf,
            calibrated_q95=math.inf,
            rmse_ratio_to_calibrated=math.inf,
            q95_ratio_to_calibrated=math.inf,
            all_finite=False,
            rmse_passed=False,
            q95_passed=False,
        )
        return HoldoutQualification(
            sample_count=0,
            delta_velocity_error_mps=nan_metric,
            rotation_geodesic_error_rad=nan_metric,
            passed=False,
            reject_reasons=_unique(reasons),
        )

    rotation = _tilt_rotation_and_derivatives(theta[6], theta[7])[0]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        candidate_force = np.einsum("ij,nj->ni", rotation, force - theta[:3])
        calibrated_force = force - calibrated_bias
        candidate_delta_velocity_error = _finite_scaled_norm(
            dt * (candidate_force - target_force),
            axis=1,
        )
        calibrated_delta_velocity_error = _finite_scaled_norm(
            dt * (calibrated_force - target_force),
            axis=1,
        )
        candidate_gyro = np.einsum("ij,nj->ni", rotation, gyro - theta[3:6])
        candidate_rotation_error = _rotvec_geodesic_errors(candidate_gyro * dt, target_gyro * dt)
        calibrated_rotation_error = _rotvec_geodesic_errors(gyro * dt, target_gyro * dt)
    delta_velocity_metric = _cal_relative_metric(
        candidate_delta_velocity_error,
        calibrated_delta_velocity_error,
        config,
    )
    rotation_metric = _cal_relative_metric(
        candidate_rotation_error,
        calibrated_rotation_error,
        config,
    )
    if not delta_velocity_metric.all_finite:
        reasons.append("holdout_delta_velocity_metric_nonfinite")
    if not rotation_metric.all_finite:
        reasons.append("holdout_rotation_geodesic_metric_nonfinite")
    if not delta_velocity_metric.rmse_passed:
        reasons.append("holdout_delta_velocity_rmse_not_cal_qualified")
    if not delta_velocity_metric.q95_passed:
        reasons.append("holdout_delta_velocity_q95_not_cal_qualified")
    if not rotation_metric.rmse_passed:
        reasons.append("holdout_rotation_geodesic_rmse_not_cal_qualified")
    if not rotation_metric.q95_passed:
        reasons.append("holdout_rotation_geodesic_q95_not_cal_qualified")
    return HoldoutQualification(
        sample_count=sample_count,
        delta_velocity_error_mps=delta_velocity_metric,
        rotation_geodesic_error_rad=rotation_metric,
        passed=not reasons,
        reject_reasons=_unique(reasons),
    )


def _cal_relative_metric(
    candidate_error: FloatArray,
    calibrated_error: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> CalRelativeMetric:
    errors_finite = bool(np.isfinite(candidate_error).all() and np.isfinite(calibrated_error).all())
    candidate_rmse = _finite_scaled_rmse(candidate_error)
    calibrated_rmse = _finite_scaled_rmse(calibrated_error)
    candidate_q95 = float(np.quantile(candidate_error, 0.95)) if errors_finite else math.inf
    calibrated_q95 = float(np.quantile(calibrated_error, 0.95)) if errors_finite else math.inf
    rmse_ratio = _safe_ratio(candidate_rmse, calibrated_rmse)
    q95_ratio = _safe_ratio(candidate_q95, calibrated_q95)
    all_finite = all(
        math.isfinite(value)
        for value in (
            candidate_rmse,
            calibrated_rmse,
            candidate_q95,
            calibrated_q95,
            rmse_ratio,
            q95_ratio,
        )
    )
    tolerance = config.qualification_absolute_tolerance
    rmse_limit = (1.0 - config.minimum_cal_rmse_improvement_fraction) * calibrated_rmse - tolerance
    q95_limit = (1.0 - config.minimum_cal_q95_improvement_fraction) * calibrated_q95 + tolerance
    return CalRelativeMetric(
        candidate_rmse=candidate_rmse,
        calibrated_rmse=calibrated_rmse,
        candidate_q95=candidate_q95,
        calibrated_q95=calibrated_q95,
        rmse_ratio_to_calibrated=rmse_ratio,
        q95_ratio_to_calibrated=q95_ratio,
        all_finite=all_finite,
        rmse_passed=(
            all_finite and candidate_rmse < calibrated_rmse and candidate_rmse <= rmse_limit
        ),
        q95_passed=all_finite and candidate_q95 <= q95_limit,
    )


def _state_bound_reasons(
    theta: FloatArray,
    config: FrozenVIOIMUObserverConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if bool(np.abs(theta[:3]).max() > config.maximum_abs_accelerometer_bias_mps2):
        reasons.append("accelerometer_bias_bound_exceeded")
    if bool(np.abs(theta[3:6]).max() > config.maximum_abs_gyroscope_bias_rad_s):
        reasons.append("gyroscope_bias_bound_exceeded")
    if bool(np.abs(theta[6:8]).max() > config.maximum_abs_tilt_rad):
        reasons.append("tilt_bound_exceeded")
    return tuple(reasons)


def canonical_observer_array_sha256(value: npt.ArrayLike) -> str:
    """Hash canonical little-endian float64 or byte-bool shape plus contents."""

    array = np.asarray(value)
    if np.issubdtype(array.dtype, np.floating):
        kind = b"float64-le"
        canonical = np.ascontiguousarray(array, dtype=np.dtype("<f8"))
    elif array.dtype == np.bool_:
        kind = b"bool-u8"
        canonical = np.ascontiguousarray(array, dtype=np.uint8)
    else:
        raise TypeError("canonical observer hashes accept only floating or bool arrays")
    digest = hashlib.sha256()
    digest.update(b"flightguard-observer-canonical-array-v1\0")
    digest.update(struct.pack("<I", len(kind)))
    digest.update(kind)
    digest.update(struct.pack("<I", canonical.ndim))
    digest.update(struct.pack(f"<{canonical.ndim}Q", *canonical.shape))
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _validate_baseline_provenance(
    provenance: FrozenObserverBaselineProvenance,
    *,
    fit_only_bias: FloatArray,
    operational_bias: FloatArray,
    valid_mask: BoolArray,
) -> tuple[str, ...]:
    if type(provenance) is not FrozenObserverBaselineProvenance:
        raise TypeError("baseline_provenance must be FrozenObserverBaselineProvenance")
    reasons: list[str] = []
    registered = _STRICTLY_LOADED_BASELINE_PROVENANCE.get(id(provenance))
    if (
        registered is None
        or registered[0] is not provenance
        or registered[1] != _baseline_provenance_binding_fingerprint(provenance)
        or not _is_sha256(registered[2])
    ):
        reasons.append("baseline_provenance_not_strict_artifact_loader_bound")
    if provenance.schema_version != BASELINE_PROVENANCE_SCHEMA_VERSION:
        reasons.append("baseline_provenance_schema_mismatch")
    if provenance.fit_only_calibration_source != FIT_ONLY_CALIBRATION_SOURCE:
        reasons.append("fit_only_calibration_source_untrusted")
    if provenance.operational_calibration_source != OPERATIONAL_CALIBRATION_SOURCE:
        reasons.append("operational_calibration_source_untrusted")
    if provenance.valid_transition_mask_source != VALID_TRANSITION_MASK_SOURCE:
        reasons.append("valid_transition_mask_source_untrusted")
    if provenance.fit_only_window != (FIT_START, FIT_STOP):
        reasons.append("fit_only_calibration_window_mismatch")
    if provenance.operational_window != (FIT_START, HOLDOUT_STOP):
        reasons.append("operational_calibration_window_mismatch")
    expected_fit_count = tuple(int(value) for value in valid_mask[FIT_START:FIT_STOP].sum(axis=0))
    expected_operational_count = tuple(
        int(value) for value in valid_mask[FIT_START:HOLDOUT_STOP].sum(axis=0)
    )
    if (
        any(type(value) is not int for value in provenance.fit_only_sample_count_by_lane)
        or provenance.fit_only_sample_count_by_lane != expected_fit_count
    ):
        reasons.append("fit_only_calibration_sample_count_mismatch")
    if (
        any(type(value) is not int for value in provenance.operational_sample_count_by_lane)
        or provenance.operational_sample_count_by_lane != expected_operational_count
    ):
        reasons.append("operational_calibration_sample_count_mismatch")
    expected_hashes = (
        (
            "fit_only_bias_sha256",
            provenance.fit_only_bias_sha256,
            canonical_observer_array_sha256(fit_only_bias),
        ),
        (
            "operational_bias_sha256",
            provenance.operational_bias_sha256,
            canonical_observer_array_sha256(operational_bias),
        ),
        (
            "valid_transition_mask_sha256",
            provenance.valid_transition_mask_sha256,
            canonical_observer_array_sha256(valid_mask),
        ),
    )
    for name, claimed, expected in expected_hashes:
        if not _is_sha256(claimed):
            reasons.append(f"{name}_malformed")
        elif claimed != expected:
            reasons.append(f"{name}_mismatch")
    if not _is_sha256(provenance.capture_artifact_sha256):
        reasons.append("capture_artifact_sha256_malformed")
    return _unique(reasons)


def _validate_provenance(
    provenance: FrozenObserverInputProvenance,
    *,
    exact_raw_native_specific_force: FloatArray | None,
    exact_raw_native_angular_velocity: FloatArray | None,
    estimator_delivered_profiled_specific_force: FloatArray,
    estimator_delivered_profiled_angular_velocity: FloatArray,
    vio_velocity_world: FloatArray,
    vio_quaternion_body_to_world: FloatArray,
    valid_transition_mask: BoolArray,
    dt: float,
) -> tuple[str, ...]:
    if type(provenance) is not FrozenObserverInputProvenance:
        raise TypeError("provenance must be FrozenObserverInputProvenance")
    for name in (
        "native_imu_was_cloned_at_record_time",
        "estimator_delivered_profiled_imu_was_captured_at_record_time",
        "vio_was_captured_at_record_time",
        "sensor_error_bank_was_preregistered_and_frozen",
        "apply_sensor_error_source_was_frozen",
        "sensor_profile_was_frozen",
        "specific_force_is_reconstructed_proxy",
    ):
        if type(getattr(provenance, name)) is not bool:
            raise TypeError(f"provenance.{name} must be exact bool")
    if provenance.binding_kind == LEGACY_UNBOUND_NATIVE_INPUT_BINDING:
        return ("legacy_unbound_native_imu_provenance",)
    if provenance.binding_kind == RECONSTRUCTED_PROXY_INPUT_BINDING:
        return ("reconstructed_specific_force_proxy_is_diagnostic_only",)

    reasons: list[str] = []
    registered = _STRICTLY_LOADED_PROVENANCE.get(id(provenance))
    if (
        registered is None
        or registered[0] is not provenance
        or registered[1] != _input_provenance_binding_fingerprint(provenance)
    ):
        reasons.append("input_provenance_not_strict_capture_loader_bound")
    if provenance.schema_version != PROVENANCE_SCHEMA_VERSION:
        reasons.append("input_provenance_schema_mismatch")
    if provenance.binding_kind != EXACT_PROFILED_INPUT_BINDING:
        reasons.append("input_provenance_binding_kind_untrusted")
    if (
        provenance.exact_raw_native_specific_force_body_source
        != EXACT_RAW_NATIVE_SPECIFIC_FORCE_SOURCE
    ):
        reasons.append("raw_specific_force_source_not_exact_native")
    if (
        provenance.exact_raw_native_angular_velocity_body_source
        != EXACT_RAW_NATIVE_ANGULAR_VELOCITY_SOURCE
    ):
        reasons.append("raw_angular_velocity_source_not_exact_native")
    if provenance.specific_force_body_source != RECORD_TIME_SPECIFIC_FORCE_SOURCE:
        if provenance.specific_force_is_reconstructed_proxy:
            reasons.append("reconstructed_specific_force_proxy_is_diagnostic_only")
        else:
            reasons.append("specific_force_not_estimator_delivered_profiled_imu")
    if provenance.angular_velocity_body_source != RECORD_TIME_ANGULAR_VELOCITY_SOURCE:
        reasons.append("angular_velocity_not_estimator_delivered_profiled_imu")
    if provenance.vio_velocity_world_source != RECORD_TIME_VIO_VELOCITY_SOURCE:
        reasons.append("velocity_not_record_time_vio")
    if provenance.vio_quaternion_body_to_world_source != RECORD_TIME_VIO_QUATERNION_SOURCE:
        reasons.append("quaternion_not_record_time_vio")
    if provenance.frozen_sensor_error_bank_source != FROZEN_SENSOR_ERROR_BANK_SOURCE:
        reasons.append("sensor_error_bank_source_not_preregistered_frozen")
    if provenance.frozen_apply_sensor_error_source != FROZEN_APPLY_SENSOR_ERROR_SOURCE:
        reasons.append("apply_sensor_error_source_not_frozen")
    if provenance.frozen_sensor_profile_source != FROZEN_SENSOR_PROFILE_SOURCE:
        reasons.append("sensor_profile_source_not_frozen")
    if (
        provenance.delivered_sample_causal_declaration
        != ESTIMATOR_DELIVERED_PROFILED_CAUSAL_DECLARATION
    ):
        reasons.append("delivered_sample_causal_declaration_mismatch")
    if not provenance.native_imu_was_cloned_at_record_time:
        reasons.append("native_imu_not_cloned_at_record_time")
    if not provenance.estimator_delivered_profiled_imu_was_captured_at_record_time:
        reasons.append("estimator_delivered_profiled_imu_not_captured_at_record_time")
    if not provenance.vio_was_captured_at_record_time:
        reasons.append("vio_not_captured_at_record_time")
    if not provenance.sensor_error_bank_was_preregistered_and_frozen:
        reasons.append("sensor_error_bank_not_preregistered_and_frozen")
    if not provenance.apply_sensor_error_source_was_frozen:
        reasons.append("apply_sensor_error_source_not_frozen")
    if not provenance.sensor_profile_was_frozen:
        reasons.append("sensor_profile_not_frozen")
    if provenance.specific_force_is_reconstructed_proxy and (
        provenance.specific_force_body_source == RECORD_TIME_SPECIFIC_FORCE_SOURCE
    ):
        reasons.append("contradictory_specific_force_provenance")
    if exact_raw_native_specific_force is None:
        reasons.append("exact_raw_native_specific_force_history_missing")
    if exact_raw_native_angular_velocity is None:
        reasons.append("exact_raw_native_angular_velocity_history_missing")

    declared_hashes = (
        (
            "exact_raw_native_specific_force_sha256",
            provenance.exact_raw_native_specific_force_sha256,
            exact_raw_native_specific_force,
        ),
        (
            "exact_raw_native_angular_velocity_sha256",
            provenance.exact_raw_native_angular_velocity_sha256,
            exact_raw_native_angular_velocity,
        ),
        (
            "estimator_delivered_profiled_specific_force_sha256",
            provenance.estimator_delivered_profiled_specific_force_sha256,
            estimator_delivered_profiled_specific_force,
        ),
        (
            "estimator_delivered_profiled_angular_velocity_sha256",
            provenance.estimator_delivered_profiled_angular_velocity_sha256,
            estimator_delivered_profiled_angular_velocity,
        ),
        (
            "vio_velocity_world_sha256",
            provenance.vio_velocity_world_sha256,
            vio_velocity_world,
        ),
        (
            "vio_quaternion_body_to_world_sha256",
            provenance.vio_quaternion_body_to_world_sha256,
            vio_quaternion_body_to_world,
        ),
        (
            "valid_transition_mask_sha256",
            provenance.valid_transition_mask_sha256,
            valid_transition_mask,
        ),
    )
    for name, claimed, actual in declared_hashes:
        if not _is_sha256(claimed):
            reasons.append(f"{name}_malformed")
        elif actual is not None and claimed != canonical_observer_array_sha256(actual):
            reasons.append(f"{name}_mismatch")
    dt_bytes = struct.pack("<d", dt)
    expected_dt_hex = dt_bytes.hex()
    expected_dt_sha256 = hashlib.sha256(dt_bytes).hexdigest()
    if (
        not isinstance(provenance.dt_seconds_float64_le_hex, str)
        or len(provenance.dt_seconds_float64_le_hex) != 16
        or any(
            character not in "0123456789abcdef"
            for character in provenance.dt_seconds_float64_le_hex
        )
    ):
        reasons.append("dt_seconds_float64_le_hex_malformed")
    elif provenance.dt_seconds_float64_le_hex != expected_dt_hex:
        reasons.append("dt_seconds_float64_le_hex_mismatch")
    if not _is_sha256(provenance.dt_seconds_float64_le_sha256):
        reasons.append("dt_seconds_float64_le_sha256_malformed")
    elif provenance.dt_seconds_float64_le_sha256 != expected_dt_sha256:
        reasons.append("dt_seconds_float64_le_sha256_mismatch")
    for name, claimed in (
        (
            "frozen_sensor_error_bank_sha256",
            provenance.frozen_sensor_error_bank_sha256,
        ),
        (
            "apply_sensor_error_source_sha256",
            provenance.apply_sensor_error_source_sha256,
        ),
        ("frozen_sensor_profile_sha256", provenance.frozen_sensor_profile_sha256),
        ("capture_artifact_sha256", provenance.capture_artifact_sha256),
    ):
        if not _is_sha256(claimed):
            reasons.append(f"{name}_malformed")
    return _unique(reasons)


def _input_provenance_binding_fingerprint(
    provenance: FrozenObserverInputProvenance,
) -> str:
    """Fingerprint every public provenance field for loader-bound identity."""

    digest = hashlib.sha256()
    digest.update(b"flightguard-strict-capture-loaded-provenance-v1\0")
    for name, value in vars(provenance).items():
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if type(value) is bool:
            digest.update(b"bool\0")
            digest.update(b"1" if value else b"0")
        elif isinstance(value, str):
            encoded = value.encode("utf-8")
            digest.update(b"str\0")
            digest.update(struct.pack("<Q", len(encoded)))
            digest.update(encoded)
        else:
            raise TypeError(f"provenance field {name} must be exact bool or str for binding")
        digest.update(b"\0")
    return digest.hexdigest()


def _baseline_provenance_binding_fingerprint(
    provenance: FrozenObserverBaselineProvenance,
) -> str:
    """Fingerprint every public baseline field for loader-bound identity."""

    digest = hashlib.sha256()
    digest.update(b"flightguard-strict-baseline-loaded-provenance-v1\0")
    for field in fields(provenance):
        name = field.name
        value = getattr(provenance, name)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if type(value) is str:
            encoded = value.encode("utf-8")
            digest.update(b"str\0")
            digest.update(struct.pack("<Q", len(encoded)))
            digest.update(encoded)
        elif type(value) is tuple:
            digest.update(b"tuple-int\0")
            digest.update(struct.pack("<Q", len(value)))
            for item in value:
                if type(item) is not int:
                    raise TypeError(f"baseline provenance field {name} must contain exact ints")
                encoded = str(item).encode("ascii")
                digest.update(struct.pack("<Q", len(encoded)))
                digest.update(encoded)
        else:
            raise TypeError(f"baseline provenance field {name} must be exact str or tuple")
        digest.update(b"\0")
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(name: str, value: Any) -> None:
    if not _is_sha256(value):
        raise ValueError(f"{name} must be a lowercase 64-hex SHA256")


def _float_array(
    name: str,
    value: npt.ArrayLike,
    expected_shape: tuple[int | None, ...],
) -> FloatArray:
    array = np.asarray(value)
    if array.ndim != len(expected_shape):
        raise ValueError(f"{name} must have {len(expected_shape)} dimensions")
    for actual, expected in zip(array.shape, expected_shape):
        if expected is not None and actual != expected:
            raise ValueError(f"{name} must have shape {expected_shape}")
    if array.shape[1] <= 0:
        raise ValueError(f"{name} batch dimension must be positive")
    if not np.issubdtype(array.dtype, np.floating):
        raise TypeError(f"{name} must be floating-point")
    return np.asarray(array, dtype=np.float64)


def _validate_dt(dt: float) -> float:
    if isinstance(dt, bool):
        raise TypeError("dt must be a finite positive number")
    try:
        value = float(dt)
    except (TypeError, ValueError) as error:
        raise ValueError("dt must be finite and positive") from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("dt must be finite and positive")
    return value


def _tilt_rotation_and_derivatives(
    roll: float,
    pitch: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    cosine_roll = math.cos(float(roll))
    sine_roll = math.sin(float(roll))
    cosine_pitch = math.cos(float(pitch))
    sine_pitch = math.sin(float(pitch))
    rotation_x = np.array(
        (
            (1.0, 0.0, 0.0),
            (0.0, cosine_roll, -sine_roll),
            (0.0, sine_roll, cosine_roll),
        ),
        dtype=np.float64,
    )
    derivative_x = np.array(
        (
            (0.0, 0.0, 0.0),
            (0.0, -sine_roll, -cosine_roll),
            (0.0, cosine_roll, -sine_roll),
        ),
        dtype=np.float64,
    )
    rotation_y = np.array(
        (
            (cosine_pitch, 0.0, sine_pitch),
            (0.0, 1.0, 0.0),
            (-sine_pitch, 0.0, cosine_pitch),
        ),
        dtype=np.float64,
    )
    derivative_y = np.array(
        (
            (-sine_pitch, 0.0, cosine_pitch),
            (0.0, 0.0, 0.0),
            (-cosine_pitch, 0.0, -sine_pitch),
        ),
        dtype=np.float64,
    )
    return (
        rotation_x @ rotation_y,
        derivative_x @ rotation_y,
        rotation_x @ derivative_y,
    )


def _quaternion_to_rotation_matrix(quaternion: FloatArray) -> FloatArray:
    w, x, y, z = np.moveaxis(quaternion, -1, 0)
    return np.stack(
        (
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - w * z),
            2.0 * (x * z + w * y),
            2.0 * (x * y + w * z),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - w * x),
            2.0 * (x * z - w * y),
            2.0 * (y * z + w * x),
            1.0 - 2.0 * (x * x + y * y),
        ),
        axis=-1,
    ).reshape(*quaternion.shape[:-1], 3, 3)


def _relative_quaternion_rotvec(
    first: FloatArray,
    second: FloatArray,
) -> FloatArray:
    conjugate = first.copy()
    conjugate[..., 1:] *= -1.0
    relative = _quaternion_multiply(conjugate, second)
    relative_norm = _finite_scaled_norm(relative, axis=-1, keepdims=True)
    relative = relative / np.maximum(relative_norm, np.finfo(np.float64).tiny)
    relative = np.where(relative[..., :1] < 0.0, -relative, relative)
    vector = relative[..., 1:]
    vector_norm = _finite_scaled_norm(vector, axis=-1, keepdims=True)
    angle = 2.0 * np.arctan2(vector_norm, np.clip(relative[..., :1], 0.0, 1.0))
    scale = np.divide(
        angle,
        vector_norm,
        out=np.full_like(angle, 2.0),
        where=vector_norm > 1.0e-12,
    )
    return vector * scale


def _quaternion_multiply(left: FloatArray, right: FloatArray) -> FloatArray:
    lw, lx, ly, lz = np.moveaxis(left, -1, 0)
    rw, rx, ry, rz = np.moveaxis(right, -1, 0)
    return np.stack(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ),
        axis=-1,
    )


def _rotvec_to_rotation_matrix(rotation_vector: FloatArray) -> FloatArray:
    angle = _finite_scaled_norm(rotation_vector, axis=-1)
    skew = np.zeros((*rotation_vector.shape[:-1], 3, 3), dtype=np.float64)
    x, y, z = np.moveaxis(rotation_vector, -1, 0)
    skew[..., 0, 1] = -z
    skew[..., 0, 2] = y
    skew[..., 1, 0] = z
    skew[..., 1, 2] = -x
    skew[..., 2, 0] = -y
    skew[..., 2, 1] = x
    angle_squared = np.square(angle)
    sine_scale = np.divide(
        np.sin(angle),
        angle,
        out=np.ones_like(angle),
        where=angle > 1.0e-12,
    )
    cosine_scale = np.divide(
        1.0 - np.cos(angle),
        angle_squared,
        out=np.full_like(angle, 0.5),
        where=angle > 1.0e-12,
    )
    identity = np.broadcast_to(np.eye(3, dtype=np.float64), skew.shape)
    return (
        identity
        + sine_scale[..., None, None] * skew
        + cosine_scale[..., None, None] * (skew @ skew)
    )


def _rotvec_geodesic_errors(
    predicted_rotation_vector: FloatArray,
    target_rotation_vector: FloatArray,
) -> FloatArray:
    predicted = _rotvec_to_rotation_matrix(predicted_rotation_vector)
    target = _rotvec_to_rotation_matrix(target_rotation_vector)
    relative = predicted.transpose(0, 2, 1) @ target
    cosine = np.clip((np.trace(relative, axis1=1, axis2=2) - 1.0) * 0.5, -1.0, 1.0)
    return np.arccos(cosine)


def _rotation_geodesic(first: FloatArray, second: FloatArray) -> float:
    relative = first.T @ second
    cosine = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
    return float(math.acos(cosine))


def _state_from_theta(theta: FloatArray) -> FrozenObserverState:
    return FrozenObserverState(
        accelerometer_bias_body_mps2=_tuple3(theta[:3]),
        gyroscope_bias_body_rad_s=_tuple3(theta[3:6]),
        delta_roll_pitch_rad=(float(theta[6]), float(theta[7])),
    )


def _tuple3(values: npt.ArrayLike) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=np.float64)
    return (float(array[0]), float(array[1]), float(array[2]))


def _finite_scaled_norm(
    value: npt.ArrayLike,
    *,
    axis: int | tuple[int, ...] | None = None,
    keepdims: bool = False,
) -> npt.NDArray[np.float64] | np.float64:
    """Overflow-safe L2 norm that maps every nonfinite slice to infinity."""

    array = np.asarray(value, dtype=np.float64)
    finite = np.isfinite(array)
    finite_slice = np.all(finite, axis=axis, keepdims=True)
    maximum = np.max(
        np.where(finite, np.abs(array), 0.0),
        axis=axis,
        keepdims=True,
    )
    safe_maximum = np.where(maximum > 0.0, maximum, 1.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        scaled = array / safe_maximum
        result = safe_maximum * np.sqrt(np.sum(np.square(scaled), axis=axis, keepdims=True))
    result = np.where(finite_slice, result, math.inf)
    if keepdims:
        return result
    if axis is None:
        return np.asarray(result).reshape(()).astype(np.float64)[()]
    return np.squeeze(result, axis=axis)


def _finite_scaled_rmse(value: npt.ArrayLike) -> float:
    """Overflow-safe scalar RMSE, rejecting empty or nonfinite inputs."""

    array = np.asarray(value, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        return math.inf
    maximum = float(np.max(np.abs(array)))
    if maximum == 0.0:
        return 0.0
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        result = maximum * math.sqrt(float(np.mean(np.square(array / maximum))))
    return float(result) if math.isfinite(result) else math.inf


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return math.inf
    if denominator > 0.0:
        ratio = numerator / denominator
        return ratio if math.isfinite(ratio) else math.inf
    return 0.0 if numerator == 0.0 else math.inf


def _window_label(start: int, stop: int) -> str:
    if (start, stop) == (FIT_START, FIT_STOP):
        return "full_fit"
    if (start, stop) == (FIT_START, (FIT_START + FIT_STOP) // 2):
        return "first_fit_half"
    if (start, stop) == ((FIT_START + FIT_STOP) // 2, FIT_STOP):
        return "second_fit_half"
    return f"fit_{start}_{stop}"


def _unique(values: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))
