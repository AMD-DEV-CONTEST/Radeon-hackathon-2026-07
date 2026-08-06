from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    RubricDefinitionRecord,
    RubricDimensionRecord,
    RubricVersionRecord,
    StageApplicabilityRecord,
)


AI_SHORT_DRAMA_RUBRIC_ID = "ai-short-drama"
AI_SHORT_DRAMA_RUBRIC_VERSION = 1
AI_SHORT_DRAMA_RUBRIC_VERSION_ID = UUID(
    "c9b2cf58-47ab-5fa8-88a2-b8a86d99bb63"
)
AI_SHORT_DRAMA_PROFILE_ID = "short-drama-v1"
RUBRIC_FROZEN_AT = datetime(2026, 7, 29, tzinfo=timezone.utc)


class EvaluationStage(StrEnum):
    FACTORY_QC = "factory_qc"
    HUB_AI = "hub_ai"
    HUB_HUMAN = "hub_human"


class EvaluationSubjectType(StrEnum):
    VISUAL_TAKE = "visual_take"
    DELIVERY_TAKE = "delivery_take"


class PreferenceAction(StrEnum):
    KEEP = "keep"
    EDIT = "edit"
    REROLL = "reroll"
    REWRITE = "rewrite"


DIMENSIONS = (
    (
        "technical_quality",
        "技术质量",
        "画面完整、无明显编码、闪烁、破图和合成缺陷。",
        True,
    ),
    (
        "character_consistency",
        "角色一致性",
        "人物身份、服装、面部和关键造型在镜头内保持一致。",
        True,
    ),
    (
        "scene_consistency",
        "场景一致性",
        "空间、道具、光源方向和场景语义保持连续。",
        True,
    ),
    (
        "motion_naturalness",
        "动作自然度",
        "人物、镜头和物体运动清晰、稳定且符合意图。",
        True,
    ),
    (
        "physical_plausibility",
        "物理可信度",
        "接触、重力、遮挡和物体形变没有明显违和。",
        True,
    ),
    (
        "lighting_readability",
        "光影可读性",
        "主体层次、曝光、色彩和光源逻辑服务于镜头表达。",
        False,
    ),
    (
        "subtitle_quality",
        "字幕质量",
        "字幕准确、同步、清晰且不遮挡关键视觉信息。",
        False,
    ),
    (
        "lipsync_quality",
        "口型质量",
        "口型与可听对白在时间和发音观感上匹配。",
        False,
    ),
    (
        "audio_technical_quality",
        "音频技术质量",
        "对白、环境、音效和音乐无爆音、断裂或明显混音问题。",
        False,
    ),
    (
        "narrative_effectiveness",
        "叙事有效性",
        "镜头信息推动情节，并能让观众理解当前冲突或目标。",
        True,
    ),
    (
        "performance_expression",
        "表演表达",
        "动作、表情、台词和调度共同传达角色状态。",
        True,
    ),
    (
        "pacing",
        "节奏",
        "信息密度、停顿和镜头长度适合短视频观看。",
        True,
    ),
    (
        "knowledge_alignment",
        "知识符合度",
        "成片正确落实了已批准知识包中的适用规则。",
        False,
    ),
    (
        "overall_aesthetics",
        "整体审美",
        "构图、色彩、运动和声音形成统一且有辨识度的表达。",
        True,
    ),
    (
        "publishing_fit",
        "发布适配",
        "开场吸引力、画幅、可理解性和观看完成潜力适合抖音。",
        False,
    ),
    (
        "personal_fit",
        "个人审美符合度",
        "结果符合当前用户明确表达或持续形成的偏好。",
        True,
    ),
)

