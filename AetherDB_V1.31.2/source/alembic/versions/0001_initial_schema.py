"""V1.0 initial schema.

Creates the 6 core tables matching main.py init_db():
  entities, relations, tag_index, entity_versions,
  references_map, timeline_events

Revision ID: 0001
Revises:
Create Date: 2026-06-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.Text(), primary_key=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("full_content", sa.Text(), server_default=""),
        sa.Column("ai_summary", sa.Text(), server_default=""),
        sa.Column("tags", sa.Text(), server_default="[]"),
        sa.Column("timeline_year", sa.Integer(), nullable=True),
        sa.Column("timeline_era", sa.Text(), nullable=True),
        sa.Column("importance", sa.Integer(), server_default="5"),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("is_active", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "tag_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
    )
    op.create_table(
        "entity_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("full_content", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "references_map",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("era", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("importance", sa.Integer(), server_default="5"),
    )
    # Indexes
    op.create_index("idx_entity_type", "entities", ["entity_type"])
    op.create_index("idx_entity_tags", "entities", ["tags"])
    op.create_index("idx_relation_source", "relations", ["source_id"])
    op.create_index("idx_relation_target", "relations", ["target_id"])
    op.create_index("idx_tag_entity", "tag_index", ["entity_id"])
    op.create_index("idx_tag_name", "tag_index", ["tag"])
    op.create_index("idx_entity_version", "entity_versions", ["entity_id"])


def downgrade() -> None:
    op.drop_index("idx_entity_version")
    op.drop_index("idx_tag_name")
    op.drop_index("idx_tag_entity")
    op.drop_index("idx_relation_target")
    op.drop_index("idx_relation_source")
    op.drop_index("idx_entity_tags")
    op.drop_index("idx_entity_type")
    op.drop_table("timeline_events")
    op.drop_table("references_map")
    op.drop_table("entity_versions")
    op.drop_table("tag_index")
    op.drop_table("relations")
    op.drop_table("entities")
