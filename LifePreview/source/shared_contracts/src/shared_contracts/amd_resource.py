from __future__ import annotations

import hmac
import inspect
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    model_validator,
)

from .models import StrictFrozenModel, canonical_json, stable_json_sha256


AMD_HARD_MEMORY_MAX_BYTES = 59_055_800_320
AMD_WARN_MEMORY_BYTES = 47_244_640_256
AMD_DRAIN_MEMORY_BYTES = 53_150_220_288
AMD_RECOVERY_MEMORY_BYTES = 44_291_850_240
AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS = 5
AMD_ADMISSION_LEASE_MAX_SECONDS = 4


def _require_true(value: bool) -> bool:
    if value is not True:
        raise ValueError("value must be true")
    return value


def _require_false(value: bool) -> bool:
    if value is not False:
        raise ValueError("value must be false")
    return value


StrictNonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
StrictPositiveInt = Annotated[int, Field(strict=True, gt=0)]
StrictZeroInt = Annotated[int, Field(strict=True, ge=0, le=0)]
StrictOneInt = Annotated[int, Field(strict=True, ge=1, le=1)]
StrictTwoInt = Annotated[int, Field(strict=True, ge=2, le=2)]
StrictBoolean = Annotated[bool, Field(strict=True)]
StrictTrue = Annotated[bool, Field(strict=True), AfterValidator(_require_true)]
StrictFalse = Annotated[bool, Field(strict=True), AfterValidator(_require_false)]


class AMDModelFamily(StrEnum):
    FLUX2_DEV = "flux2-dev"
    MINIMAX_H3 = "minimax-h3"


class AMDAdmissionReason(StrEnum):
    MEMORY_MAX_INVALID = "memory_max_invalid"
    SWAP_NOT_DISABLED = "swap_not_disabled"
    SNAPSHOT_STALE = "snapshot_stale"
    SNAPSHOT_TIME_INVALID = "snapshot_time_invalid"
    COUNTER_REGRESSION = "counter_regression"
    OOM_COUNTER_NONZERO = "oom_counter_nonzero"
    OOM_COUNTER_INCREASE = "oom_counter_increase"
    MEMORY_WARN_THRESHOLD = "memory_warn_threshold"
    MEMORY_DRAIN_THRESHOLD = "memory_drain_threshold"
    MEMORY_DRAIN_THRESHOLD_CROSSED = "memory_drain_threshold_crossed"
    MEMORY_MAX_EVENT_INCREASE = "memory_max_event_increase"
    CGROUP_GENERATION_MISMATCH = "cgroup_generation_mismatch"
    LOCAL_GPU_TASK_ACTIVE = "local_gpu_task_active"
    OTHER_MODEL_RESIDENT = "other_model_resident"
    RESERVATION_NOT_ACQUIRED = "reservation_not_acquired"
    RESERVATION_BINDING_MISMATCH = "reservation_binding_mismatch"
    LEASE_AUTHORITY_UNTRUSTED = "lease_authority_untrusted"
    RECOVERY_AUTHORITY_UNTRUSTED = "recovery_authority_untrusted"
    RECOVERY_BINDING_MISMATCH = "recovery_binding_mismatch"
    PRESSURE_RECOVERY_INCOMPLETE = "pressure_recovery_incomplete"
    PRESSURE_RECOVERY_PENDING_COMMIT = "pressure_recovery_pending_commit"


class AMDMemoryPressureBand(StrEnum):
    NOMINAL = "nominal"
    WARN = "warn"
    DRAIN = "drain"


class AMDCgroupV2MemoryEventsV1(StrictFrozenModel):
    low: StrictNonNegativeInt
    high: StrictNonNegativeInt
    max: StrictNonNegativeInt
    oom: StrictNonNegativeInt
    oom_kill: StrictNonNegativeInt
    oom_group_kill: StrictNonNegativeInt

    def as_counter_tuple(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.low,
            self.high,
            self.max,
            self.oom,
            self.oom_kill,
            self.oom_group_kill,
        )

    def as_oom_counter_tuple(self) -> tuple[int, int, int]:
        return (self.oom, self.oom_kill, self.oom_group_kill)


ObservedLimit = StrictNonNegativeInt | Literal["max"] | None


class AMDResourceSnapshotV1(StrictFrozenModel):
    cgroup_version: StrictTwoInt
    cgroup_generation_id: UUID
    snapshot_sequence: StrictPositiveInt
    captured_at: AwareDatetime
    memory_current_bytes: StrictNonNegativeInt
    memory_peak_bytes: StrictNonNegativeInt
    memory_max_bytes: ObservedLimit
    memory_swap_current_bytes: StrictZeroInt
    memory_swap_max_bytes: ObservedLimit
    memory_events: AMDCgroupV2MemoryEventsV1
    vram_total_bytes: StrictPositiveInt
    vram_used_bytes: StrictNonNegativeInt

    @model_validator(mode="after")
    def validate_resource_bounds(self) -> AMDResourceSnapshotV1:
        if self.memory_peak_bytes < self.memory_current_bytes:
            raise ValueError("memory peak cannot be lower than memory current")
        if self.vram_used_bytes > self.vram_total_bytes:
            raise ValueError("VRAM used cannot exceed VRAM total")
        return self


class AMDExecutionTopologyV1(StrictFrozenModel):
    gpu_count: StrictOneInt
    comfyui_instance_count: StrictOneInt
    video_worker_count: StrictOneInt
    single_gpu_serial_execution: StrictTrue
    flux_h3_mutually_exclusive: StrictTrue
    active_local_gpu_task_id: UUID | None
    active_task_model_family: AMDModelFamily | None
    resident_model_family: AMDModelFamily | None
    resident_model_unload_confirmed: StrictBoolean
    in_flight_delivery: StrictBoolean

    @model_validator(mode="after")
    def validate_active_gpu_authority(self) -> AMDExecutionTopologyV1:
        task_is_active = self.active_local_gpu_task_id is not None
        task_model_is_declared = self.active_task_model_family is not None
        if task_is_active != task_model_is_declared:
            raise ValueError("active GPU task and task model must be declared together")
        if self.resident_model_family is None:
            if not self.resident_model_unload_confirmed:
                raise ValueError("absent resident model requires confirmed unload")
        elif self.resident_model_unload_confirmed:
            raise ValueError("resident model cannot also be confirmed unloaded")
        if task_is_active and self.resident_model_family != self.active_task_model_family:
            raise ValueError("active task model must be the resident model")
        if self.in_flight_delivery and not task_is_active:
            raise ValueError("in-flight delivery requires an active local GPU task")
        return self


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
AuthorityKeyId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]

