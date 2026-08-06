"""Add append-only project cloud execution policy revisions.

Revision ID: orch_0003
Revises: orch_0002
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from creative_hub.models import ProjectCloudPolicyRecord


revision = "orch_0003"
down_revision = "orch_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ProjectCloudPolicyRecord.__table__.create(bind, checkfirst=True)
    op.execute(
        """
        CREATE TRIGGER trg_project_cloud_policies_immutable
        BEFORE UPDATE OR DELETE
        ON orchestration.project_cloud_policies
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM orchestration.project_cloud_policies)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete cloud policy facts; set "
            "ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only for an "
            "empty disposable environment"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_project_cloud_policies_immutable "
        "ON orchestration.project_cloud_policies"
    )
    ProjectCloudPolicyRecord.__table__.drop(bind, checkfirst=True)
