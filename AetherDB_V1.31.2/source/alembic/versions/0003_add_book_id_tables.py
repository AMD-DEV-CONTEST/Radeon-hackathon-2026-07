"""V1.30: Add book_id to remaining tables.

Adds book_id column to:
  - relations (already in entities, completes the pair)
  - tag_index
  - entity_versions
  - references_map
  - timeline_events
  - chapter_versions
  - prompt_profiles

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "relations",
    "tag_index",
    "entity_versions",
    "references_map",
    "timeline_events",
    "chapter_versions",
    "prompt_profiles",
]

def column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def upgrade() -> None:
    for table in TABLES:
        if not column_exists(table, "book_id"):
            op.add_column(table, sa.Column("book_id", sa.Text(), server_default="default"))
            op.create_index(f"idx_{table}_book", table, ["book_id"])

def downgrade() -> None:
    for table in reversed(TABLES):
        if column_exists(table, "book_id"):
            op.drop_index(f"idx_{table}_book", table_name=table)
            op.drop_column(table, "book_id")