class AMDRecoveryHealthSampleV1(StrictFrozenModel):
    sample_id: UUID
    sample_ordinal: StrictPositiveInt
    drain_epoch: StrictPositiveInt
    cgroup_generation_id: UUID
    snapshot_sequence: StrictPositiveInt
    captured_at: AwareDatetime
    valid_until: AwareDatetime
    memory_current_bytes: Annotated[
        int,
        Field(strict=True, ge=0, lt=AMD_RECOVERY_MEMORY_BYTES),
    ]
    memory_events_low: StrictNonNegativeInt
    memory_events_high: StrictNonNegativeInt
    memory_events_max: StrictNonNegativeInt
    memory_events_oom: StrictZeroInt
    memory_events_oom_kill: StrictZeroInt
    memory_events_oom_group_kill: StrictZeroInt
    sample_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_sample_digest(self) -> AMDRecoveryHealthSampleV1:
        if self.valid_until <= self.captured_at:
            raise ValueError("AMD recovery health sample must have a validity window")
        identity = self.model_dump(mode="json", exclude={"sample_digest"})
        actual = stable_json_sha256(identity)
        if not hmac.compare_digest(actual, self.sample_digest):
            raise ValueError("AMD recovery health sample digest mismatch")
        return self


class AMDUnloadConfirmationAuthorityV1(StrictFrozenModel):
    confirmation_id: UUID
    drain_epoch: StrictPositiveInt
    cgroup_generation_id: UUID
    unloaded_model_family: AMDModelFamily
    confirmed_at: AwareDatetime
    confirmation_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_confirmation_digest(self) -> AMDUnloadConfirmationAuthorityV1:
        identity = self.model_dump(mode="json", exclude={"confirmation_digest"})
        actual = stable_json_sha256(identity)
        if not hmac.compare_digest(actual, self.confirmation_digest):
            raise ValueError("AMD unload confirmation digest mismatch")
        return self


class AMDPressureEventWatermarkV1(StrictFrozenModel):
    cgroup_generation_id: UUID
    snapshot_sequence: StrictNonNegativeInt
    memory_events_low: StrictNonNegativeInt
    memory_events_high: StrictNonNegativeInt
    memory_events_max: StrictNonNegativeInt
    memory_events_oom: StrictNonNegativeInt
    memory_events_oom_kill: StrictNonNegativeInt
    memory_events_oom_group_kill: StrictNonNegativeInt

    def as_counter_tuple(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.memory_events_low,
            self.memory_events_high,
            self.memory_events_max,
            self.memory_events_oom,
            self.memory_events_oom_kill,
            self.memory_events_oom_group_kill,
        )


class AMDAdmissionLeaseAuthorityV1(StrictFrozenModel):
    schema_version: Literal["amd.admission-lease-authority.v1"]
    authority_key_id: AuthorityKeyId
    mac_algorithm: Literal["hmac-sha256"]
    lease_id: UUID
    lease_epoch: StrictPositiveInt
    fencing_token: StrictPositiveInt
    expected_version: StrictNonNegativeInt
    observed_version: StrictNonNegativeInt
    committed_version: StrictNonNegativeInt
    cas_acquired: StrictBoolean
    reserved_submission_id: UUID
    requested_model_family: AMDModelFamily
    cgroup_generation_id: UUID
    expires_at: AwareDatetime
    binding_payload_digest: Sha256Digest
    authority_mac: Sha256Digest

    def authority_mac_payload(self) -> bytes:
        identity = self.model_dump(mode="json", exclude={"authority_mac"})
        return canonical_json(identity).encode("utf-8")  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_atomic_cas_result(self) -> AMDAdmissionLeaseAuthorityV1:
        if self.cas_acquired:
            if self.observed_version != self.expected_version:
                raise ValueError("acquired lease must observe the expected version")
            if self.committed_version != self.expected_version + 1:
                raise ValueError("acquired lease must atomically advance one version")
        elif self.committed_version != self.observed_version:
            raise ValueError("failed lease CAS must report the observed version")
        identity = self.model_dump(
            mode="json",
            exclude={"binding_payload_digest", "authority_mac"},
        )
        actual = stable_json_sha256(identity)
        if not hmac.compare_digest(actual, self.binding_payload_digest):
            raise ValueError("AMD admission lease binding digest mismatch")
        return self


