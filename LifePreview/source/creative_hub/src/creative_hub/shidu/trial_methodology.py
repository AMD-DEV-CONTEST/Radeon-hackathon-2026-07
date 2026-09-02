"""Frozen v0.1 contract for the Shidu critical-moment trial method."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from uuid import UUID

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.schemas import (
    FreezeTrialMethodology,
    TrialMethodologyRevision,
)
from creative_hub.shidu.safety_cards import (
    safety_cards_manifest,
    safety_cards_v1,
)

if TYPE_CHECKING:
    from creative_hub.shidu.repository import ShiduRepository


METHODOLOGY_KEY = "shidu-critical-moment"
METHODOLOGY_VERSION = "0.1"
TRIAL_VALIDATOR_VERSION = "shidu-trial-validator-v1"
TRIAL_SCRIPT_SCHEMA_VERSION = "shidu-trial-script-v1"
METHODOLOGY_PROMPT = (
    "Use one first-person narrator in one continuous moment and one present "
    "conflict. Lock known_now and unknown_now. Build six action/state beats "
    "before narration. Do not reveal future outcomes, endings, mysteries, or "
    "long source passages. Ground every factual and style judgement in the "
    "selected frozen direction and evidence pack. Apply every frozen Shidu "
    "category safety card before and after compilation; blocked output must "
    "remain review-only and every rewrite must append a script revision."
)
METHODOLOGY_PROMPT_DIGEST = hashlib.sha256(
    METHODOLOGY_PROMPT.encode("utf-8")
).hexdigest()

SHOT_BEATS: tuple[dict[str, Any], ...] = (
    {
        "ordinal": 1,
        "key": "anomaly_entry",
        "narrative_task": "异常进入",
        "required_change": "平常→异常",
        "duration_min_seconds": 6,
        "duration_max_seconds": 8,
    },
    {
        "ordinal": 2,
        "key": "desire_revealed",
        "narrative_task": "欲望显影",
        "required_change": "模糊→明确",
        "duration_min_seconds": 8,
        "duration_max_seconds": 10,
    },
    {
        "ordinal": 3,
        "key": "pressure_closes_in",
        "narrative_task": "压力逼近",
        "required_change": "可回避→不可回避",
        "duration_min_seconds": 9,
        "duration_max_seconds": 11,
    },
    {
        "ordinal": 4,
        "key": "costly_choice",
        "narrative_task": "代价选择",
        "required_change": "犹豫→决断",
        "duration_min_seconds": 9,
        "duration_max_seconds": 11,
    },
    {
        "ordinal": 5,
        "key": "consequence_arrives",
        "narrative_task": "后果抵达",
        "required_change": "决断→失去或获得",
        "duration_min_seconds": 9,
        "duration_max_seconds": 11,
    },
    {
        "ordinal": 6,
        "key": "reading_pull",
        "narrative_task": "阅读拉力",
        "required_change": "暂时落点→未解问题",
        "duration_min_seconds": 7,
        "duration_max_seconds": 9,
    },
)

_PAYLOAD: dict[str, Any] = {
    "methodology_key": METHODOLOGY_KEY,
    "methodology_version": METHODOLOGY_VERSION,
    "name": "临界一刻试读法",
    "experience_promise": (
        "我不替这本书下结论。我只让你借主人公的眼睛，经历一个足以改变方向的瞬间。"
    ),
    "hard_rules": [
        "one_first_person_narrator",
        "one_continuous_moment",
        "one_present_conflict",
        "limited_knowledge",
        "emotion_carried_by_action",
        "leave_one_open_question",
    ],
    "generation_order": ["action_skeleton", "narration"],
    "shot_beats": list(SHOT_BEATS),
    "narration_chinese_character_min": 180,
    "narration_chinese_character_max": 230,
    "total_duration_min_seconds": 50,
    "total_duration_max_seconds": 70,
    "opening_line_default": "ai_adapted",
    "opening_line_kinds": ["ai_adapted", "verified_quote"],
    "spoiler_policy_default": "light",
    "script_schema_version": TRIAL_SCRIPT_SCHEMA_VERSION,
    "validator_version": TRIAL_VALIDATOR_VERSION,
    "prompt_digest": METHODOLOGY_PROMPT_DIGEST,
    "safety_cards_schema_version": safety_cards_manifest().schema_version,
    "safety_cards_manifest": safety_cards_manifest().model_dump(mode="json"),
    "safety_cards": [
        card.model_dump(mode="json") for card in safety_cards_v1()
    ],
    "safety_gate_phases": ["pre_compile", "post_compile"],
    "safety_rewrite_policy": "append_trial_script_revision",
}
METHODOLOGY_PAYLOAD_DIGEST = canonical_json_digest(_PAYLOAD)


def methodology_v01_payload() -> dict[str, Any]:
    """Return an isolated copy of the single application-owned v0.1 contract."""

    return deepcopy(_PAYLOAD)


class TrialMethodologyService:
    def __init__(self, repository: ShiduRepository) -> None:
        self._repository = repository

    def freeze(
        self,
        project_id: UUID,
        *,
        command_key: str = "trial-methodology:shidu-critical-moment:v0.1",
    ) -> TrialMethodologyRevision:
        return self._repository.freeze_trial_methodology(
            FreezeTrialMethodology(
                project_id=project_id,
                methodology_key=METHODOLOGY_KEY,
                methodology_version=METHODOLOGY_VERSION,
                prompt_digest=METHODOLOGY_PROMPT_DIGEST,
                validator_version=TRIAL_VALIDATOR_VERSION,
                payload=methodology_v01_payload(),
                command_key=command_key,
            )
        )


__all__ = [
    "METHODOLOGY_KEY",
    "METHODOLOGY_PAYLOAD_DIGEST",
    "METHODOLOGY_PROMPT_DIGEST",
    "METHODOLOGY_VERSION",
    "SHOT_BEATS",
    "TRIAL_SCRIPT_SCHEMA_VERSION",
    "TRIAL_VALIDATOR_VERSION",
    "TrialMethodologyService",
    "methodology_v01_payload",
]
