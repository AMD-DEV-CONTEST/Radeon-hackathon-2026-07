"""Add preference events and shadow calibration state.

Revision ID: hub_0004
Revises: hub_0003
"""

from __future__ import annotations

from alembic import op

from creative_hub.models import (
    ActivationCandidateRecord,
    CalibrationRunRecord,
    PreferenceEventRecord,
    PreferenceProfileRecord,
)


revision = "hub_0004"
down_revision = "hub_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PreferenceEventRecord.__table__.create(bind, checkfirst=True)
    PreferenceProfileRecord.__table__.create(bind, checkfirst=True)
    CalibrationRunRecord.__table__.create(bind, checkfirst=True)
    ActivationCandidateRecord.__table__.create(bind, checkfirst=True)
    for table in (
        "preference_events",
        "calibration_runs",
        "activation_candidates",
    ):
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
    ActivationCandidateRecord.__table__.drop(bind, checkfirst=True)
    CalibrationRunRecord.__table__.drop(bind, checkfirst=True)
    PreferenceProfileRecord.__table__.drop(bind, checkfirst=True)
    PreferenceEventRecord.__table__.drop(bind, checkfirst=True)
