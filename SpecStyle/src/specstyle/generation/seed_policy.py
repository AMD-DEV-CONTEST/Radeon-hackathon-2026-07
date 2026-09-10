"""Deterministic seed derivation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import OutputProfile


def _variation_index(value: object) -> int:
    if type(value) is not int or not 0 <= value < 2**31:
        raise DomainError("variation index must be an exact int in range")
    return value


def _seed_value(
    source_sha256: Sha256,
    compiled_spec_hash: Sha256,
    output_profile: OutputProfile,
    variation_index: int,
) -> int:
    payload = {
        "domain": "specstyle.seed.v1",
        "source_sha256": source_sha256.value,
        "compiled_spec_hash": compiled_spec_hash.value,
        "output_profile": output_profile,
        "variation_index": variation_index,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") & ((1 << 63) - 1)


@dataclass(frozen=True, slots=True)
class SeedSnapshot:
    """Auditable deterministic seed snapshot."""

    source_sha256: Sha256
    compiled_spec_hash: Sha256
    output_profile: OutputProfile
    variation_index: int
    algorithm: Literal["specstyle.seed.v1"] = field(
        init=False, default="specstyle.seed.v1"
    )
    seed: int = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.source_sha256) is not Sha256
            or type(self.compiled_spec_hash) is not Sha256
        ):
            raise DomainError("seed hashes must be Sha256")
        source_sha256 = Sha256(self.source_sha256.value)
        compiled_spec_hash = Sha256(self.compiled_spec_hash.value)
        if type(self.output_profile) is not str or self.output_profile not in {
            "xhs_grid",
            "talking_head_cover",
            "background_sequence",
        }:
            raise DomainError("invalid output profile")
        index = _variation_index(self.variation_index)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "compiled_spec_hash", compiled_spec_hash)
        object.__setattr__(self, "variation_index", index)
        object.__setattr__(
            self,
            "seed",
            _seed_value(source_sha256, compiled_spec_hash, self.output_profile, index),
        )


def derive_seed(
    source_sha256: Sha256,
    compiled_spec_hash: Sha256,
    output_profile: OutputProfile,
    variation_index: int,
) -> SeedSnapshot:
    """Derive a seed solely from stable generation material."""
    return SeedSnapshot(
        source_sha256, compiled_spec_hash, output_profile, variation_index
    )
