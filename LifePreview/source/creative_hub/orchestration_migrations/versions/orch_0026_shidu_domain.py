"""Add project-scoped Shidu facts and projections.

Revision ID: orch_0026
Revises: orch_0025
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0026"
down_revision = "orch_0025"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"


def _project_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        [f"{SCHEMA}.projects.id"],
        name=name,
        ondelete="RESTRICT",
    )


def _scoped_fk(
    local_id: str, remote_table: str, name: str
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [local_id, "project_id"],
        [f"{SCHEMA}.{remote_table}.id", f"{SCHEMA}.{remote_table}.project_id"],
        name=name,
        ondelete="RESTRICT",
    )


def _sha256(column: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} ~ '^[0-9a-f]{{64}}$'", name=name
    )


def _identity_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "books",
        *_identity_columns(),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("edition", sa.String(200), nullable=False),
        sa.Column("translator", sa.String(200), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_books_scope"),
        sa.UniqueConstraint("project_id", "identity_digest", name="uq_orch_books_identity"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_books_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_books_command_length"),
        _sha256("identity_digest", "ck_orch_books_identity_digest"),
        _project_fk("fk_orch_books_project"),
        schema=SCHEMA,
    )
    op.create_table(
        "book_merge_records",
        *_identity_columns(),
        sa.Column("source_book_id", sa.Uuid(), nullable=False),
        sa.Column("target_book_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_book_merges_scope"),
        sa.UniqueConstraint("project_id", "source_book_id", name="uq_orch_book_merges_source"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_book_merges_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_book_merges_command_length"),
        sa.CheckConstraint("source_book_id <> target_book_id", name="ck_orch_book_merges_distinct"),
        _scoped_fk("source_book_id", "books", "fk_orch_book_merges_source"),
        _scoped_fk("target_book_id", "books", "fk_orch_book_merges_target"),
        schema=SCHEMA,
    )
    op.create_table(
        "input_resolutions",
        *_identity_columns(),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("normalized_input", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("candidate_book_ids", sa.JSON(), nullable=False),
        sa.Column("selected_book_id", sa.Uuid()),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_input_resolutions_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_input_resolutions_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_input_resolutions_command_length"),
        sa.CheckConstraint("status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')", name="ck_orch_input_resolutions_status"),
        _sha256("digest", "ck_orch_input_resolutions_digest"),
        _project_fk("fk_orch_input_resolutions_project"),
        _scoped_fk("selected_book_id", "books", "fk_orch_input_resolutions_book"),
        schema=SCHEMA,
    )
    op.create_table(
        "research_jobs",
        *_identity_columns(),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("provider_version", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("query_budget", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("reader_budget", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("retry_budget", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_research_jobs_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_research_jobs_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_research_jobs_command_length"),
        sa.CheckConstraint("status IN ('queued', 'resolving', 'searching', 'reading', 'extracting', 'synthesizing', 'ready', 'insufficient', 'retryable_failed', 'failed')", name="ck_orch_research_jobs_status"),
        sa.CheckConstraint("query_budget >= 0 AND reader_budget >= 0 AND retry_budget >= 0", name="ck_orch_research_jobs_budgets"),
        _sha256("digest", "ck_orch_research_jobs_digest"),
        _scoped_fk("book_id", "books", "fk_orch_research_jobs_book"),
        schema=SCHEMA,
    )
    op.create_table(
        "search_queries",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(160), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_search_queries_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_search_queries_job_scope"),
        sa.UniqueConstraint("research_job_id", "project_id", "ordinal", name="uq_orch_search_queries_ordinal"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_search_queries_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_search_queries_command_length"),
        sa.CheckConstraint("ordinal > 0", name="ck_orch_search_queries_ordinal"),
        _sha256("digest", "ck_orch_search_queries_digest"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_search_queries_job"),
        schema=SCHEMA,
    )
    op.create_table(
        "search_hits",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("search_query_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_search_hits_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_search_hits_job_scope"),
        sa.UniqueConstraint("search_query_id", "project_id", "research_job_id", "ordinal", name="uq_orch_search_hits_ordinal"),
        sa.CheckConstraint("ordinal > 0", name="ck_orch_search_hits_ordinal"),
        _sha256("digest", "ck_orch_search_hits_digest"),
        sa.ForeignKeyConstraint(
            ["search_query_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.search_queries.id", f"{SCHEMA}.search_queries.project_id", f"{SCHEMA}.search_queries.research_job_id"],
            name="fk_orch_search_hits_query",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "source_failures",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_source_failures_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_source_failures_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_source_failures_command_length"),
        sa.CheckConstraint("stage IN ('search', 'url_guard', 'reader', 'redirect')", name="ck_orch_source_failures_stage"),
        sa.CheckConstraint("attempts >= 0", name="ck_orch_source_failures_attempts"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_source_failures_job"),
        schema=SCHEMA,
    )
    op.create_table(
        "source_document_revisions",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_classification_version", sa.String(100), nullable=False),
        sa.Column("registered_domain", sa.String(253), nullable=False),
        sa.Column("search_hit_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("interaction_observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interaction_signal", sa.Float()),
        sa.Column("interaction_metrics", sa.JSON()),
        sa.Column(
            "interaction_normalization_version",
            sa.String(100),
            nullable=False,
            server_default="shidu-public-interaction-v1",
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_source_documents_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_source_documents_job_scope"),
        sa.UniqueConstraint("project_id", "canonical_url", "revision", name="uq_orch_source_documents_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_source_documents_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_source_documents_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_source_documents_revision"),
        sa.CheckConstraint(
            "(interaction_observed = true AND interaction_signal IS NOT NULL "
            "AND interaction_signal >= 0.0 AND interaction_signal <= 1.0) OR "
            "(interaction_observed = false AND interaction_signal IS NULL)",
            name="ck_orch_source_documents_interaction",
        ),
        _sha256("content_digest", "ck_orch_source_documents_content_digest"),
        _sha256("digest", "ck_orch_source_documents_digest"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_source_documents_job"),
        sa.ForeignKeyConstraint(
            ["search_hit_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.search_hits.id", f"{SCHEMA}.search_hits.project_id", f"{SCHEMA}.search_hits.research_job_id"],
            name="fk_orch_source_documents_search_hit",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_claims",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_revision_id", sa.Uuid(), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False, server_default="plot_node"),
        sa.Column("normalized_claim", sa.Text(), nullable=False),
        sa.Column("source_span", sa.JSON(), nullable=False),
        sa.Column("excerpt_digest", sa.String(64), nullable=False),
        sa.Column("is_direct_quote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spoiler_level", sa.String(16), nullable=False, server_default="light"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("conflict_group_key", sa.String(160)),
        sa.Column("conflict_severity", sa.String(16)),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_evidence_claims_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_claims_job_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_claims_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_claims_command_length"),
        sa.CheckConstraint("claim_type IN ('plot_node', 'emotional_reaction', 'style_judgement', 'reader_fit', 'factual_context')", name="ck_orch_evidence_claims_type"),
        sa.CheckConstraint("spoiler_level IN ('none', 'light', 'moderate', 'critical')", name="ck_orch_evidence_claims_spoiler"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_orch_evidence_claims_confidence"),
        sa.CheckConstraint("conflict_severity IS NULL OR conflict_severity IN ('minor', 'major', 'critical')", name="ck_orch_evidence_claims_conflict_severity"),
        _sha256("excerpt_digest", "ck_orch_evidence_claims_excerpt_digest"),
        _sha256("digest", "ck_orch_evidence_claims_digest"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_evidence_claims_job"),
        sa.ForeignKeyConstraint(
            ["source_document_revision_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.source_document_revisions.id", f"{SCHEMA}.source_document_revisions.project_id", f"{SCHEMA}.source_document_revisions.research_job_id"],
            name="fk_orch_evidence_claims_document",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_conflict_adjudication_revisions",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("evidence_set_digest", sa.String(64), nullable=False),
        sa.Column("adjudicator_version", sa.String(100), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_evidence_adjudications_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_adjudications_job_scope"),
        sa.UniqueConstraint("research_job_id", "project_id", "revision", name="uq_orch_evidence_adjudications_revision"),
        sa.UniqueConstraint("project_id", "research_job_id", "evidence_set_digest", "adjudicator_version", name="uq_orch_evidence_adjudications_semantic"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_adjudications_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_adjudications_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_evidence_adjudications_revision"),
        _sha256("evidence_set_digest", "ck_orch_evidence_adjudications_set_digest"),
        _sha256("digest", "ck_orch_evidence_adjudications_digest"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_evidence_adjudications_job"),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_conflict_adjudication_memberships",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("adjudication_revision_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_claim_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_evidence_adjudication_memberships_scope"),
        sa.UniqueConstraint("adjudication_revision_id", "project_id", "research_job_id", "ordinal", name="uq_orch_evidence_adjudication_memberships_ordinal"),
        sa.UniqueConstraint("adjudication_revision_id", "project_id", "research_job_id", "evidence_claim_id", name="uq_orch_evidence_adjudication_memberships_claim"),
        sa.CheckConstraint("ordinal > 0", name="ck_orch_evidence_adjudication_memberships_ordinal"),
        sa.ForeignKeyConstraint(
            ["adjudication_revision_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.evidence_conflict_adjudication_revisions.id", f"{SCHEMA}.evidence_conflict_adjudication_revisions.project_id", f"{SCHEMA}.evidence_conflict_adjudication_revisions.research_job_id"],
            name="fk_orch_evidence_adjudication_memberships_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_claim_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.evidence_claims.id", f"{SCHEMA}.evidence_claims.project_id", f"{SCHEMA}.evidence_claims.research_job_id"],
            name="fk_orch_evidence_adjudication_memberships_claim",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_pack_revisions",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("conflict_adjudication_revision_id", sa.Uuid(), nullable=False),
        sa.Column("adjudicator_version", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("conflict_metadata", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("coverage", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("publishable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("insufficiency_reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_evidence_packs_scope"),
        sa.UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_packs_job_scope"),
        sa.UniqueConstraint("research_job_id", "project_id", "revision", name="uq_orch_evidence_packs_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_packs_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_packs_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_evidence_packs_revision"),
        sa.CheckConstraint("evidence_count >= 0", name="ck_orch_evidence_packs_count"),
        _sha256("digest", "ck_orch_evidence_packs_digest"),
        _scoped_fk("research_job_id", "research_jobs", "fk_orch_evidence_packs_job"),
        sa.ForeignKeyConstraint(
            ["conflict_adjudication_revision_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.evidence_conflict_adjudication_revisions.id", f"{SCHEMA}.evidence_conflict_adjudication_revisions.project_id", f"{SCHEMA}.evidence_conflict_adjudication_revisions.research_job_id"],
            name="fk_orch_evidence_packs_adjudication",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_pack_memberships",
        *_identity_columns(),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_pack_revision_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_claim_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_evidence_memberships_scope"),
        sa.UniqueConstraint("evidence_pack_revision_id", "project_id", "research_job_id", "ordinal", name="uq_orch_evidence_memberships_ordinal"),
        sa.UniqueConstraint("evidence_pack_revision_id", "project_id", "research_job_id", "evidence_claim_id", name="uq_orch_evidence_memberships_claim"),
        sa.CheckConstraint("ordinal > 0", name="ck_orch_evidence_memberships_ordinal"),
        sa.ForeignKeyConstraint(
            ["evidence_pack_revision_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.evidence_pack_revisions.id", f"{SCHEMA}.evidence_pack_revisions.project_id", f"{SCHEMA}.evidence_pack_revisions.research_job_id"],
            name="fk_orch_evidence_memberships_pack",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_claim_id", "project_id", "research_job_id"],
            [f"{SCHEMA}.evidence_claims.id", f"{SCHEMA}.evidence_claims.project_id", f"{SCHEMA}.evidence_claims.research_job_id"],
            name="fk_orch_evidence_memberships_claim",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "resonance_direction_revisions",
        *_identity_columns(),
        sa.Column("evidence_pack_revision_id", sa.Uuid(), nullable=False),
        sa.Column("direction_key", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("publication_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_version", sa.String(100), nullable=False),
        sa.Column("validator_version", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_resonance_directions_scope"),
        sa.UniqueConstraint("project_id", "direction_key", "revision", name="uq_orch_resonance_directions_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", "publication_ordinal", name="uq_orch_resonance_directions_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_resonance_directions_command_length"),
        sa.CheckConstraint("revision > 0 AND publication_ordinal > 0", name="ck_orch_resonance_directions_ordinals"),
        sa.CheckConstraint("evidence_count > 0", name="ck_orch_resonance_directions_evidence_count"),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_orch_resonance_directions_score"),
        _sha256("digest", "ck_orch_resonance_directions_digest"),
        _scoped_fk("evidence_pack_revision_id", "evidence_pack_revisions", "fk_orch_resonance_directions_pack"),
        schema=SCHEMA,
    )
    op.create_table(
        "trial_methodology_revisions",
        *_identity_columns(),
        sa.Column("methodology_key", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_trial_methodologies_scope"),
        sa.UniqueConstraint("project_id", "methodology_key", "revision", name="uq_orch_trial_methodologies_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_trial_methodologies_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_trial_methodologies_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_trial_methodologies_revision"),
        _sha256("digest", "ck_orch_trial_methodologies_digest"),
        _project_fk("fk_orch_trial_methodologies_project"),
        schema=SCHEMA,
    )
    op.create_table(
        "trial_script_revisions",
        *_identity_columns(),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_pack_revision_id", sa.Uuid(), nullable=False),
        sa.Column("methodology_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_trial_scripts_scope"),
        sa.UniqueConstraint("project_id", "book_id", "revision", name="uq_orch_trial_scripts_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_trial_scripts_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_trial_scripts_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_trial_scripts_revision"),
        _sha256("digest", "ck_orch_trial_scripts_digest"),
        _scoped_fk("book_id", "books", "fk_orch_trial_scripts_book"),
        _scoped_fk("evidence_pack_revision_id", "evidence_pack_revisions", "fk_orch_trial_scripts_pack"),
        _scoped_fk("methodology_revision_id", "trial_methodology_revisions", "fk_orch_trial_scripts_methodology"),
        schema=SCHEMA,
    )
    op.create_table(
        "voice_preset_revisions",
        *_identity_columns(),
        sa.Column("preset_key", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("speaker", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_voice_presets_scope"),
        sa.UniqueConstraint("project_id", "preset_key", "revision", name="uq_orch_voice_presets_revision"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_voice_presets_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_voice_presets_command_length"),
        sa.CheckConstraint("revision > 0", name="ck_orch_voice_presets_revision"),
        _sha256("digest", "ck_orch_voice_presets_digest"),
        _project_fk("fk_orch_voice_presets_project"),
        schema=SCHEMA,
    )
    op.create_table(
        "tts_takes",
        *_identity_columns(),
        sa.Column("trial_script_revision_id", sa.Uuid(), nullable=False),
        sa.Column("voice_preset_revision_id", sa.Uuid(), nullable=False),
        sa.Column("cue_key", sa.String(160), nullable=False),
        sa.Column("audio_digest", sa.String(64), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_tts_takes_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_tts_takes_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_tts_takes_command_length"),
        _sha256("audio_digest", "ck_orch_tts_takes_audio_digest"),
        _sha256("digest", "ck_orch_tts_takes_digest"),
        _scoped_fk("trial_script_revision_id", "trial_script_revisions", "fk_orch_tts_takes_script"),
        _scoped_fk("voice_preset_revision_id", "voice_preset_revisions", "fk_orch_tts_takes_preset"),
        schema=SCHEMA,
    )
    op.create_table(
        "video_job_projections",
        *_identity_columns(),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("trial_script_revision_id", sa.Uuid(), nullable=False),
        sa.Column("external_job_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_video_jobs_scope"),
        sa.UniqueConstraint("project_id", "external_job_id", name="uq_orch_video_jobs_external"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_video_jobs_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_video_jobs_command_length"),
        _scoped_fk("book_id", "books", "fk_orch_video_jobs_book"),
        _scoped_fk("trial_script_revision_id", "trial_script_revisions", "fk_orch_video_jobs_script"),
        schema=SCHEMA,
    )
    op.create_table(
        "reader_feedback",
        *_identity_columns(),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_reader_feedback_scope"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_reader_feedback_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_reader_feedback_command_length"),
        _sha256("digest", "ck_orch_reader_feedback_digest"),
        _scoped_fk("book_id", "books", "fk_orch_reader_feedback_book"),
        schema=SCHEMA,
    )
    op.create_table(
        "video_book_bindings",
        *_identity_columns(),
        sa.Column("video_id", sa.String(200), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "project_id", name="uq_orch_video_book_bindings_scope"),
        sa.UniqueConstraint("project_id", "video_id", "book_id", name="uq_orch_video_book_bindings_pair"),
        sa.UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_video_book_bindings_command"),
        sa.CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_video_book_bindings_command_length"),
        _scoped_fk("book_id", "books", "fk_orch_video_book_bindings_book"),
        schema=SCHEMA,
    )

    immutable_tables = (
        "books",
        "book_merge_records",
        "input_resolutions",
        "search_queries",
        "search_hits",
        "source_failures",
        "source_document_revisions",
        "evidence_claims",
        "evidence_conflict_adjudication_revisions",
        "evidence_conflict_adjudication_memberships",
        "evidence_pack_revisions",
        "evidence_pack_memberships",
        "resonance_direction_revisions",
        "trial_methodology_revisions",
        "trial_script_revisions",
        "voice_preset_revisions",
        "tts_takes",
        "reader_feedback",
        "video_book_bindings",
    )
    for table_name in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.enforce_publishable_evidence_pack()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            pack_publishable boolean;
        BEGIN
            SELECT publishable
              INTO pack_publishable
              FROM {SCHEMA}.evidence_pack_revisions
             WHERE id = NEW.evidence_pack_revision_id
               AND project_id = NEW.project_id;
            IF pack_publishable IS FALSE THEN
                RAISE EXCEPTION 'critical_conflict_unresolved';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_resonance_directions_publishable_pack
        BEFORE INSERT ON {SCHEMA}.resonance_direction_revisions
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.enforce_publishable_evidence_pack()
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {SCHEMA}.enforce_publishable_evidence_pack() "
        "FROM PUBLIC"
    )
    all_tables = immutable_tables + ("research_jobs", "video_job_projections")
    op.execute(
        "REVOKE ALL ON TABLE "
        + ", ".join(f"{SCHEMA}.{table}" for table in all_tables)
        + " FROM PUBLIC"
    )
    immutable_list = ", ".join(f"{SCHEMA}.{table}" for table in immutable_tables)
    mutable_list = ", ".join(
        f"{SCHEMA}.{table}" for table in ("research_jobs", "video_job_projections")
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT, INSERT ON TABLE {immutable_list} TO {ROLE};
                GRANT SELECT, INSERT, UPDATE ON TABLE {mutable_list} TO {ROLE};
                GRANT EXECUTE ON FUNCTION {SCHEMA}.enforce_publishable_evidence_pack() TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_resonance_directions_publishable_pack "
        f"ON {SCHEMA}.resonance_direction_revisions"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.enforce_publishable_evidence_pack()"
    )
    for table_name in (
        "video_book_bindings",
        "reader_feedback",
        "video_job_projections",
        "tts_takes",
        "voice_preset_revisions",
        "trial_script_revisions",
        "trial_methodology_revisions",
        "resonance_direction_revisions",
        "evidence_pack_memberships",
        "evidence_pack_revisions",
        "evidence_conflict_adjudication_memberships",
        "evidence_conflict_adjudication_revisions",
        "evidence_claims",
        "source_document_revisions",
        "source_failures",
        "search_hits",
        "search_queries",
        "research_jobs",
        "input_resolutions",
        "book_merge_records",
        "books",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON {SCHEMA}.{table_name}"
        )
        op.drop_table(table_name, schema=SCHEMA)