FACTORY_DIMENSION_IDS = tuple(item[0] for item in DIMENSIONS[:9])
HUB_DIMENSION_IDS = tuple(item[0] for item in DIMENSIONS[9:])
STAGE_DIMENSIONS = {
    EvaluationStage.FACTORY_QC: FACTORY_DIMENSION_IDS,
    EvaluationStage.HUB_AI: HUB_DIMENSION_IDS,
    EvaluationStage.HUB_HUMAN: HUB_DIMENSION_IDS,
}
CORE_DIMENSION_IDS = frozenset(
    item[0] for item in DIMENSIONS if item[3]
)


def frozen_rubric_payload() -> dict:
    return {
        "rubric_id": AI_SHORT_DRAMA_RUBRIC_ID,
        "version": AI_SHORT_DRAMA_RUBRIC_VERSION,
        "title": "AI短剧量表 v1",
        "score_scale": {
            "minimum": 1,
            "maximum": 10,
            "integer_only": True,
            "na_allowed": True,
        },
        "dimensions": [
            {
                "dimension_id": dimension_id,
                "label": label,
                "description": description,
                "core": core,
                "weight": 1.0,
                "display_order": order,
            }
            for order, (dimension_id, label, description, core) in enumerate(
                DIMENSIONS
            )
        ],
        "stage_applicability": {
            stage.value: list(dimension_ids)
            for stage, dimension_ids in STAGE_DIMENSIONS.items()
        },
        "policy": {
            "unobservable_is_na": True,
            "frame_sampling_cannot_score_motion_audio_or_lipsync": True,
            "factory_hub_human_records_are_independent": True,
            "personal_fit_hub_only": True,
        },
    }


def rubric_payload_sha256() -> str:
    encoded = json.dumps(
        frozen_rubric_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ensure_rubric_v1(session: Session) -> RubricVersionRecord:
    existing = session.scalar(
        select(RubricVersionRecord).where(
            RubricVersionRecord.rubric_id == AI_SHORT_DRAMA_RUBRIC_ID,
            RubricVersionRecord.version == AI_SHORT_DRAMA_RUBRIC_VERSION,
        )
    )
    expected_sha = rubric_payload_sha256()
    if existing is not None:
        if existing.payload_sha256 != expected_sha:
            raise RuntimeError("frozen AI short-drama rubric hash mismatch")
        return existing

    definition = session.get(
        RubricDefinitionRecord,
        AI_SHORT_DRAMA_RUBRIC_ID,
    )
    if definition is None:
        session.add(
            RubricDefinitionRecord(
                rubric_id=AI_SHORT_DRAMA_RUBRIC_ID,
                name="AI短剧量表",
                description="工厂质检、中台 AI 与人工共用的版本化 1–10 量表。",
                active_version=AI_SHORT_DRAMA_RUBRIC_VERSION,
            )
        )
        session.flush()
    version = RubricVersionRecord(
        id=AI_SHORT_DRAMA_RUBRIC_VERSION_ID,
        rubric_id=AI_SHORT_DRAMA_RUBRIC_ID,
        version=AI_SHORT_DRAMA_RUBRIC_VERSION,
        title="AI短剧量表 v1",
        payload_sha256=expected_sha,
        frozen_at=RUBRIC_FROZEN_AT,
    )
    session.add(version)
    session.flush()
    for order, (dimension_id, label, description, core) in enumerate(DIMENSIONS):
        session.add(
            RubricDimensionRecord(
                rubric_version_id=version.id,
                dimension_id=dimension_id,
                label=label,
                description=description,
                display_order=order,
                weight=1.0,
                core=core,
            )
        )
    for stage, dimension_ids in STAGE_DIMENSIONS.items():
        for dimension_id in dimension_ids:
            session.add(
                StageApplicabilityRecord(
                    rubric_version_id=version.id,
                    stage=stage.value,
                    dimension_id=dimension_id,
                    required=True,
                )
            )
    session.flush()
    return version


def rubric_contract(session: Session) -> dict:
    version = ensure_rubric_v1(session)
    payload = frozen_rubric_payload()
    payload["payload_sha256"] = version.payload_sha256
    payload["frozen_at"] = version.frozen_at.isoformat()
    return payload
