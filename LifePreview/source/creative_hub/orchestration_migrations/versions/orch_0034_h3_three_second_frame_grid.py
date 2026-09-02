"""Allow the verified three-second H3 frame grid.

Revision ID: orch_0034
Revises: orch_0033
"""

from __future__ import annotations

from alembic import op


revision = "orch_0034"
down_revision = "orch_0033"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
TABLE = "h3_sequence_revisions"
CONSTRAINT = "ck_orch_h3_sequence_revisions_frame_grid"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "frame_count BETWEEN 73 AND 362 AND frame_count % 17 = 5",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "frame_count BETWEEN 124 AND 362 AND frame_count % 17 = 5",
        schema=SCHEMA,
    )
