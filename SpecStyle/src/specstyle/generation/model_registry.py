"""Model registry with license/revision/SHA gate (SEC-001A consumable)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError

LicenseStatus = Literal["APPROVED", "BLOCKED", "UNKNOWN"]
ModelRole = Literal[
    "base", "ip_adapter", "controlnet", "preview_adapter", "style_encoder", "l3_feature"
]
_FULL_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_LICENSE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}", re.ASCII)
_RESERVED_LICENSES = frozenset(
    {"unknown", "tbd", "todo", "placeholder", "pending", "none", "n/a", "na"}
)
_PRODUCTION_LICENSES_BY_CASEFOLD = {
    license_id.casefold(): license_id
    for license_id in ("Apache-2.0", "MIT", "OpenRAIL++-M")
}
_PLACEHOLDER_MODEL_IDS = (
    "sdxl-base-1.0",
    "ip-adapter-plus-sdxl",
    "controlnet-canny-sdxl",
    "lcm-lora-sdxl",
    "style-encoder-clip-vit-l",
    "l3-product-feature-v1",
)
_KNOWN_PLACEHOLDER_DIGESTS = frozenset(
    hashlib.sha256(f"sec001a-placeholder:{model_id}".encode()).hexdigest()
    for model_id in _PLACEHOLDER_MODEL_IDS
)


def validate_production_license(value: object) -> str:
    if type(value) is not str:
        raise DomainError("invalid production license")
    normalized = value.strip()
    casefolded = normalized.casefold()
    if (
        casefolded in _RESERVED_LICENSES
        or normalized != value
        or _LICENSE_TOKEN.fullmatch(normalized) is None
        or _PRODUCTION_LICENSES_BY_CASEFOLD.get(casefolded) != normalized
    ):
        raise DomainError("invalid production license")
    return normalized


def is_known_placeholder_digest(value: object) -> bool:
    return type(value) is Sha256 and value.value in _KNOWN_PLACEHOLDER_DIGESTS


@dataclass(frozen=True, slots=True)
class ModelPin:
    """Immutable production content pin for a resolved model component."""

    sha256: Sha256

    def __post_init__(self) -> None:
        if type(self.sha256) is not Sha256:
            raise DomainError("invalid model pin")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    model_id: str
    role: ModelRole
    revision: str
    expected_sha256: Sha256
    license_spdx: str
    license_status: LicenseStatus
    family: str

    @property
    def pin(self) -> ModelPin:
        return ModelPin(self.expected_sha256)

    def __post_init__(self) -> None:
        if type(self.model_id) is not str or not self.model_id:
            raise DomainError("invalid model descriptor")
        if self.role not in (
            "base",
            "ip_adapter",
            "controlnet",
            "preview_adapter",
            "style_encoder",
            "l3_feature",
        ):
            raise DomainError("invalid model role")
        if (
            type(self.revision) is not str
            or not self.revision
            or self.revision
            in (
                "main",
                "latest",
            )
        ):
            raise DomainError("floating revision forbidden")
        if type(self.expected_sha256) is not Sha256:
            raise DomainError("invalid model sha")
        if type(self.license_spdx) is not str or not self.license_spdx:
            raise DomainError("invalid license")
        if self.license_status not in ("APPROVED", "BLOCKED", "UNKNOWN"):
            raise DomainError("invalid license status")
        if type(self.family) is not str or not self.family:
            raise DomainError("invalid family")


class ModelRegistry:
    def __init__(self, descriptors: tuple[ModelDescriptor, ...]) -> None:
        if type(descriptors) is not tuple:
            raise DomainError("invalid registry")
        seen: set[str] = set()
        by_id: dict[str, ModelDescriptor] = {}
        for d in descriptors:
            if type(d) is not ModelDescriptor:
                raise DomainError("invalid registry")
            if d.model_id in seen:
                raise DomainError("duplicate model id")
            seen.add(d.model_id)
            by_id[d.model_id] = d
        self._by_id = by_id

    def get(self, model_id: str) -> ModelDescriptor:
        if type(model_id) is not str or model_id not in self._by_id:
            raise DomainError("model not registered")
        return self._by_id[model_id]

    def require_production(self, model_id: str) -> ModelDescriptor:
        desc = self.get(model_id)
        if desc.license_status == "UNKNOWN":
            raise DomainError("model license UNKNOWN blocked")
        if desc.license_status == "BLOCKED":
            raise DomainError("model license BLOCKED")
        if desc.license_status != "APPROVED":
            raise DomainError("model license not approved")
        validate_production_license(desc.license_spdx)
        if _FULL_REVISION.fullmatch(desc.revision) is None:
            raise DomainError("model revision must be a full lowercase commit OID")
        if is_known_placeholder_digest(desc.expected_sha256):
            raise DomainError("known placeholder digest cannot enter production")
        return desc
