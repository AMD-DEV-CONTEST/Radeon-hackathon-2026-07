"""Add read-only factory project, take, canon, and delivery mirrors.

Revision ID: hub_0005
Revises: hub_0004
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from creative_hub.models import (
    DeliveryRevisionMirrorRecord,
    FactoryProjectRecord,
    FactoryRevisionRecord,
    FactoryTakeIndexRecord,
    VisualCanonMirrorRecord,
)


revision = "hub_0005"
down_revision = "hub_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in (
        FactoryProjectRecord,
        FactoryRevisionRecord,
        FactoryTakeIndexRecord,
        VisualCanonMirrorRecord,
        DeliveryRevisionMirrorRecord,
    ):
        model.__table__.create(bind, checkfirst=True)
    for table in (
        "factory_revisions",
        "visual_canon_revisions",
        "delivery_revisions",
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
    populated = bind.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM hub.factory_revisions "
            "UNION ALL SELECT 1 FROM hub.factory_take_index "
            "UNION ALL SELECT 1 FROM hub.visual_canon_revisions "
            "UNION ALL SELECT 1 FROM hub.delivery_revisions)"
        )
    ).scalar_one()
    if populated and os.getenv("ALLOW_DESTRUCTIVE_HUB_DOWNGRADE") != "YES":
        raise RuntimeError(
            "Hub downgrade would delete factory mirrors; set "
            "ALLOW_DESTRUCTIVE_HUB_DOWNGRADE=YES only after backup"
        )
    for model in (
        DeliveryRevisionMirrorRecord,
        VisualCanonMirrorRecord,
        FactoryTakeIndexRecord,
        FactoryRevisionRecord,
        FactoryProjectRecord,
    ):
        model.__table__.drop(bind, checkfirst=True)
