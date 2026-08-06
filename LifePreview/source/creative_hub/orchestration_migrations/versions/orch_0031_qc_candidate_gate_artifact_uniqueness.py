"""Scope QC candidate artifact uniqueness to one quality gate.

Revision ID: orch_0031
Revises: orch_0030
"""

from __future__ import annotations

from alembic import op


revision = "orch_0031"
down_revision = "orch_0030"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
TABLE = "qc_candidate_versions"
CONSTRAINT = "uq_orch_qc_candidate_artifact"


def upgrade() -> None:
    op.drop_constraint(
        CONSTRAINT,
        TABLE,
        schema=SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        CONSTRAINT,
        TABLE,
        ["project_id", "artifact_id", "gate_key"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT,
        TABLE,
        schema=SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        CONSTRAINT,
        TABLE,
        ["project_id", "artifact_id"],
        schema=SCHEMA,
    )
