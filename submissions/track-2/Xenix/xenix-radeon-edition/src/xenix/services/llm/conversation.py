"""Canonical Conversation authority owned by the LLM boundary.

The service is intentionally the only production holder of the writer
capability.  It accepts immutable commands, keeps incomplete model output in
memory, and commits a complete LLM emission (including every Tool Result) or
nothing at all.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import field_validator
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, SQLModel, select

from ...exceptions import NotFoundError, ValidationError
from ...observability import (
    LLMTokenUsage,
    LLMUsageAggregate,
    LLMUsageObservation,
    LLMUsageObservability,
    NullLLMUsageObservability,
)
from ..storage.models import (
    ConversationMessageKind,
    ConversationMessageRow,
    ConversationThreadRow,
    ConversationToolResultStatus,
    default_agent_thread_system_prompt,
    generate_id,
)
from ..storage.repositories import ConversationRepository
from .messages import (
    AssistantOutputItem,
    CanonicalMessageBlock,
    DatasetBlock,
    MarkdownBlock,
    ProviderOutputItem,
    SourceAttachmentBlock,
    TextBlock,
    ToolCallOutputItem,
    blocks_from_payload,
    blocks_to_json,
    blocks_to_markdown,
    normalize_message_blocks,
)
from .providers import (
    AgentProvider,
    LLMRetryEvent,
    ProviderMessage,
    ProviderResponse,
    ProviderStreamEvent,
)
from .service import LLMModelOption, LLMService
from .tooling import (
    MAX_EXCHANGE_RESULT_BYTES,
    AgentToolRegistry,
    ToolExecutionContext,
    ToolScope,
    StagedToolCall,
    TerminalToolResult,
    canonical_tool_result_value,
    canonical_json_bytes,
    scope_fingerprint,
    terminal_tool_result,
    tool_failure_from_exception,
)


LOGGER = logging.getLogger(__name__)
THREAD_TITLE_MAX_LENGTH = 80
THREAD_TITLE_SYSTEM_PROMPT = (
    "You generate concise conversation titles for Xenix threads. "
    "Return exactly one title only. Use the user's language when it is clear. "
    "Do not include quotes, markdown, labels, or trailing punctuation."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CreateConversationThreadInput(SQLModel):
    title: str | None = None
    system_prompt: str | None = None
    interface_locale: str | None = None
    selected_fq_model_key: str | None = None


class AppendUserMessageInput(SQLModel):
    thread_id: str
    client_submission_id: str
    content_blocks: list[CanonicalMessageBlock] = Field(default_factory=list)

    @field_validator("content_blocks", mode="before")
    @classmethod
    def _parse_content_blocks(cls, value: Any) -> list[CanonicalMessageBlock]:
        return list(normalize_message_blocks(value))


class ConversationSnapshot(SQLModel):
    thread: ConversationThreadRow
    messages: list[ConversationMessageRow] = Field(default_factory=list)


@dataclass(frozen=True)
class ConversationUsageOverview:
    """A read-only usage projection for one completed User interaction."""

    root_user_message_id: str
    terminal_llm_message_id: str
    terminal_sequence_index: int
    usage: LLMUsageAggregate


@dataclass(frozen=True)
class SubmissionClaim:
    thread_id: str
    expected_frontier_id: str | None
    client_submission_id: str
    initial_title_eligible: bool = False
    existing_message_id: str | None = None


@dataclass(frozen=True)
class PendingSampling:
    pending_message_id: str
    thread_id: str
    staged_calls: tuple[StagedToolCall, ...] = ()
    has_assistant_output: bool = False


@dataclass(frozen=True)
class ConversationLiveEvent:
    kind: str
    pending_message_id: str
    retry: LLMRetryEvent | None = None
    staged_call_id: str | None = None


class ThreadPausedError(ValidationError):
    """A runtime-only Thread pause prevented a new LLM provider request."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            f"LLM sampling is paused for Thread '{thread_id}'.",
            error_code="llm_thread_paused",
        )


@dataclass
class _ThreadControl:
    """Process-local pause state; never persisted as Conversation state."""

    paused: bool = False


@dataclass
class _PendingExchange:
    pending_message_id: str
    thread_id: str
    sequence_index: int
    frontier_message_id: str
    root_user_message_id: str | None
    scope: ToolScope
    scope_fingerprint: str
    output_items: tuple[ProviderOutputItem, ...] = ()
    calls: dict[str, StagedToolCall] = field(default_factory=dict)
    results: dict[str, TerminalToolResult] = field(default_factory=dict)
    tool_execution_started: bool = False
    cancelled: bool = False


