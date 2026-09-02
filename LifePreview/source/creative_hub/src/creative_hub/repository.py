from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from shared_contracts import (
    ImportPlan,
    KnowledgePack,
    KnowledgeReview,
    KnowledgeReviewDecision,
    KnowledgeRevision,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import (
    ImportPlanRecord,
    KnowledgeCardRecord,
    KnowledgePackRecord,
    KnowledgeReviewRecord,
    KnowledgeRevisionRecord,
)


class KnowledgeRepositoryError(RuntimeError):
    pass


class KnowledgeRevisionVersionConflict(KnowledgeRepositoryError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionStoreResult:
    revision: KnowledgeRevision
    created: bool


@dataclass(frozen=True, slots=True)
class KnowledgeReviewStoreResult:
    review: KnowledgeReview
    created: bool


@dataclass(frozen=True, slots=True)
class KnowledgePackStoreResult:
    pack: KnowledgePack
    created: bool


@dataclass(frozen=True, slots=True)
class ImportPlanStoreResult:
    plan: ImportPlan
    created: bool


class KnowledgeRepository:
    """Append-only persistence for reviewed, content-addressed knowledge."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _restore_revision(
        record: KnowledgeRevisionRecord,
    ) -> KnowledgeRevision:
        try:
            revision = KnowledgeRevision.model_validate(record.payload)
        except ValidationError:
            raise KnowledgeRepositoryError(
                "stored knowledge revision is invalid"
            ) from None
        if (
            revision.revision_id != record.id
            or revision.knowledge_id != record.knowledge_id
            or revision.revision != record.revision
            or revision.revision_sha256 != record.revision_sha256
        ):
            raise KnowledgeRepositoryError(
                "stored knowledge revision metadata does not match its contract"
            )
        return revision

    @staticmethod
    def _restore_review(record: KnowledgeReviewRecord) -> KnowledgeReview:
        try:
            review = KnowledgeReview.model_validate(record.payload)
        except ValidationError:
            raise KnowledgeRepositoryError(
                "stored knowledge review is invalid"
            ) from None
        if (
            review.review_id != record.id
            or review.revision_id != record.revision_id
            or review.revision_sha256 != record.revision_sha256
            or review.review_sha256 != record.review_sha256
            or review.decision.value != record.decision
            or review.reviewed_by != record.reviewed_by
            or review.reason != record.reason
            or review.reviewed_at != _utc(record.reviewed_at)
        ):
            raise KnowledgeRepositoryError(
                "stored knowledge review metadata does not match its contract"
            )
        return review

    @staticmethod
    def _restore_pack(record: KnowledgePackRecord) -> KnowledgePack:
        try:
            pack = KnowledgePack.model_validate(record.payload)
        except ValidationError:
            raise KnowledgeRepositoryError(
                "stored knowledge pack is invalid"
            ) from None
        if pack.pack_id != record.id or pack.pack_sha256 != record.pack_sha256:
            raise KnowledgeRepositoryError(
                "stored knowledge pack metadata does not match its contract"
            )
        return pack

    def get_revision(self, revision_id: UUID) -> KnowledgeRevision | None:
        record = self._session.get(KnowledgeRevisionRecord, revision_id)
        return None if record is None else self._restore_revision(record)

    def get_review(self, revision_id: UUID) -> KnowledgeReview | None:
        record = self._session.scalar(
            select(KnowledgeReviewRecord).where(
                KnowledgeReviewRecord.revision_id == revision_id
            )
        )
        return None if record is None else self._restore_review(record)

    def get_pack(self, pack_id: UUID) -> KnowledgePack | None:
        record = self._session.get(KnowledgePackRecord, pack_id)
        return None if record is None else self._restore_pack(record)

    def list_revisions(
        self,
        *,
        review_status: str | None = None,
        limit: int = 100,
    ) -> tuple[tuple[KnowledgeRevision, KnowledgeReview | None], ...]:
        if review_status not in {None, "pending", "approved", "rejected"}:
            raise ValueError("invalid review status")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        statement = (
            select(KnowledgeRevisionRecord, KnowledgeReviewRecord)
            .outerjoin(
                KnowledgeReviewRecord,
                KnowledgeReviewRecord.revision_id
                == KnowledgeRevisionRecord.id,
            )
            .order_by(KnowledgeRevisionRecord.created_at.desc())
            .limit(limit)
        )
        if review_status == "pending":
            statement = statement.where(KnowledgeReviewRecord.id.is_(None))
        elif review_status is not None:
            statement = statement.where(
                KnowledgeReviewRecord.decision == review_status
            )
        return tuple(
            (
                self._restore_revision(revision),
                None if review is None else self._restore_review(review),
            )
            for revision, review in self._session.execute(statement)
        )

    def append_revision(
        self,
        revision: KnowledgeRevision,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeRevisionStoreResult:
        revision = KnowledgeRevision.model_validate(
            revision.model_dump(mode="json")
        )
        if expected_revision < 0:
            raise ValueError("expected revision cannot be negative")
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("knowledge revision idempotency key is invalid")

        existing = self._session.scalar(
            select(KnowledgeRevisionRecord).where(
                KnowledgeRevisionRecord.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            restored = self._restore_revision(existing)
            if restored != revision:
                raise KnowledgeRepositoryError(
                    "knowledge revision idempotency key conflicts with stored content"
                )
            return KnowledgeRevisionStoreResult(
                revision=restored,
                created=False,
            )

        card = self._session.scalar(
            select(KnowledgeCardRecord)
            .where(KnowledgeCardRecord.id == revision.knowledge_id)
            .with_for_update()
        )
        if card is None:
            if expected_revision != 0:
                raise KnowledgeRevisionVersionConflict(
                    "current revision is 0"
                )
            dialect = self._session.get_bind().dialect.name
            if dialect == "postgresql":
                insert_factory = pg_insert
            elif dialect == "sqlite":
                insert_factory = sqlite_insert
            else:
                raise KnowledgeRepositoryError(
                    f"unsupported database dialect: {dialect}"
                )
            self._session.execute(
                insert_factory(KnowledgeCardRecord)
                .values(id=revision.knowledge_id, current_revision=0)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            card = self._session.scalar(
                select(KnowledgeCardRecord)
                .where(KnowledgeCardRecord.id == revision.knowledge_id)
                .with_for_update()
            )
        if card is None:
            raise KnowledgeRepositoryError("knowledge card could not be created")

        existing = self._session.scalar(
            select(KnowledgeRevisionRecord).where(
                KnowledgeRevisionRecord.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            restored = self._restore_revision(existing)
            if restored != revision:
                raise KnowledgeRepositoryError(
                    "knowledge revision idempotency key conflicts with stored content"
                )
            return KnowledgeRevisionStoreResult(
                revision=restored,
                created=False,
            )
        if card.current_revision != expected_revision:
            raise KnowledgeRevisionVersionConflict(
                f"current revision is {card.current_revision}"
            )
        if revision.revision != expected_revision + 1:
            raise KnowledgeRevisionVersionConflict(
                "knowledge revision number does not follow the expected revision"
            )

        self._session.add(
            KnowledgeRevisionRecord(
                id=revision.revision_id,
                knowledge_id=revision.knowledge_id,
                revision=revision.revision,
                revision_sha256=revision.revision_sha256,
                idempotency_key=idempotency_key,
                payload=revision.model_dump(mode="json"),
            )
        )
        card.current_revision = revision.revision
        self._session.flush()
        return KnowledgeRevisionStoreResult(revision=revision, created=True)

    def store_review(
        self,
        review: KnowledgeReview,
    ) -> KnowledgeReviewStoreResult:
        review = KnowledgeReview.model_validate(review.model_dump(mode="json"))
        revision_record = self._session.get(
            KnowledgeRevisionRecord,
            review.revision_id,
        )
        if revision_record is None:
            raise KnowledgeRepositoryError(
                "knowledge review revision is unavailable"
            )
        revision = self._restore_revision(revision_record)
        if revision.revision_sha256 != review.revision_sha256:
            raise KnowledgeRepositoryError(
                "knowledge review targets different revision content"
            )

        existing = self._session.scalar(
            select(KnowledgeReviewRecord).where(
                KnowledgeReviewRecord.revision_id == review.revision_id
            )
        )
        if existing is not None:
            restored = self._restore_review(existing)
            if restored != review:
                raise KnowledgeRepositoryError(
                    "knowledge revision was already reviewed"
                )
            return KnowledgeReviewStoreResult(review=restored, created=False)

        self._session.add(
            KnowledgeReviewRecord(
                id=review.review_id,
                revision_id=review.revision_id,
                revision_sha256=review.revision_sha256,
                review_sha256=review.review_sha256,
                decision=review.decision.value,
                reviewed_by=review.reviewed_by,
                reason=review.reason,
                reviewed_at=review.reviewed_at,
                payload=review.model_dump(mode="json"),
            )
        )
        self._session.flush()
        return KnowledgeReviewStoreResult(review=review, created=True)

    def store_pack(self, pack: KnowledgePack) -> KnowledgePackStoreResult:
        pack = KnowledgePack.model_validate(pack.model_dump(mode="json"))
        existing = self._session.get(KnowledgePackRecord, pack.pack_id)
        if existing is not None:
            restored = self._restore_pack(existing)
            if restored != pack:
                raise KnowledgeRepositoryError(
                    "knowledge pack identity conflicts with stored content"
                )
            return KnowledgePackStoreResult(pack=restored, created=False)

        for reference in pack.revisions:
            revision_record = self._session.get(
                KnowledgeRevisionRecord,
                reference.revision_id,
            )
            review_record = self._session.get(
                KnowledgeReviewRecord,
                reference.approval_id,
            )
            if revision_record is None or review_record is None:
                raise KnowledgeRepositoryError(
                    "knowledge pack requires stored approved revisions"
                )
            revision = self._restore_revision(revision_record)
            review = self._restore_review(review_record)
            if (
                revision.knowledge_id != reference.knowledge_id
                or revision.revision != reference.revision
                or revision.revision_sha256 != reference.revision_sha256
                or review.revision_id != reference.revision_id
                or review.review_sha256 != reference.approval_sha256
                or review.decision is not KnowledgeReviewDecision.APPROVED
            ):
                raise KnowledgeRepositoryError(
                    "knowledge pack approval reference is invalid"
                )

        self._session.add(
            KnowledgePackRecord(
                id=pack.pack_id,
                pack_sha256=pack.pack_sha256,
                payload=pack.model_dump(mode="json"),
            )
        )
        self._session.flush()
        return KnowledgePackStoreResult(pack=pack, created=True)

    @staticmethod
    def _restore_import_plan(record: ImportPlanRecord) -> ImportPlan:
        try:
            plan = ImportPlan.model_validate(record.payload)
        except ValidationError:
            raise KnowledgeRepositoryError(
                "stored import plan is invalid"
            ) from None
        if (
            plan.plan_id != record.id
            or plan.plan_sha256 != record.plan_sha256
            or plan.pack_id != record.pack_id
            or plan.pack_sha256 != record.pack_sha256
            or plan.target_snapshot_sha256 != record.target_snapshot_sha256
        ):
            raise KnowledgeRepositoryError(
                "stored import plan metadata does not match its contract"
            )
        return plan

    def get_import_plan(self, plan_id: UUID) -> ImportPlan | None:
        record = self._session.get(ImportPlanRecord, plan_id)
        return None if record is None else self._restore_import_plan(record)

    def store_import_plan(
        self,
        plan: ImportPlan,
    ) -> ImportPlanStoreResult:
        plan = ImportPlan.model_validate(plan.model_dump(mode="json"))
        existing = self._session.get(ImportPlanRecord, plan.plan_id)
        if existing is not None:
            restored = self._restore_import_plan(existing)
            if restored != plan:
                raise KnowledgeRepositoryError(
                    "import plan identity conflicts with stored content"
                )
            return ImportPlanStoreResult(plan=restored, created=False)
        pack = self.get_pack(plan.pack_id)
        if pack is None or pack.pack_sha256 != plan.pack_sha256:
            raise KnowledgeRepositoryError(
                "import plan requires its stored knowledge pack"
            )
        self._session.add(
            ImportPlanRecord(
                id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                pack_id=plan.pack_id,
                pack_sha256=plan.pack_sha256,
                target_snapshot_sha256=plan.target_snapshot_sha256,
                payload=plan.model_dump(mode="json"),
            )
        )
        self._session.flush()
        return ImportPlanStoreResult(plan=plan, created=True)
