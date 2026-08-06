"""Add encrypted model credential registry.

Revision ID: hub_0006
Revises: hub_0005
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "hub_0006"
down_revision = "hub_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the historical 0006 shape explicit. Importing the live ORM model
    # here would make later ORM columns appear early during a fresh migration,
    # causing the following revision to add them twice.
    if inspect(op.get_bind()).has_table(
        "model_credentials",
        schema="hub",
    ):
        return
    op.create_table(
        "model_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("nonce", sa.String(length=32), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column(
            "key_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("key_hint", sa.String(length=16), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(provider) BETWEEN 1 AND 64",
            name="ck_model_credentials_provider_length",
        ),
        sa.CheckConstraint(
            "length(model_name) BETWEEN 1 AND 200",
            name="ck_model_credentials_model_length",
        ),
        sa.CheckConstraint(
            "length(ciphertext) BETWEEN 16 AND 8192",
            name="ck_model_credentials_ciphertext_length",
        ),
        sa.CheckConstraint(
            "length(nonce) BETWEEN 16 AND 32",
            name="ck_model_credentials_nonce_length",
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64",
            name="ck_model_credentials_fingerprint_length",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_model_credentials_revision_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "model_name",
            name="uq_model_credentials_provider_model",
        ),
        schema="hub",
    )
    op.create_index(
        "ix_model_credentials_provider_model",
        "model_credentials",
        ["provider", "model_name"],
        unique=False,
        schema="hub",
    )


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table(
        "model_credentials",
        schema="hub",
    ):
        return
    op.drop_index(
        "ix_model_credentials_provider_model",
        table_name="model_credentials",
        schema="hub",
    )
    op.drop_table("model_credentials", schema="hub")
