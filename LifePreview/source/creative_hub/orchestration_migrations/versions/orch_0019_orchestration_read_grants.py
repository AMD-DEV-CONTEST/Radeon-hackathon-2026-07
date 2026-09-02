"""Backfill orchestration reads and grant them to future tables.

Revision ID: orch_0019
Revises: orch_0018
"""

from __future__ import annotations

from alembic import op


revision = "orch_0019"
down_revision = "orch_0018"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
LEGACY_UNGRANTED_TABLES = (
    "factory_outbox_consumption",
    "generation_runs",
    "gpu_leases",
    "gpu_observations",
    "model_capabilities",
    "model_registry",
    "project_cloud_policies",
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    GRANT SELECT ON TABLES TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    tables = ", ".join(
        f"{SCHEMA}.{table}" for table in LEGACY_UNGRANTED_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    REVOKE SELECT ON TABLES FROM {ROLE};
                REVOKE SELECT ON TABLE {tables} FROM {ROLE};
            END IF;
        END
        $$;
        """
    )
