"""Add durable repair lineage to workflow runs.

Revision ID: orch_0029
Revises: orch_0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "orch_0029"
down_revision = "orch_0028"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("parent_workflow_run_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "workflow_runs",
        sa.Column("source_repair_proposal_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_workflow_runs_repair_lineage_pair",
        "workflow_runs",
        "(parent_workflow_run_id IS NULL AND "
        "source_repair_proposal_id IS NULL) OR "
        "(parent_workflow_run_id IS NOT NULL AND "
        "source_repair_proposal_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_workflow_runs_parent",
        "workflow_runs",
        "workflow_runs",
        ["parent_workflow_run_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_orch_workflow_runs_source_repair",
        "workflow_runs",
        "repair_proposals",
        ["source_repair_proposal_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_orch_workflow_runs_source_repair",
        "workflow_runs",
        ["project_id", "source_repair_proposal_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_orch_workflow_runs_source_repair",
        "workflow_runs",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_orch_workflow_runs_source_repair",
        "workflow_runs",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_orch_workflow_runs_parent",
        "workflow_runs",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_orch_workflow_runs_repair_lineage_pair",
        "workflow_runs",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column(
        "workflow_runs", "source_repair_proposal_id", schema=SCHEMA
    )
    op.drop_column("workflow_runs", "parent_workflow_run_id", schema=SCHEMA)
