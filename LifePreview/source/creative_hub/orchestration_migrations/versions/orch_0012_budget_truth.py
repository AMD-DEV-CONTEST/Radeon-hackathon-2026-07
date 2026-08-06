"""Keep actual provider cost as immutable accounting truth.

Revision ID: orch_0012
Revises: orch_0011
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0012"
down_revision = "orch_0011"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    # Admission remains bounded in BudgetRepository/DurableDagScheduler.
    # Settlement is different: once work has happened, factual spend must not
    # be rejected merely because it exceeded the earlier estimate.
    op.drop_constraint(
        "ck_orch_budget_accounts_limit",
        "budget_accounts",
        schema=SCHEMA,
        type_="check",
    )


def downgrade() -> None:
    connection = op.get_bind()
    over_limit = connection.scalar(
        sa.text(
            """
            SELECT count(*)
            FROM orchestration.budget_accounts
            WHERE reserved_micros + settled_micros > limit_micros
            """
        )
    )
    if int(over_limit or 0) != 0:
        raise RuntimeError(
            "cannot restore the legacy budget constraint while factual "
            "settlements exceed their admission limits"
        )
    op.create_check_constraint(
        "ck_orch_budget_accounts_limit",
        "budget_accounts",
        "reserved_micros + settled_micros <= limit_micros",
        schema=SCHEMA,
    )
