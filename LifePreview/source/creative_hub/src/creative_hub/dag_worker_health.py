from __future__ import annotations

import os

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from .dag_models import DagReadyQueueRecord
from .runtime_bootstrap import database_url


class DagWorkerHealthError(RuntimeError):
    """The worker still owns a scheduler lease that it stopped heartbeating."""


def assert_worker_lease_health(
    session: Session,
    *,
    worker_id: str,
) -> None:
    if not worker_id.strip():
        raise DagWorkerHealthError("DAG worker id is unavailable")
    expired = session.scalar(
        select(func.count())
        .select_from(DagReadyQueueRecord)
        .where(
            DagReadyQueueRecord.state == "LEASED",
            DagReadyQueueRecord.lease_owner == worker_id,
            DagReadyQueueRecord.lease_expires_at <= func.now(),
        )
    )
    if int(expired or 0) > 0:
        raise DagWorkerHealthError(
            "DAG worker owns an expired scheduler lease"
        )


def main() -> None:
    worker_id = os.getenv("CREATIVE_HUB_DAG_WORKER_ID", "")
    database_url = (
        os.getenv("CREATIVE_ORCHESTRATION_DATABASE_URL")
        or database_url("CREATIVE_ORCHESTRATION")
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            assert_worker_lease_health(session, worker_id=worker_id)
    finally:
        engine.dispose()


__all__ = [
    "DagWorkerHealthError",
    "assert_worker_lease_health",
    "main",
]
