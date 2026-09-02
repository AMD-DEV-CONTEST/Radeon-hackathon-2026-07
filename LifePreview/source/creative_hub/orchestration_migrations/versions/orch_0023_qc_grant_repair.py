"""Repair append-only QC privileges for the orchestration role.

Revision ID: orch_0023
Revises: orch_0022

The original QC migration granted writes only when the application role
already existed.  Databases that created the role later therefore remained
read-only.  Reapply the existing-table grants without widening default write
privileges for future orchestration tables.
"""

from __future__ import annotations

from alembic import op


revision = "orch_0023"
down_revision = "orch_0022"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
QC_TABLES = (
    "qc_prompt_revisions",
    "qc_gate_policy_snapshots",
    "qc_evaluation_facts",
    "qc_candidate_versions",
    "qc_gold_dataset_revisions",
    "qc_calibration_reports",
    "qc_certification_events",
    "qc_gate_decisions",
)


def upgrade() -> None:
    tables = ", ".join(f"{SCHEMA}.{table}" for table in QC_TABLES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT, INSERT ON TABLE {tables} TO {ROLE};
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
    # This least-privilege repair is intentionally monotonic.  Moving the
    # Alembic marker backwards must not make a working deployment read-only.
    pass
