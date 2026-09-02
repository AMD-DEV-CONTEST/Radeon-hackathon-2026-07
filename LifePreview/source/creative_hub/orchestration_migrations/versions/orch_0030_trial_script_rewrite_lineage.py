"""Add immutable safety-rewrite lineage to trial scripts.

Revision ID: orch_0030
Revises: orch_0029
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "orch_0030"
down_revision = "orch_0029"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "trial_script_revisions",
        sa.Column("source_trial_script_revision_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "trial_script_revisions",
        sa.Column("source_safety_decision_digest", sa.String(64), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_trial_scripts_source_safety_digest",
        "trial_script_revisions",
        "length(source_safety_decision_digest) = 64",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_trial_scripts_source_pair",
        "trial_script_revisions",
        "(source_trial_script_revision_id IS NULL AND "
        "source_safety_decision_digest IS NULL) OR "
        "(source_trial_script_revision_id IS NOT NULL AND "
        "source_safety_decision_digest IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_trial_scripts_source_not_self",
        "trial_script_revisions",
        "source_trial_script_revision_id IS NULL OR "
        "source_trial_script_revision_id <> id",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_trial_scripts_source",
        "trial_script_revisions",
        "trial_script_revisions",
        ["source_trial_script_revision_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.enforce_trial_script_source_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_row {SCHEMA}.trial_script_revisions%ROWTYPE;
        BEGIN
            IF NEW.source_trial_script_revision_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT * INTO source_row
            FROM {SCHEMA}.trial_script_revisions
            WHERE id = NEW.source_trial_script_revision_id
              AND project_id = NEW.project_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'trial script rewrite source does not exist in project';
            END IF;
            IF source_row.id = NEW.id
               OR source_row.book_id <> NEW.book_id
               OR source_row.evidence_pack_revision_id
                  <> NEW.evidence_pack_revision_id
               OR source_row.resonance_direction_revision_id
                  <> NEW.resonance_direction_revision_id
               OR source_row.methodology_revision_id
                  <> NEW.methodology_revision_id
               OR source_row.revision >= NEW.revision THEN
                RAISE EXCEPTION 'trial script rewrite source lineage is invalid';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_trial_script_source_lineage
        BEFORE INSERT ON {SCHEMA}.trial_script_revisions
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.enforce_trial_script_source_lineage()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_trial_script_source_lineage "
        f"ON {SCHEMA}.trial_script_revisions"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS "
        f"{SCHEMA}.enforce_trial_script_source_lineage()"
    )
    op.drop_constraint(
        "fk_orch_trial_scripts_source",
        "trial_script_revisions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_orch_trial_scripts_source_not_self",
        "trial_script_revisions",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_orch_trial_scripts_source_pair",
        "trial_script_revisions",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_orch_trial_scripts_source_safety_digest",
        "trial_script_revisions",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column(
        "trial_script_revisions",
        "source_safety_decision_digest",
        schema=SCHEMA,
    )
    op.drop_column(
        "trial_script_revisions",
        "source_trial_script_revision_id",
        schema=SCHEMA,
    )