class LLMConversationService:
    """Deep Conversation facade and sole canonical writer.

    Provider and Tool I/O deliberately run outside a Thread gate.  Every
    callback re-enters through the pending-message compare-and-swap below.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        llm_service: LLMService | None = None,
        tool_registry: AgentToolRegistry | None = None,
        context_messages_provider: Callable[[ConversationSnapshot], list[ProviderMessage]] | None = None,
        usage_observability: LLMUsageObservability | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._llm_service = llm_service
        self._tool_registry = tool_registry or AgentToolRegistry()
        self._context_messages_provider = context_messages_provider
        self._usage_observability = usage_observability or NullLLMUsageObservability()
        self._repository = ConversationRepository()
        self._gates_lock = threading.Lock()
        self._thread_gates: dict[str, threading.RLock] = {}
        self._claims: set[tuple[str, str]] = set()
        self._claims_lock = threading.Lock()
        self._pending: dict[str, _PendingExchange] = {}
        self._pending_lock = threading.RLock()
        self._thread_controls: dict[str, _ThreadControl] = {}

    @property
    def tool_registry(self) -> AgentToolRegistry:
        return self._tool_registry

    def model_options(self) -> list[LLMModelOption]:
        return self._require_llm_service().model_options()

    def default_fq_model_key(self) -> str:
        return self._require_llm_service().default_fq_model_key()

    def validate_fq_model_key(self, fq_model_key: str) -> str:
        return self._require_llm_service().validate_fq_model_key(fq_model_key)

    def has_thread_title_model(self) -> bool:
        return self._thread_title_fq_model_key() is not None

    def generate_thread_title(self, thread_id: str) -> str:
        """Return a manual title proposal without changing the Thread."""

        if not self.has_thread_title_model():
            raise ValidationError("Thread title model is not configured.")
        title = self._model_thread_title(
            self._thread_title_snapshot_prompt(self.get_thread_snapshot(thread_id)),
            thread_id=thread_id,
        )
        if title is None:
            raise ValidationError("Thread title model returned an empty title.")
        return title

    def auto_title_initial_thread(
        self,
        *,
        claim: SubmissionClaim,
        first_user_message_id: str,
        appended_snapshot: ConversationSnapshot | None = None,
    ) -> ConversationSnapshot | None:
        """Persist metadata for a just-appended first UserMessage when eligible.

        The claim captures the pre-append eligibility from canonical state; the
        caller supplies the first Message identity from the append result.  A
        Harness may retain that append snapshot while primary sampling begins;
        using it as the preflight witness avoids a fast Assistant completion
        changing the definition of the already-eligible initial exchange.
        Provider I/O remains outside the write gate, so a manual rename never
        waits on the title model and always wins the conditional write.
        """

        thread_id = claim.thread_id
        if not claim.initial_title_eligible:
            return self.get_thread_snapshot(thread_id)
        if appended_snapshot is not None:
            if appended_snapshot.thread.id != thread_id:
                raise ValidationError("The supplied append snapshot belongs to a different Thread.")
            snapshot = appended_snapshot
            if not self._is_initial_title_target(snapshot, first_user_message_id):
                return self.get_thread_snapshot(thread_id)
        else:
            with self._gate(thread_id):
                snapshot = self.get_thread_snapshot(thread_id)
                if not self._is_initial_title_target(snapshot, first_user_message_id):
                    return snapshot

        try:
            title = self._automatic_initial_thread_title(snapshot)
        except ThreadPausedError:
            return None
        with self._pending_lock:
            with self._gate(thread_id):
                if self._thread_control_locked(thread_id).paused:
                    return None
                with self._session_factory() as session:
                    row = self._repository.set_initial_title_if_blank(
                        session,
                        thread_id=thread_id,
                        title=title,
                        now=_utc_now(),
                    )
                    if row is None:
                        raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                    messages = self._repository.list_messages(session, thread_id)
                    session.commit()
                    return ConversationSnapshot(thread=row, messages=messages)

    def create_thread(self, input_data: CreateConversationThreadInput | None = None) -> ConversationSnapshot:
        input_data = input_data or CreateConversationThreadInput()
        title = input_data.title.strip() if input_data.title else None
        system_prompt = (input_data.system_prompt or "").strip() or default_agent_thread_system_prompt(
            input_data.interface_locale
        )
        model_key = (input_data.selected_fq_model_key or "").strip() or None
        now = _utc_now()
        row = ConversationThreadRow(
            title=title,
            system_prompt=system_prompt,
            selected_fq_model_key=model_key,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            self._repository.create_thread(session, row)
            session.commit()
        return ConversationSnapshot(thread=row, messages=[])

    def list_threads(self) -> list[ConversationThreadRow]:
        with self._session_factory() as session:
            return self._repository.list_threads(session)

    def get_thread_snapshot(self, thread_id: str) -> ConversationSnapshot:
        with self._session_factory() as session:
            thread = self._repository.get_thread(session, thread_id)
            if thread is None:
                raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
            return ConversationSnapshot(thread=thread, messages=self._repository.list_messages(session, thread_id))

    def usage_overviews(self, snapshot: ConversationSnapshot) -> tuple[ConversationUsageOverview, ...]:
        """Read safe token totals for completed User-to-LLM interactions.

        Canonical Messages determine which interactions are complete.  The
        injected observability reader contributes only independently-recorded
        token facts; missing or failing telemetry never changes the snapshot
        or any Conversation command.
        """

        completed = self._completed_user_interactions(snapshot.messages)
        if not completed:
            return ()
        try:
            aggregates = self._usage_observability.query_primary_usage(
                thread_id=snapshot.thread.id,
                root_user_message_ids=[root.id for root, _terminal in completed],
            )
        except Exception as exc:
            LOGGER.warning("LLM usage observability query failed: %s", exc.__class__.__name__)
            return ()
        return tuple(
            ConversationUsageOverview(
                root_user_message_id=root.id,
                terminal_llm_message_id=terminal.id,
                terminal_sequence_index=terminal.sequence_index,
                usage=aggregate,
            )
            for root, terminal in completed
            if (aggregate := aggregates.get(root.id)) is not None and aggregate.request_count > 0
        )

    def rename_thread(self, thread_id: str, title: str | None) -> ConversationSnapshot:
        with self._gate(thread_id):
            with self._session_factory() as session:
                row = self._repository.rename_thread(session, thread_id, title.strip() if title else None, _utc_now())
                if row is None:
                    raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                session.commit()
            return self.get_thread_snapshot(thread_id)

    def set_thread_model(self, thread_id: str, fq_model_key: str) -> ConversationSnapshot:
        selected = self.validate_fq_model_key(fq_model_key)
        with self._gate(thread_id):
            with self._session_factory() as session:
                thread = self._repository.get_thread(session, thread_id)
                if thread is None:
                    raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                if self._repository.list_pending(session, thread_id):
                    raise ValidationError("Cannot change the model while LLM sampling is pending.")
                thread.selected_fq_model_key = selected
                thread.updated_at = _utc_now()
                session.add(thread)
                session.commit()
            return self.get_thread_snapshot(thread_id)

    def delete_thread(self, thread_id: str) -> None:
        with self._pending_lock:
            with self._gate(thread_id):
                with self._session_factory() as session:
                    if self._repository.list_pending(session, thread_id):
                        raise ValidationError("Cannot delete a Thread while LLM sampling is pending.")
                    row = self._repository.delete_thread(session, thread_id)
                    if row is None:
                        raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                    session.commit()
                self._thread_controls.pop(thread_id, None)

    def pause_thread(self, thread_id: str) -> None:
        """Pause new LLM provider sends for one Thread in this process only."""

        with self._pending_lock:
            with self._gate(thread_id):
                with self._session_factory() as session:
                    if self._repository.get_thread(session, thread_id) is None:
                        raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                control = self._thread_control_locked(thread_id)
                if not control.paused:
                    control.paused = True

    def is_thread_paused(self, thread_id: str) -> bool:
        """Return only runtime pause state; it is intentionally not durable."""

        with self._pending_lock:
            return self._thread_control_locked(thread_id).paused

    def claim_user_submission(
        self,
        *,
        thread_id: str | None,
        expected_frontier_id: str | None,
        client_submission_id: str,
    ) -> SubmissionClaim:
        normalized_id = client_submission_id.strip()
        if not normalized_id:
            raise ValidationError("Client submission ID cannot be empty.")
        if thread_id is None:
            return SubmissionClaim(thread_id="", expected_frontier_id=None, client_submission_id=normalized_id)
        with self._pending_lock:
            with self._gate(thread_id):
                snapshot = self.get_thread_snapshot(thread_id)
                duplicate = next(
                    (message for message in snapshot.messages if message.client_submission_id == normalized_id),
                    None,
                )
                if duplicate is not None:
                    return SubmissionClaim(
                        thread_id=thread_id,
                        expected_frontier_id=expected_frontier_id,
                        client_submission_id=normalized_id,
                        existing_message_id=duplicate.id,
                    )
                self._validate_user_append_messages(
                    snapshot.messages,
                    expected_frontier_id,
                    allow_paused_tool_result=self._thread_control_locked(thread_id).paused,
                )
                key = (thread_id, normalized_id)
                with self._claims_lock:
                    if key in self._claims:
                        raise ValidationError("This submission is already being prepared.")
                    self._claims.add(key)
                return SubmissionClaim(
                    thread_id=thread_id,
                    expected_frontier_id=expected_frontier_id,
                    client_submission_id=normalized_id,
                    initial_title_eligible=self.is_initial_title_eligible(snapshot),
                )

    def release_user_submission_claim(self, claim: SubmissionClaim) -> None:
        if not claim.thread_id:
            return
        with self._claims_lock:
            self._claims.discard((claim.thread_id, claim.client_submission_id))

    def append_user_message(
        self,
        input_data: AppendUserMessageInput,
        *,
        expected_frontier_id: str | None = None,
    ) -> ConversationSnapshot:
        client_submission_id = input_data.client_submission_id.strip()
        if not client_submission_id:
            raise ValidationError("Client submission ID cannot be empty.")
        with self._pending_lock:
            with self._gate(input_data.thread_id):
                control = self._thread_control_locked(input_data.thread_id)
                with self._session_factory() as session:
                    thread = self._repository.get_thread(session, input_data.thread_id)
                    if thread is None:
                        raise NotFoundError(f"Conversation Thread '{input_data.thread_id}' was not found.")
                    messages = self._repository.list_messages(session, input_data.thread_id)
                    duplicate = next(
                        (row for row in messages if row.client_submission_id == client_submission_id),
                        None,
                    )
                    if duplicate is None:
                        self._validate_user_append_messages(
                            messages,
                            expected_frontier_id,
                            allow_paused_tool_result=control.paused,
                        )
                        canonical_blocks = normalize_message_blocks(input_data.content_blocks)
                        if any(isinstance(block, SourceAttachmentBlock) for block in canonical_blocks):
                            raise ValidationError(
                                "SourceAttachmentBlock is a legacy presentation block and cannot be written to a new User Message."
                            )
                        row = ConversationMessageRow(
                            thread_id=input_data.thread_id,
                            sequence_index=len(messages),
                            kind=ConversationMessageKind.USER,
                            client_submission_id=client_submission_id,
                            content_payload={"blocks": blocks_to_json(canonical_blocks)},
                            created_at=_utc_now(),
                        )
                        self._repository.append_message(session, row)
                        thread.updated_at = _utc_now()
                        session.add(thread)
                        session.commit()
                        # A new explicit User Message is the only re-entry
                        # command.  It never automatically replays the paused
                        # ToolResult frontier.
                        if control.paused:
                            control.paused = False
                    return ConversationSnapshot(
                        thread=thread,
                        messages=self._repository.list_messages(session, input_data.thread_id),
                    )

    def sample_existing_frontier(
        self,
        *,
        thread_id: str,
        expected_frontier_id: str,
        tool_scope: ToolScope | None = None,
        fq_model_key: str | None = None,
        provider: AgentProvider | None = None,
        retry_callback: Callable[[LLMRetryEvent], None] | None = None,
    ) -> PendingSampling:
        pending = self.begin_sampling(
            thread_id=thread_id,
            expected_frontier_id=expected_frontier_id,
            tool_scope=tool_scope or ToolScope(),
        )
        return self.complete_pending_sampling(
            pending_message_id=pending.pending_message_id,
            provider=provider,
            fq_model_key=fq_model_key,
            retry_callback=retry_callback,
        )

    def begin_sampling(
        self,
        *,
        thread_id: str,
        expected_frontier_id: str,
        tool_scope: ToolScope | None = None,
    ) -> PendingSampling:
        """Persist the pre-I/O placeholder and grant a live sampling capability."""

        return self._begin_sampling(
            thread_id=thread_id,
            expected_frontier_id=expected_frontier_id,
            tool_scope=tool_scope or ToolScope(),
        )

    def complete_pending_sampling(
        self,
        *,
        pending_message_id: str,
        provider: AgentProvider | None = None,
        fq_model_key: str | None = None,
        retry_callback: Callable[[LLMRetryEvent], None] | None = None,
    ) -> PendingSampling:
        """Perform provider I/O for an already-created pending placeholder."""

        try:
            with self._pending_lock:
                exchange = self._current_exchange(pending_message_id)
                scope = exchange.scope
                thread_id = exchange.thread_id
            snapshot = self.get_thread_snapshot(thread_id)
            selected_model_key = fq_model_key or snapshot.thread.selected_fq_model_key
            response = self._complete(
                provider=provider,
                fq_model_key=selected_model_key,
                messages=self._provider_messages(snapshot),
                tool_scope=scope,
                retry_callback=retry_callback,
                before_provider_request=lambda: self._admit_provider_request(pending_message_id),
            )
            return self._stage_provider_response(
                pending_message_id,
                response,
                fq_model_key=selected_model_key,
            )
        except Exception:
            self.cancel_sampling(pending_message_id)
            raise

    def sample_existing_frontier_stream(
        self,
        *,
        thread_id: str,
        expected_frontier_id: str,
        tool_scope: ToolScope | None = None,
        fq_model_key: str | None = None,
    ) -> Iterator[ConversationLiveEvent | PendingSampling]:
        effective_scope = tool_scope or ToolScope()
        pending = self.begin_sampling(
            thread_id=thread_id,
            expected_frontier_id=expected_frontier_id,
            tool_scope=effective_scope,
        )
        handed_off = False
        try:
            yield ConversationLiveEvent(kind="sampling_started", pending_message_id=pending.pending_message_id)
            snapshot = self.get_thread_snapshot(thread_id)
            service = self._require_llm_service()
            selected_model_key = fq_model_key or snapshot.thread.selected_fq_model_key
            final_response: ProviderResponse | None = None
            stream_arguments = {
                "fq_model_key": selected_model_key,
                "messages": self._provider_messages(snapshot),
                "tools": self._tool_registry.list_specs(effective_scope),
                "before_provider_request": lambda: self._admit_provider_request(pending.pending_message_id),
            }
            for event in service.stream(**stream_arguments):
                if isinstance(event, LLMRetryEvent):
                    yield ConversationLiveEvent(kind="retry", pending_message_id=pending.pending_message_id, retry=event)
                elif isinstance(event, ProviderStreamEvent):
                    if event.is_tool_call_delta:
                        yield ConversationLiveEvent(kind="tool_progress", pending_message_id=pending.pending_message_id)
                    if event.response is not None:
                        final_response = event.response
            if final_response is None:
                raise ValidationError("LLM stream completed without a normalized response.")
            staged = self._stage_provider_response(
                pending.pending_message_id,
                final_response,
                fq_model_key=selected_model_key,
            )
            # Once the staged capability is delivered, the caller owns the
            # next explicit action: finalize it or cancel it.  Before that
            # handoff, generator abandonment must revoke the placeholder.
            handed_off = True
            yield staged
        finally:
            if not handed_off:
                self.cancel_sampling(pending.pending_message_id)

    def list_staged_tool_calls(self, pending_message_id: str) -> tuple[StagedToolCall, ...]:
        with self._pending_lock:
            exchange = self._pending.get(pending_message_id)
            if exchange is None or exchange.cancelled:
                raise ValidationError("The pending LLM exchange is no longer current.")
            return tuple(exchange.calls.values())

    def finalize_pending_assistant(self, pending_message_id: str) -> ConversationSnapshot:
        with self._pending_lock:
            exchange = self._current_exchange(pending_message_id)
            if exchange.calls:
                raise ValidationError("A tool-calling exchange can finalize only after all Tool Results exist.")
            with self._gate(exchange.thread_id):
                if self._exchange_is_paused_locked(exchange):
                    self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)
                    raise ThreadPausedError(exchange.thread_id)
        return self._finalize_exchange(pending_message_id)

    def invoke_staged_tool(
        self,
        *,
        pending_message_id: str,
        staged_call_message_id: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ConversationSnapshot | None:
        cancel_requested = cancel_requested or (lambda: False)
        with self._pending_lock:
            exchange = self._pending.get(pending_message_id)
            if exchange is None or exchange.cancelled:
                # A provider/tool callback can arrive after cancellation has
                # revoked its live capability.  It is not an invalid command
                # and must not resurrect or poison the Thread.
                return None
            call = exchange.calls.get(staged_call_message_id)
            if call is None:
                raise ValidationError("The staged Tool Call is not part of this pending exchange.")
            if staged_call_message_id in exchange.results:
                raise ValidationError("The staged Tool Call already has a terminal result.")
            with self._gate(exchange.thread_id):
                # Once one Tool in an admitted exchange has crossed this
                # boundary, its complete result set may still converge after
                # a pause.  Before that boundary, Stop wins without starting
                # a fresh domain-side effect.
                if not exchange.tool_execution_started and self._exchange_is_paused_locked(exchange):
                    self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)
                    raise ThreadPausedError(exchange.thread_id)
                exchange.tool_execution_started = True

        if cancel_requested():
            self.cancel_sampling(pending_message_id)
            return None
        try:
            outcome = self._tool_registry.invoke(
                tool_name=call.tool_name,
                provider_name=call.provider_name,
                arguments=call.arguments,
                context=ToolExecutionContext(
                    thread_id=exchange.thread_id,
                    dataset_ids=exchange.scope.dataset_ids,
                    cancel_requested=cancel_requested,
                ),
                scope=exchange.scope,
            )
            terminal = terminal_tool_result(outcome)
        except Exception as exc:
            # Project the failure once into the same canonical value consumed
            # by the provider and Chatbot.  Only explicitly public validation
            # diagnostics survive; unexpected exceptions stay generic.
            terminal = terminal_tool_result(tool_failure_from_exception(exc))

        if cancel_requested():
            self.cancel_sampling(pending_message_id)
            return None

        try:
            with self._pending_lock:
                exchange = self._pending.get(pending_message_id)
                if exchange is None or exchange.cancelled:
                    return None
                if staged_call_message_id not in exchange.calls:
                    raise ValidationError("The staged Tool Call is not part of this pending exchange.")
                if staged_call_message_id in exchange.results:
                    raise ValidationError("The staged Tool Call already has a terminal result.")
                exchange.results[staged_call_message_id] = terminal
                if len(exchange.results) != len(exchange.calls):
                    return None
                self._validate_exchange_result_budget(exchange)
        except Exception:
            # A complete result set that cannot be committed is no longer a
            # valid live exchange.  Discard its placeholder instead of leaving
            # a hidden pending tombstone that blocks future client messages.
            self.cancel_sampling(pending_message_id)
            raise
        return self._finalize_exchange(pending_message_id)

    def cancel_sampling(self, pending_message_id: str) -> None:
        with self._pending_lock:
            exchange = self._pending.get(pending_message_id)
            if exchange is None:
                return
            with self._gate(exchange.thread_id):
                self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)

    def discard_stale_pending_messages(self) -> int:
        """Main-writer startup barrier only; workers must never call this."""

        removed = 0
        with self._session_factory() as session:
            stale = session.exec(
                select(ConversationMessageRow).where(
                    ConversationMessageRow.kind == ConversationMessageKind.PENDING_LLM_SAMPLING
                )
            ).all()
            for row in stale:
                session.delete(row)
                removed += 1
            session.commit()
        with self._pending_lock:
            self._pending.clear()
        return removed

    def _begin_sampling(
        self,
        *,
        thread_id: str,
        expected_frontier_id: str,
        tool_scope: ToolScope,
    ) -> PendingSampling:
        # Tool definitions are part of the pre-I/O sampling capability.  Fully
        # validate their fingerprint before durable state changes so an invalid
        # registry cannot leave a placeholder tombstone behind.
        advertised_scope_fingerprint = scope_fingerprint(
            tool_scope, self._tool_registry.list_specs(tool_scope)
        )
        # Every path that both observes and mutates a pending capability takes
        # the locks in this order.  It prevents a begin/cancel inversion while
        # keeping provider and tool I/O outside both locks.
        with self._pending_lock:
            with self._gate(thread_id):
                control = self._thread_control_locked(thread_id)
                if control.paused:
                    raise ThreadPausedError(thread_id)
                with self._session_factory() as session:
                    thread = self._repository.get_thread(session, thread_id)
                    if thread is None:
                        raise NotFoundError(f"Conversation Thread '{thread_id}' was not found.")
                    messages = self._repository.list_messages(session, thread_id)
                    if any(row.kind is ConversationMessageKind.PENDING_LLM_SAMPLING for row in messages):
                        raise ValidationError("LLM sampling is already pending for this Thread.")
                    if not messages or messages[-1].id != expected_frontier_id:
                        raise ValidationError("The requested LLM frontier is stale.")
                    if messages[-1].kind not in {
                        ConversationMessageKind.USER,
                        ConversationMessageKind.CLIENT_CONTROL,
                        ConversationMessageKind.TOOL_RESULT,
                    }:
                        raise ValidationError("The Thread frontier is not eligible for LLM sampling.")
                    row = ConversationMessageRow(
                        thread_id=thread_id,
                        sequence_index=len(messages),
                        kind=ConversationMessageKind.PENDING_LLM_SAMPLING,
                        created_at=_utc_now(),
                    )
                    self._repository.append_message(session, row)
                    session.commit()
                exchange = _PendingExchange(
                    pending_message_id=row.id,
                    thread_id=thread_id,
                    sequence_index=row.sequence_index,
                    frontier_message_id=expected_frontier_id,
                    root_user_message_id=self._primary_usage_root(messages),
                    scope=tool_scope,
                    scope_fingerprint=advertised_scope_fingerprint,
                )
                self._pending[row.id] = exchange
                return PendingSampling(
                    pending_message_id=row.id,
                    thread_id=thread_id,
                )

    def _stage_provider_response(
        self,
        pending_message_id: str,
        response: ProviderResponse,
        *,
        fq_model_key: str | None,
    ) -> PendingSampling:
        observation = self._primary_usage_observation(
            pending_message_id=pending_message_id,
            usage_payload=response.usage_payload,
            fq_model_key=fq_model_key,
        )
        if observation is not None:
            # The provider has already spent these tokens even if later
            # canonical-output validation rejects the response.  The journal
            # preserves that fact; only a closed canonical interaction makes
            # it eligible for a Chatbot overview.
            self._record_usage_observation(observation)
        self._accept_provider_response(pending_message_id)
        pending = self._stage_provider_output(pending_message_id, response.output_items)
        return pending

    def _stage_provider_output(
        self,
        pending_message_id: str,
        output_items: list[ProviderOutputItem],
    ) -> PendingSampling:
        if not output_items:
            raise ValidationError("LLM output is empty.")
        with self._pending_lock:
            exchange = self._current_exchange(pending_message_id)
            calls: dict[str, StagedToolCall] = {}
            assistant_seen = False
            for item in output_items:
                if isinstance(item, AssistantOutputItem):
                    if assistant_seen or item.is_empty:
                        raise ValidationError("LLM Assistant output is malformed.")
                    assistant_seen = True
                    continue
                if not isinstance(item, ToolCallOutputItem):
                    raise ValidationError("LLM output item is unsupported.")
                self._tool_registry.validate_call(
                    tool_name=item.tool_name,
                    provider_name=item.provider_name,
                    arguments=dict(item.arguments),
                    scope=exchange.scope,
                )
                call_id = generate_id()
                calls[call_id] = StagedToolCall(
                    pending_message_id=pending_message_id,
                    staged_call_id=call_id,
                    provider_call_id=item.provider_call_id,
                    tool_name=item.tool_name,
                    provider_name=item.provider_name,
                    arguments=dict(item.arguments),
                    scope_fingerprint=exchange.scope_fingerprint,
                )
            exchange.output_items = tuple(output_items)
            exchange.calls = calls
            return PendingSampling(
                pending_message_id=pending_message_id,
                thread_id=exchange.thread_id,
                staged_calls=tuple(calls.values()),
                has_assistant_output=assistant_seen,
            )

    def _finalize_exchange(self, pending_message_id: str) -> ConversationSnapshot:
        with self._pending_lock:
            exchange = self._current_exchange(pending_message_id)
            if exchange.calls and len(exchange.calls) != len(exchange.results):
                raise ValidationError("The complete terminal Tool Result set is required before finalization.")
        try:
            with self._pending_lock:
                exchange = self._current_exchange(pending_message_id)
                self._validate_exchange_result_budget(exchange)
                with self._gate(exchange.thread_id):
                    if not exchange.tool_execution_started and self._exchange_is_paused_locked(exchange):
                        self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)
                        raise ThreadPausedError(exchange.thread_id)
                    with self._session_factory() as session:
                        pending = self._repository.get_message(session, pending_message_id)
                        if pending is None or pending.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING:
                            raise ValidationError("The pending LLM exchange is no longer current.")
                        if pending.thread_id != exchange.thread_id:
                            raise ValidationError("The pending LLM exchange has an invalid Thread.")
                        session.delete(pending)
                        # The final Message reuses the placeholder's sequence slot.
                        # SQLite unique checks run per statement, so force the delete
                        # before staging its immutable replacements.
                        session.flush()
                        sequence = exchange.sequence_index
                        inserted = self._final_message_rows(exchange, sequence)
                        for row in inserted:
                            session.add(row)
                        thread = self._repository.get_thread(session, exchange.thread_id)
                        if thread is None:
                            raise NotFoundError(f"Conversation Thread '{exchange.thread_id}' was not found.")
                        thread.updated_at = _utc_now()
                        session.add(thread)
                        session.commit()
                        snapshot = ConversationSnapshot(
                            thread=thread,
                            messages=self._repository.list_messages(session, exchange.thread_id),
                        )
                    self._pending.pop(pending_message_id, None)
                    return snapshot
        except Exception:
            # Any failure after the exchange passed its public preconditions
            # must leave neither a durable placeholder nor an in-memory writer
            # capability.  Canonical state therefore returns to its client
            # frontier rather than retaining a recoverable pseudo-run.
            self.cancel_sampling(pending_message_id)
            raise

    def _final_message_rows(self, exchange: _PendingExchange, sequence: int) -> list[ConversationMessageRow]:
        rows: list[ConversationMessageRow] = []
        for item in exchange.output_items:
            if isinstance(item, AssistantOutputItem):
                rows.append(
                    ConversationMessageRow(
                        thread_id=exchange.thread_id,
                        sequence_index=sequence,
                        kind=ConversationMessageKind.ASSISTANT,
                        text=item.text,
                        reasoning=item.reasoning,
                        refusal=item.refusal,
                        created_at=_utc_now(),
                    )
                )
                sequence += 1
        for call in exchange.calls.values():
            rows.append(
                ConversationMessageRow(
                    id=call.staged_call_id,
                    thread_id=exchange.thread_id,
                    sequence_index=sequence,
                    kind=ConversationMessageKind.TOOL_CALL,
                    # ``tool_name`` is canonical registry identity; the
                    # provider-facing name is adapter pairing data needed for
                    # faithful replay and belongs in this immutable payload.
                    content_payload={
                        "tool_name": call.tool_name,
                        "provider_name": call.provider_name,
                    },
                    provider_call_id=call.provider_call_id,
                    tool_id=call.tool_name,
                    contract_version="v1",
                    arguments_payload=dict(call.arguments),
                    scope_fingerprint=call.scope_fingerprint,
                    created_at=_utc_now(),
                )
            )
            sequence += 1
        for call in exchange.calls.values():
            result = exchange.results[call.staged_call_id]
            rows.append(
                ConversationMessageRow(
                    thread_id=exchange.thread_id,
                    sequence_index=sequence,
                    kind=ConversationMessageKind.TOOL_RESULT,
                    content_payload={"tool_name": call.tool_name},
                    tool_call_message_id=call.staged_call_id,
                    result_status=ConversationToolResultStatus(result.status),
                    value_payload=result.value,
                    # New failures are their own typed canonical value.  Keep
                    # this legacy column empty rather than duplicating a
                    # competing failure summary.
                    error_summary=None,
                    created_at=_utc_now(),
                )
            )
            sequence += 1
        if not rows:
            raise ValidationError("LLM output produced no final Message.")
        return rows

    def _complete(
        self,
        *,
        provider: AgentProvider | None,
        fq_model_key: str | None,
        messages: list[ProviderMessage],
        tool_scope: ToolScope,
        retry_callback: Callable[[LLMRetryEvent], None] | None,
        before_provider_request: Callable[[], None] | None = None,
    ) -> ProviderResponse:
        specs = self._tool_registry.list_specs(tool_scope)
        if provider is not None:
            if before_provider_request is not None:
                before_provider_request()
            return provider.complete(messages, specs)
        arguments = {
            "fq_model_key": fq_model_key,
            "messages": messages,
            "tools": specs,
            "retry_callback": retry_callback,
            "before_provider_request": before_provider_request,
        }
        return self._require_llm_service().complete(**arguments)

    def is_initial_title_eligible(self, snapshot: ConversationSnapshot) -> bool:
        """Whether an append may establish this Thread's initial title."""

        final_messages = [
            message
            for message in snapshot.messages
            if message.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING
        ]
        return _is_blank_thread_title(snapshot.thread.title) and not final_messages

    def _automatic_initial_thread_title(self, snapshot: ConversationSnapshot) -> str:
        fallback = self._fallback_initial_thread_title(snapshot)
        if not self.has_thread_title_model():
            return fallback
        try:
            title = self._model_thread_title(
                self._initial_thread_title_prompt(snapshot),
                thread_id=snapshot.thread.id,
            )
            if title is None:
                raise ValidationError("Thread title model returned an empty title.")
            return title
        except ThreadPausedError:
            raise
        except Exception as exc:
            LOGGER.warning("Initial Thread title model failed; using deterministic fallback: %s", exc)
            return fallback

    def _model_thread_title(self, prompt: str, *, thread_id: str) -> str | None:
        response = self._complete_thread_title(
            [
                ProviderMessage(role="system", content=THREAD_TITLE_SYSTEM_PROMPT),
                ProviderMessage(role="user", content=prompt),
            ],
            thread_id=thread_id,
        )
        return _sanitize_thread_title(_assistant_response_text(response))

    def _complete_thread_title(
        self,
        messages: list[ProviderMessage],
        *,
        thread_id: str,
    ) -> ProviderResponse:
        fq_model_key = self._thread_title_fq_model_key()
        if fq_model_key is None:
            raise ValidationError("Thread title model is not configured.")
        gateway = self._require_llm_service()
        if isinstance(gateway, LLMService):
            response = gateway.complete(
                fq_model_key=fq_model_key,
                messages=messages,
                tools=[],
                before_provider_request=lambda: self._admit_auxiliary_provider_request(thread_id),
            )
        else:
            # Tests and third-party in-process gateways predating the
            # per-attempt admission hook retain their narrow ``complete``
            # signature.  They still receive one admission before I/O; the
            # production LLMService performs it before every retry attempt.
            self._admit_auxiliary_provider_request(thread_id)
            response = gateway.complete(
                fq_model_key=fq_model_key,
                messages=messages,
                tools=[],
            )
        self._record_auxiliary_usage(
            operation="thread_title",
            thread_id=thread_id,
            usage_payload=response.usage_payload,
            fq_model_key=fq_model_key,
        )
        # Usage records the completed provider request even when a Thread
        # pause won while it was in flight.  Its response, however, may not
        # produce a title proposal or canonical metadata mutation afterward.
        self._accept_auxiliary_provider_response(thread_id)
        return response

    def _thread_title_fq_model_key(self) -> str | None:
        if self._llm_service is None:
            return None
        value = self._llm_service.thread_title_fq_model_key()
        if not isinstance(value, str):
            return None
        return value.strip() or None

    @staticmethod
    def _is_initial_title_target(snapshot: ConversationSnapshot, first_user_message_id: str) -> bool:
        final_messages = [
            message
            for message in snapshot.messages
            if message.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING
        ]
        return (
            _is_blank_thread_title(snapshot.thread.title)
            and len(final_messages) == 1
            and final_messages[0].id == first_user_message_id
            and final_messages[0].kind is ConversationMessageKind.USER
        )

    @staticmethod
    def _initial_thread_title_prompt(snapshot: ConversationSnapshot) -> str:
        first_message = next(
            (
                message
                for message in snapshot.messages
                if message.kind is ConversationMessageKind.USER
            ),
            None,
        )
        content = (
            blocks_to_markdown(blocks_from_payload(first_message.content_payload))
            if first_message is not None
            else ""
        )
        return "Create a short title for this first user message.\n\nMessage:\n" + content

    @staticmethod
    def _thread_title_snapshot_prompt(snapshot: ConversationSnapshot) -> str:
        messages = [
            {
                "kind": message.kind.value,
                "text": _thread_title_message_text(message),
            }
            for message in snapshot.messages
            if message.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING
        ]
        payload = {
            "thread_id": snapshot.thread.id,
            "current_title": snapshot.thread.title,
            "messages": messages,
        }
        return (
            "Create a short title for this full conversation thread. "
            "Use all persisted messages in the JSON payload.\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def _fallback_initial_thread_title(snapshot: ConversationSnapshot) -> str:
        first_message = next(
            (
                message
                for message in snapshot.messages
                if message.kind is ConversationMessageKind.USER
            ),
            None,
        )
        if first_message is None:
            return "New analysis"
        for block in blocks_from_payload(first_message.content_payload):
            if isinstance(block, (TextBlock, MarkdownBlock)):
                title = _sanitize_thread_title(block.text)
            elif isinstance(block, DatasetBlock):
                title = _sanitize_thread_title(block.name)
            elif isinstance(block, SourceAttachmentBlock):
                title = _sanitize_thread_title(_file_stem(block.file_name))
            else:
                title = None
            if title is not None:
                return title
        return "New analysis"

    def _provider_messages(self, snapshot: ConversationSnapshot) -> list[ProviderMessage]:
        rows: list[ProviderMessage] = [ProviderMessage(role="system", content=snapshot.thread.system_prompt)]
        if self._context_messages_provider is not None:
            # Composition injects provider-neutral contextual instructions.
            # They are derived from finalized Messages only and never mutate
            # the canonical conversation or introduce a Harness dependency.
            rows.extend(self._context_messages_provider(snapshot))
        messages = [row for row in snapshot.messages if row.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING]
        index = 0
        while index < len(messages):
            row = messages[index]
            if row.kind is ConversationMessageKind.USER:
                blocks = blocks_from_payload(row.content_payload)
                rows.append(
                    ProviderMessage(
                        role="user",
                        content="",
                        content_blocks=list(blocks),
                        source_message_id=row.id,
                    )
                )
            elif row.kind is ConversationMessageKind.CLIENT_CONTROL:
                blocks = blocks_from_payload(row.content_payload)
                rows.append(
                    ProviderMessage(
                        role="user",
                        content="",
                        content_blocks=list(blocks),
                        source_message_id=row.id,
                    )
                )
            elif row.kind is ConversationMessageKind.ASSISTANT:
                calls: list[ConversationMessageRow] = []
                index += 1
                while index < len(messages) and messages[index].kind is ConversationMessageKind.TOOL_CALL:
                    calls.append(messages[index])
                    index += 1
                payload: dict[str, Any] = {}
                if row.reasoning:
                    payload["reasoning_content"] = row.reasoning
                if row.refusal:
                    payload["refusal"] = row.refusal
                if calls:
                    payload["tool_calls"] = [self._provider_call_payload(call) for call in calls]
                blocks = blocks_from_payload(row.content_payload)
                rows.append(
                    ProviderMessage(
                        role="assistant",
                        content=row.text or "",
                        content_blocks=list(blocks),
                        provider_payload=payload,
                        source_message_id=row.id,
                    )
                )
                continue
            elif row.kind is ConversationMessageKind.TOOL_CALL:
                calls = []
                while index < len(messages) and messages[index].kind is ConversationMessageKind.TOOL_CALL:
                    calls.append(messages[index])
                    index += 1
                rows.append(
                    ProviderMessage(
                        role="assistant",
                        content="",
                        provider_payload={"tool_calls": [self._provider_call_payload(call) for call in calls]},
                        source_message_id=calls[0].id,
                    )
                )
                continue
            elif row.kind is ConversationMessageKind.TOOL_RESULT:
                call = next((candidate for candidate in messages if candidate.id == row.tool_call_message_id), None)
                if call is not None:
                    rows.append(
                        ProviderMessage(
                            role="tool",
                            tool_result_value=self._canonical_tool_result_value(row),
                            provider_payload={"tool_call_id": call.provider_call_id or ""},
                            source_message_id=row.id,
                        )
                    )
            index += 1
        return rows

    def _primary_usage_observation(
        self,
        *,
        pending_message_id: str,
        usage_payload: dict[str, Any] | None,
        fq_model_key: str | None,
    ) -> LLMUsageObservation | None:
        usage = LLMTokenUsage.from_payload(usage_payload)
        if usage is None:
            return None
        with self._pending_lock:
            exchange = self._pending.get(pending_message_id)
            if exchange is None:
                return None
            return LLMUsageObservation(
                operation="primary",
                usage=usage,
                thread_id=exchange.thread_id,
                root_user_message_id=exchange.root_user_message_id,
                frontier_message_id=exchange.frontier_message_id,
                pending_message_id=exchange.pending_message_id,
                fq_model_key=fq_model_key,
            )

    def _record_auxiliary_usage(
        self,
        *,
        operation: str,
        thread_id: str,
        usage_payload: dict[str, Any] | None,
        fq_model_key: str | None,
    ) -> None:
        usage = LLMTokenUsage.from_payload(usage_payload)
        if usage is None:
            return
        self._record_usage_observation(
            LLMUsageObservation(
                operation=operation,
                usage=usage,
                thread_id=thread_id,
                fq_model_key=fq_model_key,
            )
        )

    def _record_usage_observation(self, observation: LLMUsageObservation) -> None:
        try:
            self._usage_observability.record_llm_usage(observation)
        except Exception as exc:
            LOGGER.warning("LLM usage observability write failed: %s", exc.__class__.__name__)

    @staticmethod
    def _primary_usage_root(messages: list[ConversationMessageRow]) -> str | None:
        if not messages:
            return None
        frontier = messages[-1]
        if frontier.kind is ConversationMessageKind.USER:
            return frontier.id
        if frontier.kind is not ConversationMessageKind.TOOL_RESULT:
            return None
        for row in reversed(messages[:-1]):
            if row.kind is ConversationMessageKind.USER:
                return row.id
        return None

    @staticmethod
    def _completed_user_interactions(
        messages: list[ConversationMessageRow],
    ) -> list[tuple[ConversationMessageRow, ConversationMessageRow]]:
        """Find terminal LLM emissions without inventing a durable Turn."""

        rows = sorted(
            (
                row
                for row in messages
                if row.kind is not ConversationMessageKind.PENDING_LLM_SAMPLING
            ),
            key=lambda row: row.sequence_index,
        )
        completed: list[tuple[ConversationMessageRow, ConversationMessageRow]] = []
        active_user: ConversationMessageRow | None = None
        index = 0
        llm_kinds = {ConversationMessageKind.ASSISTANT, ConversationMessageKind.TOOL_CALL}
        while index < len(rows):
            row = rows[index]
            if row.kind is ConversationMessageKind.USER:
                active_user = row
                index += 1
                continue
            if row.kind not in llm_kinds:
                index += 1
                continue
            emission: list[ConversationMessageRow] = []
            while index < len(rows) and rows[index].kind in llm_kinds:
                emission.append(rows[index])
                index += 1
            has_tool_calls = any(item.kind is ConversationMessageKind.TOOL_CALL for item in emission)
            terminal = next(
                (item for item in reversed(emission) if item.kind is ConversationMessageKind.ASSISTANT),
                None,
            )
            if active_user is not None and not has_tool_calls and terminal is not None:
                completed.append((active_user, terminal))
                active_user = None
        return completed

    def _validate_exchange_result_budget(self, exchange: _PendingExchange) -> None:
        total = 0
        for result in exchange.results.values():
            envelope = {
                "status": result.status,
                "value": result.value,
            }
            total += len(canonical_json_bytes(envelope))
        if total > MAX_EXCHANGE_RESULT_BYTES:
            raise ValidationError("The staged Tool Result exchange exceeds its byte limit.")

    @staticmethod
    def _validate_user_append_messages(
        messages: list[ConversationMessageRow],
        expected_frontier_id: str | None,
        *,
        allow_paused_tool_result: bool = False,
    ) -> None:
        if any(row.kind is ConversationMessageKind.PENDING_LLM_SAMPLING for row in messages):
            raise ValidationError("Cannot append a User Message while LLM sampling is pending.")
        if not messages:
            if expected_frontier_id is not None:
                raise ValidationError("The requested User frontier is stale.")
            return
        tail = messages[-1]
        if expected_frontier_id is not None and tail.id != expected_frontier_id:
            raise ValidationError("The requested User frontier is stale.")
        if tail.kind in {
            ConversationMessageKind.USER,
            ConversationMessageKind.CLIENT_CONTROL,
        }:
            raise ValidationError("The existing Client frontier must be sampled before another User Message.")
        if tail.kind is ConversationMessageKind.TOOL_RESULT and not allow_paused_tool_result:
            raise ValidationError("The existing Client frontier must be sampled before another User Message.")

    def _admit_provider_request(self, pending_message_id: str) -> None:
        """Linearize one provider attempt against the runtime Thread pause."""

        with self._pending_lock:
            exchange = self._current_exchange(pending_message_id)
            with self._gate(exchange.thread_id):
                if self._exchange_is_paused_locked(exchange):
                    self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)
                    raise ThreadPausedError(exchange.thread_id)

    def _accept_provider_response(self, pending_message_id: str) -> None:
        """Discard a response that returned after a Thread pause won."""

        with self._pending_lock:
            exchange = self._current_exchange(pending_message_id)
            with self._gate(exchange.thread_id):
                if self._exchange_is_paused_locked(exchange):
                    self._discard_pending_locked(exchange.thread_id, expected_pending_id=pending_message_id)
                    raise ThreadPausedError(exchange.thread_id)

    def _accept_auxiliary_provider_response(self, thread_id: str) -> None:
        """Reject metadata-provider output returned after a Thread pause."""

        with self._pending_lock:
            with self._gate(thread_id):
                if self._thread_control_locked(thread_id).paused:
                    raise ThreadPausedError(thread_id)

    def _admit_auxiliary_provider_request(self, thread_id: str) -> None:
        """Give metadata LLM work the same Thread-pause admission rule."""

        with self._pending_lock:
            with self._gate(thread_id):
                if self._thread_control_locked(thread_id).paused:
                    raise ThreadPausedError(thread_id)

    def _exchange_is_paused_locked(self, exchange: _PendingExchange) -> bool:
        return self._thread_control_locked(exchange.thread_id).paused

    def _thread_control_locked(self, thread_id: str) -> _ThreadControl:
        """Return a Thread control while ``_pending_lock`` is held."""

        return self._thread_controls.setdefault(thread_id, _ThreadControl())

    def _discard_pending_locked(self, thread_id: str, expected_pending_id: str | None) -> None:
        matching_ids = {
            pending_id
            for pending_id, exchange in self._pending.items()
            if exchange.thread_id == thread_id
            and (expected_pending_id is None or pending_id == expected_pending_id)
        }
        committed = False
        try:
            with self._session_factory() as session:
                pending_rows = self._repository.list_pending(session, thread_id)
                for row in pending_rows:
                    if expected_pending_id is not None and row.id != expected_pending_id:
                        continue
                    matching_ids.add(row.id)
                    session.delete(row)
                session.commit()
                committed = True
        finally:
            if committed:
                # A finalization can commit before reading the final snapshot
                # fails; there is then no DB placeholder left to discover, but
                # the memory capability must still be revoked exactly once.
                # Conversely, a failed deletion transaction retains the live
                # capability so the caller sees the database failure instead
                # of being left with an unreachable durable placeholder.
                for pending_id in matching_ids:
                    exchange = self._pending.pop(pending_id, None)
                    if exchange is not None:
                        exchange.cancelled = True

    def _current_exchange(self, pending_message_id: str) -> _PendingExchange:
        exchange = self._pending.get(pending_message_id)
        if exchange is None or exchange.cancelled:
            raise ValidationError("The pending LLM exchange is no longer current.")
        return exchange

    def _gate_for(self, thread_id: str) -> threading.RLock:
        with self._gates_lock:
            return self._thread_gates.setdefault(thread_id, threading.RLock())

    @contextmanager
    def _gate(self, thread_id: str):
        gate = self._gate_for(thread_id)
        with gate:
            yield

    def _provider_call_payload(self, call: ConversationMessageRow) -> dict[str, Any]:
        payload = call.content_payload if isinstance(call.content_payload, dict) else {}
        raw_provider_name = payload.get("provider_name")
        if isinstance(raw_provider_name, str) and raw_provider_name.strip():
            provider_name = raw_provider_name.strip()
        else:
            # v14-to-v15 rows written before the provider-name preservation
            # repair contain only the canonical registry name.  The LLM-owned
            # registry is the only compatible fallback authority; new rows
            # always persist the provider-facing name above.
            tool_name = (call.tool_id or "").strip()
            try:
                provider_name = self._tool_registry.get(tool_name).spec.provider_name
            except ValidationError:
                provider_name = tool_name
        return {
            "id": call.provider_call_id or "",
            "type": "function",
            "function": {
                "name": provider_name,
                "arguments": json.dumps(call.arguments_payload or {}, ensure_ascii=False, separators=(",", ":")),
            },
        }

    @staticmethod
    def _canonical_tool_result_value(result: ConversationMessageRow) -> Any:
        status = getattr(result, "result_status", None)
        failed = status is ConversationToolResultStatus.FAILED or getattr(status, "value", status) == "failed"
        return canonical_tool_result_value(
            value=result.value_payload,
            failed=failed,
            legacy_error_summary=result.error_summary,
        )

    def _require_llm_service(self) -> LLMService:
        if self._llm_service is None:
            raise ValidationError("LLM Conversation Service has no model gateway.")
        return self._llm_service


