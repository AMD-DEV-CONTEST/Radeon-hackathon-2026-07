from __future__ import annotations

import ast
import hashlib
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError, stable_digest


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPDX = re.compile(r"^[A-Za-z0-9.+-]+$")


class UpstreamCategory(str, Enum):
    MODEL = "model"
    TRAINING = "training"
    AGENT = "agent"
    IMAGE = "image"
    VIDEO = "video"
    SUPER_RESOLUTION = "super_resolution"
    SEGMENTATION = "segmentation"
    OCR = "ocr"
    AUDIO = "audio"
    EVALUATION = "evaluation"
    MARKETING_AGENT = "marketing_agent"


class IntegrationMode(str, Enum):
    ADAPTER = "adapter"
    WRAPPER = "wrapper"
    WORKFLOW = "workflow"
    PATCH = "patch"
    REFERENCE_ONLY = "reference_only"


class RocmEvidenceLevel(str, Enum):
    UNTESTED = "untested"
    UPSTREAM_CLAIM = "upstream_claim"
    OBSERVED = "observed"


class ReuseDecision(str, Enum):
    REUSE = "reuse"
    PATCH = "patch"
    BUILD = "build"
    REJECT = "reject"


@dataclass(frozen=True)
class UpstreamProject:
    project_id: str
    name: str
    repository_url: str
    revision: str
    observed_at: str
    pushed_at: str
    categories: tuple[UpstreamCategory, ...]
    license_spdx: str
    license_evidence_url: str
    license_approved_for_code_reuse: bool
    integration_mode: IntegrationMode
    import_roots: tuple[str, ...]
    hardware_assumption: str
    cuda_only_components: tuple[str, ...]
    rocm_candidate_components: tuple[str, ...]
    rocm_evidence_level: RocmEvidenceLevel = RocmEvidenceLevel.UNTESTED
    rocm_receipt_locator: str | None = None
    archived: bool = False

    def __post_init__(self) -> None:
        if not self.project_id.strip() or not self.name.strip():
            raise V10ContractError("upstream identity is incomplete")
        if not self.repository_url.startswith("https://github.com/"):
            raise V10ContractError("upstream repository must be an official HTTPS GitHub locator")
        if not _COMMIT.fullmatch(self.revision):
            raise V10ContractError("upstream revision must be an immutable 40-character commit")
        if not self.categories or len(set(self.categories)) != len(self.categories):
            raise V10ContractError("upstream categories must be nonempty and unique")
        if not self.hardware_assumption.strip():
            raise V10ContractError("hardware assumption is required")
        if not self.import_roots or any(not item.strip() for item in self.import_roots):
            raise V10ContractError("at least one import root is required")
        for value in (self.observed_at, self.pushed_at):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise V10ContractError("upstream timestamps must be ISO-8601") from error
        if self.license_spdx == "UNRESOLVED":
            if self.license_approved_for_code_reuse:
                raise V10ContractError("unresolved licenses cannot be approved")
        elif not _SPDX.fullmatch(self.license_spdx):
            raise V10ContractError("license_spdx must be SPDX-like or UNRESOLVED")
        if not self.license_evidence_url.startswith("https://"):
            raise V10ContractError("license evidence URL is required")
        if self.rocm_evidence_level is RocmEvidenceLevel.OBSERVED:
            if not self.rocm_receipt_locator:
                raise V10ContractError("observed ROCm support requires a receipt")
        elif self.rocm_receipt_locator is not None:
            raise V10ContractError("non-observed ROCm status cannot carry an observed receipt")

    @property
    def executable_admission(self) -> bool:
        return (
            self.license_approved_for_code_reuse
            and not self.archived
            and self.rocm_evidence_level is RocmEvidenceLevel.OBSERVED
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "categories": [item.value for item in self.categories],
            "integration_mode": self.integration_mode.value,
            "rocm_evidence_level": self.rocm_evidence_level.value,
            "executable_admission": self.executable_admission,
        }


