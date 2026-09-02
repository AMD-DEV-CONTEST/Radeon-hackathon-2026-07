"""Bind human review tasks to the exact waiting gate attempt.

Revision ID: orch_0016
Revises: orch_0015
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0016"
down_revision = "orch_0015"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "human_review_tasks",
        sa.Column("gate_operation_run_id", sa.Uuid(as_uuid=True)),
        schema=SCHEMA,
    )
    op.add_column(
        "human_review_tasks",
        sa.Column("gate_operation_attempt_id", sa.Uuid(as_uuid=True)),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_human_review_gate_binding_pair",
        "human_review_tasks",
        "(gate_operation_run_id IS NULL "
        "AND gate_operation_attempt_id IS NULL) OR "
        "(gate_operation_run_id IS NOT NULL "
        "AND gate_operation_attempt_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_human_review_gate_attempt",
        "human_review_tasks",
        "operation_attempts",
        [
            "gate_operation_attempt_id",
            "gate_operation_run_id",
            "project_id",
        ],
        ["id", "operation_run_id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_orch_human_review_gate_attempt",
        "human_review_tasks",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_orch_human_review_gate_binding_pair",
        "human_review_tasks",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column(
        "human_review_tasks",
        "gate_operation_attempt_id",
        schema=SCHEMA,
    )
    op.drop_column(
        "human_review_tasks",
        "gate_operation_run_id",
        schema=SCHEMA,
    )
