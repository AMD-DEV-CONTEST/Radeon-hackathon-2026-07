from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, update
from sqlmodel import Session, col, select

from ....exceptions import ValidationError
from ..models import ConversationMessageRow, ConversationThreadRow


class ConversationRepository:
    """Persistence primitives for the Conversation aggregate.

    The repository deliberately has no generic Call/Result mutation helpers. A
    complete LLM emission and its Tool Results are written by the private
    Conversation writer in one transaction.
    """

    def create_thread(self, session: Session, row: ConversationThreadRow) -> ConversationThreadRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_thread(self, session: Session, thread_id: str) -> ConversationThreadRow | None:
        return session.get(ConversationThreadRow, thread_id)

    def list_threads(self, session: Session) -> list[ConversationThreadRow]:
        statement = select(ConversationThreadRow).order_by(ConversationThreadRow.updated_at.desc())
        return list(session.exec(statement))

    def list_thread_ids_referencing_model(
        self,
        session: Session,
        fq_model_key: str,
    ) -> tuple[str, ...]:
        """Return exact historical Thread references without making them blockers.

        The LLM settings owner uses this narrow query only to classify a removed
        generation's retained history.  A persisted Thread reference is stale
        after removal rather than authority to retain remote compute.
        """

        normalized = fq_model_key.strip()
        if not normalized:
            raise ValidationError("LLM model key cannot be blank.")
        statement = select(ConversationThreadRow.id).where(
            ConversationThreadRow.selected_fq_model_key == normalized
        )
        return tuple(str(thread_id) for thread_id in session.exec(statement))

    def rename_thread(
        self,
        session: Session,
        thread_id: str,
        title: str | None,
        now: datetime,
    ) -> ConversationThreadRow | None:
        row = self.get_thread(session, thread_id)
        if row is None:
            return None
        row.title = title
        row.updated_at = now
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def set_initial_title_if_blank(
        self,
        session: Session,
        *,
        thread_id: str,
        title: str,
        now: datetime,
    ) -> ConversationThreadRow | None:
        """Set an automatic initial title only while the Thread is untitled."""

        statement = (
            update(ConversationThreadRow)
            .where(
                ConversationThreadRow.id == thread_id,
                or_(
                    ConversationThreadRow.title.is_(None),
                    func.trim(ConversationThreadRow.title) == "",
                ),
            )
            .values(title=title, updated_at=now)
        )
        session.execute(statement)
        session.flush()
        session.expire_all()
        return self.get_thread(session, thread_id)

    def next_message_sequence(self, session: Session, thread_id: str) -> int:
        statement = select(func.max(col(ConversationMessageRow.sequence_index))).where(
            ConversationMessageRow.thread_id == thread_id
        )
        current = session.exec(statement).one()
        return 0 if current is None else int(current) + 1

    def append_message(self, session: Session, row: ConversationMessageRow) -> ConversationMessageRow:
        if row.kind in {
            "tool_call",
            "tool_result",
        }:
            raise ValidationError("Tool Call/Result messages are committed only by the Conversation writer.")
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_message(self, session: Session, message_id: str) -> ConversationMessageRow | None:
        return session.get(ConversationMessageRow, message_id)

    def list_messages(self, session: Session, thread_id: str) -> list[ConversationMessageRow]:
        statement = (
            select(ConversationMessageRow)
            .where(ConversationMessageRow.thread_id == thread_id)
            .order_by(ConversationMessageRow.sequence_index)
        )
        return list(session.exec(statement))

    def list_pending(self, session: Session, thread_id: str) -> list[ConversationMessageRow]:
        statement = (
            select(ConversationMessageRow)
            .where(
                ConversationMessageRow.thread_id == thread_id,
                ConversationMessageRow.kind == "pending_llm_sampling",
            )
            .order_by(ConversationMessageRow.sequence_index)
        )
        return list(session.exec(statement))

    def delete_thread(self, session: Session, thread_id: str) -> ConversationThreadRow | None:
        row = self.get_thread(session, thread_id)
        if row is None:
            return None

        dependent_results = session.exec(
            select(ConversationMessageRow).where(
                ConversationMessageRow.thread_id == thread_id,
                ConversationMessageRow.tool_call_message_id.is_not(None),
            )
        ).all()
        for message in dependent_results:
            session.delete(message)
        session.flush()

        remaining_messages = session.exec(
            select(ConversationMessageRow).where(ConversationMessageRow.thread_id == thread_id)
        ).all()
        for message in remaining_messages:
            session.delete(message)
        session.flush()
        session.delete(row)
        session.flush()
        return row
