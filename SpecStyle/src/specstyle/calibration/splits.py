"""Calibration / validation / test split isolation by content hash."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

SplitName = Literal["calibration", "validation", "test"]


@dataclass(frozen=True, slots=True)
class SampleRef:
    sample_id: str
    content_sha256: Sha256
    style_id: str
    content_id: str
    label_positive: bool

    def __post_init__(self) -> None:
        if type(self.sample_id) is not str or not self.sample_id:
            raise DomainError("invalid sample")
        if type(self.content_sha256) is not Sha256:
            raise DomainError("invalid sample hash")
        if type(self.style_id) is not str or not self.style_id:
            raise DomainError("invalid sample style")
        if type(self.content_id) is not str or not self.content_id:
            raise DomainError("invalid sample content")
        if type(self.label_positive) is not bool:
            raise DomainError("invalid sample label")


@dataclass(frozen=True, slots=True)
class SplitManifest:
    protocol_version: str
    calibration: tuple[SampleRef, ...]
    validation: tuple[SampleRef, ...]
    test: tuple[SampleRef, ...]
    manifest_hash: Sha256

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not str or not self.protocol_version:
            raise DomainError("invalid split protocol")
        for name in ("calibration", "validation", "test"):
            if type(getattr(self, name)) is not tuple:
                raise DomainError("invalid split")
        if type(self.manifest_hash) is not Sha256:
            raise DomainError("invalid split hash")


def assign_split(content_sha256: Sha256, salt: str = "lookfile-split-v1") -> SplitName:
    """Deterministic 60/20/20 split by content hash (not by style alone)."""
    if type(content_sha256) is not Sha256:
        raise DomainError("invalid content hash")
    if type(salt) is not str or not salt:
        raise DomainError("invalid split salt")
    material = hash_bytes(f"{salt}:{content_sha256.value}".encode()).value
    bucket = int(material[:8], 16) % 100
    if bucket < 60:
        return "calibration"
    if bucket < 80:
        return "validation"
    return "test"


def build_split_manifest(
    samples: tuple[SampleRef, ...],
    *,
    protocol_version: str = "split-v1",
    salt: str = "lookfile-split-v1",
) -> SplitManifest:
    if type(samples) is not tuple:
        raise DomainError("invalid samples")
    buckets: dict[SplitName, list[SampleRef]] = {
        "calibration": [],
        "validation": [],
        "test": [],
    }
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for sample in samples:
        if type(sample) is not SampleRef:
            raise DomainError("invalid sample")
        if sample.sample_id in seen_ids:
            raise DomainError("duplicate sample id")
        if sample.content_sha256.value in seen_hashes:
            raise DomainError("duplicate content hash leakage")
        seen_ids.add(sample.sample_id)
        seen_hashes.add(sample.content_sha256.value)
        buckets[assign_split(sample.content_sha256, salt)].append(sample)
    cal = tuple(buckets["calibration"])
    val = tuple(buckets["validation"])
    test = tuple(buckets["test"])
    # Content-id must not appear in more than one split (source isolation).
    _assert_content_id_isolation(cal, val, test)
    material = _manifest_material(protocol_version, cal, val, test)
    return SplitManifest(
        protocol_version, cal, val, test, hash_bytes(material.encode())
    )


def _assert_content_id_isolation(
    cal: tuple[SampleRef, ...],
    val: tuple[SampleRef, ...],
    test: tuple[SampleRef, ...],
) -> None:
    maps = (
        ("calibration", {s.content_id for s in cal}),
        ("validation", {s.content_id for s in val}),
        ("test", {s.content_id for s in test}),
    )
    for i, (n1, s1) in enumerate(maps):
        for n2, s2 in maps[i + 1 :]:
            overlap = s1 & s2
            if overlap:
                raise DomainError(f"content_id leak {n1}/{n2}")


def _manifest_material(
    protocol: str,
    cal: tuple[SampleRef, ...],
    val: tuple[SampleRef, ...],
    test: tuple[SampleRef, ...],
) -> str:
    def part(name: str, items: tuple[SampleRef, ...]) -> str:
        rows = sorted(f"{s.sample_id}:{s.content_sha256.value}" for s in items)
        return name + ":" + ",".join(rows)

    return "|".join((protocol, part("cal", cal), part("val", val), part("test", test)))
