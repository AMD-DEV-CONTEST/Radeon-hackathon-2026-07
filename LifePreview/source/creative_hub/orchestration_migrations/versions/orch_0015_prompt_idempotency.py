"""Persist project-scoped prompt revision idempotency keys.

Revision ID: orch_0015
Revises: orch_0014
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0015"
down_revision = "orch_0014"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "qc_prompt_revisions",
        sa.Column(
            "command_idempotency_key",
            sa.String(255),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_qc_prompt_command_length",
        "qc_prompt_revisions",
        "command_idempotency_key IS NULL OR "
        "length(command_idempotency_key) BETWEEN 1 AND 255",
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_orch_qc_prompt_command",
        "qc_prompt_revisions",
        ["project_id", "command_idempotency_key"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_orch_qc_prompt_command",
        "qc_prompt_revisions",
        type_="unique",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_orch_qc_prompt_command_length",
        "qc_prompt_revisions",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column(
        "qc_prompt_revisions",
        "command_idempotency_key",
        schema=SCHEMA,
    )
