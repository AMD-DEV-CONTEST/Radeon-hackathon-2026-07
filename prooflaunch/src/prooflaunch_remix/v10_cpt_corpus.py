from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError


TARGET_CPT_TOKENS = 15_000_000
MAX_PROVIDER_SHARE = 0.15
MIN_PROVIDER_COUNT = 10
APPROVED_CPT_LICENSES = frozenset(
    {"Apache-2.0", "MIT", "BSD-3-Clause", "CC0-1.0"}
)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))


def shingle_set(text: str, *, width: int = 5) -> frozenset[str]:
    words = normalized_words(text)
    if not words:
        return frozenset()
    if len(words) < width:
        return frozenset({" ".join(words)})
    return frozenset(" ".join(words[index : index + width]) for index in range(len(words) - width + 1))


def near_duplicate(left: frozenset[str], right: frozenset[str], *, threshold: float = 0.90) -> bool:
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= threshold


@dataclass(frozen=True)
class CPTCorpusRecord:
    record_id: str
    provider: str
    source_id: str
    source_path: str
    source_revision: str
    license_spdx: str
    license_evidence_url: str
    permitted_use: str
    asset_level_rights_verified: bool
    commercial_training_allowed: bool
    rights_basis: str
    content_class: str
    text: str
    token_count: int
    content_sha256: str
    training_admitted: bool = True
    model_output: bool = False
    evaluation_contaminated: bool = False

    def __post_init__(self) -> None:
        required = (
            self.record_id,
            self.provider,
            self.source_id,
            self.source_path,
            self.source_revision,
            self.license_evidence_url,
            self.permitted_use,
            self.rights_basis,
            self.content_class,
            self.text,
        )
        if any(not value.strip() for value in required):
            raise V10ContractError("CPT record identity, provenance and text are required")
        if self.license_spdx not in APPROVED_CPT_LICENSES:
            raise V10ContractError(f"CPT license is not admitted: {self.license_spdx}")
        if self.permitted_use != "training_candidate":
            raise V10ContractError("CPT record must be an explicit training candidate")
        if not self.asset_level_rights_verified or not self.commercial_training_allowed:
            raise V10ContractError("CPT record lacks asset-level commercial training rights")
        if self.token_count <= 0:
            raise V10ContractError("CPT record token count must be positive")
        if self.content_sha256 != text_sha256(self.text):
            raise V10ContractError("CPT record content hash mismatch")
        if not self.training_admitted or self.model_output or self.evaluation_contaminated:
            raise V10ContractError("CPT record violates the training truth boundary")


def verify_cpt_summary(summary: Mapping[str, object]) -> None:
    if int(summary.get("token_count", -1)) != TARGET_CPT_TOKENS:
        raise V10ContractError("CPT corpus must contain exactly 15,000,000 tokenizer-observed tokens")
    if not bool(summary.get("token_count_observed", False)):
        raise V10ContractError("CPT token count must be observed with the pinned tokenizer")
    if int(summary.get("provider_count", 0)) < MIN_PROVIDER_COUNT:
        raise V10ContractError("CPT corpus lacks provider diversity")
    maximum_share = float(summary.get("maximum_provider_share", math.inf))
    if not math.isfinite(maximum_share) or maximum_share > MAX_PROVIDER_SHARE:
        raise V10ContractError("CPT corpus exceeds the single-provider concentration cap")
    zero_fields = (
        "duplicate_record_count",
        "near_duplicate_record_count",
        "unresolved_rights_count",
        "model_output_record_count",
        "evaluation_contamination_count",
        "forbidden_evaluation_class_token_count",
    )
    if any(int(summary.get(name, -1)) != 0 for name in zero_fields):
        raise V10ContractError("CPT corpus dedupe, rights, model-output or evaluation gate failed")
    for name in ("tokenizer_sha256", "manifest_sha256", "corpus_content_sha256"):
        value = str(summary.get(name, ""))
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise V10ContractError(f"CPT summary requires a SHA-256 field: {name}")
    provider_tokens = summary.get("provider_token_counts")
    if not isinstance(provider_tokens, Mapping):
        raise V10ContractError("CPT provider token counts are required")
    if sum(int(value) for value in provider_tokens.values()) != TARGET_CPT_TOKENS:
        raise V10ContractError("CPT provider token counts do not reconcile")


def verify_record_identities(records: Sequence[CPTCorpusRecord]) -> None:
    if len({record.record_id for record in records}) != len(records):
        raise V10ContractError("CPT record IDs must be unique")
    if len({record.content_sha256 for record in records}) != len(records):
        raise V10ContractError("CPT record content hashes must be unique")
