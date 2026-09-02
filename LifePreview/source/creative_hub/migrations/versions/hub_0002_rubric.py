"""Freeze the AI short-drama rubric v1 and stage applicability.

Revision ID: hub_0002
Revises: hub_0001
"""

from __future__ import annotations

from alembic import op

from creative_hub.models import (
    RubricDefinitionRecord,
    RubricDimensionRecord,
    RubricVersionRecord,
    StageApplicabilityRecord,
)
from creative_hub.rubric import (
    AI_SHORT_DRAMA_RUBRIC_ID,
    AI_SHORT_DRAMA_RUBRIC_VERSION,
    AI_SHORT_DRAMA_RUBRIC_VERSION_ID,
    DIMENSIONS,
    RUBRIC_FROZEN_AT,
    STAGE_DIMENSIONS,
    rubric_payload_sha256,
)


revision = "hub_0002"
down_revision = "hub_0001"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "rubric_definitions",
    "rubric_versions",
    "rubric_dimensions",
    "stage_applicability",
)


def upgrade() -> None:
    bind = op.get_bind()
    RubricDefinitionRecord.__table__.create(bind, checkfirst=True)
    RubricVersionRecord.__table__.create(bind, checkfirst=True)
    RubricDimensionRecord.__table__.create(bind, checkfirst=True)
    StageApplicabilityRecord.__table__.create(bind, checkfirst=True)
    bind.execute(
        RubricDefinitionRecord.__table__.insert().values(
            rubric_id=AI_SHORT_DRAMA_RUBRIC_ID,
            name="AI短剧量表",
            description="工厂质检、中台 AI 与人工共用的版本化 1–10 量表。",
            active_version=AI_SHORT_DRAMA_RUBRIC_VERSION,
        )
    )
    bind.execute(
        RubricVersionRecord.__table__.insert().values(
            id=AI_SHORT_DRAMA_RUBRIC_VERSION_ID,
            rubric_id=AI_SHORT_DRAMA_RUBRIC_ID,
            version=AI_SHORT_DRAMA_RUBRIC_VERSION,
            title="AI短剧量表 v1",
            payload_sha256=rubric_payload_sha256(),
            frozen_at=RUBRIC_FROZEN_AT,
        )
    )
    bind.execute(
        RubricDimensionRecord.__table__.insert(),
        [
            {
                "rubric_version_id": AI_SHORT_DRAMA_RUBRIC_VERSION_ID,
                "dimension_id": dimension_id,
                "label": label,
                "description": description,
                "display_order": order,
                "weight": 1.0,
                "core": core,
            }
            for order, (dimension_id, label, description, core) in enumerate(
                DIMENSIONS
            )
        ],
    )
    bind.execute(
        StageApplicabilityRecord.__table__.insert(),
        [
            {
                "rubric_version_id": AI_SHORT_DRAMA_RUBRIC_VERSION_ID,
                "stage": stage.value,
                "dimension_id": dimension_id,
                "required": True,
            }
            for stage, dimension_ids in STAGE_DIMENSIONS.items()
            for dimension_id in dimension_ids
        ],
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_hub_immutable
            BEFORE UPDATE OR DELETE ON hub.{table}
            FOR EACH ROW
            EXECUTE FUNCTION hub.reject_immutable_hub_mutation()
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    StageApplicabilityRecord.__table__.drop(bind, checkfirst=True)
    RubricDimensionRecord.__table__.drop(bind, checkfirst=True)
    RubricVersionRecord.__table__.drop(bind, checkfirst=True)
    RubricDefinitionRecord.__table__.drop(bind, checkfirst=True)