class AMDPressureRecoveryAuthorityV1(StrictFrozenModel):
    schema_version: Literal["amd.pressure-recovery-authority.v1"]
    authority_key_id: AuthorityKeyId
    mac_algorithm: Literal["hmac-sha256"]
    state_version: StrictPositiveInt
    fencing_token: StrictPositiveInt
    admission_lease_id: UUID
    admission_lease_epoch: StrictPositiveInt
    admission_lease_committed_version: StrictNonNegativeInt
    requested_model_family: AMDModelFamily
    cgroup_generation_id: UUID
    drain_epoch: StrictNonNegativeInt
    recovered_epoch: StrictNonNegativeInt
    drain_opened_at: AwareDatetime | None
    consumed_event_watermark: AMDPressureEventWatermarkV1
    unload_confirmation: AMDUnloadConfirmationAuthorityV1 | None
    healthy_samples: tuple[AMDRecoveryHealthSampleV1, ...] = Field(max_length=16)
    required_consecutive_healthy_snapshots: StrictTwoInt
    recovery_payload_digest: Sha256Digest
    authority_mac: Sha256Digest

    def authority_mac_payload(self) -> bytes:
        identity = self.model_dump(mode="json", exclude={"authority_mac"})
        return canonical_json(identity).encode("utf-8")  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_recovery_epochs(self) -> AMDPressureRecoveryAuthorityV1:
        if self.recovered_epoch > self.drain_epoch:
            raise ValueError("recovered epoch cannot exceed drain epoch")
        if (
            self.consumed_event_watermark.cgroup_generation_id
            != self.cgroup_generation_id
        ):
            raise ValueError("consumed event watermark cgroup generation mismatch")
        if self.drain_epoch == 0:
            if (
                self.recovered_epoch != 0
                or self.drain_opened_at is not None
                or self.unload_confirmation is not None
                or self.healthy_samples
            ):
                raise ValueError("initial pressure authority cannot claim recovery")
        elif self.drain_opened_at is None:
            raise ValueError("drain authority requires its open timestamp")

        if self.unload_confirmation is not None:
            if self.unload_confirmation.drain_epoch != self.drain_epoch:
                raise ValueError("unload confirmation must bind the current drain epoch")
            if (
                self.unload_confirmation.cgroup_generation_id
                != self.cgroup_generation_id
            ):
                raise ValueError("unload confirmation cgroup generation mismatch")
            if (
                self.unload_confirmation.unloaded_model_family
                != self.requested_model_family
            ):
                raise ValueError("unload confirmation model family mismatch")
            if (
                self.drain_opened_at is None
                or self.unload_confirmation.confirmed_at <= self.drain_opened_at
            ):
                raise ValueError("unload confirmation must follow drain opening")

        sample_ids = tuple(sample.sample_id for sample in self.healthy_samples)
        sample_digests = tuple(
            sample.sample_digest for sample in self.healthy_samples
        )
        sample_ordinals = tuple(
            sample.sample_ordinal for sample in self.healthy_samples
        )
        sample_times = tuple(sample.captured_at for sample in self.healthy_samples)
        snapshot_sequences = tuple(
            sample.snapshot_sequence for sample in self.healthy_samples
        )
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("recovery health sample ids must be unique")
        if len(sample_digests) != len(set(sample_digests)):
            raise ValueError("recovery health sample digests must be unique")
        if sample_ordinals != tuple(range(1, len(sample_ordinals) + 1)):
            raise ValueError("recovery health samples must have a strict sequence")
        if sample_times != tuple(sorted(sample_times)) or len(sample_times) != len(
            set(sample_times)
        ):
            raise ValueError("recovery health sample times must be strictly ordered")
        if snapshot_sequences and snapshot_sequences != tuple(
            range(
                snapshot_sequences[0],
                snapshot_sequences[0] + len(snapshot_sequences),
            )
        ):
            raise ValueError("recovery snapshot sequences must be contiguous")
        for sample in self.healthy_samples:
            if sample.drain_epoch != self.drain_epoch:
                raise ValueError("health sample must bind the current drain epoch")
            if sample.cgroup_generation_id != self.cgroup_generation_id:
                raise ValueError("health sample cgroup generation mismatch")
            if self.drain_opened_at is None or sample.captured_at <= self.drain_opened_at:
                raise ValueError("health sample must be captured after drain opening")
            if (
                sample.snapshot_sequence
                <= self.consumed_event_watermark.snapshot_sequence
            ):
                raise ValueError("health sample must follow consumed pressure evidence")
            if (
                sample.memory_events_low
                < self.consumed_event_watermark.memory_events_low
                or sample.memory_events_high
                < self.consumed_event_watermark.memory_events_high
                or sample.memory_events_max
                < self.consumed_event_watermark.memory_events_max
                or sample.memory_events_oom
                < self.consumed_event_watermark.memory_events_oom
                or sample.memory_events_oom_kill
                < self.consumed_event_watermark.memory_events_oom_kill
                or sample.memory_events_oom_group_kill
                < self.consumed_event_watermark.memory_events_oom_group_kill
            ):
                raise ValueError("health sample event counters cannot regress")
            if (
                self.unload_confirmation is not None
                and sample.captured_at <= self.unload_confirmation.confirmed_at
            ):
                raise ValueError("health sample must follow confirmed model unload")

        if self.recovered_epoch == self.drain_epoch and self.drain_epoch > 0:
            if self.unload_confirmation is None:
                raise ValueError("closed recovery epoch requires unload authority")
            if len(self.healthy_samples) != self.required_consecutive_healthy_snapshots:
                raise ValueError("closed recovery epoch requires exactly two samples")

        identity = self.model_dump(
            mode="json",
            exclude={"recovery_payload_digest", "authority_mac"},
        )
        actual = stable_json_sha256(identity)
        if not hmac.compare_digest(actual, self.recovery_payload_digest):
            raise ValueError("AMD pressure recovery binding digest mismatch")
        return self


class AMDTrustedAuthorityVerifier(Protocol):
    def verify_admission_lease(
        self,
        receipt: AMDAdmissionLeaseAuthorityV1,
        *,
        trusted_now: datetime,
        expected_lease_epoch: int,
        expected_fencing_token: int,
        expected_lease_cas_version: int,
    ) -> bool: ...

    def verify_pressure_recovery(
        self,
        receipt: AMDPressureRecoveryAuthorityV1,
        *,
        trusted_now: datetime,
        expected_state_version: int,
        expected_lease_epoch: int,
        expected_fencing_token: int,
        expected_lease_cas_version: int,
        expected_consumed_event_watermark: AMDPressureEventWatermarkV1,
    ) -> bool: ...

    def verify_and_consume_admission(
        self,
        request: AMDResourceAdmissionRequestV1,
        decision: AMDProvisionalResourceAdmissionDecisionV1,
        *,
        request_digest: str,
        decision_digest: str,
        cgroup_generation_id: UUID,
        lease_epoch: int,
        fencing_token: int,
        expected_state_version: int,
        expected_lease_cas_version: int,
        expected_consumed_event_watermark: AMDPressureEventWatermarkV1,
        trusted_now: datetime,
    ) -> bool:
        """Authenticate and consume with one fail-closed persisted-state CAS.

        The implementation must compare every explicit expected value with the
        same trusted record, bind both digests to the supplied objects, reject a
        previously consumed lease/submission, and commit consumption atomically.
        The record and consumed marker must be durable across process restarts;
        an instance-local set is not compliant. Concurrent verifier instances
        must serialize on the same storage CAS. Returning anything except the
        literal boolean ``True`` is rejection.
        """
        ...


def _strict_authority_verifier_result(call) -> bool:
    try:
        result = call()
    except Exception:
        return False
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        return False
    return result is True


class AMDResourceAdmissionRequestV1(StrictFrozenModel):
    submission_id: UUID
    requested_model_family: AMDModelFamily
    evaluated_at: AwareDatetime
    before_snapshot: AMDResourceSnapshotV1
    after_snapshot: AMDResourceSnapshotV1
    topology: AMDExecutionTopologyV1
    admission_lease: AMDAdmissionLeaseAuthorityV1
    pressure_recovery: AMDPressureRecoveryAuthorityV1


