"""Add model credential connection verification state.

Revision ID: hub_0007
Revises: hub_0006
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "hub_0007"
down_revision = "hub_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {
        item["name"]
        for item in inspector.get_columns(
            "model_credentials",
            schema="hub",
        )
    }
    if "verification_status" not in columns:
        op.add_column(
            "model_credentials",
            sa.Column(
                "verification_status",
                sa.String(length=16),
                server_default="unchecked",
                nullable=False,
            ),
            schema="hub",
        )
    if "verified_at" not in columns:
        op.add_column(
            "model_credentials",
            sa.Column(
                "verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            schema="hub",
        )
    if "verification_error_code" not in columns:
        op.add_column(
            "model_credentials",
            sa.Column(
                "verification_error_code",
                sa.String(length=64),
                nullable=True,
            ),
            schema="hub",
        )
    constraints = {
        item["name"]
        for item in inspect(op.get_bind()).get_check_constraints(
            "model_credentials",
            schema="hub",
        )
    }
    if "ck_model_credentials_verification_status" not in constraints:
        op.create_check_constraint(
            "ck_model_credentials_verification_status",
            "model_credentials",
            (
                "verification_status IN "
                "('unchecked', 'available', 'invalid')"
            ),
            schema="hub",
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    constraints = {
        item["name"]
        for item in inspector.get_check_constraints(
            "model_credentials",
            schema="hub",
        )
    }
    if "ck_model_credentials_verification_status" in constraints:
        op.drop_constraint(
            "ck_model_credentials_verification_status",
            "model_credentials",
            type_="check",
            schema="hub",
        )
    columns = {
        item["name"]
        for item in inspect(op.get_bind()).get_columns(
            "model_credentials",
            schema="hub",
        )
    }
    for column in (
        "verification_error_code",
        "verified_at",
        "verification_status",
    ):
        if column in columns:
            op.drop_column(
                "model_credentials",
                column,
                schema="hub",
            )
