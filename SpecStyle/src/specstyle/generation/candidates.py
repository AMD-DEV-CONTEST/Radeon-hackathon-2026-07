"""SEC-001A candidate model catalog — license gate inputs only.

Real production weights stay UNKNOWN until a human sets APPROVED with pinned
revision + content hash evidence. Code never downloads models and never treats
UNKNOWN/BLOCKED as production-ready.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.model_registry import (
    LicenseStatus,
    ModelDescriptor,
    ModelRegistry,
    ModelRole,
    is_known_placeholder_digest,
    validate_production_license,
)

Redistribution = Literal["allowed", "restricted", "forbidden", "unknown"]
CommercialUse = Literal["allowed", "restricted", "forbidden", "unknown"]
_FULL_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


@dataclass(frozen=True, slots=True)
class LicenseEvidence:
    """Human-auditable license record (no secrets)."""

    spdx: str
    license_url: str
    commercial_use: CommercialUse
    redistribution: Redistribution
    derivative_works: Redistribution
    notes: str

    def __post_init__(self) -> None:
        if type(self.spdx) is not str or not self.spdx.strip():
            raise DomainError("invalid license evidence")
        if type(self.license_url) is not str or not self.license_url.startswith(
            ("https://", "http://")
        ):
            raise DomainError("invalid license evidence url")
        for field in (
            self.commercial_use,
            self.redistribution,
            self.derivative_works,
        ):
            if field not in ("allowed", "restricted", "forbidden", "unknown"):
                raise DomainError("invalid license evidence use flag")
        if type(self.notes) is not str:
            raise DomainError("invalid license evidence notes")


@dataclass(frozen=True, slots=True)
class CandidateModel:
    """Pinned candidate; status is human-owned, not auto-inferred."""

    model_id: str
    role: ModelRole
    family: str
    revision: str
    expected_sha256: Sha256
    license_status: LicenseStatus
    evidence: LicenseEvidence
    weights_relpath: str
    purpose: str

    def __post_init__(self) -> None:
        if type(self.model_id) is not str or not self.model_id:
            raise DomainError("invalid candidate")
        if self.role not in (
            "base",
            "ip_adapter",
            "controlnet",
            "preview_adapter",
            "style_encoder",
            "l3_feature",
        ):
            raise DomainError("invalid candidate role")
        if type(self.family) is not str or not self.family:
            raise DomainError("invalid candidate family")
        if (
            type(self.revision) is not str
            or not self.revision
            or self.revision in ("main", "latest")
        ):
            raise DomainError("floating revision forbidden")
        if type(self.expected_sha256) is not Sha256:
            raise DomainError("invalid candidate sha")
        if self.license_status not in ("APPROVED", "BLOCKED", "UNKNOWN"):
            raise DomainError("invalid candidate license status")
        if type(self.evidence) is not LicenseEvidence:
            raise DomainError("invalid candidate evidence")
        if type(self.weights_relpath) is not str or not self.weights_relpath:
            raise DomainError("invalid candidate weights path")
        if ".." in self.weights_relpath.split("/"):
            raise DomainError("weights path escape")
        if type(self.purpose) is not str or not self.purpose:
            raise DomainError("invalid candidate purpose")

    def to_descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            self.model_id,
            self.role,
            self.revision,
            self.expected_sha256,
            self.evidence.spdx,
            self.license_status,
            self.family,
        )


def _sha_marker(tag: str) -> Sha256:
    """Stable placeholder digest for unweighed pins (not a real weight hash)."""
    from specstyle.observability.hashing import hash_bytes

    return hash_bytes(f"sec001a-placeholder:{tag}".encode())


def default_candidates() -> tuple[CandidateModel, ...]:
    """Frozen first-wave SDXL stack — all UNKNOWN until human SEC-001A approve."""
    fam = "sdxl"
    return (
        CandidateModel(
            "sdxl-base-1.0",
            "base",
            fam,
            "rev-placeholder-001",
            _sha_marker("sdxl-base-1.0"),
            "UNKNOWN",
            LicenseEvidence(
                "OpenRAIL++-M",
                "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
                "restricted",
                "restricted",
                "restricted",
                "Human must pin real git revision + content hash before APPROVED",
            ),
            "sdxl-base-1.0/rev-placeholder-001",
            "production base img2img",
        ),
        CandidateModel(
            "ip-adapter-plus-sdxl",
            "ip_adapter",
            fam,
            "rev-placeholder-001",
            _sha_marker("ip-adapter-plus-sdxl"),
            "UNKNOWN",
            LicenseEvidence(
                "Apache-2.0",
                "https://huggingface.co/h94/IP-Adapter",
                "unknown",
                "unknown",
                "unknown",
                "Confirm commercial terms + weight hash before APPROVED",
            ),
            "ip-adapter-plus-sdxl/rev-placeholder-001",
            "style reference conditioning",
        ),
        CandidateModel(
            "controlnet-canny-sdxl",
            "controlnet",
            fam,
            "rev-placeholder-001",
            _sha_marker("controlnet-canny-sdxl"),
            "UNKNOWN",
            LicenseEvidence(
                "Apache-2.0",
                "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0",
                "unknown",
                "unknown",
                "unknown",
                "Confirm license + weight hash before APPROVED",
            ),
            "controlnet-canny-sdxl/rev-placeholder-001",
            "structure ControlNet (canny only)",
        ),
        CandidateModel(
            "lcm-lora-sdxl",
            "preview_adapter",
            fam,
            "rev-placeholder-001",
            _sha_marker("lcm-lora-sdxl"),
            "UNKNOWN",
            LicenseEvidence(
                "OpenRAIL++-M",
                "https://huggingface.co/latent-consistency/lcm-lora-sdxl",
                "restricted",
                "restricted",
                "restricted",
                "Preview-only; never mixed into Production QA metrics",
            ),
            "lcm-lora-sdxl/rev-placeholder-001",
            "preview LCM-LoRA adapter",
        ),
        CandidateModel(
            "style-encoder-clip-vit-l",
            "style_encoder",
            fam,
            "rev-placeholder-001",
            _sha_marker("style-encoder-clip-vit-l"),
            "UNKNOWN",
            LicenseEvidence(
                "MIT",
                "https://github.com/openai/CLIP",
                "allowed",
                "allowed",
                "allowed",
                "Style features only after L2-005 calibration; not content gate",
            ),
            "style-encoder-clip-vit-l/rev-placeholder-001",
            "L2 style encoder candidate",
        ),
        CandidateModel(
            "l3-product-feature-v1",
            "l3_feature",
            fam,
            "rev-placeholder-001",
            _sha_marker("l3-product-feature-v1"),
            "UNKNOWN",
            LicenseEvidence(
                "UNKNOWN",
                "https://example.invalid/l3-feature-pending",
                "unknown",
                "unknown",
                "unknown",
                "No production L3 feature model selected; remain UNKNOWN",
            ),
            "l3-product-feature-v1/rev-placeholder-001",
            "L3 product local feature extractor",
        ),
    )


def with_license_status(
    candidates: tuple[CandidateModel, ...],
    model_id: str,
    status: LicenseStatus,
) -> tuple[CandidateModel, ...]:
    """Return a copy with one candidate's human status updated."""
    if type(candidates) is not tuple or type(model_id) is not str:
        raise DomainError("invalid candidates update")
    if status not in ("APPROVED", "BLOCKED", "UNKNOWN"):
        raise DomainError("invalid license status")
    out: list[CandidateModel] = []
    found = False
    for item in candidates:
        if type(item) is not CandidateModel:
            raise DomainError("invalid candidate")
        if item.model_id == model_id:
            if status == "APPROVED" and _FULL_REVISION.fullmatch(item.revision) is None:
                raise DomainError("placeholder or floating revision cannot be approved")
            if status == "APPROVED":
                validate_production_license(item.evidence.spdx)
                if is_known_placeholder_digest(item.expected_sha256):
                    raise DomainError("known placeholder digest cannot be approved")
            out.append(replace(item, license_status=status))
            found = True
        else:
            out.append(item)
    if not found:
        raise DomainError("model not in candidates")
    return tuple(out)


