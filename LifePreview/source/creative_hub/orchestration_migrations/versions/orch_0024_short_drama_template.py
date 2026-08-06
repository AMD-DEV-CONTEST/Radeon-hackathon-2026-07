"""Seed the versioned short-drama template and repair explicit bindings.

Revision ID: orch_0024
Revises: orch_0023

Fresh databases previously registered only ``general_video@1``.  The formal
project creation API therefore persisted an explicit ``project_type`` of
``short_drama`` while the project foreign key still pointed at the fallback
template.  This data-only migration registers the approved ``short_drama@2``
contract and mechanically repairs only rows whose own config declares that
project type.  Existing general-video projects are unchanged.
"""

from __future__ import annotations

from alembic import op


revision = "orch_0024"
down_revision = "orch_0023"
branch_labels = None
depends_on = None

SHORT_DRAMA_TEMPLATE_ID = "88b80429-b4f5-5011-850b-5e4e6076593c"
SHORT_DRAMA_TEMPLATE_DIGEST = (
    "8f856fdd1d3c12241f942c02843b7585fcae951825fc74082930af0c894673d6"
)
SHORT_DRAMA_FOLDER_SCHEMA = (
    '{"roles":["source","story_bible","character_bible","world_bible",'
    '"style_bible","characters","scenes","props","episodes","shots",'
    '"candidates","quality","deliveries"]}'
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO orchestration.project_templates (
            id, template_key, version, work_unit_kind,
            folder_schema, workflow_schema, digest, created_by_actor
        )
        SELECT '{SHORT_DRAMA_TEMPLATE_ID}', 'short_drama', 2, 'episode',
               '{SHORT_DRAMA_FOLDER_SCHEMA}'::jsonb,
               '{{"key":"short_drama"}}'::jsonb,
               '{SHORT_DRAMA_TEMPLATE_DIGEST}', 'system.product-backfill'
        WHERE NOT EXISTS (
            SELECT 1 FROM orchestration.project_templates
            WHERE template_key = 'short_drama' AND version = 2
        )
        """
    )
    op.execute(
        """
        UPDATE orchestration.projects
        SET template_key = 'short_drama', template_version = 2
        WHERE template_key = 'general_video'
          AND template_version = 1
          AND config ->> 'project_type' = 'short_drama'
        """
    )


def downgrade() -> None:
    # Project templates are protected by the orchestration immutable-fact
    # trigger.  Retaining this registered revision on code downgrade is safer
    # than disabling the trigger or rewriting projects back to a false type.
    pass