class AMDProvisionalResourceAdmissionDecisionV1(StrictFrozenModel):
    """Non-authoritative evaluation output; atomic verification is mandatory."""

    submission_id: UUID
    requested_model_family: AMDModelFamily
    cgroup_generation_id: UUID
    before_snapshot: AMDResourceSnapshotV1
    after_snapshot: AMDResourceSnapshotV1
    pressure_band: AMDMemoryPressureBand
    authorization_state: Literal["provisional_non_authoritative"]
    provisional_admit_new_work: StrictBoolean
    reasons: tuple[AMDAdmissionReason, ...] = Field(max_length=32)
    stop_accepting_next: StrictBoolean
    request_unload_after_in_flight: StrictBoolean
    request_recovery: StrictBoolean
    new_pressure_increment: StrictBoolean
    open_drain_epoch: StrictNonNegativeInt | None
    next_consumed_event_watermark: AMDPressureEventWatermarkV1 | None
    complete_recovery_epoch: StrictNonNegativeInt | None
    terminate_in_flight_delivery: StrictFalse
    in_flight_policy: Literal["preserve_until_delivery"]
    admission_lease: AMDAdmissionLeaseAuthorityV1
    pressure_recovery: AMDPressureRecoveryAuthorityV1
    topology: AMDExecutionTopologyV1
    lease_authority_verified: StrictBoolean
    recovery_authority_verified: StrictBoolean
    evaluated_at: AwareDatetime
    decision_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_decision_consistency(
        self,
    ) -> AMDProvisionalResourceAdmissionDecisionV1:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("admission reasons must be unique")
        if self.provisional_admit_new_work != (not self.reasons):
            raise ValueError("admission must fail closed when any reason is present")
        reason_set = set(self.reasons)
        active_task = self.topology.active_local_gpu_task_id is not None
        if (AMDAdmissionReason.LOCAL_GPU_TASK_ACTIVE in reason_set) != active_task:
            raise ValueError("active-task reason does not match topology authority")
        other_model_resident = (
            self.topology.resident_model_family is not None
            and self.topology.resident_model_family != self.requested_model_family
        )
        if (
            AMDAdmissionReason.OTHER_MODEL_RESIDENT in reason_set
        ) != other_model_resident:
            raise ValueError("resident-model reason does not match topology authority")
        lease_binding_matches = (
            self.admission_lease.reserved_submission_id == self.submission_id
            and self.admission_lease.requested_model_family
            == self.requested_model_family
            and self.admission_lease.cgroup_generation_id
            == self.cgroup_generation_id
        )
        recovery_binding_matches = (
            self.pressure_recovery.requested_model_family
            == self.requested_model_family
            and self.pressure_recovery.cgroup_generation_id
            == self.cgroup_generation_id
            and self.pressure_recovery.admission_lease_id
            == self.admission_lease.lease_id
            and self.pressure_recovery.admission_lease_epoch
            == self.admission_lease.lease_epoch
            and self.pressure_recovery.admission_lease_committed_version
            == self.admission_lease.committed_version
            and self.pressure_recovery.fencing_token
            == self.admission_lease.fencing_token
        )
        if self.after_snapshot.cgroup_generation_id != self.cgroup_generation_id:
            raise ValueError("decision cgroup generation must match its after snapshot")
        snapshots_same_generation = (
            self.before_snapshot.cgroup_generation_id
            == self.after_snapshot.cgroup_generation_id
        )
        if (
            AMDAdmissionReason.CGROUP_GENERATION_MISMATCH in reason_set
        ) == snapshots_same_generation:
            raise ValueError("cgroup generation reason is inconsistent")
        if (
            AMDAdmissionReason.RESERVATION_BINDING_MISMATCH in reason_set
        ) == lease_binding_matches:
            raise ValueError("reservation binding reason is inconsistent")
        if (
            AMDAdmissionReason.RECOVERY_BINDING_MISMATCH in reason_set
        ) == recovery_binding_matches:
            raise ValueError("recovery binding reason is inconsistent")
        if (
            AMDAdmissionReason.LEASE_AUTHORITY_UNTRUSTED in reason_set
        ) == self.lease_authority_verified:
            raise ValueError("lease verifier result is inconsistent")
        if (
            AMDAdmissionReason.RECOVERY_AUTHORITY_UNTRUSTED in reason_set
        ) == self.recovery_authority_verified:
            raise ValueError("recovery verifier result is inconsistent")
        expected_counter_regression = _has_regressed(
            self.before_snapshot,
            self.after_snapshot,
        ) or _snapshots_regress_consumed_watermark(
            self.before_snapshot,
            self.after_snapshot,
            self.pressure_recovery,
        )
        if (AMDAdmissionReason.COUNTER_REGRESSION in reason_set) != (
            expected_counter_regression
        ):
            raise ValueError("counter-regression reason is inconsistent")
        lease_acquired = (
            self.admission_lease.cas_acquired
            and self.admission_lease.expires_at > self.evaluated_at
            and self.admission_lease.expires_at - self.evaluated_at
            <= timedelta(seconds=AMD_ADMISSION_LEASE_MAX_SECONDS)
        )
        if (AMDAdmissionReason.RESERVATION_NOT_ACQUIRED in reason_set) == (
            lease_acquired
        ):
            raise ValueError("reservation reason does not match lease CAS authority")
        expected_pressure = AMDMemoryPressureBand.NOMINAL
        if AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD in reason_set:
            expected_pressure = AMDMemoryPressureBand.DRAIN
        elif AMDAdmissionReason.MEMORY_WARN_THRESHOLD in reason_set:
            expected_pressure = AMDMemoryPressureBand.WARN
        if self.pressure_band != expected_pressure:
            raise ValueError("pressure band does not match threshold reasons")
        if (
            AMDAdmissionReason.MEMORY_WARN_THRESHOLD in reason_set
            and AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD in reason_set
        ):
            raise ValueError("warn and drain threshold reasons are mutually exclusive")
        if (
            AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD_CROSSED in reason_set
            and AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD not in reason_set
        ):
            raise ValueError("drain crossing requires the drain threshold reason")
        expected_stop = bool(reason_set & _STOP_REASONS)
        expected_unload = bool(reason_set & _UNLOAD_REASONS) or (
            AMDAdmissionReason.PRESSURE_RECOVERY_INCOMPLETE in reason_set
            and self.recovery_authority_verified
            and recovery_binding_matches
            and self.pressure_recovery.recovered_epoch
            < self.pressure_recovery.drain_epoch
            and (
                self.pressure_recovery.unload_confirmation is None
                or self.topology.resident_model_family is not None
                or not self.topology.resident_model_unload_confirmed
            )
        )
        expected_recovery = bool(reason_set & _RECOVERY_REASONS)
        if self.stop_accepting_next != expected_stop:
            raise ValueError("stop-accepting-next does not match admission reasons")
        if self.request_unload_after_in_flight != expected_unload:
            raise ValueError("unload request does not match admission reasons")
        if self.request_recovery != expected_recovery:
            raise ValueError("recovery request does not match admission reasons")
        expected_new_pressure = (
            self.lease_authority_verified
            and lease_binding_matches
            and lease_acquired
            and self.recovery_authority_verified
            and recovery_binding_matches
            and _has_unconsumed_pressure_increment(
                self.before_snapshot,
                self.after_snapshot,
                self.pressure_recovery,
                evaluated_at=self.evaluated_at,
            )
        )
        if self.new_pressure_increment != expected_new_pressure:
            raise ValueError("new-pressure flag does not match trusted watermark evidence")
        recovery_is_closed = (
            self.pressure_recovery.recovered_epoch
            == self.pressure_recovery.drain_epoch
        )
        should_open_drain = (
            self.new_pressure_increment
            and self.recovery_authority_verified
            and recovery_binding_matches
            and recovery_is_closed
        )
        if (self.open_drain_epoch is not None) != should_open_drain:
            raise ValueError("drain epoch transition does not match admission reasons")
        if (
            self.open_drain_epoch is not None
            and self.open_drain_epoch != self.pressure_recovery.drain_epoch + 1
        ):
            raise ValueError("new drain epoch must advance exactly once")
        if self.open_drain_epoch is None:
            if self.next_consumed_event_watermark is not None:
                raise ValueError("event watermark can advance only with a drain epoch")
        elif self.next_consumed_event_watermark != _watermark_from_snapshot(
            self.after_snapshot
        ):
            raise ValueError("new drain epoch must consume the exact after watermark")
        recovery_ready = (
            AMDAdmissionReason.PRESSURE_RECOVERY_PENDING_COMMIT in reason_set
        )
        if (self.complete_recovery_epoch is not None) != recovery_ready:
            raise ValueError("recovery completion does not match admission reasons")
        if self.complete_recovery_epoch is not None and (
            self.complete_recovery_epoch != self.pressure_recovery.drain_epoch
            or self.pressure_recovery.recovered_epoch
            >= self.pressure_recovery.drain_epoch
            or not self.recovery_authority_verified
            or not recovery_binding_matches
            or not self.lease_authority_verified
            or not lease_binding_matches
            or not lease_acquired
            or not _recovery_receipt_is_ready(
                self.pressure_recovery,
                self.before_snapshot,
                self.after_snapshot,
                evaluated_at=self.evaluated_at,
            )
            or self.topology.resident_model_family is not None
            or not self.topology.resident_model_unload_confirmed
        ):
            raise ValueError("recovery completion is not bound to the pending epoch")
        if self.open_drain_epoch is not None and self.complete_recovery_epoch is not None:
            raise ValueError("a decision cannot open and complete recovery together")
        identity = self.model_dump(mode="json", exclude={"decision_digest"})
        actual = stable_json_sha256(identity)
        if not hmac.compare_digest(actual, self.decision_digest):
            raise ValueError("AMD resource admission decision digest mismatch")
        return self


