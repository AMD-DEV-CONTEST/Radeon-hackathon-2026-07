"""V1.2 schema: book_id + entity_translations + FTS5.

Adds:
  1. book_id column to all 6 core tables
  2. entity_translations table (multi-language support)
  3. entities_fts FTS5 virtual table (full-text search)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["entities", "relations", "tag_index", "entity_versions", "references_map", "timeline_events"]

def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a SQLite table."""
    conn = op.get_bind()
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def upgrade() -> None:
    # 1. Add book_id to each core table
    for table in TABLES:
        if not column_exists(table, "book_id"):
            op.add_column(table, sa.Column("book_id", sa.Text(), server_default="default"))
            op.create_index(f"idx_{table}_book", table, ["book_id"])

    # 2. Create entity_translations table
    op.create_table(
        "entity_translations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("full_content", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("book_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "language"),
    )
    op.create_index("idx_et_entity", "entity_translations", ["entity_id"])
    op.create_index("idx_et_lang", "entity_translations", ["language"])

    # 3. Create FTS5 virtual table
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5("
        "entity_id UNINDEXED, title, content, full_content, "
        "tokenize='unicode61 remove_diacritics 2')"
    )

    # 4. Indexes for entity_translations
    op.create_index("idx_et_book", "entity_translations", ["book_id"])

def downgrade() -> None:
    # 1. Drop FTS5 virtual table
    op.execute("DROP TABLE IF EXISTS entities_fts")
    op.execute("DROP TABLE IF EXISTS entities_fts_config")
    op.execute("DROP TABLE IF EXISTS entities_fts_content")
    op.execute("DROP TABLE IF EXISTS entities_fts_data")
    op.execute("DROP TABLE IF EXISTS entities_fts_docsize")
    op.execute("DROP TABLE IF EXISTS entities_fts_idx")

    # 2. Drop entity_translations
    op.drop_index("idx_et_book", table_name="entity_translations")
    op.drop_index("idx_et_lang", table_name="entity_translations")
    op.drop_index("idx_et_entity", table_name="entity_translations")
    op.drop_table("entity_translations")

    # 3. Remove book_id columns
    for table in reversed(TABLES):
        if column_exists(table, "book_id"):
            op.drop_index(f"idx_{table}_book", table_name=table)
            op.drop_column(table, "book_id")
