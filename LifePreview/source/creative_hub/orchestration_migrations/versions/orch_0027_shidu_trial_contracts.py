"""Freeze Shidu methodology and selected-direction script lineage.

Revision ID: orch_0027
Revises: orch_0026
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0027"
down_revision = "orch_0026"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "trial_methodology_revisions",
        sa.Column(
            "methodology_version",
            sa.String(16),
            nullable=False,
            server_default="0.1",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "trial_methodology_revisions",
        sa.Column(
            "prompt_digest",
            sa.String(64),
            nullable=False,
            server_default="0" * 64,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "trial_methodology_revisions",
        sa.Column(
            "validator_version",
            sa.String(100),
            nullable=False,
            server_default="shidu-trial-validator-v1",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_trial_methodologies_prompt_digest",
        "trial_methodology_revisions",
        "prompt_digest ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.alter_column(
        "trial_methodology_revisions",
        "methodology_version",
        server_default=None,
        schema=SCHEMA,
    )
    op.alter_column(
        "trial_methodology_revisions",
        "prompt_digest",
        server_default=None,
        schema=SCHEMA,
    )
    op.alter_column(
        "trial_methodology_revisions",
        "validator_version",
        server_default=None,
        schema=SCHEMA,
    )

    op.add_column(
        "trial_script_revisions",
        sa.Column("resonance_direction_revision_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "trial_script_revisions",
        sa.Column(
            "validator_version",
            sa.String(100),
            nullable=False,
            server_default="shidu-trial-validator-v1",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_trial_scripts_direction",
        "trial_script_revisions",
        "resonance_direction_revisions",
        ["resonance_direction_revision_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.trial_script_revisions
           SET resonance_direction_revision_id =
               NULLIF(payload ->> 'resonance_direction_revision_id', '')::uuid
         WHERE resonance_direction_revision_id IS NULL
        """
    )
    op.alter_column(
        "trial_script_revisions",
        "resonance_direction_revision_id",
        nullable=False,
        schema=SCHEMA,
    )
    op.alter_column(
        "trial_script_revisions",
        "validator_version",
        server_default=None,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_orch_trial_scripts_direction",
        "trial_script_revisions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column(
        "trial_script_revisions", "validator_version", schema=SCHEMA
    )
    op.drop_column(
        "trial_script_revisions",
        "resonance_direction_revision_id",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_orch_trial_methodologies_prompt_digest",
        "trial_methodology_revisions",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column(
        "trial_methodology_revisions", "validator_version", schema=SCHEMA
    )
    op.drop_column(
        "trial_methodology_revisions", "prompt_digest", schema=SCHEMA
    )
    op.drop_column(
        "trial_methodology_revisions", "methodology_version", schema=SCHEMA
    )
