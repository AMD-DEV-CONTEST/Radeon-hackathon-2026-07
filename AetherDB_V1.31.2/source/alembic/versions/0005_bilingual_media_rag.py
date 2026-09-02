"""V1.31.2 bilingual media binding and annotation provenance.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind().connection
    annotation_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(media_annotations)").fetchall()
    }
    if "language_code" not in annotation_columns:
        conn.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN language_code TEXT NOT NULL DEFAULT 'und'"
        )
    if "source_revision_hash" not in annotation_columns:
        conn.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN source_revision_hash TEXT NOT NULL DEFAULT ''"
        )
    if "is_stale" not in annotation_columns:
        conn.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0 CHECK(is_stale IN (0,1))"
        )
    binding_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(media_asset_bindings)").fetchall()
    }
    if "language_code" not in binding_columns:
        conn.execute("ALTER TABLE media_asset_bindings ADD COLUMN language_code TEXT")
    conn.executescript(
        """
        UPDATE media_annotations
           SET version_id=COALESCE(
                version_id,
                (
                    SELECT v.version_id
                      FROM media_asset_versions v
                     WHERE v.asset_id=media_annotations.asset_id
                     ORDER BY v.version_number DESC
                     LIMIT 1
                )
           );
        UPDATE media_annotations
           SET source_revision_hash=COALESCE(
                (
                    SELECT v.content_hash
                      FROM media_asset_versions v
                     WHERE v.version_id=media_annotations.version_id
                ),
                ''
           )
         WHERE source_revision_hash='';
        CREATE INDEX IF NOT EXISTS idx_media_annotations_language
        ON media_annotations(
            database_id,book_id,asset_id,language_code,approval_status,is_stale
        );
        CREATE INDEX IF NOT EXISTS idx_media_bindings_language_scope
        ON media_asset_bindings(
            database_id,book_id,target_type,target_id,language_code,sort_order
        );
        """
    )
    has_localizations = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='chapter_localizations'"
    ).fetchone()
    if has_localizations:
        conn.execute(
            """UPDATE media_asset_bindings
                  SET language_code=(
                        SELECT l.language_code
                          FROM chapter_localizations l
                         WHERE l.chapter_id=media_asset_bindings.target_id
                      )
                WHERE target_type='chapter' AND language_code IS NULL"""
        )


def downgrade() -> None:
    # SQLite cannot safely drop these additive columns without rebuilding both
    # tables. Keeping them is backward compatible with revision 0004.
    pass
