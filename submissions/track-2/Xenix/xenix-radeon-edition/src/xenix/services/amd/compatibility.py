"""Pure compatibility planning over immutable AMD manifests and redacted facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .manifests import (
    CapacityRequirements,
    CompatibilityCell,
    CompatibilityTargetKind,
    ComponentManifest,
    ManifestAdmission,
    ManifestAdmissionBlocker,
    ManifestCatalog,
)


class CompatibilityPhase(StrEnum):
    MANIFEST = "manifest"
    TARGET = "target"
    CAPACITY = "capacity"


class CompatibilityReason(StrEnum):
    PROFILE_NOT_ADMITTED = "profile_not_admitted"
    COMPONENT_NOT_ADMITTED = "component_not_admitted"
    CELL_NOT_ADMITTED = "cell_not_admitted"
    TARGET_FACT_MISSING = "target_fact_missing"
    TARGET_KIND_MISMATCH = "target_kind_mismatch"
    OS_NAME_MISMATCH = "os_name_mismatch"
    OS_VERSION_MISMATCH = "os_version_mismatch"
    KERNEL_VERSION_MISMATCH = "kernel_version_mismatch"
    ARCHITECTURE_MISMATCH = "architecture_mismatch"
    GPU_ARCHITECTURE_MISMATCH = "gpu_architecture_mismatch"
    DRIVER_VERSION_MISMATCH = "driver_version_mismatch"
    ROCM_VERSION_MISMATCH = "rocm_version_mismatch"
    HIP_VERSION_MISMATCH = "hip_version_mismatch"
    PYTHON_VERSION_MISMATCH = "python_version_mismatch"
    GPU_COUNT_INSUFFICIENT = "gpu_count_insufficient"
    VRAM_INSUFFICIENT = "vram_insufficient"
    SYSTEM_MEMORY_INSUFFICIENT = "system_memory_insufficient"
    PERSISTENT_STORAGE_INSUFFICIENT = "persistent_storage_insufficient"
    CAPACITY_REQUIREMENT_UNMEASURED = "capacity_requirement_unmeasured"


class AmdCompatibilityError(RuntimeError):
    """A manifest cannot be admitted on the observed target facts."""

    def __init__(self, decision: CompatibilityDecision) -> None:
        self.decision = decision
        reasons = ", ".join(issue.reason.value for issue in decision.issues)
        super().__init__(f"AMD target is incompatible: {reasons or 'unknown_reason'}")


@dataclass(frozen=True, slots=True)
class TargetCompatibilityFacts:
    """Typed, redacted target observations.

    Host addresses, credentials, paths, device serials, and live process facts do
    not belong here.  ``free_persistent_bytes`` must describe the product-authorized
    persistent root, never an arbitrary large overlay or an evidence-only lab path.
    ``None`` means the placement did not establish that fact.
    """

    os_name: str | None
    os_version: str | None
    kernel_version: str | None
    architecture: str | None
    gpu_architectures: tuple[str, ...]
    driver_version: str | None
    rocm_version: str | None
    hip_version: str | None
    python_version: str | None
    gpu_count: int | None
    free_vram_bytes: int | None
    free_system_memory_bytes: int | None
    free_persistent_bytes: int | None
    target_kind: CompatibilityTargetKind = CompatibilityTargetKind.NATIVE_LINUX
    wsl_runtime_proven: bool = False

    def __post_init__(self) -> None:
        for label, value in (
            ("Operating system name", self.os_name),
            ("Operating system version", self.os_version),
            ("Kernel version", self.kernel_version),
            ("Architecture", self.architecture),
            ("Driver version", self.driver_version),
            ("ROCm version", self.rocm_version),
            ("HIP version", self.hip_version),
            ("Python version", self.python_version),
        ):
            _validate_observed_text(value, label)
        if not isinstance(self.target_kind, CompatibilityTargetKind):
            raise ValueError("Compatibility target kind is invalid.")
        if not isinstance(self.wsl_runtime_proven, bool):
            raise ValueError("WSL runtime proof is invalid.")
        if self.wsl_runtime_proven and self.target_kind is not CompatibilityTargetKind.WSL2:
            raise ValueError("Only WSL2 compatibility facts may claim a WSL runtime proof.")

        architectures = tuple(self.gpu_architectures)
        for architecture in architectures:
            _validate_observed_text(architecture, "GPU architecture", required=True)
        if len(set(architectures)) != len(architectures):
            raise ValueError("GPU architecture observations must be unique.")
        object.__setattr__(self, "gpu_architectures", architectures)

        for label, capacity_value in (
            ("GPU count", self.gpu_count),
            ("Free VRAM", self.free_vram_bytes),
            ("Free system memory", self.free_system_memory_bytes),
            ("Free persistent storage", self.free_persistent_bytes),
        ):
            if capacity_value is not None and (
                not isinstance(capacity_value, int) or isinstance(capacity_value, bool) or capacity_value < 0
            ):
                raise ValueError(f"{label} must be a non-negative integer or unobserved.")
        if self.gpu_count is not None and len(architectures) > self.gpu_count:
            raise ValueError("GPU architecture observations exceed the observed GPU count.")


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    phase: CompatibilityPhase
    reason: CompatibilityReason
    field: str
    expected: str
    observed: str


@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    subject_digest: str
    compatibility_cell_id: str
    component_manifest_digests: tuple[str, ...]
    issues: tuple[CompatibilityIssue, ...]

    @property
    def supported(self) -> bool:
        return not self.issues

    def require_supported(self) -> None:
        if self.issues:
            raise AmdCompatibilityError(self)


@dataclass(frozen=True, slots=True)
class CompatibilityPlanner:
    """Read-only planner; it never mutates target, catalog, settings, or SQLite."""

    catalog: ManifestCatalog

    def plan_profile(
        self,
        profile_manifest_digest: str,
        facts: TargetCompatibilityFacts,
    ) -> CompatibilityDecision:
        profile = self.catalog.profile(profile_manifest_digest)
        components = self.catalog.profile_components(profile)
        issues: list[CompatibilityIssue] = []

        if profile.admission is not ManifestAdmission.ADMITTED:
            issues.append(
                _manifest_issue(
                    CompatibilityReason.PROFILE_NOT_ADMITTED,
                    "profile_admission",
                    profile.admission_blockers,
                )
            )

        for component in components:
            if component.admission is not ManifestAdmission.ADMITTED:
                issues.append(
                    _manifest_issue(
                        CompatibilityReason.COMPONENT_NOT_ADMITTED,
                        f"component:{component.capability.value}",
                        component.admission_blockers,
                    )
                )
            cell = _component_cell(component, profile.compatibility_cell_id)
            issues.extend(_cell_issues(cell, facts))

        issues.extend(_capacity_issues(profile.capacity, facts))
        return CompatibilityDecision(
            subject_digest=profile.manifest_digest,
            compatibility_cell_id=profile.compatibility_cell_id,
            component_manifest_digests=tuple(component.manifest_digest for component in components),
            issues=_deduplicate_issues(issues),
        )

    def plan_component(
        self,
        component_manifest_digest: str,
        compatibility_cell_id: str,
        facts: TargetCompatibilityFacts,
    ) -> CompatibilityDecision:
        component = self.catalog.component(component_manifest_digest)
        issues: list[CompatibilityIssue] = []
        if component.admission is not ManifestAdmission.ADMITTED:
            issues.append(
                _manifest_issue(
                    CompatibilityReason.COMPONENT_NOT_ADMITTED,
                    f"component:{component.capability.value}",
                    component.admission_blockers,
                )
            )
        issues.extend(_cell_issues(_component_cell(component, compatibility_cell_id), facts))
        issues.extend(_capacity_issues(component.capacity, facts))
        return CompatibilityDecision(
            subject_digest=component.manifest_digest,
            compatibility_cell_id=compatibility_cell_id,
            component_manifest_digests=(component.manifest_digest,),
            issues=_deduplicate_issues(issues),
        )


def _component_cell(component: ComponentManifest, cell_id: str) -> CompatibilityCell:
    for cell in component.compatibility_cells:
        if cell.cell_id == cell_id:
            return cell
    # ManifestCatalog validates profile edges.  This branch remains useful for
    # direct component planning with a caller-supplied cell.
    raise ValueError("Compatibility cell is absent from the component manifest.")


def _manifest_issue(
    reason: CompatibilityReason,
    field: str,
    blockers: tuple[ManifestAdmissionBlocker, ...],
) -> CompatibilityIssue:
    return CompatibilityIssue(
        phase=CompatibilityPhase.MANIFEST,
        reason=reason,
        field=field,
        expected="admitted",
        observed="draft:" + ",".join(blocker.value for blocker in blockers),
    )


def _cell_issues(
    cell: CompatibilityCell,
    facts: TargetCompatibilityFacts,
) -> list[CompatibilityIssue]:
    issues: list[CompatibilityIssue] = []
    if cell.admission is not ManifestAdmission.ADMITTED:
        issues.append(
            _manifest_issue(
                CompatibilityReason.CELL_NOT_ADMITTED,
                f"cell:{cell.cell_id}",
                cell.admission_blockers,
            )
        )

    if cell.target_kind is not facts.target_kind:
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.TARGET,
                reason=CompatibilityReason.TARGET_KIND_MISMATCH,
                field="target_kind",
                expected=cell.target_kind.value,
                observed=facts.target_kind.value,
            )
        )

    _compare_text(
        issues,
        field="os_name",
        expected=cell.os_name,
        observed=facts.os_name,
        reason=CompatibilityReason.OS_NAME_MISMATCH,
        case_insensitive=True,
    )
    _compare_text(
        issues,
        field="os_version",
        expected=cell.os_version,
        observed=facts.os_version,
        reason=CompatibilityReason.OS_VERSION_MISMATCH,
    )
    if cell.target_kind is CompatibilityTargetKind.WSL2:
        _compare_wsl2_kernel(issues, facts.kernel_version)
    else:
        _compare_text(
            issues,
            field="kernel_version",
            expected=cell.kernel_version,
            observed=facts.kernel_version,
            reason=CompatibilityReason.KERNEL_VERSION_MISMATCH,
        )
    _compare_text(
        issues,
        field="architecture",
        expected=cell.architecture,
        observed=facts.architecture,
        reason=CompatibilityReason.ARCHITECTURE_MISMATCH,
        case_insensitive=True,
    )
    if not facts.gpu_architectures:
        issues.append(_missing_fact("gpu_architectures", cell.gpu_architecture))
    elif cell.gpu_architecture.casefold() not in {architecture.casefold() for architecture in facts.gpu_architectures}:
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.TARGET,
                reason=CompatibilityReason.GPU_ARCHITECTURE_MISMATCH,
                field="gpu_architectures",
                expected=cell.gpu_architecture,
                observed=",".join(sorted(facts.gpu_architectures)),
            )
        )
    if cell.target_kind is CompatibilityTargetKind.WSL2:
        if not facts.wsl_runtime_proven:
            issues.append(
                CompatibilityIssue(
                    phase=CompatibilityPhase.TARGET,
                    reason=CompatibilityReason.DRIVER_VERSION_MISMATCH,
                    field="wsl_rocm_runtime",
                    expected=cell.driver_version,
                    observed="unproven",
                )
            )
    else:
        _compare_text(
            issues,
            field="driver_version",
            expected=cell.driver_version,
            observed=facts.driver_version,
            reason=CompatibilityReason.DRIVER_VERSION_MISMATCH,
        )
    _compare_text(
        issues,
        field="rocm_version",
        expected=cell.rocm_version,
        observed=facts.rocm_version,
        reason=CompatibilityReason.ROCM_VERSION_MISMATCH,
    )
    _compare_text(
        issues,
        field="hip_version",
        expected=cell.hip_version,
        observed=facts.hip_version,
        reason=CompatibilityReason.HIP_VERSION_MISMATCH,
    )
    _compare_text(
        issues,
        field="python_version",
        expected=cell.python_version,
        observed=facts.python_version,
        reason=CompatibilityReason.PYTHON_VERSION_MISMATCH,
    )
    return issues


def _capacity_issues(
    requirements: CapacityRequirements,
    facts: TargetCompatibilityFacts,
) -> list[CompatibilityIssue]:
    issues: list[CompatibilityIssue] = []
    _compare_capacity(
        issues,
        field="gpu_count",
        required=requirements.min_gpu_count,
        observed=facts.gpu_count,
        reason=CompatibilityReason.GPU_COUNT_INSUFFICIENT,
    )
    _compare_capacity(
        issues,
        field="free_vram_bytes",
        required=requirements.min_free_vram_bytes,
        observed=facts.free_vram_bytes,
        reason=CompatibilityReason.VRAM_INSUFFICIENT,
    )
    _compare_capacity(
        issues,
        field="free_system_memory_bytes",
        required=requirements.min_free_system_memory_bytes,
        observed=facts.free_system_memory_bytes,
        reason=CompatibilityReason.SYSTEM_MEMORY_INSUFFICIENT,
    )
    _compare_capacity(
        issues,
        field="free_persistent_bytes",
        required=requirements.required_persistent_bytes,
        observed=facts.free_persistent_bytes,
        reason=CompatibilityReason.PERSISTENT_STORAGE_INSUFFICIENT,
    )
    return issues


def _compare_text(
    issues: list[CompatibilityIssue],
    *,
    field: str,
    expected: str,
    observed: str | None,
    reason: CompatibilityReason,
    case_insensitive: bool = False,
) -> None:
    if observed is None:
        issues.append(_missing_fact(field, expected))
        return
    left = expected.casefold() if case_insensitive else expected
    right = observed.casefold() if case_insensitive else observed
    if left != right:
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.TARGET,
                reason=reason,
                field=field,
                expected=expected,
                observed=observed,
            )
        )


def _compare_wsl2_kernel(
    issues: list[CompatibilityIssue],
    observed: str | None,
) -> None:
    """Validate the documented WSL2 kernel family without inventing a version.

    WSL's kernel is owned by Windows rather than the Ubuntu distribution, and
    AMD's WSL support matrices name the WSL2 platform family instead of a
    generic-Linux exact kernel build.  The raw observed value remains in the
    fact object; this deliberate semantic check never rewrites it.
    """

    expected = "microsoft-standard-wsl2"
    if observed is None:
        issues.append(_missing_fact("kernel_version", expected))
        return
    if expected not in observed.casefold():
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.TARGET,
                reason=CompatibilityReason.KERNEL_VERSION_MISMATCH,
                field="kernel_version",
                expected=expected,
                observed=observed,
            )
        )


def _compare_capacity(
    issues: list[CompatibilityIssue],
    *,
    field: str,
    required: int | None,
    observed: int | None,
    reason: CompatibilityReason,
) -> None:
    if required is None:
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.MANIFEST,
                reason=CompatibilityReason.CAPACITY_REQUIREMENT_UNMEASURED,
                field=field,
                expected="measured_positive_integer",
                observed="unmeasured",
            )
        )
        return
    if observed is None:
        issues.append(_missing_fact(field, str(required), phase=CompatibilityPhase.CAPACITY))
        return
    if observed < required:
        issues.append(
            CompatibilityIssue(
                phase=CompatibilityPhase.CAPACITY,
                reason=reason,
                field=field,
                expected=str(required),
                observed=str(observed),
            )
        )


def _missing_fact(
    field: str,
    expected: str,
    *,
    phase: CompatibilityPhase = CompatibilityPhase.TARGET,
) -> CompatibilityIssue:
    return CompatibilityIssue(
        phase=phase,
        reason=CompatibilityReason.TARGET_FACT_MISSING,
        field=field,
        expected=expected,
        observed="unobserved",
    )


def _deduplicate_issues(issues: list[CompatibilityIssue]) -> tuple[CompatibilityIssue, ...]:
    return tuple(
        dict.fromkeys(
            sorted(
                issues,
                key=lambda issue: (
                    issue.phase.value,
                    issue.reason.value,
                    issue.field,
                    issue.expected,
                    issue.observed,
                ),
            )
        )
    )


def _validate_observed_text(value: str | None, label: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{label} is required.")
        return
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError(f"{label} observation is invalid.")


__all__ = [
    "AmdCompatibilityError",
    "CompatibilityDecision",
    "CompatibilityIssue",
    "CompatibilityPhase",
    "CompatibilityPlanner",
    "CompatibilityReason",
    "TargetCompatibilityFacts",
]
