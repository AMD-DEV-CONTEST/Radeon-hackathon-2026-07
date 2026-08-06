"""Durable storage for the E6/M5 privacy review, route matrix, and approvals.

Kept in its own module rather than added to `SQLiteAssetRepository`: E6 stores
policy outcomes bound to an exact (asset, version, content hash) triple, and
that binding rule is the whole point of the store. Folded into the general
repository it would read as three more tables among forty and the rule would
survive only as long as the next author noticed it.

Every read is binding-scoped. A review or approval stored against a different
version is not a stale copy to refresh — it answers a different question, and
the read misses rather than returning it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.experience_asset.application.m5.contracts import (
    PrivacyReviewV1,
    RouteReadinessMatrixV1,
)
from app.experience_asset.domain.models import ApprovalRecord
from app.experience_asset.policy.m5 import route_matrix_hash


class M5StoreError(Exception):
    """A durable M5 write contradicted the state it was bound to."""


@dataclass(frozen=True)
class StoredM5Approval:
    approval: ApprovalRecord
    asset_id: UUID
    version_id: UUID
    content_hash: str
    draft_id: UUID | None
    draft_binding_hash: str
    matrix_hash: str
    stale_since: str | None
    stale_reason: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


class M5Store:
    """Binding-scoped persistence for E6 policy outcomes."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def save_workflow_command(
        self,
        *,
        run_id: UUID,
        command_kind: str,
        finding_id: UUID | None = None,
        privacy_action: str | None = None,
        route_draft_id: UUID | None = None,
        user_action: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Persist sanitized command authority outside the bounded checkpoint."""

        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO m5_workflow_commands(
                    run_id, command_kind, finding_id, privacy_action,
                    route_draft_id, user_action, idempotency_key, created_at
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(run_id),
                    command_kind,
                    str(finding_id) if finding_id else None,
                    privacy_action,
                    str(route_draft_id) if route_draft_id else None,
                    user_action,
                    idempotency_key,
                    _now(),
                ),
            )
            connection.commit()

    def read_workflow_command(self, run_id: UUID) -> dict[str, str | None]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM m5_workflow_commands WHERE run_id=?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise M5StoreError(f"missing M5 workflow command for run {run_id}")
        return {
            "command_kind": row["command_kind"],
            "finding_id": row["finding_id"],
            "privacy_action": row["privacy_action"],
            "route_draft_id": row["route_draft_id"],
            "user_action": row["user_action"],
            "idempotency_key": row["idempotency_key"],
        }

    # ---- privacy review -------------------------------------------------

    def save_evaluation(
        self,
        review: PrivacyReviewV1,
        matrix: RouteReadinessMatrixV1,
        *,
        content_hash: str,
        run_id: UUID,
    ) -> bool:
        """Atomically replace the live review/matrix pair when its binding changed.

        Returning ``False`` means the exact policy outcome was already current;
        callers must not stale an approval merely because the user asked to
        evaluate the same immutable input again.
        """

        matrix_digest = route_matrix_hash(matrix)
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_review = connection.execute(
                """SELECT review_hash FROM m5_privacy_reviews
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (str(review.asset_id), str(review.version_id), content_hash),
            ).fetchone()
            previous_matrix = connection.execute(
                """SELECT matrix_hash, review_hash FROM m5_route_matrices
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (str(matrix.asset_id), str(matrix.version_id), content_hash),
            ).fetchone()
            if (
                previous_review is not None
                and previous_matrix is not None
                and previous_review["review_hash"] == review.review_hash
                and previous_matrix["matrix_hash"] == matrix_digest
                and previous_matrix["review_hash"] == review.review_hash
            ):
                connection.rollback()
                return False
            connection.execute(
                """UPDATE m5_privacy_reviews SET superseded_at=?
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (now, str(review.asset_id), str(review.version_id), content_hash),
            )
            connection.execute(
                """UPDATE m5_route_matrices SET superseded_at=?
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (now, str(matrix.asset_id), str(matrix.version_id), content_hash),
            )
            connection.execute(
                """INSERT INTO m5_privacy_reviews(
                    review_id, asset_id, version_id, content_hash, review_hash,
                    status, failure_code, content_json, created_by_run_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    str(review.asset_id),
                    str(review.version_id),
                    content_hash,
                    review.review_hash,
                    review.status.value,
                    review.failure_code,
                    review.model_dump_json(),
                    str(run_id),
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO m5_route_matrices(
                    matrix_id, asset_id, version_id, content_hash, matrix_hash,
                    review_hash, content_json, created_by_run_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    str(matrix.asset_id),
                    str(matrix.version_id),
                    content_hash,
                    matrix_digest,
                    review.review_hash,
                    matrix.model_dump_json(),
                    str(run_id),
                    now,
                ),
            )
            connection.commit()
        return True

    def save_privacy_review(
        self,
        review: PrivacyReviewV1,
        *,
        content_hash: str,
        run_id: UUID,
    ) -> PrivacyReviewV1:
        """Store one review as the live one for its binding.

        Supersedes rather than replaces: the user resolved findings against the
        text a specific review showed them, and overwriting it would leave the
        approval trail pointing at wording nobody ever saw.
        """

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE m5_privacy_reviews SET superseded_at=?
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (_now(), str(review.asset_id), str(review.version_id), content_hash),
            )
            connection.execute(
                """INSERT INTO m5_privacy_reviews(
                    review_id, asset_id, version_id, content_hash, review_hash,
                    status, failure_code, content_json, created_by_run_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    str(review.asset_id),
                    str(review.version_id),
                    content_hash,
                    review.review_hash,
                    review.status.value,
                    review.failure_code,
                    review.model_dump_json(),
                    str(run_id),
                    _now(),
                ),
            )
            connection.commit()
        return review

    def read_privacy_review(
        self, *, asset_id: UUID, version_id: UUID, content_hash: str
    ) -> PrivacyReviewV1 | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT content_json FROM m5_privacy_reviews
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (str(asset_id), str(version_id), content_hash),
            ).fetchone()
        if row is None:
            return None
        return PrivacyReviewV1.model_validate_json(row["content_json"])

    # ---- route matrix ---------------------------------------------------

    def save_route_matrix(
        self,
        matrix: RouteReadinessMatrixV1,
        *,
        content_hash: str,
        review_hash: str | None,
        run_id: UUID,
    ) -> RouteReadinessMatrixV1:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE m5_route_matrices SET superseded_at=?
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (_now(), str(matrix.asset_id), str(matrix.version_id), content_hash),
            )
            connection.execute(
                """INSERT INTO m5_route_matrices(
                    matrix_id, asset_id, version_id, content_hash, matrix_hash,
                    review_hash, content_json, created_by_run_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    str(matrix.asset_id),
                    str(matrix.version_id),
                    content_hash,
                    route_matrix_hash(matrix),
                    review_hash,
                    matrix.model_dump_json(),
                    str(run_id),
                    _now(),
                ),
            )
            connection.commit()
        return matrix

    def read_route_matrix(
        self, *, asset_id: UUID, version_id: UUID, content_hash: str
    ) -> RouteReadinessMatrixV1 | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT content_json FROM m5_route_matrices
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (str(asset_id), str(version_id), content_hash),
            ).fetchone()
        if row is None:
            return None
        return RouteReadinessMatrixV1.model_validate_json(row["content_json"])

    def read_route_matrix_run_id(
        self, *, asset_id: UUID, version_id: UUID, content_hash: str
    ) -> UUID | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT created_by_run_id FROM m5_route_matrices
                WHERE asset_id=? AND version_id=? AND content_hash=?
                  AND superseded_at IS NULL""",
                (str(asset_id), str(version_id), content_hash),
            ).fetchone()
        return UUID(row["created_by_run_id"]) if row is not None else None

    # ---- approvals ------------------------------------------------------

    def save_approval(
        self,
        approval: ApprovalRecord,
        *,
        asset_id: UUID,
        version_id: UUID,
        content_hash: str,
        draft_id: UUID,
        draft_binding_hash: str,
        matrix_hash: str,
        run_id: UUID,
    ) -> ApprovalRecord:
        """Append one approval. Approvals are never updated in place."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT approval_id FROM m5_approvals WHERE approval_id=?",
                (str(approval.approval_id),),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return approval
            connection.execute(
                """INSERT INTO m5_approvals(
                    approval_id, asset_id, version_id, content_hash, route,
                    language, draft_id, draft_binding_hash, review_hash,
                    matrix_hash, content_json, created_by_run_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(approval.approval_id),
                    str(asset_id),
                    str(version_id),
                    content_hash,
                    approval.route.value,
                    approval.language,
                    str(draft_id),
                    draft_binding_hash,
                    approval.privacy_review_hash,
                    matrix_hash,
                    approval.model_dump_json(),
                    str(run_id),
                    _now(),
                ),
            )
            connection.commit()
        return approval

    def list_approvals(
        self, *, asset_id: UUID, version_id: UUID, content_hash: str
    ) -> list[ApprovalRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT content_json FROM m5_approvals
                WHERE asset_id=? AND version_id=? AND content_hash=?
                ORDER BY created_at, approval_id""",
                (str(asset_id), str(version_id), content_hash),
            ).fetchall()
        return [ApprovalRecord.model_validate_json(row["content_json"]) for row in rows]

    def read_approval(self, approval_id: UUID) -> StoredM5Approval:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM m5_approvals WHERE approval_id=?",
                (str(approval_id),),
            ).fetchone()
        if row is None:
            raise M5StoreError(f"unknown approval {approval_id}")
        try:
            draft_id = UUID(row["draft_id"])
        except (TypeError, ValueError):
            # PR #52 briefly stored the legacy route-draft hash in this column.
            # Preserve the audit row but never reinterpret it as live authority.
            draft_id = None
        return StoredM5Approval(
            approval=ApprovalRecord.model_validate_json(row["content_json"]),
            asset_id=UUID(row["asset_id"]),
            version_id=UUID(row["version_id"]),
            content_hash=row["content_hash"],
            draft_id=draft_id,
            draft_binding_hash=row["draft_binding_hash"],
            matrix_hash=row["matrix_hash"],
            stale_since=row["stale_since"],
            stale_reason=row["stale_reason"],
        )

    def mark_approvals_stale(
        self, *, asset_id: UUID, reason: str, keep_content_hash: str | None = None
    ) -> int:
        """Mark every approval for an asset stale except the named binding.

        Called when a bound input changes. The rows stay: an approval the user
        granted and then invalidated by editing is a different fact from an
        approval that never happened, and the export audit needs both.
        """

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if keep_content_hash is None:
                cursor = connection.execute(
                    """UPDATE m5_approvals SET stale_since=?, stale_reason=?
                    WHERE asset_id=? AND stale_since IS NULL""",
                    (_now(), reason, str(asset_id)),
                )
            else:
                cursor = connection.execute(
                    """UPDATE m5_approvals SET stale_since=?, stale_reason=?
                    WHERE asset_id=? AND stale_since IS NULL AND content_hash<>?""",
                    (_now(), reason, str(asset_id), keep_content_hash),
                )
            changed = cursor.rowcount
            connection.commit()
        return changed

    def read_approval_staleness(self, approval_id: UUID) -> tuple[str | None, str | None]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT stale_since, stale_reason FROM m5_approvals WHERE approval_id=?",
                (str(approval_id),),
            ).fetchone()
        if row is None:
            raise M5StoreError(f"unknown approval {approval_id}")
        return row["stale_since"], row["stale_reason"]


__all__ = ["M5Store", "M5StoreError", "StoredM5Approval"]