def approved_production_registry(
    candidates: tuple[CandidateModel, ...],
    manifests: tuple[object, ...],
    approvals: tuple[object, ...],
) -> ModelRegistry:
    """Build the production registry only from independently approved manifests."""
    from specstyle.generation.model_approval import LicenseApproval
    from specstyle.generation.weight_manifest import (
        WeightManifest,
        manifest_root_sha256,
        manifest_sha256,
    )

    if (
        type(candidates) is not tuple
        or type(manifests) is not tuple
        or type(approvals) is not tuple
        or len(candidates) != 3
        or len(manifests) != 3
        or len(approvals) != 3
        or any(type(item) is not CandidateModel for item in candidates)
        or any(type(item) is not WeightManifest for item in manifests)
        or any(type(item) is not LicenseApproval for item in approvals)
    ):
        raise DomainError("invalid independent production approval inputs")
    required_roles = ("base", "ip_adapter", "controlnet")
    candidate_by_role = _exact_role_map(candidates, required_roles)
    manifest_by_role = _exact_role_map(manifests, required_roles)
    approval_by_model = {item.model_id: item for item in approvals}
    if len(approval_by_model) != 3:
        raise DomainError("duplicate independent production approval")
    descriptors: list[ModelDescriptor] = []
    families: set[str] = set()
    for role in required_roles:
        candidate = candidate_by_role[role]
        manifest = manifest_by_role[role]
        approval = approval_by_model.get(candidate.model_id)
        if approval is None:
            raise DomainError("independent production approval missing")
        if (
            candidate.license_status != "APPROVED"
            or candidate.model_id != manifest.model_id
            or candidate.revision != manifest.revision
            or candidate.weights_relpath != manifest.relative_root
            or candidate.expected_sha256 != manifest.root_sha256
            or manifest.root_sha256 != manifest_root_sha256(manifest)
            or approval.revision != manifest.revision
            or approval.manifest_sha256 != manifest_sha256(manifest)
            or approval.license_spdx != candidate.evidence.spdx
            or approval.evidence_url != candidate.evidence.license_url
        ):
            raise DomainError("independent production approval mismatch")
        validate_production_license(candidate.evidence.spdx)
        if is_known_placeholder_digest(candidate.expected_sha256):
            raise DomainError("known placeholder digest cannot enter production")
        descriptor = candidate.to_descriptor()
        ModelRegistry((descriptor,)).require_production(candidate.model_id)
        descriptors.append(descriptor)
        families.add(candidate.family)
    if len(families) != 1:
        raise DomainError("production model family mismatch")
    return ModelRegistry(tuple(descriptors))


def _exact_role_map(
    items: tuple[object, ...], required_roles: tuple[str, ...]
) -> dict[str, object]:
    by_role: dict[str, object] = {}
    for item in items:
        role = item.role  # type: ignore[attr-defined]
        if role in by_role:
            raise DomainError("duplicate production component role")
        by_role[role] = item
    if set(by_role) != set(required_roles):
        raise DomainError("invalid production component roles")
    return by_role


def catalog_summary(
    candidates: tuple[CandidateModel, ...],
) -> tuple[dict[str, str], ...]:
    """Non-secret summary for audit logs (status + urls only)."""
    if type(candidates) is not tuple:
        raise DomainError("invalid candidates")
    rows: list[dict[str, str]] = []
    for item in candidates:
        if type(item) is not CandidateModel:
            raise DomainError("invalid candidate")
        rows.append(
            {
                "model_id": item.model_id,
                "role": item.role,
                "revision": item.revision,
                "license_status": item.license_status,
                "spdx": item.evidence.spdx,
                "license_url": item.evidence.license_url,
                "purpose": item.purpose,
            }
        )
    return tuple(rows)
