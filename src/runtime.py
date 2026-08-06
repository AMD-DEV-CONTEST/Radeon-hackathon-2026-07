"""Shared runtime service graph for Bunker's FastAPI app and Gradio UI.

``src.main.py`` builds exactly one :class:`BunkerRuntime` and hands it to both
the FastAPI lifespan (which may attach the multi-hop RAG program) and the
mounted Gradio app. That guarantees the chat UI, the privacy dashboard, the
audit log, and the RAG/agent pipeline all observe the *same* service instances
instead of separate per-layer copies with independent (and inconsistent)
in-memory state.

The UI never touches the orchestrator's result dict directly:
:class:`BunkerOrchestratorAdapter` maps the dict returned by
``BunkerOrchestrator.run`` into the ``(response, thoughts)`` tuple that
``BunkerGradioApp.handle_message`` expects, so the gradio layer stays agnostic
to the internal result shape (https://dspy.ai/tutorials/conversation_history/).
"""

import logging
from typing import Any, Dict, Optional

from .agent import BunkerOrchestrator, DspyReActAgent, PermissionController
from .config import get_config
from .memory.context_manager import ContextManager
from .memory.session_store import SessionStore
from .privacy import AuditLogger, DataFlowMonitor, PrivacyDashboard

logger = logging.getLogger(__name__)


class BunkerOrchestratorAdapter:
    """Maps a dict-returning orchestrator to the UI's ``(response, thoughts)`` contract.

    ``BunkerGradioApp.handle_message`` calls ``agent.run(message, session_id)``
    and expects a ``(response, thoughts)`` tuple. ``BunkerOrchestrator.run``
    returns a result dict instead; this adapter bridges the two without
    coupling the UI layer to the orchestrator's internals. Results that are
    already a tuple (e.g. a legacy agent-like object) pass through unchanged.
    """

    def __init__(self, orchestrator: Any):
        self._orchestrator = orchestrator

    @property
    def orchestrator(self) -> Any:
        """The wrapped ``BunkerOrchestrator`` instance."""
        return self._orchestrator

    def run(self, message: str, session_id: str = ""):
        """Run one turn and return ``(response, thoughts_markdown)``."""
        result = self._orchestrator.run(message, session_id=session_id)
        if not isinstance(result, dict):
            return result
        response = result.get("response", "No response produced.")
        return (response, _format_thoughts(result))


def _format_thoughts(result: Dict[str, Any]) -> str:
    """Render a routed turn's reasoning into the markdown thoughts panel.

    RAG turns show the grounded/citation summary plus the search queries and
    notes gathered; agent turns list the ordered tool calls with their
    observations. Unknown/empty results still produce a route header so the
    UI never renders a blank reasoning box.
    """
    intent = result.get("intent", "unknown")
    lines = [f"**Route**: `{intent}`"]

    if intent == "rag":
        grounded = "yes" if result.get("grounded") else "no"
        lines.append(
            f"**Grounded**: {grounded} · **Citations**: {result.get('citations', 0)}"
        )
        queries = result.get("queries") or []
        if queries:
            lines.append("**Search queries**:")
            lines.extend(f"- {query}" for query in queries)
        notes = result.get("notes") or []
        if notes:
            lines.append("**Notes gathered**:")
            lines.extend(f"- {note}" for note in notes)
    else:
        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            lines.append("**Tool calls**:")
            for call in tool_calls:
                tool = call.get("tool", "?")
                args = call.get("args") or {}
                if isinstance(args, dict):
                    args_text = ", ".join(f"{k}={v}" for k, v in args.items())
                else:
                    args_text = str(args)
                line = f"- `{tool}({args_text})`"
                observation = call.get("observation", "")
                if observation:
                    line += f" → {observation}"
                lines.append(line)

    return "\n".join(lines)


class BunkerRuntime:
    """Single shared service graph for the FastAPI lifespan and the Gradio UI.

    Args:
        config: Optional ``BunkerConfig``; defaults to the cached process-wide
            config. Paths can be overridden directly for tests.
        db_path: Override for the SessionStore SQLite path.
        audit_log_path: Override for the AuditLogger JSONL path.
        base_dir: Allowed base directory for the agent's file tools.
        max_iters: Max ReAct iterations for the shared ``DspyReActAgent``.
    """

    def __init__(
        self,
        config: Any = None,
        *,
        db_path: Optional[str] = None,
        audit_log_path: Optional[str] = None,
        base_dir: str = "./data/documents",
        max_iters: int = 15,
    ):
        self.config = config or get_config()

        self.audit_logger = AuditLogger(
            log_path=audit_log_path or self.config.privacy.audit_log_path
        )
        self.data_flow_monitor = DataFlowMonitor()
        self.permission_controller = PermissionController(
            privacy_config={"demo_mode": self.config.privacy.demo_mode}
        )
        self.dashboard = PrivacyDashboard(
            audit_logger=self.audit_logger,
            data_flow_monitor=self.data_flow_monitor,
        )
        self.session_store = SessionStore(db_path=db_path or self.config.memory.db_path)
        self.context_manager = ContextManager(
            session_store=self.session_store,
            max_tokens=self.config.memory.max_context_tokens,
            chars_per_token=self.config.memory.chars_per_token,
        )

        self.agent = DspyReActAgent(
            permission_controller=self.permission_controller,
            base_dir=base_dir,
            max_iters=max_iters,
            data_flow_monitor=self.data_flow_monitor,
            audit_logger=self.audit_logger,
        )
        self.rag: Any = None
        self.orchestrator = BunkerOrchestrator(
            rag=self.rag,
            agent=self.agent,
            session_store=self.session_store,
            context_manager=self.context_manager,
        )
        self.adapter = BunkerOrchestratorAdapter(self.orchestrator)

    def configure_rag(self, config: Any = None) -> Any:
        """Build the vector store + multi-hop RAG program and attach it.

        Runs at FastAPI startup with graceful degradation: when the embedding
        model or vector store cannot initialize (e.g. no model download), the
        orchestrator keeps the ``rag=None`` fallback and the RAG program runs
        with no retrieval (returning ``INSUFFICIENT_CONTEXT`` rather than
        hallucinating).

        Returns:
            The configured ``BunkerMultiHopRAG`` program.
        """
        config = config or self.config
        search = None
        try:
            from .rag.embeddings import ROCEmbeddings
            from .rag.vector_store import VectorStore
            from .rag.multihop_rag import load_bunker_rag_program, make_chromadb_search

            embeddings = ROCEmbeddings(model_name=config.rag.embedding_model)
            vector_store = VectorStore(
                embeddings=embeddings,
                persist_dir=config.rag.vector_db_path,
            )
            if hasattr(vector_store, "search"):
                search = make_chromadb_search(vector_store)
        except Exception as exc:
            logger.warning(
                "VectorStore / ROCEmbeddings uninitialized (degraded RAG mode): %s", exc
            )

        self.rag = load_bunker_rag_program(
            search=search,
            num_hops=config.rag.num_hops,
            num_docs=config.rag.num_docs,
            max_backtracks=config.rag.max_backtracks,
        )
        self.orchestrator.rag = self.rag
        return self.rag