@dataclass(frozen=True)
class ReuseManifest:
    projects: tuple[UpstreamProject, ...]
    required_pins: tuple[str, ...]
    observed_at: str
    source_snapshot_sha256: str
    schema: str = "ProofLaunchReuseManifestV1"

    def __post_init__(self) -> None:
        if not self.projects:
            raise V10ContractError("reuse manifest cannot be empty")
        ids = [item.project_id for item in self.projects]
        repos = [item.repository_url for item in self.projects]
        if len(ids) != len(set(ids)) or len(repos) != len(set(repos)):
            raise V10ContractError("upstream project IDs and repositories must be unique")
        if set(self.required_pins) - set(ids):
            raise V10ContractError("required upstream pins are missing")
        covered = {category for item in self.projects for category in item.categories}
        if covered != set(UpstreamCategory):
            missing = sorted(item.value for item in set(UpstreamCategory) - covered)
            raise V10ContractError(f"upstream catalog categories are incomplete: {missing}")
        if not _SHA256.fullmatch(self.source_snapshot_sha256):
            raise V10ContractError("source snapshot must be content addressed")
        try:
            datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("manifest observed_at must be ISO-8601") from error

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": self.schema,
            "observed_at": self.observed_at,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "required_pins": list(self.required_pins),
            "category_index": {
                category.value: [
                    item.project_id for item in self.projects if category in item.categories
                ]
                for category in UpstreamCategory
            },
            "projects": [item.to_dict() for item in self.projects],
            "truth_boundary": (
                "Catalog, revision and source-license observations do not prove weight/data rights, "
                "ROCm compatibility, performance or training success. No upstream is executable-admitted "
                "until an observed pinned-revision ROCm receipt exists."
            ),
        }
        if include_digest:
            payload["content_sha256"] = stable_digest(payload)
        return payload


@dataclass(frozen=True)
class AdapterBinding:
    adapter_id: str
    project_id: str
    upstream_revision: str
    capability: str
    input_schema: str
    output_schema: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.adapter_id,
                self.project_id,
                self.capability,
                self.input_schema,
                self.output_schema,
            )
        ):
            raise V10ContractError("adapter binding fields cannot be empty")
        if not _COMMIT.fullmatch(self.upstream_revision):
            raise V10ContractError("adapter must bind an immutable upstream revision")


class AdapterRegistry:
    def __init__(self, manifest: ReuseManifest) -> None:
        self._projects = {item.project_id: item for item in manifest.projects}
        self._bindings: dict[str, AdapterBinding] = {}

    def register(self, binding: AdapterBinding) -> None:
        project = self._projects.get(binding.project_id)
        if project is None:
            raise V10ContractError("adapter references an unknown upstream")
        if project.revision != binding.upstream_revision:
            raise V10ContractError("adapter revision does not match the reuse manifest")
        if not project.license_approved_for_code_reuse:
            raise V10ContractError("adapter cannot register an unapproved source license")
        if binding.adapter_id in self._bindings:
            raise V10ContractError("adapter IDs are immutable and unique")
        self._bindings[binding.adapter_id] = binding

    def resolve(self, adapter_id: str) -> AdapterBinding:
        try:
            return self._bindings[adapter_id]
        except KeyError as error:
            raise V10ContractError("all upstream execution must resolve through a registered adapter") from error


def find_unmediated_imports(source: str, forbidden_roots: Sequence[str]) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise V10ContractError("source must parse before upstream import review") from error
    roots = set(forbidden_roots)
    findings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            findings.update(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in roots)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in roots:
                findings.add(root)
    return tuple(sorted(findings))


@dataclass(frozen=True)
class PatchRecord:
    patch_id: str
    project_id: str
    upstream_revision: str
    patch_sha256: str
    rationale: str
    source_issue_or_pr: str
    regression_test_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.patch_id.strip() or not self.project_id.strip() or not self.rationale.strip():
            raise V10ContractError("patch identity, project and rationale are required")
        if not _COMMIT.fullmatch(self.upstream_revision) or not _SHA256.fullmatch(self.patch_sha256):
            raise V10ContractError("patch must bind an immutable revision and content hash")
        if not self.source_issue_or_pr.startswith("https://"):
            raise V10ContractError("patch provenance requires an issue or PR locator")
        if not self.regression_test_ids or any(not item.strip() for item in self.regression_test_ids):
            raise V10ContractError("patch requires named regression tests")


@dataclass(frozen=True)
class MigrationPlan:
    project_id: str
    from_revision: str
    to_revision: str
    parity_case_ids: tuple[str, ...]
    rollback_revision: str

    def __post_init__(self) -> None:
        for value in (self.from_revision, self.to_revision, self.rollback_revision):
            if not _COMMIT.fullmatch(value):
                raise V10ContractError("migration revisions must be immutable commits")
        if self.from_revision == self.to_revision:
            raise V10ContractError("migration must compare distinct revisions")
        if self.rollback_revision != self.from_revision:
            raise V10ContractError("migration rollback must restore the prior revision")
        if not self.parity_case_ids:
            raise V10ContractError("migration requires parity cases")