# Backward-compatible import alias. The aliased type is deliberately
# provisional and exposes no executable ``admit_new_work`` authorization.
AMDResourceAdmissionDecisionV1 = AMDProvisionalResourceAdmissionDecisionV1


_PRESSURE_ACTION_REASONS = {
    AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD,
    AMDAdmissionReason.MEMORY_MAX_EVENT_INCREASE,
    AMDAdmissionReason.OOM_COUNTER_NONZERO,
    AMDAdmissionReason.OOM_COUNTER_INCREASE,
}
_STOP_REASONS = _PRESSURE_ACTION_REASONS | {
    AMDAdmissionReason.PRESSURE_RECOVERY_INCOMPLETE,
    AMDAdmissionReason.PRESSURE_RECOVERY_PENDING_COMMIT,
    AMDAdmissionReason.RECOVERY_AUTHORITY_UNTRUSTED,
    AMDAdmissionReason.RECOVERY_BINDING_MISMATCH,
}
_UNLOAD_REASONS = _PRESSURE_ACTION_REASONS
_RECOVERY_REASONS = _PRESSURE_ACTION_REASONS | {
    AMDAdmissionReason.MEMORY_MAX_INVALID,
    AMDAdmissionReason.SWAP_NOT_DISABLED,
    AMDAdmissionReason.SNAPSHOT_STALE,
    AMDAdmissionReason.SNAPSHOT_TIME_INVALID,
    AMDAdmissionReason.CGROUP_GENERATION_MISMATCH,
    AMDAdmissionReason.COUNTER_REGRESSION,
    AMDAdmissionReason.RESERVATION_NOT_ACQUIRED,
    AMDAdmissionReason.RESERVATION_BINDING_MISMATCH,
    AMDAdmissionReason.LEASE_AUTHORITY_UNTRUSTED,
    AMDAdmissionReason.RECOVERY_AUTHORITY_UNTRUSTED,
    AMDAdmissionReason.RECOVERY_BINDING_MISMATCH,
    AMDAdmissionReason.PRESSURE_RECOVERY_INCOMPLETE,
}


def _has_regressed(
    before: AMDResourceSnapshotV1,
    after: AMDResourceSnapshotV1,
) -> bool:
    if after.memory_peak_bytes < before.memory_peak_bytes:
        return True
    return any(
        after_value < before_value
        for before_value, after_value in zip(
            before.memory_events.as_counter_tuple(),
            after.memory_events.as_counter_tuple(),
        )
    )


def _snapshots_regress_consumed_watermark(
    before: AMDResourceSnapshotV1,
    after: AMDResourceSnapshotV1,
    recovery: AMDPressureRecoveryAuthorityV1,
) -> bool:
    watermark = recovery.consumed_event_watermark
    if (
        before.cgroup_generation_id != watermark.cgroup_generation_id
        or after.cgroup_generation_id != watermark.cgroup_generation_id
    ):
        return False
    if (
        before.snapshot_sequence < watermark.snapshot_sequence
        or after.snapshot_sequence < watermark.snapshot_sequence
    ):
        return True
    return any(
        snapshot_value < consumed_value
        for snapshot in (before, after)
        for snapshot_value, consumed_value in zip(
            snapshot.memory_events.as_counter_tuple(),
            watermark.as_counter_tuple(),
        )
    )


def _snapshots_are_authoritative(
    before: AMDResourceSnapshotV1,
    after: AMDResourceSnapshotV1,
    *,
    evaluated_at: AwareDatetime,
) -> bool:
    return (
        before.cgroup_generation_id == after.cgroup_generation_id
        and before.snapshot_sequence < after.snapshot_sequence
        and before.captured_at < after.captured_at
        and before.captured_at <= evaluated_at
        and after.captured_at <= evaluated_at
        and evaluated_at - before.captured_at
        <= timedelta(seconds=AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS)
        and evaluated_at - after.captured_at
        <= timedelta(seconds=AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS)
    )


