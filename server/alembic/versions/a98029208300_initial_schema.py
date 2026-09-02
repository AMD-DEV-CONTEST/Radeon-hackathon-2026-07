"""initial_schema

Revision ID: a98029208300
Revises:
Create Date: 2026-08-05 18:59:57.231752

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a98029208300"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), server_default="recruiter", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
    )
    op.create_index(op.f("ix_refresh_tokens_jti"), "refresh_tokens", ["jti"], unique=False)
    op.create_index(
        op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False
    )

    op.create_table(
        "candidates",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("level", sa.String(length=100), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("target_role", sa.String(length=255), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=50), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidates_email"), "candidates", ["email"], unique=False)
    op.create_index(op.f("ix_candidates_user_id"), "candidates", ["user_id"], unique=False)

    op.create_table(
        "resumes",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="uploaded", nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("parsed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resumes_candidate_id"), "resumes", ["candidate_id"], unique=False)

    op.create_table(
        "interviews",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="scheduled", nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("complexity", sa.String(length=100), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interviews_candidate_id"), "interviews", ["candidate_id"], unique=False
    )
    op.create_index(op.f("ix_interviews_resume_id"), "interviews", ["resume_id"], unique=False)
    op.create_index(op.f("ix_interviews_status"), "interviews", ["status"], unique=False)
    op.create_index(op.f("ix_interviews_user_id"), "interviews", ["user_id"], unique=False)

    op.create_table(
        "questions",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("difficulty", sa.String(length=20), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_questions_interview_id"), "questions", ["interview_id"], unique=False)

    op.create_table(
        "agent_logs",
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("agent", sa.String(length=100), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_logs_agent"), "agent_logs", ["agent"], unique=False)
    op.create_index(
        op.f("ix_agent_logs_interview_id"), "agent_logs", ["interview_id"], unique=False
    )
    op.create_index(op.f("ix_agent_logs_status"), "agent_logs", ["status"], unique=False)

    op.create_table(
        "evaluations",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("competency_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pulse_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluations_interview_id"), "evaluations", ["interview_id"], unique=True
    )

    op.create_table(
        "reports",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=50), nullable=True),
        sa.Column("performance_confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("executive_note", sa.Text(), nullable=True),
        sa.Column("competency_matrix", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pulse_series", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("export_path", sa.String(length=1024), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reports_interview_id"), "reports", ["interview_id"], unique=True)

    op.create_table(
        "transcripts",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("speaker", sa.String(length=50), nullable=False),
        sa.Column("speaker_name", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column(
            "spoken_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transcripts_interview_id"), "transcripts", ["interview_id"], unique=False
    )
    op.create_index(
        op.f("ix_transcripts_question_id"), "transcripts", ["question_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transcripts_question_id"), table_name="transcripts")
    op.drop_index(op.f("ix_transcripts_interview_id"), table_name="transcripts")
    op.drop_table("transcripts")

    op.drop_index(op.f("ix_reports_interview_id"), table_name="reports")
    op.drop_table("reports")

    op.drop_index(op.f("ix_evaluations_interview_id"), table_name="evaluations")
    op.drop_table("evaluations")

    op.drop_index(op.f("ix_agent_logs_status"), table_name="agent_logs")
    op.drop_index(op.f("ix_agent_logs_interview_id"), table_name="agent_logs")
    op.drop_index(op.f("ix_agent_logs_agent"), table_name="agent_logs")
    op.drop_table("agent_logs")

    op.drop_index(op.f("ix_questions_interview_id"), table_name="questions")
    op.drop_table("questions")

    op.drop_index(op.f("ix_interviews_user_id"), table_name="interviews")
    op.drop_index(op.f("ix_interviews_status"), table_name="interviews")
    op.drop_index(op.f("ix_interviews_resume_id"), table_name="interviews")
    op.drop_index(op.f("ix_interviews_candidate_id"), table_name="interviews")
    op.drop_table("interviews")

    op.drop_index(op.f("ix_resumes_candidate_id"), table_name="resumes")
    op.drop_table("resumes")

    op.drop_index(op.f("ix_candidates_user_id"), table_name="candidates")
    op.drop_index(op.f("ix_candidates_email"), table_name="candidates")
    op.drop_table("candidates")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_jti"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
