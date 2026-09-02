"""Add immutable evaluation scores and evidence.

Revision ID: hub_0003
Revises: hub_0002
"""

from __future__ import annotations

from alembic import op

from creative_hub.models import (
    EvaluationEvidenceRecord,
    EvaluationRecord,
    EvaluationScoreRecord,
)


revision = "hub_0003"
down_revision = "hub_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    EvaluationRecord.__table__.create(bind, checkfirst=True)
    EvaluationScoreRecord.__table__.create(bind, checkfirst=True)
    EvaluationEvidenceRecord.__table__.create(bind, checkfirst=True)
    for table in ("evaluations", "evaluation_scores", "evaluation_evidence"):
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
    EvaluationEvidenceRecord.__table__.drop(bind, checkfirst=True)
    EvaluationScoreRecord.__table__.drop(bind, checkfirst=True)
    EvaluationRecord.__table__.drop(bind, checkfirst=True)