def _watermark_from_snapshot(
    snapshot: AMDResourceSnapshotV1,
) -> AMDPressureEventWatermarkV1:
    return AMDPressureEventWatermarkV1(
        cgroup_generation_id=snapshot.cgroup_generation_id,
        snapshot_sequence=snapshot.snapshot_sequence,
        memory_events_low=snapshot.memory_events.low,
        memory_events_high=snapshot.memory_events.high,
        memory_events_max=snapshot.memory_events.max,
        memory_events_oom=snapshot.memory_events.oom,
        memory_events_oom_kill=snapshot.memory_events.oom_kill,
        memory_events_oom_group_kill=snapshot.memory_events.oom_group_kill,
    )


def _has_unconsumed_pressure_increment(
    before: AMDResourceSnapshotV1,
    after: AMDResourceSnapshotV1,
    recovery: AMDPressureRecoveryAuthorityV1,
    *,
    evaluated_at: AwareDatetime,
) -> bool:
    if not _snapshots_are_authoritative(
        before,
        after,
        evaluated_at=evaluated_at,
    ):
        return False
    if _has_regressed(before, after) or _snapshots_regress_consumed_watermark(
        before,
        after,
        recovery,
    ):
        return False
    watermark = recovery.consumed_event_watermark
    if (
        watermark.cgroup_generation_id != after.cgroup_generation_id
        or after.snapshot_sequence <= watermark.snapshot_sequence
    ):
        return False
    if (
        after.memory_events.max < watermark.memory_events_max
        or after.memory_events.oom < watermark.memory_events_oom
        or after.memory_events.oom_kill < watermark.memory_events_oom_kill
        or after.memory_events.oom_group_kill
        < watermark.memory_events_oom_group_kill
    ):
        return False
    max_advanced = after.memory_events.max > watermark.memory_events_max
    after_oom = after.memory_events.as_oom_counter_tuple()
    watermark_oom = (
        watermark.memory_events_oom,
        watermark.memory_events_oom_kill,
        watermark.memory_events_oom_group_kill,
    )
    oom_advanced = any(
        after_value > consumed_value
        for after_value, consumed_value in zip(after_oom, watermark_oom)
    )
    drain_pressure = after.memory_current_bytes >= AMD_DRAIN_MEMORY_BYTES
    return max_advanced or oom_advanced or drain_pressure


def _health_sample_matches_snapshot(
    sample: AMDRecoveryHealthSampleV1,
    snapshot: AMDResourceSnapshotV1,
    *,
    evaluated_at: AwareDatetime,
) -> bool:
    return (
        sample.valid_until > evaluated_at
        and sample.cgroup_generation_id == snapshot.cgroup_generation_id
        and sample.snapshot_sequence == snapshot.snapshot_sequence
        and sample.captured_at == snapshot.captured_at
        and sample.memory_current_bytes == snapshot.memory_current_bytes
        and sample.memory_events_low == snapshot.memory_events.low
        and sample.memory_events_high == snapshot.memory_events.high
        and sample.memory_events_max == snapshot.memory_events.max
        and sample.memory_events_oom == snapshot.memory_events.oom
        and sample.memory_events_oom_kill == snapshot.memory_events.oom_kill
        and sample.memory_events_oom_group_kill
        == snapshot.memory_events.oom_group_kill
    )


def _recovery_receipt_is_ready(
    recovery: AMDPressureRecoveryAuthorityV1,
    before: AMDResourceSnapshotV1,
    after: AMDResourceSnapshotV1,
    *,
    evaluated_at: AwareDatetime,
) -> bool:
    return (
        recovery.drain_epoch > recovery.recovered_epoch
        and recovery.unload_confirmation is not None
        and after.snapshot_sequence == before.snapshot_sequence + 1
        and len(recovery.healthy_samples)
        == recovery.required_consecutive_healthy_snapshots
        and _health_sample_matches_snapshot(
            recovery.healthy_samples[0],
            before,
            evaluated_at=evaluated_at,
        )
        and _health_sample_matches_snapshot(
            recovery.healthy_samples[1],
            after,
            evaluated_at=evaluated_at,
        )
    )