def _assistant_response_text(response: ProviderResponse) -> str:
    return "\n".join(
        item.text.strip()
        for item in response.output_items
        if isinstance(item, AssistantOutputItem) and item.text and item.text.strip()
    )


def _thread_title_message_text(message: ConversationMessageRow) -> str:
    if message.kind in {ConversationMessageKind.USER, ConversationMessageKind.CLIENT_CONTROL}:
        return blocks_to_markdown(blocks_from_payload(message.content_payload))
    if message.kind is ConversationMessageKind.ASSISTANT:
        return "\n".join(value for value in (message.text, message.refusal) if value)
    if message.kind is ConversationMessageKind.TOOL_CALL:
        return f"Tool call: {message.tool_id or ''}".strip()
    if message.kind is ConversationMessageKind.TOOL_RESULT:
        return message.error_summary or "Tool result"
    return ""


def _file_stem(file_name: str | None) -> str:
    return Path(file_name).stem if file_name else ""


def _is_blank_thread_title(value: str | None) -> bool:
    return not value or not value.strip()


def _sanitize_thread_title(raw: str) -> str | None:
    title = re.sub(r"\s+", " ", raw).strip().lstrip("#-*• ").strip()
    for prefix in ("Title:", "title:", "标题：", "标题:"):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
            break
    title = title.strip("\"'`“”‘’").rstrip(".。!！?？").strip()
    return (title[:THREAD_TITLE_MAX_LENGTH].rstrip() or None) if title else None
