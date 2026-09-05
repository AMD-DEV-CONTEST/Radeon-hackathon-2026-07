"""Live Agent coordination over the canonical LLM Conversation boundary.

The Harness owns application work around a conversation: attachment import,
stream/event projection and the decision to continue sampling after a Tool
Result.  It neither persists conversation state nor dispatches tools.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from queue import SimpleQueue
from typing import Any, Iterator
from uuid import uuid4

from sqlmodel import Field, SQLModel

from ...exceptions import NotFoundError, ValidationError
from ..dataset_service import DatasetService, RegisterDatasetInput
from ..llm import (
    AppendUserMessageInput,
    CanonicalMessageBlock,
    ConversationLiveEvent,
    ConversationSnapshot,
    ConversationUsageOverview,
    CreateConversationThreadInput,
    DatasetBlock,
    LLMConversationService,
    PendingSampling,
    SubmissionClaim,
    ThreadPausedError,
    TextBlock,
    blocks_from_payload,
)
from ..llm.providers import AgentProvider, LLMRetryEvent
from ..llm.service import LLMModelOption, LLMService
from ..llm.tooling import ToolScope
from .chatbot_events import (
    ChatbotEvent,
    ChatbotEventAuthor,
    ChatbotEventKind,
    ChatbotEventStatus,
    build_activity_chatbot_event,
    build_llm_connection_chatbot_event,
    build_thinking_chatbot_event,
    enrich_chatbot_events_with_source_attachments,
    project_chatbot_events,
)
from .tool_presentations import tool_presentation_for_name

LOGGER = logging.getLogger(__name__)


class DatasetAttachmentInput(SQLModel):
    dataset_id: str
    name: str
    row_count: int
    column_count: int


class SourceAttachmentInput(SQLModel):
    """Transient UI input for a source file that has not yet been imported."""

    file_path: str


class SubmitUserTurnInput(SQLModel):
    thread_id: str | None = None
    text: str
    dataset_attachments: list[DatasetAttachmentInput] = Field(default_factory=list)
    source_attachments: list[SourceAttachmentInput] = Field(default_factory=list)
    fq_model_key: str | None = None
    interface_locale: str | None = None
    client_submission_id: str | None = None


class AttachmentImportStatus(StrEnum):
    """Transient source-materialization state for one Composer attachment."""

    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True)
class AttachmentImportProgress:
    """Path-free source-materialization state within the stream envelope."""

    source_index: int
    status: AttachmentImportStatus


@dataclass(frozen=True)
class _InitialTitleTask:
    """A non-durable title side task whose outcome is safe to drop."""

    completed: threading.Event
    outcomes: SimpleQueue[ConversationSnapshot | None]

    def result(self) -> ConversationSnapshot | None:
        self.completed.wait()
        return self.outcomes.get()


@dataclass(frozen=True)
class AgentHarnessStreamEvent:
    kind: str
    thread_id: str | None = None
    pending_message_id: str | None = None
    client_submission_id: str | None = None
    attachment_import: AttachmentImportProgress | None = None
    chatbot_event: ChatbotEvent | None = None
    chatbot_events: list[ChatbotEvent] | None = None
    snapshot: ConversationSnapshot | None = None
    is_final: bool = False


class AgentHarnessService:
    """Thin, process-local coordination facade for the Agent UI."""

    def __init__(
        self,
        *,
        conversation_service: LLMConversationService,
        tool_presentation_registry: Any | None = None,
        provider: AgentProvider | None = None,
        llm_service: LLMService | None = None,
        dataset_service: DatasetService | None = None,
        tool_name_scope_provider: Callable[[ConversationSnapshot], tuple[str, ...] | None] | None = None,
    ) -> None:
        self._conversation_service = conversation_service
        self._tool_presentation_registry = tool_presentation_registry
        self._provider = provider
        self._llm_service = llm_service
        self._dataset_service = dataset_service
        # The composition root may project a bounded advertised tool set from
        # finalized Conversation state (for example, active Agent Skills).
        # It never receives a writer capability and the Conversation service
        # still freezes/validates the resulting scope for each provider call.
        self._tool_name_scope_provider = tool_name_scope_provider
        self._cancel_events: dict[str, threading.Event] = {}
        self._pending_threads: dict[str, str] = {}
        # The local maps are only a live callback aid.  No helper recurses
        # through this lock; the Conversation service remains the sole source
        # of truth for whether a pending Message exists.
        self._cancel_lock = threading.Lock()

    def create_thread(
        self,
        title: str | None = None,
        fq_model_key: str | None = None,
        interface_locale: str | None = None,
    ) -> ConversationSnapshot:
        selected = self._resolve_fq_model_key(fq_model_key, None)
        return self._conversation_service.create_thread(
            CreateConversationThreadInput(
                title=title,
                interface_locale=interface_locale,
                selected_fq_model_key=selected,
            )
        )

    def list_threads(self):
        return self._conversation_service.list_threads()

    def rename_thread(self, thread_id: str, title: str | None) -> ConversationSnapshot:
        return self._conversation_service.rename_thread(thread_id, title)

    def delete_thread(self, thread_id: str) -> None:
        self._conversation_service.delete_thread(thread_id)

    def get_thread_snapshot(self, thread_id: str) -> ConversationSnapshot:
        return self._conversation_service.get_thread_snapshot(thread_id)

    def list_llm_model_options(self) -> list[LLMModelOption]:
        return self._conversation_service.model_options() if self._llm_service is not None else []

    def default_fq_model_key(self) -> str | None:
        return self._conversation_service.default_fq_model_key() if self._llm_service is not None else None

    def set_thread_model(self, thread_id: str, fq_model_key: str) -> ConversationSnapshot:
        return self._conversation_service.set_thread_model(thread_id, fq_model_key)

    def project_chatbot_events(self, snapshot: ConversationSnapshot) -> list[ChatbotEvent]:
        canonical_events = project_chatbot_events(snapshot, tool_presentation_lookup=self._tool_presentation)
        canonical_events = enrich_chatbot_events_with_source_attachments(
            snapshot,
            canonical_events,
            self._resolve_dataset_source_presentation,
        )
        usage_by_terminal = {
            overview.terminal_llm_message_id: _usage_chatbot_event(overview)
            for overview in self._conversation_service.usage_overviews(snapshot)
        }
        events: list[ChatbotEvent] = []
        for event in canonical_events:
            events.append(event)
            usage_event = usage_by_terminal.pop(event.id, None)
            if usage_event is not None:
                events.append(usage_event)
        return events

    def set_provider(self, provider: AgentProvider | None) -> None:
        self._provider = provider

    def has_thread_title_provider(self) -> bool:
        return self._conversation_service.has_thread_title_model()

    def generate_thread_title(self, thread_id: str) -> str:
        return self._conversation_service.generate_thread_title(thread_id)

    def pause_thread(self, thread_id: str) -> None:
        """Pause future sampling for one Thread without cancelling a Tool.

        Pending-message cancellation remains an internal cleanup capability.  A
        user-facing Stop targets the Thread because the pending Message id is
        only a provisional correlation and may already have been replaced by a
        terminal Tool Result before the next sample is admitted.
        """

        self._conversation_service.pause_thread(thread_id)

    def is_thread_paused(self, thread_id: str) -> bool:
        checker = getattr(self._conversation_service, "is_thread_paused", None)
        return bool(checker(thread_id)) if callable(checker) else False

    def cancel_sampling(self, pending_message_id: str) -> None:
        with self._cancel_lock:
            event = self._cancel_events.get(pending_message_id)
            if event is not None:
                event.set()
        self._conversation_service.cancel_sampling(pending_message_id)

    def submit_user_turn(self, input_data: SubmitUserTurnInput) -> ConversationSnapshot:
        final: ConversationSnapshot | None = None
        for event in self.submit_user_turn_stream(input_data):
            if event.snapshot is not None:
                final = event.snapshot
        if final is None:
            raise ValidationError("LLM sampling did not produce a conversation snapshot.")
        return final

    def submit_user_turn_stream(self, input_data: SubmitUserTurnInput) -> Iterator[AgentHarnessStreamEvent]:
        self._validate_submission(input_data)
        thread_id = input_data.thread_id
        if thread_id is None:
            thread_id = self.create_thread(
                fq_model_key=input_data.fq_model_key,
                interface_locale=input_data.interface_locale,
            ).thread.id
        else:
            snapshot = self.get_thread_snapshot(thread_id)
            selected = self._resolve_fq_model_key(input_data.fq_model_key, snapshot.thread.selected_fq_model_key)
            if selected and selected != snapshot.thread.selected_fq_model_key:
                self._conversation_service.set_thread_model(thread_id, selected)

        submission_id = (input_data.client_submission_id or uuid4().hex).strip()
        claim = self._conversation_service.claim_user_submission(
            thread_id=thread_id,
            expected_frontier_id=self._frontier_id(thread_id),
            client_submission_id=submission_id,
        )
        existing_message_id = getattr(claim, "existing_message_id", None)
        if existing_message_id:
            # A retried client acknowledgement is not a new UserMessage.  Do
            # not import attachments, clear a Thread pause, or re-sample the
            # old frontier; simply project the already-canonical snapshot.
            try:
                snapshot = self.get_thread_snapshot(thread_id)
                yield AgentHarnessStreamEvent(
                    kind="snapshot",
                    thread_id=thread_id,
                    client_submission_id=submission_id,
                    snapshot=snapshot,
                    chatbot_events=self.project_chatbot_events(snapshot),
                    is_final=True,
                )
            finally:
                self._conversation_service.release_user_submission_claim(claim)
            return
        try:
            imported: list[DatasetAttachmentInput] = []
            for source_index, source in enumerate(input_data.source_attachments):
                yield AgentHarnessStreamEvent(
                    kind="attachment_import",
                    thread_id=thread_id,
                    client_submission_id=submission_id,
                    attachment_import=AttachmentImportProgress(
                        source_index=source_index,
                        status=AttachmentImportStatus.PENDING,
                    ),
                )
                try:
                    imported.extend(self._import_source_attachment(source))
                except Exception:
                    # The event is intentionally path-free.  The UI already
                    # owns the local path and maps this index back to its tag.
                    yield AgentHarnessStreamEvent(
                        kind="attachment_import",
                        thread_id=thread_id,
                        client_submission_id=submission_id,
                        attachment_import=AttachmentImportProgress(
                            source_index=source_index,
                            status=AttachmentImportStatus.FAILED,
                        ),
                    )
                    raise
            blocks = self._user_content_blocks(
                input_data.text,
                [*input_data.dataset_attachments, *imported],
            )
            snapshot = self._conversation_service.append_user_message(
                AppendUserMessageInput(
                    thread_id=thread_id,
                    client_submission_id=submission_id,
                    content_blocks=blocks,
                ),
                expected_frontier_id=claim.expected_frontier_id,
            )
        finally:
            self._conversation_service.release_user_submission_claim(claim)

        yield AgentHarnessStreamEvent(
            kind="snapshot",
            thread_id=thread_id,
            client_submission_id=submission_id,
            snapshot=snapshot,
            chatbot_events=self.project_chatbot_events(snapshot),
        )
        title_task: _InitialTitleTask | None = None
        first_user_message_id = snapshot.messages[-1].id
        for event in self._sample_until_client_frontier(
            thread_id,
            first_user_message_id,
            client_submission_id=submission_id,
        ):
            yield event
            # Resuming after the real Thinking event guarantees that the
            # append acknowledgement and pending sampling Message already
            # exist before title-model I/O starts.
            if title_task is None and claim.initial_title_eligible and event.kind == "thinking":
                title_task = self._start_initial_title_task(
                    claim=claim,
                    first_user_message_id=first_user_message_id,
                    appended_snapshot=snapshot,
                )
        if title_task is not None:
            if title_task.result() is not None:
                # Title I/O may finish while the primary pending placeholder
                # still exists.  Re-read after the terminal sampling event so
                # a metadata update never replays that provisional Message.
                titled_snapshot = self._snapshot_if_thread_exists(thread_id)
            else:
                titled_snapshot = None
            if titled_snapshot is not None:
                yield AgentHarnessStreamEvent(
                    kind="title",
                    thread_id=thread_id,
                    snapshot=titled_snapshot,
                    is_final=True,
                )

    def _sample_until_client_frontier(
        self,
        thread_id: str,
        frontier_id: str,
        *,
        client_submission_id: str | None = None,
    ) -> Iterator[AgentHarnessStreamEvent]:
        while True:
            # A Thread pause is a live admission barrier.  The current
            # exchange, if any, is allowed to settle; a paused loop must never
            # start another provider request merely because an old Tool Result
            # snapshot was already yielded.
            if self.is_thread_paused(thread_id):
                yield from self._paused_pending_events(
                    thread_id,
                    pending_message_id=None,
                    client_submission_id=client_submission_id,
                )
                return
            scope = self._sampling_tool_scope(thread_id)
            pending: PendingSampling | None = None
            active_pending_id: str | None = None
            try:
                if self._provider is not None:
                    retry_events: list[dict[str, Any]] = []
                    started = self._conversation_service.begin_sampling(
                        thread_id=thread_id,
                        expected_frontier_id=frontier_id,
                        tool_scope=scope,
                    )
                    active_pending_id = started.pending_message_id
                    self._register_cancel_event(active_pending_id, thread_id)
                    yield from self._sampling_started_events(
                        thread_id,
                        active_pending_id,
                        retry_events,
                        client_submission_id=client_submission_id,
                    )
                    try:
                        def record_retry(
                            retry: LLMRetryEvent,
                            event_log: list[dict[str, Any]] = retry_events,
                        ) -> None:
                            event_log.append(_retry_payload(retry))

                        pending = self._conversation_service.complete_pending_sampling(
                            pending_message_id=active_pending_id,
                            provider=self._provider,
                            retry_callback=record_retry,
                        )
                    except ThreadPausedError:
                        yield from self._paused_pending_events(
                            thread_id,
                            pending_message_id=active_pending_id,
                            client_submission_id=client_submission_id,
                        )
                        return
                    except ValidationError:
                        if self._cancel_requested(active_pending_id)():
                            yield from self._cancelled_pending_events(
                                thread_id,
                                active_pending_id,
                                client_submission_id=client_submission_id,
                            )
                            return
                        raise
                    if retry_events:
                        yield AgentHarnessStreamEvent(
                            kind="connection",
                            thread_id=thread_id,
                            pending_message_id=active_pending_id,
                            client_submission_id=client_submission_id,
                            chatbot_event=build_llm_connection_chatbot_event(
                                sampling_id=active_pending_id, retry_events=retry_events,
                            ),
                        )
                else:
                    try:
                        for live in self._conversation_service.sample_existing_frontier_stream(
                            thread_id=thread_id,
                            expected_frontier_id=frontier_id,
                            tool_scope=scope,
                        ):
                            if isinstance(live, ConversationLiveEvent) and live.kind == "sampling_started":
                                active_pending_id = live.pending_message_id
                                self._register_cancel_event(active_pending_id, thread_id)
                            if isinstance(live, PendingSampling):
                                pending = live
                                continue
                            yield from self._project_live_event(
                                live,
                                thread_id=thread_id,
                                client_submission_id=client_submission_id,
                            )
                    except ThreadPausedError:
                        yield from self._paused_pending_events(
                            thread_id,
                            pending_message_id=active_pending_id,
                            client_submission_id=client_submission_id,
                        )
                        return
                    except ValidationError:
                        if active_pending_id is not None and self._cancel_requested(active_pending_id)():
                            yield from self._cancelled_pending_events(
                                thread_id,
                                active_pending_id,
                                client_submission_id=client_submission_id,
                            )
                            return
                        raise
                if pending is None:
                    raise ValidationError("LLM sampling did not complete its pending exchange.")

                active_pending_id = pending.pending_message_id
                self._register_cancel_event(active_pending_id, thread_id)
                if not pending.staged_calls:
                    snapshot = self._conversation_service.finalize_pending_assistant(active_pending_id)
                    self._clear_cancel_event(active_pending_id)
                    active_pending_id = None
                    yield AgentHarnessStreamEvent(
                        kind="snapshot",
                        thread_id=thread_id,
                        pending_message_id=pending.pending_message_id,
                        client_submission_id=client_submission_id,
                        snapshot=snapshot, chatbot_events=self.project_chatbot_events(snapshot), is_final=True,
                    )
                    return
                snapshot: ConversationSnapshot | None = None
                for call in pending.staged_calls:
                    snapshot = self._conversation_service.invoke_staged_tool(
                        pending_message_id=active_pending_id,
                        staged_call_message_id=call.staged_call_id,
                        cancel_requested=self._cancel_requested(active_pending_id),
                    )
                self._clear_cancel_event(active_pending_id)
                active_pending_id = None
                if snapshot is None:
                    # A cancellation removes the pending placeholder and is intentionally not recoverable.
                    snapshot = self._snapshot_if_thread_exists(thread_id)
                    if snapshot is None:
                        return
                    yield AgentHarnessStreamEvent(
                        kind="snapshot",
                        thread_id=thread_id,
                        pending_message_id=pending.pending_message_id,
                        client_submission_id=client_submission_id,
                        snapshot=snapshot, chatbot_events=self.project_chatbot_events(snapshot), is_final=True,
                    )
                    return
                paused = self.is_thread_paused(thread_id)
                yield AgentHarnessStreamEvent(
                    kind="snapshot",
                    thread_id=thread_id,
                    pending_message_id=pending.pending_message_id,
                    client_submission_id=client_submission_id,
                    snapshot=snapshot, chatbot_events=self.project_chatbot_events(snapshot),
                    is_final=paused,
                )
                if paused:
                    return
                frontier_id = snapshot.messages[-1].id
            except ThreadPausedError:
                yield from self._paused_pending_events(
                    thread_id,
                    pending_message_id=active_pending_id,
                    client_submission_id=client_submission_id,
                )
                return
            except Exception:
                if active_pending_id is not None and self._cancel_requested(active_pending_id)():
                    yield from self._cancelled_pending_events(
                        thread_id,
                        active_pending_id,
                        client_submission_id=client_submission_id,
                    )
                    return
                raise
            finally:
                if active_pending_id is not None:
                    try:
                        # Closing a stream is semantically cancellation until a
                        # final snapshot has been committed.  Do not leave a
                        # durable placeholder merely because the UI stopped
                        # consuming its live events.
                        self._conversation_service.cancel_sampling(active_pending_id)
                    finally:
                        self._clear_cancel_event(active_pending_id)

    def _sampling_started_events(
        self,
        thread_id: str,
        pending_message_id: str,
        retry_events: list[dict[str, Any]],
        *,
        client_submission_id: str | None = None,
    ) -> Iterator[AgentHarnessStreamEvent]:
        yield AgentHarnessStreamEvent(
            kind="thinking",
            thread_id=thread_id,
            pending_message_id=pending_message_id,
            client_submission_id=client_submission_id,
            chatbot_event=build_thinking_chatbot_event(
                pending_message_id=pending_message_id, status=ChatbotEventStatus.IN_PROGRESS,
            ),
        )
        if retry_events:
            yield AgentHarnessStreamEvent(
                kind="connection",
                thread_id=thread_id,
                pending_message_id=pending_message_id,
                client_submission_id=client_submission_id,
                chatbot_event=build_llm_connection_chatbot_event(
                    sampling_id=pending_message_id, retry_events=retry_events,
                ),
            )

    def _project_live_event(
        self,
        event: ConversationLiveEvent,
        *,
        thread_id: str,
        client_submission_id: str | None = None,
    ) -> Iterator[AgentHarnessStreamEvent]:
        if event.kind == "sampling_started":
            yield from self._sampling_started_events(
                thread_id,
                event.pending_message_id,
                [],
                client_submission_id=client_submission_id,
            )
        elif event.kind == "retry" and event.retry is not None:
            yield AgentHarnessStreamEvent(
                kind="connection",
                thread_id=thread_id,
                pending_message_id=event.pending_message_id,
                client_submission_id=client_submission_id,
                chatbot_event=build_llm_connection_chatbot_event(
                    sampling_id=event.pending_message_id, retry_events=[_retry_payload(event.retry)],
                ),
            )
        elif event.kind == "tool_progress":
            yield AgentHarnessStreamEvent(
                kind="activity",
                thread_id=thread_id,
                pending_message_id=event.pending_message_id,
                client_submission_id=client_submission_id,
                chatbot_event=build_activity_chatbot_event(
                    pending_message_id=event.pending_message_id, sequence_index=0,
                ),
            )

    def _validate_submission(self, input_data: SubmitUserTurnInput) -> None:
        if not input_data.text.strip() and not input_data.dataset_attachments and not input_data.source_attachments:
            raise ValidationError("A conversation message needs text or at least one attachment.")
        if input_data.thread_id is not None:
            self.get_thread_snapshot(input_data.thread_id)

    def _resolve_fq_model_key(self, requested: str | None, current: str | None) -> str | None:
        selected = (requested or current or "").strip() or None
        if selected and self._llm_service is not None:
            return self._conversation_service.validate_fq_model_key(selected)
        if selected is None and self._llm_service is not None:
            return self._conversation_service.default_fq_model_key()
        return selected

    def _frontier_id(self, thread_id: str) -> str | None:
        snapshot = self.get_thread_snapshot(thread_id)
        return snapshot.messages[-1].id if snapshot.messages else None

    def _snapshot_if_thread_exists(self, thread_id: str) -> ConversationSnapshot | None:
        try:
            return self.get_thread_snapshot(thread_id)
        except NotFoundError:
            # Cancellation and Thread deletion may linearize before a late
            # provider/tool callback returns.  There is then no snapshot to
            # project; the stream still has a clean terminal outcome.
            return None

    def _cancelled_pending_events(
        self,
        thread_id: str,
        pending_message_id: str,
        *,
        client_submission_id: str | None = None,
    ) -> Iterator[AgentHarnessStreamEvent]:
        snapshot = self._snapshot_if_thread_exists(thread_id)
        self._clear_cancel_event(pending_message_id)
        if snapshot is None:
            return
        yield AgentHarnessStreamEvent(
            kind="snapshot",
            thread_id=thread_id,
            pending_message_id=pending_message_id,
            client_submission_id=client_submission_id,
            snapshot=snapshot,
            chatbot_events=self.project_chatbot_events(snapshot),
            is_final=True,
        )

    def _paused_pending_events(
        self,
        thread_id: str,
        pending_message_id: str | None,
        *,
        client_submission_id: str | None = None,
    ) -> Iterator[AgentHarnessStreamEvent]:
        """Close a paused loop with the stable canonical projection.

        A Thread pause does not itself delete a pending exchange.  The
        Conversation service either already discarded a pre-admission
        placeholder or will let an admitted provider/Tool exchange settle.
        This projection is therefore only a UI terminal acknowledgement; it is
        never a durable Run/Turn or a synthetic Message.
        """

        snapshot = self._snapshot_if_thread_exists(thread_id)
        if pending_message_id is not None:
            self._clear_cancel_event(pending_message_id)
        if snapshot is None:
            return
        yield AgentHarnessStreamEvent(
            kind="snapshot",
            thread_id=thread_id,
            pending_message_id=pending_message_id,
            client_submission_id=client_submission_id,
            snapshot=snapshot,
            chatbot_events=self.project_chatbot_events(snapshot),
            is_final=True,
        )

    def _dataset_ids(self, thread_id: str) -> list[str]:
        return self._dataset_ids_from_snapshot(self.get_thread_snapshot(thread_id))

    def _sampling_tool_scope(self, thread_id: str) -> ToolScope:
        snapshot = self.get_thread_snapshot(thread_id)
        tool_names: tuple[str, ...] = ()
        if self._tool_name_scope_provider is not None:
            selected = self._tool_name_scope_provider(snapshot)
            if selected is not None:
                tool_names = self._normalize_tool_scope_names(selected)
        return ToolScope(
            tool_names=tool_names,
            dataset_ids=tuple(self._dataset_ids_from_snapshot(snapshot)),
        )

    @staticmethod
    def _normalize_tool_scope_names(names: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("Tool scope names must be non-empty strings.")
            value = name.strip()
            if value not in normalized:
                normalized.append(value)
        return tuple(normalized)

    @staticmethod
    def _dataset_ids_from_snapshot(snapshot: ConversationSnapshot) -> list[str]:
        found: list[str] = []
        for message in snapshot.messages:
            payload = message.content_payload if isinstance(message.content_payload, dict) else None
            for block in blocks_from_payload(payload):
                if isinstance(block, DatasetBlock) and block.dataset_id not in found:
                    found.append(block.dataset_id)
        return found

    def _import_source_attachment(self, source: SourceAttachmentInput) -> list[DatasetAttachmentInput]:
        if self._dataset_service is None:
            raise ValidationError("Source attachment import requires the dataset service.")
        source_path = Path(source.file_path).expanduser()
        try:
            source_path = source_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValidationError("The selected source file is no longer available.") from exc
        if not source_path.is_file():
            raise ValidationError("The selected source path is not a file.")
        registered = self._dataset_service.register_dataset_attachment(
            RegisterDatasetInput(source_path=str(source_path), name=source_path.stem)
        )
        return [
            DatasetAttachmentInput(
                dataset_id=item.dataset_id,
                name=item.name,
                row_count=item.row_count,
                column_count=item.column_count,
            )
            for item in registered.datasets
        ]

    def _start_initial_title_task(
        self,
        *,
        claim: SubmissionClaim,
        first_user_message_id: str,
        appended_snapshot: ConversationSnapshot,
    ) -> _InitialTitleTask:
        completed = threading.Event()
        outcomes: SimpleQueue[ConversationSnapshot | None] = SimpleQueue()

        def run() -> None:
            snapshot: ConversationSnapshot | None = None
            try:
                snapshot = self._conversation_service.auto_title_initial_thread(
                    claim=claim,
                    first_user_message_id=first_user_message_id,
                    appended_snapshot=appended_snapshot,
                )
            except Exception as exc:
                # Automatic naming is metadata.  It must never surface as a
                # failure of an already-acknowledged conversation exchange.
                LOGGER.warning("Initial Thread title update failed: %s", exc.__class__.__name__)
            finally:
                outcomes.put(snapshot)
                completed.set()

        threading.Thread(target=run, name="xenix-initial-thread-title", daemon=True).start()
        return _InitialTitleTask(completed=completed, outcomes=outcomes)

    def _resolve_dataset_source_presentation(self, dataset_id: str):
        """Read presentation metadata without allowing it to affect replay."""

        resolver = getattr(self._dataset_service, "resolve_dataset_source_presentation", None)
        if not callable(resolver):
            return None
        try:
            return resolver(dataset_id)
        except Exception:
            return None

    def _tool_presentation(self, tool_name: str):
        lookup = getattr(self._tool_presentation_registry, "tool_presentation", None)
        return lookup(tool_name) if callable(lookup) else tool_presentation_for_name(tool_name)

    def _register_cancel_event(self, pending_message_id: str, thread_id: str) -> None:
        with self._cancel_lock:
            self._cancel_events.setdefault(pending_message_id, threading.Event())
            self._pending_threads[pending_message_id] = thread_id

    def _clear_cancel_event(self, pending_message_id: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(pending_message_id, None)
            self._pending_threads.pop(pending_message_id, None)

    def _cancel_requested(self, pending_message_id: str):
        with self._cancel_lock:
            event = self._cancel_events.get(pending_message_id)

        def requested() -> bool:
            return event.is_set() if event is not None else False

        return requested

    @staticmethod
    def _user_content_blocks(
        text: str,
        datasets: list[DatasetAttachmentInput],
    ) -> list[CanonicalMessageBlock]:
        blocks: list[CanonicalMessageBlock] = [TextBlock(text.strip())] if text.strip() else []
        blocks.extend(
            DatasetBlock(
                dataset_id=item.dataset_id,
                name=item.name,
                row_count=item.row_count,
                column_count=item.column_count,
            )
            for item in datasets
        )
        return blocks


def _usage_chatbot_event(overview: ConversationUsageOverview) -> ChatbotEvent:
    return ChatbotEvent(
        id=f"{overview.terminal_llm_message_id}:usage",
        kind=ChatbotEventKind.USAGE,
        sequence_index=overview.terminal_sequence_index,
        author=ChatbotEventAuthor.ASSISTANT,
        status=ChatbotEventStatus.COMPLETED,
        source_message_ids=[overview.root_user_message_id, overview.terminal_llm_message_id],
        usage_payload=overview.usage.to_payload(),
    )


def _retry_payload(retry: LLMRetryEvent) -> dict[str, Any]:
    return retry.to_payload()
