from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.add_column("sources", sa.Column("checksum", sa.String(64), nullable=True))
    op.add_column("sources", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sources_checksum", "sources", ["checksum"])

    op.create_table(
        "source_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("world_id", sa.String(36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])
    op.create_index("ix_source_chunks_world_id", "source_chunks", ["world_id"])

def downgrade():
    op.drop_table("source_chunks")
    op.drop_index("ix_sources_checksum", table_name="sources")
    op.drop_column("sources", "created_at")
    op.drop_column("sources", "checksum")
