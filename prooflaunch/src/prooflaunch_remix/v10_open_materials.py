from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable
from urllib.parse import urlparse

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


class MaterialKind(str, Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    BRAND = "brand"
    PRODUCT_VISUAL = "product_visual"
    SCENE_VISUAL = "scene_visual"
    VIDEO = "video"
    FONT = "font"
    AUDIO = "audio"


class Admission(str, Enum):
    TRAINING = "training"
    REFERENCE_ONLY = "reference_only"
    REJECT = "reject"


PERMISSIVE_TRAINING_LICENSES = frozenset(
    {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0", "OFL-1.1"}
)


@dataclass(frozen=True)
class OpenMaterial:
    source_id: str
    kind: MaterialKind
    title: str
    asset_url: str
    evidence_url: str
    license_id: str
    license_url: str
    revision: str
    upstream_digest_algorithm: str
    upstream_digest: str
    media_type: str
    attribution: str
    asset_granular_license_verified: bool
    commercial_allowed: bool
    derivatives_allowed: bool
    redistribution_allowed: bool
    training_allowed: bool
    trademark_hold: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        required = (
            self.source_id,
            self.title,
            self.license_id,
            self.revision,
            self.upstream_digest_algorithm,
            self.upstream_digest,
            self.media_type,
            self.attribution,
        )
        if not all(value.strip() for value in required):
            raise V10ContractError("open material identity is incomplete")
        for label, locator in (
            ("asset", self.asset_url),
            ("evidence", self.evidence_url),
            ("license", self.license_url),
        ):
            parsed = urlparse(locator)
            if parsed.scheme != "https" or not parsed.hostname:
                raise V10ContractError(f"{label} locator must be public HTTPS")
        if self.kind in {
            MaterialKind.PRODUCT_VISUAL,
            MaterialKind.SCENE_VISUAL,
            MaterialKind.VIDEO,
            MaterialKind.FONT,
            MaterialKind.AUDIO,
        } and not self.asset_granular_license_verified:
            raise V10ContractError("media requires asset-granular license evidence")
        if self.training_allowed and self.license_id not in PERMISSIVE_TRAINING_LICENSES:
            raise V10ContractError("training cannot rely on an unapproved license")
        if self.training_allowed and self.trademark_hold:
            raise V10ContractError("trademark-held material cannot enter training")

    @property
    def admission(self) -> Admission:
        if self.training_allowed and not self.trademark_hold:
            return Admission.TRAINING
        if self.evidence_url and self.license_url:
            return Admission.REFERENCE_ONLY
        return Admission.REJECT

    @property
    def identity_sha256(self) -> str:
        return stable_sha256(asdict(self))


@dataclass(frozen=True)
class OpenMaterialBundle:
    records: tuple[OpenMaterial, ...]
    target_source_count: int = 2_000

    def __post_init__(self) -> None:
        if not self.records:
            raise V10ContractError("open material bundle cannot be empty")
        ids = [item.source_id for item in self.records]
        if len(ids) != len(set(ids)):
            raise V10ContractError("open material source IDs must be unique")
        missing = set(MaterialKind) - {item.kind for item in self.records}
        if missing:
            raise V10ContractError(
                "open material bundle misses kinds: "
                + ", ".join(sorted(item.value for item in missing))
            )
        if self.target_source_count <= 0:
            raise V10ContractError("target source count must be positive")

    @property
    def content_sha256(self) -> str:
        return stable_sha256([item.identity_sha256 for item in self.records])

    def counts(self) -> dict[str, int]:
        return {
            kind.value: sum(item.kind is kind for item in self.records)
            for kind in MaterialKind
        }

    def receipt(self) -> dict[str, object]:
        training = tuple(
            item.source_id for item in self.records if item.admission is Admission.TRAINING
        )
        held = tuple(
            item.source_id
            for item in self.records
            if item.admission is Admission.REFERENCE_ONLY
        )
        return {
            "schema": "ProofLaunchOpenMaterialBundleV1",
            "record_count": len(self.records),
            "counts": self.counts(),
            "training_admitted_ids": training,
            "reference_only_ids": held,
            "target_source_count": self.target_source_count,
            "target_complete": len(self.records) >= self.target_source_count,
            "promotion_eligible": False,
            "content_sha256": self.content_sha256,
            "truth_boundary": (
                "This is a 24-record rights-verified intake seed, not the required "
                "2,000-source Agency Corpus V2 bundle. Brand and trademark-bearing "
                "records remain reference-only."
            ),
        }


def build_bundle(records: Iterable[OpenMaterial]) -> OpenMaterialBundle:
    return OpenMaterialBundle(tuple(records))
