"""Keep future orchestration tables read-only by default.

Revision ID: orch_0022
Revises: orch_0021

``orch_0021`` originally widened the application role's default privileges
while granting the command ledger its explicit append permission.  Existing
tables use deliberate per-table grants; future tables must inherit only
``SELECT`` until a migration explicitly grants writes.
"""

from __future__ import annotations

from alembic import op


revision = "orch_0022"
down_revision = "orch_0021"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    REVOKE INSERT ON TABLES FROM {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    GRANT SELECT ON TABLES TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # This security repair is intentionally monotonic.  Returning the Alembic
    # marker to orch_0021 must not silently restore broad future write access.
    pass
