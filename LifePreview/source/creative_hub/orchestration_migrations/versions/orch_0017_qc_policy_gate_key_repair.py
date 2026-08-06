"""Repair legacy QC policy tables that predate per-gate authority.

Revision ID: orch_0017
Revises: orch_0016
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0017"
down_revision = "orch_0016"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"
TABLE = "qc_gate_policy_snapshots"


def _unique_columns(inspector, name: str) -> tuple[str, ...] | None:
    for constraint in inspector.get_unique_constraints(
        TABLE,
        schema=SCHEMA,
    ):
        if constraint["name"] == name:
            return tuple(constraint["column_names"])
    return None


def _index_columns(inspector, name: str) -> tuple[str, ...] | None:
    for index in inspector.get_indexes(TABLE, schema=SCHEMA):
        if index["name"] == name:
            return tuple(index["column_names"])
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        item["name"]
        for item in inspector.get_columns(TABLE, schema=SCHEMA)
    }
    if "gate_key" not in columns:
        op.add_column(
            TABLE,
            sa.Column("gate_key", sa.String(200)),
            schema=SCHEMA,
        )
        op.execute(
            sa.text(
                "UPDATE orchestration.qc_gate_policy_snapshots "
                "SET gate_key = stage || :legacy_suffix "
                "WHERE gate_key IS NULL"
            ).bindparams(legacy_suffix=":legacy")
        )
        op.alter_column(
            TABLE,
            "gate_key",
            existing_type=sa.String(200),
            nullable=False,
            schema=SCHEMA,
        )

    inspector = sa.inspect(bind)
    check_names = {
        item["name"]
        for item in inspector.get_check_constraints(
            TABLE,
            schema=SCHEMA,
        )
    }
    if "ck_orch_qc_gate_policy_gate_key" not in check_names:
        op.create_check_constraint(
            "ck_orch_qc_gate_policy_gate_key",
            TABLE,
            "length(trim(gate_key)) > 0",
            schema=SCHEMA,
        )

    expected_stage = (
        "project_id",
        "workflow_run_id",
        "stage",
        "gate_key",
    )
    current_stage = _unique_columns(
        inspector,
        "uq_orch_qc_gate_policy_stage",
    )
    if current_stage != expected_stage:
        if current_stage is not None:
            op.drop_constraint(
                "uq_orch_qc_gate_policy_stage",
                TABLE,
                type_="unique",
                schema=SCHEMA,
            )
        op.create_unique_constraint(
            "uq_orch_qc_gate_policy_stage",
            TABLE,
            list(expected_stage),
            schema=SCHEMA,
        )

    expected_scope = ("id", "project_id", "gate_key")
    current_scope = _unique_columns(
        inspector,
        "uq_orch_qc_gate_policy_gate_scope",
    )
    if current_scope != expected_scope:
        if current_scope is not None:
            op.drop_constraint(
                "uq_orch_qc_gate_policy_gate_scope",
                TABLE,
                type_="unique",
                schema=SCHEMA,
            )
        op.create_unique_constraint(
            "uq_orch_qc_gate_policy_gate_scope",
            TABLE,
            list(expected_scope),
            schema=SCHEMA,
        )

    expected_index = ("project_id", "workflow_run_id", "gate_key")
    current_index = _index_columns(
        inspector,
        "ix_orch_qc_gate_policy_workflow",
    )
    if current_index != expected_index:
        if current_index is not None:
            op.drop_index(
                "ix_orch_qc_gate_policy_workflow",
                table_name=TABLE,
                schema=SCHEMA,
            )
        op.create_index(
            "ix_orch_qc_gate_policy_workflow",
            TABLE,
            list(expected_index),
            schema=SCHEMA,
        )


def downgrade() -> None:
    # This is a forward-only drift repair. ``gate_key`` is part of the
    # canonical orch_0011 schema, so removing it would make a fresh downgrade
    # disagree with the historical migration chain.
    pass
