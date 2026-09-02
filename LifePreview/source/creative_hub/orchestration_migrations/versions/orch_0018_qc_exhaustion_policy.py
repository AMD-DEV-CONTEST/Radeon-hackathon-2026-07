"""Persist the frozen QC exhaustion policy.

Revision ID: orch_0018
Revises: orch_0017
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0018"
down_revision = "orch_0017"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.add_column(
        "qc_gate_policy_snapshots",
        sa.Column(
            "exhaustion_policy",
            sa.String(24),
            nullable=False,
            server_default="DEGRADED_ACCEPT",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_qc_gate_policy_exhaustion",
        "qc_gate_policy_snapshots",
        "exhaustion_policy IN ('BLOCK', 'DEGRADED_ACCEPT')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_orch_qc_gate_policy_exhaustion",
        "qc_gate_policy_snapshots",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column(
        "qc_gate_policy_snapshots",
        "exhaustion_policy",
        schema=SCHEMA,
    )
