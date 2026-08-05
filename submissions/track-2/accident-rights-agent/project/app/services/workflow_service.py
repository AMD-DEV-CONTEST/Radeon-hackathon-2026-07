"""Thread-safe, stepwise orchestration for UI progress and safe stopping."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.agents.model_adapter import (
    AgentModelAdapter,
    DeterministicAgentModelAdapter,
    LocalVLLMAgentModelAdapter,
)
from app.evidence.model_client import LocalVLLMClient
from app.graph.workflow import CaseOrchestrator
from app.rag.service import build_retriever
from app.schemas.ui import WorkflowMode
from app.services.case_service import CaseService


class WorkflowService:
    def __init__(
        self,
        case_service: CaseService,
        *,
        checkpoint_path: Path | str = Path(
            "data/checkpoints/orchestrator.sqlite3"
        ),
        legal_corpus_path: Path | str = Path(
            "data/laws/legal_corpus.sqlite3"
        ),
        qdrant_path: Path | str = Path("data/qdrant/legal"),
    ):
        self.case_service = case_service
        self.checkpoint_path = Path(checkpoint_path)
        self.legal_corpus_path = Path(legal_corpus_path)
        self.qdrant_path = Path(qdrant_path)
        self._stop_requests: set[str] = set()
        self._lock = threading.RLock()

    @staticmethod
    def new_thread_id(case_id: str) -> str:
        return f"THREAD-{case_id[-20:]}-{uuid.uuid4().hex[:8].upper()}"

    def request_stop(self, thread_id: str) -> None:
        """Request a cooperative stop after the currently running graph node."""

        with self._lock:
            self._stop_requests.add(thread_id)

    def clear_stop(self, thread_id: str) -> None:
        with self._lock:
            self._stop_requests.discard(thread_id)

    def stop_requested(self, thread_id: str) -> bool:
        with self._lock:
            return thread_id in self._stop_requests

    @contextmanager
    def _orchestrator(
        self, mode: WorkflowMode | str
    ) -> Iterator[CaseOrchestrator]:
        selected_mode = WorkflowMode(mode)
        adapter: AgentModelAdapter
        if selected_mode is WorkflowMode.LOCAL_VLLM:
            client = LocalVLLMClient()
            client.model_name()
            adapter = LocalVLLMAgentModelAdapter(client)
            retriever = build_retriever(
                corpus_path=self.legal_corpus_path,
                qdrant_path=self.qdrant_path,
            )
        else:
            adapter = DeterministicAgentModelAdapter()
            retriever = build_retriever(
                corpus_path=self.legal_corpus_path,
                qdrant_path=self.qdrant_path,
                embedding_provider="hash",
                reranker_provider="heuristic",
            )
        orchestrator = CaseOrchestrator(
            workspace=self.case_service.workspace,
            retriever=retriever,
            checkpoint_path=self.checkpoint_path,
            model_adapter=adapter,
        )
        try:
            yield orchestrator
        finally:
            orchestrator.close()
            retriever.close()

    def run_incremental(
        self,
        case_id: str,
        *,
        thread_id: str | None = None,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
        simulate_json_error_at: str | None = None,
        simulate_failure_at: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        selected_mode = WorkflowMode(mode)
        selected_thread = thread_id or self.new_thread_id(case_id)
        self.clear_stop(selected_thread)
        started = time.perf_counter()
        self.case_service.register_thread(
            case_id,
            selected_thread,
            mode=selected_mode,
            status="running",
        )
        paused_envelope: dict[str, Any] | None = None
        with self._orchestrator(selected_mode) as orchestrator:
            state = orchestrator.run(
                case_id,
                thread_id=selected_thread,
                interrupt_after="intake_complete",
                simulate_json_error_at=simulate_json_error_at,
                simulate_failure_at=simulate_failure_at,
            )
            yield self._envelope(
                orchestrator, state, selected_mode, started
            )
            while True:
                status = orchestrator.status(selected_thread)
                if not status["next"]:
                    break
                if self.stop_requested(selected_thread):
                    self.case_service.register_thread(
                        case_id,
                        selected_thread,
                        mode=selected_mode,
                        status="paused",
                        current_node=status["current_node"],
                        recoverable=status["recoverable"],
                    )
                    paused_envelope = self._envelope(
                        orchestrator,
                        orchestrator.state(selected_thread),
                        selected_mode,
                        started,
                        paused=True,
                    )
                    break
                next_node = status["next"][0]
                state = orchestrator.resume(
                    selected_thread, interrupt_after=next_node
                )
                yield self._envelope(
                    orchestrator, state, selected_mode, started
                )

            if paused_envelope is None:
                final_state = orchestrator.state(selected_thread)
                final_status = self._completion_status(final_state)
                self.case_service.register_thread(
                    case_id,
                    selected_thread,
                    mode=selected_mode,
                    status=final_status,
                    current_node=final_state.get("current_node", "unknown"),
                    recoverable=False,
                )
        if paused_envelope is not None:
            yield paused_envelope

    def resume_incremental(
        self,
        thread_id: str,
        *,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
    ) -> Generator[dict[str, Any], None, None]:
        selected_mode = WorkflowMode(mode)
        self.clear_stop(thread_id)
        started = time.perf_counter()
        paused_envelope: dict[str, Any] | None = None
        with self._orchestrator(selected_mode) as orchestrator:
            status = orchestrator.status(thread_id)
            case_id = status.get("case_id")
            if not case_id:
                raise KeyError(thread_id)
            if not status["next"]:
                yield self._envelope(
                    orchestrator,
                    orchestrator.state(thread_id),
                    selected_mode,
                    started,
                )
                return
            while status["next"]:
                if self.stop_requested(thread_id):
                    self.case_service.register_thread(
                        case_id,
                        thread_id,
                        mode=selected_mode,
                        status="paused",
                        current_node=status["current_node"],
                        recoverable=True,
                    )
                    paused_envelope = self._envelope(
                        orchestrator,
                        orchestrator.state(thread_id),
                        selected_mode,
                        started,
                        paused=True,
                    )
                    break
                state = orchestrator.resume(
                    thread_id, interrupt_after=status["next"][0]
                )
                yield self._envelope(
                    orchestrator, state, selected_mode, started
                )
                status = orchestrator.status(thread_id)
            if paused_envelope is None:
                final_state = orchestrator.state(thread_id)
                self.case_service.register_thread(
                    case_id,
                    thread_id,
                    mode=selected_mode,
                    status=self._completion_status(final_state),
                    current_node=final_state.get("current_node", "unknown"),
                    recoverable=False,
                )
        if paused_envelope is not None:
            yield paused_envelope

    def retry_failed(
        self,
        thread_id: str,
        *,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
    ) -> dict[str, Any]:
        selected_mode = WorkflowMode(mode)
        started = time.perf_counter()
        with self._orchestrator(selected_mode) as orchestrator:
            state = orchestrator.retry_failed(thread_id)
            case_id = state["case_id"]
            self.case_service.register_thread(
                case_id,
                thread_id,
                mode=selected_mode,
                status=self._completion_status(state),
                current_node=state.get("current_node", "unknown"),
                recoverable=orchestrator.status(thread_id)["recoverable"],
            )
            return self._envelope(
                orchestrator, state, selected_mode, started
            )

    def status(
        self,
        thread_id: str,
        *,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
    ) -> dict[str, Any]:
        with self._orchestrator(mode) as orchestrator:
            status = orchestrator.status(thread_id)
            status["state"] = orchestrator.state(thread_id)
            return status

    def state(
        self,
        thread_id: str,
        *,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
    ) -> dict[str, Any]:
        with self._orchestrator(mode) as orchestrator:
            return orchestrator.state(thread_id)

    def decide_approval(
        self,
        thread_id: str,
        *,
        decision: str,
        approver: str,
        comments: str,
        mode: WorkflowMode | str = WorkflowMode.MOCK,
    ) -> dict[str, Any]:
        with self._orchestrator(mode) as orchestrator:
            status = orchestrator.decide_approval(
                thread_id,
                decision=decision,
                approver=approver,
                comments=comments,
            )
            status["state"] = orchestrator.state(thread_id)
            return status

    @staticmethod
    def _completion_status(state: dict[str, Any]) -> str:
        if any(
            result.get("status") == "failed"
            for result in state.get("node_results", {}).values()
        ):
            return "failed"
        if state.get("policy_gate", {}).get("decision") == "block":
            return "blocked"
        if state.get("approval_status") == "pending":
            return "approval_pending"
        return str(state.get("approval_status") or "succeeded")

    @staticmethod
    def _envelope(
        orchestrator: CaseOrchestrator,
        state: dict[str, Any],
        mode: WorkflowMode,
        started: float,
        *,
        paused: bool = False,
    ) -> dict[str, Any]:
        thread_id = state["thread_id"]
        status = orchestrator.status(thread_id)
        node_results = state.get("node_results", {})
        return {
            "case_id": state["case_id"],
            "thread_id": thread_id,
            "mode": mode.value,
            "paused": paused,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "current_node": state.get("current_node", "unknown"),
            "progress": state.get("progress", 0.0),
            "recoverable": status["recoverable"],
            "next": status["next"],
            "state": state,
            "node_durations_ms": {
                name: result.get("metrics", {}).get("duration_ms", 0.0)
                for name, result in node_results.items()
            },
            "warning_count": sum(
                len(result.get("warnings", []))
                for result in node_results.values()
            ),
            "failure_count": sum(
                result.get("status") == "failed"
                for result in node_results.values()
            ),
        }
