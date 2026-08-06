"""Add generation, provider outbox, model registry, and GPU mirrors.

Revision ID: orch_0002
Revises: orch_0001
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from creative_hub.models import (
    FactoryOutboxConsumptionRecord,
    GenerationRunMirrorRecord,
    GpuLeaseMirrorRecord,
    GpuObservationRecord,
    ModelCapabilityRecord,
    ModelRegistryRecord,
)


revision = "orch_0002"
down_revision = "orch_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in (
        GenerationRunMirrorRecord,
        FactoryOutboxConsumptionRecord,
        ModelRegistryRecord,
        ModelCapabilityRecord,
        GpuLeaseMirrorRecord,
        GpuObservationRecord,
    ):
        model.__table__.create(bind, checkfirst=True)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION orchestration.reject_immutable_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'orchestration fact is immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in ("factory_outbox_consumption", "gpu_observations"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON orchestration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM orchestration.generation_runs "
            "UNION ALL SELECT 1 FROM orchestration.factory_outbox_consumption "
            "UNION ALL SELECT 1 FROM orchestration.gpu_observations)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete generation facts; set "
            "ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after backup"
        )
    for model in (
        GpuObservationRecord,
        GpuLeaseMirrorRecord,
        ModelCapabilityRecord,
        ModelRegistryRecord,
        FactoryOutboxConsumptionRecord,
        GenerationRunMirrorRecord,
    ):
        model.__table__.drop(bind, checkfirst=True)
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.reject_immutable_fact_mutation()"
    )
