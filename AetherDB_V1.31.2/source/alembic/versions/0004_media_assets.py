"""V1.32 MM-01: unified media asset metadata.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DDL = """
CREATE TABLE IF NOT EXISTS media_assets (
    asset_id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    modality TEXT NOT NULL CHECK(modality IN ('image','audio','video')),
    mime_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
    source_type TEXT NOT NULL CHECK(source_type IN ('imported','generated','captured','derived')),
    lifecycle_status TEXT NOT NULL DEFAULT 'temporary'
        CHECK(lifecycle_status IN ('temporary','pending_review','approved','archived','soft_deleted','rejected')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by_task_id TEXT,
    approved_at TIMESTAMP,
    archived_at TIMESTAMP,
    deleted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_media_assets_scope
ON media_assets(database_id,book_id,lifecycle_status,modality,created_at);
CREATE INDEX IF NOT EXISTS idx_media_assets_hash
ON media_assets(database_id,content_hash);

CREATE TABLE IF NOT EXISTS media_asset_versions (
    version_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK(version_number > 0),
    mime_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id,version_number),
    FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_versions_scope
ON media_asset_versions(database_id,book_id,asset_id,version_number);

CREATE TABLE IF NOT EXISTS media_asset_derivatives (
    derivative_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    source_version_id TEXT,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    derivative_type TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by_task_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(source_version_id) REFERENCES media_asset_versions(version_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_media_derivatives_scope
ON media_asset_derivatives(database_id,book_id,asset_id,derivative_type);

CREATE TABLE IF NOT EXISTS media_annotations (
    annotation_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    annotation_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'manual'
        CHECK(source_type IN ('manual','model','imported')),
    approval_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(approval_status IN ('pending','approved','rejected')),
    model_profile_id TEXT,
    source_task_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES media_asset_versions(version_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_media_annotations_scope
ON media_annotations(database_id,book_id,asset_id,approval_status);

CREATE TABLE IF NOT EXISTS media_asset_bindings (
    binding_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    database_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    binding_type TEXT NOT NULL,
    timeline_id TEXT,
    branch_id TEXT,
    valid_from_anchor_id TEXT,
    valid_to_anchor_id TEXT,
    entity_state_segment_id TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id,target_type,target_id,binding_type,timeline_id,branch_id),
    FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE RESTRICT,
    FOREIGN KEY(timeline_id) REFERENCES timelines(id) ON DELETE RESTRICT,
    FOREIGN KEY(valid_from_anchor_id) REFERENCES temporal_anchors(id) ON DELETE RESTRICT,
    FOREIGN KEY(valid_to_anchor_id) REFERENCES temporal_anchors(id) ON DELETE RESTRICT,
    FOREIGN KEY(entity_state_segment_id) REFERENCES entity_state_segments(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_media_bindings_scope
ON media_asset_bindings(database_id,book_id,target_type,target_id,sort_order);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(DDL)


def downgrade() -> None:
    conn = op.get_bind().connection
    conn.executescript(
        """
        DROP TABLE IF EXISTS media_asset_bindings;
        DROP TABLE IF EXISTS media_annotations;
        DROP TABLE IF EXISTS media_asset_derivatives;
        DROP TABLE IF EXISTS media_asset_versions;
        DROP TABLE IF EXISTS media_assets;
        """
    )
