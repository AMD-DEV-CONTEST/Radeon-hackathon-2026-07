"""Add durable DAG scheduling, admission, leases, and scoped budgets.

Revision ID: orch_0007
Revises: orch_0006
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0007"
down_revision = "orch_0006"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"
POOLS = "'cpu', 'local_gpu', 'cloud_image', 'cloud_video', 'llm'"


def _operation_scope_fk(
    name: str, local_column: str
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [local_column, "workflow_run_id", "project_id"],
        [
            f"{SCHEMA}.operation_runs.id",
            f"{SCHEMA}.operation_runs.workflow_run_id",
            f"{SCHEMA}.operation_runs.project_id",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # T2 accounts were project-only.  The scheduler admits against the policy's
    # ordered GLOBAL -> PROJECT -> WORKFLOW dimensions, one pool at a time.
    op.drop_constraint(
        "fk_orch_budget_reservations_account",
        "budget_reservations",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_orch_budget_ledger_account",
        "budget_ledger_entries",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_orch_budget_accounts_key",
        "budget_accounts",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "uq_orch_budget_accounts_scope",
        "budget_accounts",
        schema=SCHEMA,
        type_="unique",
    )
    op.alter_column(
        "budget_accounts", "project_id", schema=SCHEMA, nullable=True
    )
    op.add_column(
        "budget_accounts",
        sa.Column(
            "scope_kind",
            sa.String(16),
            nullable=False,
            server_default="PROJECT",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "budget_accounts",
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True)),
        schema=SCHEMA,
    )
    op.add_column(
        "budget_accounts",
        sa.Column(
            "resource_pool",
            sa.String(24),
            nullable=False,
            server_default="cpu",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_budget_accounts_scope_shape",
        "budget_accounts",
        "(scope_kind = 'GLOBAL' AND project_id IS NULL "
        "AND workflow_run_id IS NULL) OR "
        "(scope_kind = 'PROJECT' AND project_id IS NOT NULL "
        "AND workflow_run_id IS NULL) OR "
        "(scope_kind = 'WORKFLOW' AND project_id IS NOT NULL "
        "AND workflow_run_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_budget_accounts_scope_kind",
        "budget_accounts",
        "scope_kind IN ('GLOBAL', 'PROJECT', 'WORKFLOW')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_budget_accounts_resource_pool",
        "budget_accounts",
        f"resource_pool IN ({POOLS})",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_budget_accounts_workflow",
        "budget_accounts",
        "workflow_runs",
        ["workflow_run_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_orch_budget_accounts_global_dimension",
        "budget_accounts",
        ["account_key", "resource_pool"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("scope_kind = 'GLOBAL'"),
    )
    op.create_index(
        "uq_orch_budget_accounts_project_dimension",
        "budget_accounts",
        ["project_id", "account_key", "resource_pool"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("scope_kind = 'PROJECT'"),
    )
    op.create_index(
        "uq_orch_budget_accounts_workflow_dimension",
        "budget_accounts",
        ["workflow_run_id", "account_key", "resource_pool"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("scope_kind = 'WORKFLOW'"),
    )
    op.create_foreign_key(
        "fk_orch_budget_reservations_account",
        "budget_reservations",
        "budget_accounts",
        ["account_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_orch_budget_ledger_account",
        "budget_ledger_entries",
        "budget_accounts",
        ["account_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.create_unique_constraint(
        "uq_orch_operation_runs_dag_scope",
        "operation_runs",
        ["id", "workflow_run_id", "project_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "workflow_run_edges",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "upstream_operation_run_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "downstream_operation_run_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "required_status",
            sa.String(16),
            nullable=False,
            server_default="SUCCEEDED",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "upstream_operation_run_id <> downstream_operation_run_id",
            name="ck_orch_workflow_edges_not_self",
        ),
        sa.CheckConstraint(
            "required_status IN ('SUCCEEDED', 'TERMINAL')",
            name="ck_orch_workflow_edges_required",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [f"{SCHEMA}.workflow_runs.id", f"{SCHEMA}.workflow_runs.project_id"],
            name="fk_orch_workflow_edges_workflow",
            ondelete="RESTRICT",
        ),
        _operation_scope_fk(
            "fk_orch_workflow_edges_upstream",
            "upstream_operation_run_id",
        ),
        _operation_scope_fk(
            "fk_orch_workflow_edges_downstream",
            "downstream_operation_run_id",
        ),
        sa.UniqueConstraint(
            "workflow_run_id",
            "upstream_operation_run_id",
            "downstream_operation_run_id",
            name="uq_orch_workflow_edges_pair",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_edges_upstream",
        "workflow_run_edges",
        ["upstream_operation_run_id", "downstream_operation_run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_edges_downstream",
        "workflow_run_edges",
        ["downstream_operation_run_id", "upstream_operation_run_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "operation_dependency_states",
        sa.Column(
            "operation_run_id", sa.Uuid(as_uuid=True), primary_key=True
        ),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "dependency_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "satisfied_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('WAITING', 'READY', 'DISPATCHED', 'PAUSED_HUMAN', "
            "'BLOCKED', 'TERMINAL')",
            name="ck_orch_dependency_state_status",
        ),
        sa.CheckConstraint(
            "dependency_count >= 0 AND satisfied_count >= 0 "
            "AND failed_count >= 0 AND "
            "satisfied_count + failed_count <= dependency_count",
            name="ck_orch_dependency_state_counts",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_dependency_state_version",
        ),
        _operation_scope_fk(
            "fk_orch_dependency_state_operation", "operation_run_id"
        ),
        sa.UniqueConstraint(
            "operation_run_id",
            "workflow_run_id",
            "project_id",
            name="uq_orch_dependency_state_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dependency_state_workflow_status",
        "operation_dependency_states",
        ["workflow_run_id", "status", "operation_run_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "resource_pool_quotas",
        sa.Column("resource_pool", sa.String(24), primary_key=True),
        sa.Column("max_concurrent", sa.Integer(), nullable=False),
        sa.Column(
            "in_use", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"resource_pool IN ({POOLS})",
            name="ck_orch_resource_quota_pool",
        ),
        sa.CheckConstraint(
            "max_concurrent > 0 AND in_use >= 0 "
            "AND in_use <= max_concurrent",
            name="ck_orch_resource_quota_capacity",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_resource_quota_version",
        ),
        schema=SCHEMA,
    )
    op.bulk_insert(
        sa.table(
            "resource_pool_quotas",
            sa.column("resource_pool", sa.String()),
            sa.column("max_concurrent", sa.Integer()),
            schema=SCHEMA,
        ),
        [
            {"resource_pool": "cpu", "max_concurrent": 8},
            {"resource_pool": "local_gpu", "max_concurrent": 2},
            {"resource_pool": "cloud_image", "max_concurrent": 4},
            {"resource_pool": "cloud_video", "max_concurrent": 2},
            {"resource_pool": "llm", "max_concurrent": 8},
        ],
        multiinsert=True,
    )

    op.create_table(
        "dag_ready_queue",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("resource_pool", sa.String(24), nullable=False),
        sa.Column("priority_class", sa.String(16), nullable=False),
        sa.Column("priority_value", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_cost_micros", sa.BigInteger(), nullable=False
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column(
            "not_before", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column(
            "lease_generation",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_id", sa.Uuid(as_uuid=True)),
        sa.Column(
            "dispatch_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("blocked_reason", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"resource_pool IN ({POOLS})",
            name="ck_orch_dag_ready_resource_pool",
        ),
        sa.CheckConstraint(
            "priority_class IN ('batch', 'interactive', 'urgent', 'system')",
            name="ck_orch_dag_ready_priority",
        ),
        sa.CheckConstraint(
            "state IN ('WAITING', 'READY', 'LEASED', 'PAUSED_HUMAN', "
            "'BUDGET_BLOCKED', 'DONE', 'CANCELLED')",
            name="ck_orch_dag_ready_state",
        ),
        sa.CheckConstraint(
            "estimated_cost_micros >= 0",
            name="ck_orch_dag_ready_estimated_cost",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0 AND dispatch_count >= 0",
            name="ck_orch_dag_ready_counters",
        ),
        sa.CheckConstraint(
            "(state = 'LEASED' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND attempt_id IS NOT NULL) "
            "OR (state <> 'LEASED' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_orch_dag_ready_lease_shape",
        ),
        _operation_scope_fk(
            "fk_orch_dag_ready_operation", "operation_run_id"
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_dag_ready_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "operation_run_id", name="uq_orch_dag_ready_operation"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dag_ready_claim",
        "dag_ready_queue",
        ["state", "resource_pool", "not_before", "enqueued_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dag_ready_workflow_state",
        "dag_ready_queue",
        ["workflow_run_id", "state"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dag_ready_expired_lease",
        "dag_ready_queue",
        ["lease_expires_at", "id"],
        schema=SCHEMA,
    )

    op.create_table(
        "scheduler_fairness_counters",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("resource_pool", sa.String(24), nullable=False),
        sa.Column(
            "dispatch_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "scope_kind IN ('RESOURCE_POOL', 'PROJECT', 'WORKFLOW')",
            name="ck_orch_scheduler_fairness_scope",
        ),
        sa.CheckConstraint(
            f"resource_pool IN ({POOLS})",
            name="ck_orch_scheduler_fairness_pool",
        ),
        sa.CheckConstraint(
            "dispatch_count >= 0",
            name="ck_orch_scheduler_fairness_dispatches",
        ),
        sa.UniqueConstraint(
            "scope_kind",
            "scope_key",
            "resource_pool",
            name="uq_orch_scheduler_fairness_dimension",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_scheduler_fairness_order",
        "scheduler_fairness_counters",
        ["resource_pool", "scope_kind", "dispatch_count"],
        schema=SCHEMA,
    )

    op.create_table(
        "dag_admission_reservations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("queue_entry_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("budget_account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "budget_reservation_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="RESERVED",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'RELEASED', 'SETTLED')",
            name="ck_orch_dag_admission_status",
        ),
        sa.CheckConstraint(
            "amount_micros > 0",
            name="ck_orch_dag_admission_amount",
        ),
        sa.ForeignKeyConstraint(
            ["queue_entry_id"],
            [f"{SCHEMA}.dag_ready_queue.id"],
            name="fk_orch_dag_admission_queue",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["budget_account_id"],
            [f"{SCHEMA}.budget_accounts.id"],
            name="fk_orch_dag_admission_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "budget_reservation_id",
                "budget_account_id",
                "project_id",
            ],
            [
                f"{SCHEMA}.budget_reservations.id",
                f"{SCHEMA}.budget_reservations.account_id",
                f"{SCHEMA}.budget_reservations.project_id",
            ],
            name="fk_orch_dag_admission_reservation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "queue_entry_id",
            "lease_generation",
            "budget_account_id",
            name="uq_orch_dag_admission_account",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dag_admission_attempt",
        "dag_admission_reservations",
        ["attempt_id", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "dag_scheduler_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("queue_entry_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_id", sa.Uuid(as_uuid=True)),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("data_digest", sa.String(64), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "sequence > 0", name="ck_orch_dag_scheduler_event_sequence"
        ),
        sa.CheckConstraint(
            "length(data_digest) = 64",
            name="ck_orch_dag_scheduler_event_digest",
        ),
        sa.ForeignKeyConstraint(
            ["queue_entry_id"],
            [f"{SCHEMA}.dag_ready_queue.id"],
            name="fk_orch_dag_scheduler_event_queue",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "queue_entry_id",
            "sequence",
            name="uq_orch_dag_scheduler_event_sequence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_dag_scheduler_event_workflow",
        "dag_scheduler_events",
        ["workflow_run_id", "occurred_at"],
        schema=SCHEMA,
    )

    for table_name in ("workflow_run_edges", "dag_scheduler_events"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"{SCHEMA}.reject_immutable_fact_mutation()"
        )

    tables = (
        "workflow_run_edges, operation_dependency_states, dag_ready_queue, "
        "resource_pool_quotas, scheduler_fairness_counters, "
        "dag_admission_reservations, dag_scheduler_events"
    )
    qualified_tables = tables.replace(", ", f", {SCHEMA}.")
    op.execute(
        f"REVOKE ALL ON TABLE {SCHEMA}.{qualified_tables} FROM PUBLIC"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'creative_orchestrator_app'
            ) THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON {SCHEMA}.operation_dependency_states,
                       {SCHEMA}.dag_ready_queue,
                       {SCHEMA}.resource_pool_quotas,
                       {SCHEMA}.scheduler_fairness_counters,
                       {SCHEMA}.dag_admission_reservations
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON {SCHEMA}.workflow_run_edges,
                       {SCHEMA}.dag_scheduler_events
                    TO creative_orchestrator_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM orchestration.workflow_run_edges "
            "UNION ALL SELECT 1 FROM orchestration.dag_ready_queue "
            "UNION ALL SELECT 1 FROM orchestration.dag_scheduler_events "
            "UNION ALL SELECT 1 FROM orchestration.dag_admission_reservations "
            "UNION ALL SELECT 1 FROM orchestration.budget_accounts "
            "WHERE scope_kind <> 'PROJECT')"
        )
    ).scalar_one()
    destructive = (
        os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") == "YES"
    )
    if populated and not destructive:
        raise RuntimeError(
            "orchestration downgrade would delete DAG scheduler facts or "
            "non-project budget accounts; set "
            "ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after backup"
        )

    if destructive:
        op.execute(
            "DELETE FROM orchestration.dag_admission_reservations "
            "WHERE budget_account_id IN "
            "(SELECT id FROM orchestration.budget_accounts "
            "WHERE scope_kind <> 'PROJECT')"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_budget_ledger_entries_immutable "
            "ON orchestration.budget_ledger_entries"
        )
        op.execute(
            "DELETE FROM orchestration.budget_ledger_entries "
            "WHERE account_id IN (SELECT id FROM orchestration.budget_accounts "
            "WHERE scope_kind <> 'PROJECT')"
        )
        op.execute(
            "DELETE FROM orchestration.budget_reservations "
            "WHERE account_id IN (SELECT id FROM orchestration.budget_accounts "
            "WHERE scope_kind <> 'PROJECT')"
        )
        op.execute(
            "DELETE FROM orchestration.budget_accounts "
            "WHERE scope_kind <> 'PROJECT'"
        )
        op.execute(
            "CREATE TRIGGER trg_budget_ledger_entries_immutable "
            "BEFORE UPDATE OR DELETE "
            "ON orchestration.budget_ledger_entries FOR EACH ROW "
            "EXECUTE FUNCTION "
            "orchestration.reject_immutable_fact_mutation()"
        )

    for table_name in ("dag_scheduler_events", "workflow_run_edges"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON {SCHEMA}.{table_name}"
        )
    for table_name in (
        "dag_scheduler_events",
        "dag_admission_reservations",
        "scheduler_fairness_counters",
        "dag_ready_queue",
        "resource_pool_quotas",
        "operation_dependency_states",
        "workflow_run_edges",
    ):
        op.drop_table(table_name, schema=SCHEMA)

    op.drop_constraint(
        "uq_orch_operation_runs_dag_scope",
        "operation_runs",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_orch_budget_reservations_account",
        "budget_reservations",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_orch_budget_ledger_account",
        "budget_ledger_entries",
        schema=SCHEMA,
        type_="foreignkey",
    )
    for index_name in (
        "uq_orch_budget_accounts_workflow_dimension",
        "uq_orch_budget_accounts_project_dimension",
        "uq_orch_budget_accounts_global_dimension",
    ):
        op.drop_index(index_name, table_name="budget_accounts", schema=SCHEMA)
    op.drop_constraint(
        "fk_orch_budget_accounts_workflow",
        "budget_accounts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    for constraint_name in (
        "ck_orch_budget_accounts_resource_pool",
        "ck_orch_budget_accounts_scope_kind",
        "ck_orch_budget_accounts_scope_shape",
    ):
        op.drop_constraint(
            constraint_name,
            "budget_accounts",
            schema=SCHEMA,
            type_="check",
        )
    op.drop_column("budget_accounts", "resource_pool", schema=SCHEMA)
    op.drop_column("budget_accounts", "workflow_run_id", schema=SCHEMA)
    op.drop_column("budget_accounts", "scope_kind", schema=SCHEMA)
    op.alter_column(
        "budget_accounts", "project_id", schema=SCHEMA, nullable=False
    )
    op.create_unique_constraint(
        "uq_orch_budget_accounts_key",
        "budget_accounts",
        ["project_id", "account_key"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_orch_budget_accounts_scope",
        "budget_accounts",
        ["id", "project_id"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_budget_reservations_account",
        "budget_reservations",
        "budget_accounts",
        ["account_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_orch_budget_ledger_account",
        "budget_ledger_entries",
        "budget_accounts",
        ["account_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
