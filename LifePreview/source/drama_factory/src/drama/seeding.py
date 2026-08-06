from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Final


SEED_DERIVATION_VERSION: Final = "sha256-v1"
MAX_LEGACY_SEED: Final = 0x7FFFFFFF


@dataclass(frozen=True, slots=True)
class SeedDerivation:
    resolved_seed: int
    seed_derivation_version: str
    seed_input_hash: str


def _derive(parts: tuple[str, ...]) -> SeedDerivation:
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).digest()
    return SeedDerivation(
        resolved_seed=(int.from_bytes(digest[:8], "big") % MAX_LEGACY_SEED) + 1,
        seed_derivation_version=SEED_DERIVATION_VERSION,
        seed_input_hash=digest.hex(),
    )


def derive_initial_seed(
    *,
    project_revision_id: str,
    clip_id: str,
    generation_mode: str,
    model_id: str,
    initial_seed_slot: str = "default",
) -> SeedDerivation:
    return _derive(
        (
            "initial",
            project_revision_id,
            clip_id,
            generation_mode,
            model_id,
            initial_seed_slot,
        )
    )


def derive_reroll_seed(
    *,
    parent_resolved_seed: int,
    reroll_index: int,
) -> SeedDerivation:
    if reroll_index < 1:
        raise ValueError("reroll_index must be positive")
    return _derive(
        (
            "reroll",
            str(parent_resolved_seed),
            str(reroll_index),
            SEED_DERIVATION_VERSION,
        )
    )


def derive_legacy_seed(namespace: str, identifier: str) -> SeedDerivation:
    """Stable bridge seed for legacy objects that lack a project revision."""

    if not namespace or not identifier:
        raise ValueError("namespace and identifier are required")
    return _derive(("legacy", namespace, identifier))
