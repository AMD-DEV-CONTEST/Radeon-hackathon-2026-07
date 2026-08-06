from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .v10_contracts import V10ContractError
from .v10_sft_contract import CurriculumInput, CurriculumStage, default_stage_definitions


TARGET_SFT_EPISODES = 15_000
TRAIN_EPISODES = 13_500
VALIDATION_EPISODES = 1_500
SFT_CORPUS_SCHEMA = "ProofLaunchSFTEpisodeCorpusV1"
SFT_RECORD_SCHEMA = "ProofLaunchSFTEpisodeV1"

_REQUIRED_OUTPUTS = {
    item.stage.value: item.required_outputs for item in default_stage_definitions()
}


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SFTEpisode:
    schema: str
    episode_id: str
    scenario_family_id: str
    split: str
    stage: str
    input_kind: str
    system_prompt: str
    user_prompt: str
    completion: Mapping[str, Any]
    source_ids: tuple[str, ...]
    source_revisions: tuple[str, ...]
    source_identity_sha256s: tuple[str, ...]
    evidence_urls: tuple[str, ...]
    asset_urls: tuple[str, ...]
    license_ids: tuple[str, ...]
    license_urls: tuple[str, ...]
    rights_verified: bool
    training_allowed: bool
    trademark_hold: bool
    model_generated: bool
    hidden_reasoning: bool
    external_side_effect: bool
    modality_payload_observed: bool
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schema != SFT_RECORD_SCHEMA:
            raise V10ContractError("unknown SFT episode schema")
        if self.split not in {"train", "validation"}:
            raise V10ContractError("SFT split must be train or validation")
        if self.stage not in {item.value for item in CurriculumStage}:
            raise V10ContractError("unknown SFT curriculum stage")
        if self.input_kind not in {item.value for item in CurriculumInput}:
            raise V10ContractError("unknown SFT input kind")
        if not self.episode_id or not self.scenario_family_id:
            raise V10ContractError("episode and scenario family ids are required")
        widths = {
            len(self.source_ids),
            len(self.source_revisions),
            len(self.source_identity_sha256s),
            len(self.evidence_urls),
            len(self.asset_urls),
            len(self.license_ids),
            len(self.license_urls),
        }
        if widths != {len(self.source_ids)} or not self.source_ids:
            raise V10ContractError("source provenance columns must be aligned and non-empty")
        if not self.rights_verified or not self.training_allowed or self.trademark_hold:
            raise V10ContractError("every SFT source must pass asset-level training rights")
        if self.model_generated or self.hidden_reasoning or self.external_side_effect:
            raise V10ContractError("unreviewed model output, hidden reasoning, and side effects are forbidden")
        if any(len(value) != 64 for value in self.source_identity_sha256s):
            raise V10ContractError("source identities must be SHA-256")
        required = set(_REQUIRED_OUTPUTS[self.stage])
        outputs = self.completion.get("outputs")
        if not isinstance(outputs, Mapping) or not required.issubset(outputs):
            raise V10ContractError("completion is missing stage-required outputs")
        if self.completion.get("scenario_family_id") != self.scenario_family_id:
            raise V10ContractError("completion must remain scenario-family bound")
        material = asdict(self)
        observed_digest = material.pop("content_sha256")
        if observed_digest != stable_sha256(material):
            raise V10ContractError("SFT episode content hash mismatch")


def verify_sft_summary(summary: Mapping[str, Any]) -> None:
    exact = {
        "episode_count": TARGET_SFT_EPISODES,
        "train_count": TRAIN_EPISODES,
        "validation_count": VALIDATION_EPISODES,
        "duplicate_episode_count": 0,
        "duplicate_content_count": 0,
        "rights_failure_count": 0,
        "model_generated_count": 0,
        "hidden_reasoning_count": 0,
        "external_side_effect_count": 0,
        "test_split_count": 0,
    }
    for key, expected in exact.items():
        if int(summary.get(key, -1)) != expected:
            raise V10ContractError(f"SFT summary {key} must equal {expected}")
    if set(summary.get("stage_counts", {})) != {item.value for item in CurriculumStage}:
        raise V10ContractError("all fourteen SFT stages are required")
    if set(summary.get("input_counts", {})) != {item.value for item in CurriculumInput}:
        raise V10ContractError("all nine SFT input kinds are required")
    if max(summary["stage_counts"].values()) - min(summary["stage_counts"].values()) > 1:
        raise V10ContractError("SFT stage distribution must differ by at most one")
    if max(summary["input_counts"].values()) - min(summary["input_counts"].values()) > 1:
        raise V10ContractError("SFT input distribution must differ by at most one")
    if float(summary.get("maximum_provider_share", 1.0)) > 0.40:
        raise V10ContractError("SFT provider concentration exceeds forty percent")
    for key in ("manifest_sha256", "corpus_content_sha256"):
        if len(str(summary.get(key, ""))) != 64:
            raise V10ContractError(f"{key} is required")
