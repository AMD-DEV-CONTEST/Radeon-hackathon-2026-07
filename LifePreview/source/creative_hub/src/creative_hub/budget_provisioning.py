from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from creative_hub.cost_budgets import (
    BudgetConfigurationError,
    CostBudgetPolicy,
)
from creative_hub.db.models import BudgetAccountRecord


def ensure_global_budget_accounts(
    session: Session,
    policy: CostBudgetPolicy,
) -> int:
    """Create the durable snapshots required by configured global budgets.

    Admission remains fail-closed: an existing account whose limit differs
    from the mounted policy aborts worker startup instead of silently changing
    a live spend ledger. PostgreSQL workers serialize concurrent Compose
    startup with a transaction-scoped advisory lock.
    """

    global_budgets = tuple(
        budget for budget in policy.budgets if budget.scope == "global"
    )
    if not global_budgets:
        return 0
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:identity, 0))"
            ),
            {"identity": "creative-hub:global-budget-account-bootstrap"},
        )

    created = 0
    for budget in global_budgets:
        existing = session.scalar(
            select(BudgetAccountRecord).where(
                BudgetAccountRecord.scope_kind == "GLOBAL",
                BudgetAccountRecord.project_id.is_(None),
                BudgetAccountRecord.workflow_run_id.is_(None),
                BudgetAccountRecord.resource_pool == budget.resource_pool,
                BudgetAccountRecord.account_key == budget.budget_id,
            )
        )
        if existing is not None:
            if (
                existing.currency != "USD"
                or existing.limit_micros != budget.hard_limit_micros
            ):
                raise BudgetConfigurationError(
                    "global budget account does not match mounted policy"
                )
            continue
        session.add(
            BudgetAccountRecord(
                project_id=None,
                scope_kind="GLOBAL",
                workflow_run_id=None,
                resource_pool=budget.resource_pool,
                account_key=budget.budget_id,
                currency="USD",
                limit_micros=budget.hard_limit_micros,
            )
        )
        created += 1
    session.flush()
    return created


__all__ = ["ensure_global_budget_accounts"]
