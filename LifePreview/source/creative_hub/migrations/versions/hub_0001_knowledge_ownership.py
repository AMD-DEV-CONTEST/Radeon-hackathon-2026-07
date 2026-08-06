"""Take ownership of knowledge, import plans, and factory import mirrors.

Revision ID: hub_0001
Revises: None
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import inspect, text

from creative_hub.models import HUB_SCHEMA, HubBase


revision = "hub_0001"
down_revision = None
branch_labels = None
depends_on = None


TAKEOVER_TABLES = (
    "knowledge_cards",
    "knowledge_revisions",
    "knowledge_reviews",
    "knowledge_packs",
)
IMMUTABLE_TABLES = (
    "knowledge_revisions",
    "knowledge_reviews",
    "knowledge_packs",
    "import_plans",
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {HUB_SCHEMA}")
    schema = inspect(bind)
    for table in TAKEOVER_TABLES:
        if schema.has_table(table, schema="public") and not schema.has_table(
            table,
            schema=HUB_SCHEMA,
        ):
            op.execute(
                f'ALTER TABLE public."{table}" SET SCHEMA {HUB_SCHEMA}'
            )
    HubBase.metadata.create_all(bind=bind, checkfirst=True)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION hub.reject_immutable_hub_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'hub record is immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_trigger
                    WHERE tgname = 'trg_{table}_hub_immutable'
                      AND tgrelid = 'hub.{table}'::regclass
                ) THEN
                    CREATE TRIGGER trg_{table}_hub_immutable
                    BEFORE UPDATE OR DELETE ON hub.{table}
                    FOR EACH ROW
                    EXECUTE FUNCTION hub.reject_immutable_hub_mutation();
                END IF;
            END
            $$;
            """
        )

    op.execute("REVOKE CREATE ON SCHEMA hub FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA hub FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'creative_hub_app'
            ) THEN
                GRANT USAGE ON SCHEMA hub TO creative_hub_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA hub TO creative_hub_app;
                GRANT USAGE, SELECT
                    ON ALL SEQUENCES IN SCHEMA hub TO creative_hub_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA hub
                    GRANT SELECT, INSERT, UPDATE, DELETE
                    ON TABLES TO creative_hub_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM hub.knowledge_revisions "
            "UNION ALL SELECT 1 FROM hub.knowledge_reviews "
            "UNION ALL SELECT 1 FROM hub.knowledge_packs "
            "UNION ALL SELECT 1 FROM hub.import_plans"
            ")"
        )
    ).scalar_one()
    if populated and os.getenv("ALLOW_DESTRUCTIVE_HUB_DOWNGRADE") != "YES":
        raise RuntimeError(
            "Hub downgrade would delete immutable facts; set "
            "ALLOW_DESTRUCTIVE_HUB_DOWNGRADE=YES only after a verified backup"
        )
    HubBase.metadata.drop_all(bind=bind, checkfirst=True)
    op.execute("DROP FUNCTION IF EXISTS hub.reject_immutable_hub_mutation()")