def evaluate_amd_resource_admission(
    request: AMDResourceAdmissionRequestV1,
    *,
    trusted_authority_verifier: AMDTrustedAuthorityVerifier,
) -> AMDProvisionalResourceAdmissionDecisionV1:
    """Fail-closed admission for the single AMD GPU without killing delivery."""

    before = request.before_snapshot
    after = request.after_snapshot
    reasons: list[AMDAdmissionReason] = []

    if (
        before.memory_max_bytes != AMD_HARD_MEMORY_MAX_BYTES
        or after.memory_max_bytes != AMD_HARD_MEMORY_MAX_BYTES
    ):
        reasons.append(AMDAdmissionReason.MEMORY_MAX_INVALID)
    if (
        before.memory_swap_current_bytes != 0
        or after.memory_swap_current_bytes != 0
        or before.memory_swap_max_bytes != 0
        or after.memory_swap_max_bytes != 0
    ):
        reasons.append(AMDAdmissionReason.SWAP_NOT_DISABLED)

    if before.cgroup_generation_id != after.cgroup_generation_id:
        reasons.append(AMDAdmissionReason.CGROUP_GENERATION_MISMATCH)

    if (
        before.captured_at >= after.captured_at
        or before.snapshot_sequence >= after.snapshot_sequence
        or before.captured_at > request.evaluated_at
        or after.captured_at > request.evaluated_at
    ):
        reasons.append(AMDAdmissionReason.SNAPSHOT_TIME_INVALID)
    if (
        request.evaluated_at - before.captured_at
        > timedelta(seconds=AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS)
        or request.evaluated_at - after.captured_at
        > timedelta(seconds=AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS)
    ):
        reasons.append(AMDAdmissionReason.SNAPSHOT_STALE)

    if _has_regressed(before, after):
        reasons.append(AMDAdmissionReason.COUNTER_REGRESSION)
    if after.memory_events.max > before.memory_events.max:
        reasons.append(AMDAdmissionReason.MEMORY_MAX_EVENT_INCREASE)

    before_oom = before.memory_events.as_oom_counter_tuple()
    after_oom = after.memory_events.as_oom_counter_tuple()
    if any(after_oom):
        reasons.append(AMDAdmissionReason.OOM_COUNTER_NONZERO)
    if any(
        after_value > before_value
        for before_value, after_value in zip(before_oom, after_oom)
    ):
        reasons.append(AMDAdmissionReason.OOM_COUNTER_INCREASE)

    if after.memory_current_bytes >= AMD_DRAIN_MEMORY_BYTES:
        pressure_band = AMDMemoryPressureBand.DRAIN
        reasons.append(AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD)
        if before.memory_current_bytes < AMD_DRAIN_MEMORY_BYTES:
            reasons.append(AMDAdmissionReason.MEMORY_DRAIN_THRESHOLD_CROSSED)
    elif after.memory_current_bytes >= AMD_WARN_MEMORY_BYTES:
        pressure_band = AMDMemoryPressureBand.WARN
        reasons.append(AMDAdmissionReason.MEMORY_WARN_THRESHOLD)
    else:
        pressure_band = AMDMemoryPressureBand.NOMINAL

    active_gpu_task = request.topology.active_local_gpu_task_id is not None
    if active_gpu_task:
        reasons.append(AMDAdmissionReason.LOCAL_GPU_TASK_ACTIVE)
    resident_model = request.topology.resident_model_family
    if resident_model is not None and resident_model != request.requested_model_family:
        reasons.append(AMDAdmissionReason.OTHER_MODEL_RESIDENT)

    lease = request.admission_lease
    lease_authority_verified = _strict_authority_verifier_result(
        lambda: trusted_authority_verifier.verify_admission_lease(
            lease,
            trusted_now=request.evaluated_at,
            expected_lease_epoch=lease.lease_epoch,
            expected_fencing_token=lease.fencing_token,
            expected_lease_cas_version=lease.committed_version,
        )
    )
    if not lease_authority_verified:
        reasons.append(AMDAdmissionReason.LEASE_AUTHORITY_UNTRUSTED)
    lease_binding_matches = (
        lease.reserved_submission_id == request.submission_id
        and lease.requested_model_family == request.requested_model_family
        and lease.cgroup_generation_id == after.cgroup_generation_id
    )
    if not lease_binding_matches:
        reasons.append(AMDAdmissionReason.RESERVATION_BINDING_MISMATCH)
    if (
        not lease.cas_acquired
        or lease.expires_at <= request.evaluated_at
        or lease.expires_at - request.evaluated_at
        > timedelta(seconds=AMD_ADMISSION_LEASE_MAX_SECONDS)
    ):
        reasons.append(AMDAdmissionReason.RESERVATION_NOT_ACQUIRED)

    recovery = request.pressure_recovery
    recovery_authority_verified = _strict_authority_verifier_result(
        lambda: trusted_authority_verifier.verify_pressure_recovery(
            recovery,
            trusted_now=request.evaluated_at,
            expected_state_version=recovery.state_version,
            expected_lease_epoch=lease.lease_epoch,
            expected_fencing_token=lease.fencing_token,
            expected_lease_cas_version=lease.committed_version,
            expected_consumed_event_watermark=recovery.consumed_event_watermark,
        )
    )
    if not recovery_authority_verified:
        reasons.append(AMDAdmissionReason.RECOVERY_AUTHORITY_UNTRUSTED)
    recovery_binding_matches = (
        recovery.requested_model_family == request.requested_model_family
        and recovery.cgroup_generation_id == after.cgroup_generation_id
        and recovery.admission_lease_id == lease.lease_id
        and recovery.admission_lease_epoch == lease.lease_epoch
        and recovery.admission_lease_committed_version == lease.committed_version
        and recovery.fencing_token == lease.fencing_token
    )
    if not recovery_binding_matches:
        reasons.append(AMDAdmissionReason.RECOVERY_BINDING_MISMATCH)
    if (
        _snapshots_regress_consumed_watermark(before, after, recovery)
        and AMDAdmissionReason.COUNTER_REGRESSION not in reasons
    ):
        reasons.append(AMDAdmissionReason.COUNTER_REGRESSION)

    watermark = recovery.consumed_event_watermark
    if (
        _snapshots_are_authoritative(
            before,
            after,
            evaluated_at=request.evaluated_at,
        )
        and not _has_regressed(before, after)
        and watermark.cgroup_generation_id == after.cgroup_generation_id
        and after.snapshot_sequence > watermark.snapshot_sequence
        and after.memory_events.max > watermark.memory_events_max
        and AMDAdmissionReason.MEMORY_MAX_EVENT_INCREASE not in reasons
    ):
        reasons.append(AMDAdmissionReason.MEMORY_MAX_EVENT_INCREASE)

    recovery_pending = recovery.recovered_epoch < recovery.drain_epoch
    completion_epoch: int | None = None
    if recovery_pending:
        healthy_snapshots = (
            before.memory_current_bytes < AMD_RECOVERY_MEMORY_BYTES
            and after.memory_current_bytes < AMD_RECOVERY_MEMORY_BYTES
        )
        recovery_evidence_ready = (
            recovery_authority_verified
            and recovery_binding_matches
            and _recovery_receipt_is_ready(
                recovery,
                before,
                after,
                evaluated_at=request.evaluated_at,
            )
            and request.topology.resident_model_family is None
            and request.topology.resident_model_unload_confirmed
            and healthy_snapshots
        )
        if recovery_evidence_ready and not reasons:
            reasons.append(AMDAdmissionReason.PRESSURE_RECOVERY_PENDING_COMMIT)
            completion_epoch = recovery.drain_epoch
        else:
            reasons.append(AMDAdmissionReason.PRESSURE_RECOVERY_INCOMPLETE)

    reasons_set = set(reasons)
    new_pressure_increment = (
        lease_authority_verified
        and lease_binding_matches
        and lease.cas_acquired
        and lease.expires_at > request.evaluated_at
        and recovery_authority_verified
        and recovery_binding_matches
        and _has_unconsumed_pressure_increment(
            before,
            after,
            recovery,
            evaluated_at=request.evaluated_at,
        )
    )
    recovery_is_closed = recovery.recovered_epoch == recovery.drain_epoch
    open_drain_epoch = (
        recovery.drain_epoch + 1
        if (
            new_pressure_increment
            and recovery_authority_verified
            and recovery_binding_matches
            and recovery_is_closed
        )
        else None
    )
    if open_drain_epoch is not None:
        completion_epoch = None
    next_consumed_event_watermark = (
        _watermark_from_snapshot(after) if open_drain_epoch is not None else None
    )

    reasons_tuple = tuple(sorted(reasons_set, key=lambda reason: reason.value))

    identity: dict[str, object] = {
        "submission_id": str(request.submission_id),
        "requested_model_family": request.requested_model_family.value,
        "cgroup_generation_id": str(after.cgroup_generation_id),
        "before_snapshot": before.model_dump(mode="json"),
        "after_snapshot": after.model_dump(mode="json"),
        "pressure_band": pressure_band.value,
        "authorization_state": "provisional_non_authoritative",
        "provisional_admit_new_work": not reasons_tuple,
        "reasons": [reason.value for reason in reasons_tuple],
        "stop_accepting_next": bool(reasons_set & _STOP_REASONS),
        "request_unload_after_in_flight": bool(reasons_set & _UNLOAD_REASONS)
        or (
            AMDAdmissionReason.PRESSURE_RECOVERY_INCOMPLETE in reasons_set
            and recovery_authority_verified
            and recovery_binding_matches
            and recovery_pending
            and (
                recovery.unload_confirmation is None
                or request.topology.resident_model_family is not None
                or not request.topology.resident_model_unload_confirmed
            )
        ),
        "request_recovery": bool(reasons_set & _RECOVERY_REASONS),
        "new_pressure_increment": new_pressure_increment,
        "open_drain_epoch": open_drain_epoch,
        "next_consumed_event_watermark": (
            next_consumed_event_watermark.model_dump(mode="json")
            if next_consumed_event_watermark is not None
            else None
        ),
        "complete_recovery_epoch": completion_epoch,
        "terminate_in_flight_delivery": False,
        "in_flight_policy": "preserve_until_delivery",
        "admission_lease": lease.model_dump(mode="json"),
        "pressure_recovery": recovery.model_dump(mode="json"),
        "topology": request.topology.model_dump(mode="json"),
        "lease_authority_verified": lease_authority_verified,
        "recovery_authority_verified": recovery_authority_verified,
        "evaluated_at": request.evaluated_at.isoformat().replace("+00:00", "Z"),
    }
    identity["decision_digest"] = stable_json_sha256(identity)  # type: ignore[arg-type]
    return AMDProvisionalResourceAdmissionDecisionV1.model_validate(identity)


