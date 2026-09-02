"""Add immutable Reader-verified Shidu discovery and selection facts.

Revision ID: orch_0032
Revises: orch_0031
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0032"
down_revision = "orch_0031"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
CANDIDATE_TABLE = "book_discovery_candidates"
SELECTION_TABLE = "book_discovery_selections"


def _sha256(column: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} ~ '^[0-9a-f]{{64}}$'",
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        CANDIDATE_TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("input_resolution_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("edition", sa.String(200), nullable=False),
        sa.Column("translator", sa.String(200), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "reader_content_digest",
            sa.String(64),
            nullable=False,
            comment="SHA-256 of the exact Reader body observed and verified locally",
        ),
        sa.Column("search_provider", sa.String(200), nullable=False),
        sa.Column("search_schema_digest", sa.String(64), nullable=False),
        sa.Column("reader_provider", sa.String(200), nullable=False),
        sa.Column("reader_schema_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_book_discovery_candidates_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "input_resolution_id",
            name="uq_orch_book_discovery_candidates_resolution_scope",
        ),
        sa.UniqueConstraint(
            "input_resolution_id",
            "project_id",
            "ordinal",
            name="uq_orch_book_discovery_candidates_ordinal",
        ),
        sa.UniqueConstraint(
            "input_resolution_id",
            "project_id",
            "identity_digest",
            name="uq_orch_book_discovery_candidates_identity",
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name="ck_orch_book_discovery_candidates_ordinal",
        ),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 300",
            name="ck_orch_book_discovery_candidates_title_length",
        ),
        sa.CheckConstraint(
            "length(author) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_author_length",
        ),
        sa.CheckConstraint(
            "length(language) BETWEEN 1 AND 32",
            name="ck_orch_book_discovery_candidates_language_length",
        ),
        sa.CheckConstraint(
            "length(edition) <= 200 AND length(translator) <= 200",
            name="ck_orch_book_discovery_candidates_optional_identity_length",
        ),
        sa.CheckConstraint(
            "length(search_provider) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_search_provider_length",
        ),
        sa.CheckConstraint(
            "length(reader_provider) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_reader_provider_length",
        ),
        sa.CheckConstraint(
            "canonical_url LIKE 'https://%' AND length(canonical_url) <= 2048",
            name="ck_orch_book_discovery_candidates_https_url",
        ),
        _sha256(
            "identity_digest",
            "ck_orch_book_discovery_candidates_identity_digest",
        ),
        _sha256(
            "reader_content_digest",
            "ck_orch_book_discovery_candidates_content_digest",
        ),
        _sha256(
            "search_schema_digest",
            "ck_orch_book_discovery_candidates_search_schema",
        ),
        _sha256(
            "reader_schema_digest",
            "ck_orch_book_discovery_candidates_reader_schema",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_book_discovery_candidates_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_resolution_id", "project_id"],
            [
                f"{SCHEMA}.input_resolutions.id",
                f"{SCHEMA}.input_resolutions.project_id",
            ],
            name="fk_orch_book_discovery_candidates_resolution",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_book_discovery_candidates_resolution",
        CANDIDATE_TABLE,
        ["project_id", "input_resolution_id", "ordinal"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_book_discovery_candidates_identity",
        CANDIDATE_TABLE,
        ["project_id", "identity_digest"],
        schema=SCHEMA,
    )
    op.create_table(
        SELECTION_TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("input_resolution_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_book_discovery_selections_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "input_resolution_id",
            name="uq_orch_book_discovery_selections_resolution",
        ),
        sa.UniqueConstraint(
            "project_id",
            "input_resolution_id",
            "candidate_id",
            "book_id",
            name="uq_orch_book_discovery_selections_fact",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_book_discovery_selections_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_book_discovery_selections_command_length",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_book_discovery_selections_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_resolution_id", "project_id"],
            [
                f"{SCHEMA}.input_resolutions.id",
                f"{SCHEMA}.input_resolutions.project_id",
            ],
            name="fk_orch_book_discovery_selections_resolution",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "project_id", "input_resolution_id"],
            [
                f"{SCHEMA}.book_discovery_candidates.id",
                f"{SCHEMA}.book_discovery_candidates.project_id",
                f"{SCHEMA}.book_discovery_candidates.input_resolution_id",
            ],
            name="fk_orch_book_discovery_selections_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["book_id", "project_id"],
            [f"{SCHEMA}.books.id", f"{SCHEMA}.books.project_id"],
            name="fk_orch_book_discovery_selections_book",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_book_discovery_selections_resolution",
        SELECTION_TABLE,
        ["project_id", "input_resolution_id"],
        schema=SCHEMA,
    )
    for table in (CANDIDATE_TABLE, SELECTION_TABLE):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        "REVOKE ALL ON TABLE "
        f"{SCHEMA}.{CANDIDATE_TABLE}, {SCHEMA}.{SELECTION_TABLE} FROM PUBLIC"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                GRANT SELECT, INSERT ON TABLE
                    {SCHEMA}.{CANDIDATE_TABLE}, {SCHEMA}.{SELECTION_TABLE}
                    TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_{SELECTION_TABLE}_immutable "
        f"ON {SCHEMA}.{SELECTION_TABLE}"
    )
    op.drop_index(
        "ix_orch_book_discovery_selections_resolution",
        table_name=SELECTION_TABLE,
        schema=SCHEMA,
    )
    op.drop_table(SELECTION_TABLE, schema=SCHEMA)
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_{CANDIDATE_TABLE}_immutable "
        f"ON {SCHEMA}.{CANDIDATE_TABLE}"
    )
    op.drop_index(
        "ix_orch_book_discovery_candidates_identity",
        table_name=CANDIDATE_TABLE,
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_orch_book_discovery_candidates_resolution",
        table_name=CANDIDATE_TABLE,
        schema=SCHEMA,
    )
    op.drop_table(CANDIDATE_TABLE, schema=SCHEMA)