@dataclass(frozen=True)
class HealthObservation:
    project_id: str
    archived: bool
    pushed_at: str
    observed_at: str
    license_approved: bool
    revision_resolved: bool
    smoke_passed: bool

    def score(self) -> int:
        observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        pushed = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
        age_days = max(0, (observed - pushed).days)
        freshness = 20 if age_days <= 180 else 10 if age_days <= 730 else 0
        return (
            (0 if self.archived else 20)
            + freshness
            + (25 if self.license_approved else 0)
            + (10 if self.revision_resolved else 0)
            + (25 if self.smoke_passed else 0)
        )

    def requires_fallback(self, threshold: int = 70) -> bool:
        if not 0 <= threshold <= 100:
            raise V10ContractError("health threshold must be within 0..100")
        return self.archived or self.score() < threshold


@dataclass(frozen=True)
class BuildObservation:
    strategy: str
    environment_sha256: str
    success: bool
    wall_seconds: float
    peak_memory_mb: float
    artifact_sha256: str

    def __post_init__(self) -> None:
        if self.strategy not in {"wheel", "source_build"}:
            raise V10ContractError("build strategy must be wheel or source_build")
        if not _SHA256.fullmatch(self.environment_sha256) or not _SHA256.fullmatch(self.artifact_sha256):
            raise V10ContractError("build observation hashes are required")
        if not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0:
            raise V10ContractError("build wall time must be positive and observed")
        if not math.isfinite(self.peak_memory_mb) or self.peak_memory_mb <= 0:
            raise V10ContractError("build peak memory must be positive and observed")


def select_build_strategy(observations: Sequence[BuildObservation]) -> str:
    if {item.strategy for item in observations} != {"wheel", "source_build"}:
        raise V10ContractError("wheel-vs-build requires both observed strategies")
    environments = {item.environment_sha256 for item in observations}
    if len(environments) != 1:
        raise V10ContractError("wheel-vs-build must use the same environment")
    successful = [item for item in observations if item.success]
    if not successful:
        raise V10ContractError("no build strategy passed")
    return min(successful, key=lambda item: (item.wall_seconds, item.peak_memory_mb, item.strategy)).strategy


def duplicate_function_fingerprints(source: str) -> Mapping[str, tuple[str, ...]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise V10ContractError("duplicate scan requires valid Python") from error
    groups: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha256(body_dump.encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append(node.name)
    return {
        digest: tuple(sorted(names))
        for digest, names in groups.items()
        if len(names) > 1
    }


@dataclass(frozen=True)
class CandidateAssessment:
    project_id: str
    revision: str
    evaluated: bool
    suitable: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.project_id.strip() or not _COMMIT.fullmatch(self.revision) or not self.reason.strip():
            raise V10ContractError("reuse candidate assessment is incomplete")
        if self.suitable and not self.evaluated:
            raise V10ContractError("an unevaluated candidate cannot be suitable")


@dataclass(frozen=True)
class ReuseReview:
    module_path: str
    need: str
    candidates: tuple[CandidateAssessment, ...]
    decision: ReuseDecision
    selected_project_id: str | None
    falsifiable_benefit: str
    evidence_locator: str

    def __post_init__(self) -> None:
        if not self.module_path.strip() or not self.need.strip() or not self.evidence_locator.strip():
            raise V10ContractError("reuse review path, need and evidence are required")
        if not self.candidates:
            raise V10ContractError("reuse review must evaluate upstream candidates")
        if self.decision in {ReuseDecision.REUSE, ReuseDecision.PATCH}:
            selected = [item for item in self.candidates if item.project_id == self.selected_project_id]
            if len(selected) != 1 or not selected[0].suitable:
                raise V10ContractError("reuse/patch decisions require one suitable selected upstream")
        elif self.decision is ReuseDecision.BUILD:
            if self.selected_project_id is not None:
                raise V10ContractError("build decision cannot select an upstream")
            if any(not item.evaluated or item.suitable for item in self.candidates):
                raise V10ContractError("original build requires every candidate to be evaluated and unsuitable")
            if not self.falsifiable_benefit.strip():
                raise V10ContractError("original build requires a falsifiable benefit")
        elif self.selected_project_id is not None:
            raise V10ContractError("rejected review cannot select an upstream")


def smoke_plan(manifest: ReuseManifest) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "project_id": item.project_id,
            "revision": item.revision,
            "license_gate": item.license_approved_for_code_reuse,
            "rocm_evidence_level": item.rocm_evidence_level.value,
            "network_fetch_required": True,
            "execution_status": "not_run",
        }
        for item in manifest.projects
    )