def verify_amd_resource_admission_decision(
    decision: AMDProvisionalResourceAdmissionDecisionV1,
    *,
    trusted_request: AMDResourceAdmissionRequestV1,
    trusted_authority_verifier: AMDTrustedAuthorityVerifier,
    trusted_now: datetime,
) -> bool:
    """Verify a live admission and atomically consume its persisted lease once."""

    try:
        if trusted_now.tzinfo is None or trusted_now.utcoffset() is None:
            return False
        if trusted_now < trusted_request.evaluated_at:
            return False
        if (
            trusted_now - trusted_request.evaluated_at
            > timedelta(seconds=AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS)
        ):
            return False
        if (
            trusted_now - trusted_request.evaluated_at
            > timedelta(seconds=AMD_ADMISSION_LEASE_MAX_SECONDS)
        ):
            return False
        if not _snapshots_are_authoritative(
            trusted_request.before_snapshot,
            trusted_request.after_snapshot,
            evaluated_at=trusted_now,
        ):
            return False
        lease = trusted_request.admission_lease
        recovery = trusted_request.pressure_recovery
        if (
            lease.expires_at <= trusted_now
            or lease.expires_at - trusted_request.evaluated_at
            > timedelta(seconds=AMD_ADMISSION_LEASE_MAX_SECONDS)
        ):
            return False
        lease_is_current = _strict_authority_verifier_result(
            lambda: trusted_authority_verifier.verify_admission_lease(
                lease,
                trusted_now=trusted_now,
                expected_lease_epoch=lease.lease_epoch,
                expected_fencing_token=lease.fencing_token,
                expected_lease_cas_version=lease.committed_version,
            )
        )
        recovery_is_current = _strict_authority_verifier_result(
            lambda: trusted_authority_verifier.verify_pressure_recovery(
                recovery,
                trusted_now=trusted_now,
                expected_state_version=recovery.state_version,
                expected_lease_epoch=lease.lease_epoch,
                expected_fencing_token=lease.fencing_token,
                expected_lease_cas_version=lease.committed_version,
                expected_consumed_event_watermark=(
                    recovery.consumed_event_watermark
                ),
            )
        )
        if not lease_is_current or not recovery_is_current:
            return False
        expected = evaluate_amd_resource_admission(
            trusted_request,
            trusted_authority_verifier=trusted_authority_verifier,
        )
        actual_json = canonical_json(  # type: ignore[arg-type]
            decision.model_dump(mode="json")
        )
        expected_json = canonical_json(  # type: ignore[arg-type]
            expected.model_dump(mode="json")
        )
        if not hmac.compare_digest(actual_json, expected_json):
            return False
        if not expected.provisional_admit_new_work:
            return False
        request_digest = stable_json_sha256(
            trusted_request.model_dump(mode="json")
        )
        return _strict_authority_verifier_result(
            lambda: trusted_authority_verifier.verify_and_consume_admission(
                trusted_request,
                expected,
                request_digest=request_digest,
                decision_digest=expected.decision_digest,
                cgroup_generation_id=expected.cgroup_generation_id,
                lease_epoch=lease.lease_epoch,
                fencing_token=lease.fencing_token,
                expected_state_version=recovery.state_version,
                expected_lease_cas_version=lease.committed_version,
                expected_consumed_event_watermark=(
                    recovery.consumed_event_watermark
                ),
                trusted_now=trusted_now,
            )
        )
    except Exception:
        return False


__all__ = [
    "AMD_ADMISSION_LEASE_MAX_SECONDS",
    "AMD_DRAIN_MEMORY_BYTES",
    "AMD_HARD_MEMORY_MAX_BYTES",
    "AMD_RECOVERY_MEMORY_BYTES",
    "AMD_RESOURCE_SNAPSHOT_MAX_AGE_SECONDS",
    "AMD_WARN_MEMORY_BYTES",
    "AMDAdmissionLeaseAuthorityV1",
    "AMDAdmissionReason",
    "AMDCgroupV2MemoryEventsV1",
    "AMDExecutionTopologyV1",
    "AMDMemoryPressureBand",
    "AMDModelFamily",
    "AMDPressureRecoveryAuthorityV1",
    "AMDPressureEventWatermarkV1",
    "AMDRecoveryHealthSampleV1",
    "AMDProvisionalResourceAdmissionDecisionV1",
    "AMDResourceAdmissionDecisionV1",
    "AMDResourceAdmissionRequestV1",
    "AMDResourceSnapshotV1",
    "AMDTrustedAuthorityVerifier",
    "AMDUnloadConfirmationAuthorityV1",
    "evaluate_amd_resource_admission",
    "verify_amd_resource_admission_decision",
]
