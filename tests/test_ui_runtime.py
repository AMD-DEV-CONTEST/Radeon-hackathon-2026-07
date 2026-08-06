"""UI-level tests for the shared Bunker runtime.

``src.main`` mounts the Gradio app and the FastAPI lifespan against one shared
``BunkerRuntime``. These tests pin that contract: the UI handler
(``BunkerGradioApp.handle_message``) drives the *real* ``BunkerOrchestrator``
through ``BunkerOrchestratorAdapter`` for both the RAG and the agent intents,
multi-turn history is persisted to the shared ``SessionStore``, and failures
still degrade to a user-facing error instead of a raw exception.

The only components replaced here are the orchestrator's RAG program and agent
(themselves exercised end-to-end in ``tests/test_e2e_dspy.py``) so routing is
deterministic and LM-free via ``heuristic_router``.
"""

import types

import numpy  # noqa: F401 — fully initialize numpy before dspy/chromadb (lazy-import proxy guard)

from src.agent.orchestrator import BunkerOrchestrator, heuristic_router
from src.runtime import BunkerRuntime, BunkerOrchestratorAdapter
from src.ui.gradio_app import BunkerGradioApp


# ---------------------------------------------------------------------------
# Deterministic, LM-free stand-ins for the sub-pipeline (the real RAG program
# and DspyReActAgent are exercised in tests/test_e2e_dspy.py).
# ---------------------------------------------------------------------------


class _FakeRag:
    def __call__(self, question):
        return types.SimpleNamespace(
            answer=f"rag answer for: {question}",
            grounded=True,
            citation_count=2,
            queries=["Where is the Eiffel Tower located?"],
            notes=["The Eiffel Tower is in Paris."],
        )


class _FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, user_message, session_id="", context=None):
        self.calls.append({
            "user_message": user_message,
            "session_id": session_id,
            "context": [dict(m) for m in (context or [])],
        })
        return {
            "response": "agent answer",
            "trajectory": {},
            "tool_calls": [
                {
                    "tool": "email_draft",
                    "args": {"to": "alice@example.com"},
                    "thought": "Draft the email.",
                    "observation": "drafted",
                },
            ],
        }


def _build_runtime(tmp_path):
    """Build a real shared BunkerRuntime, then wire deterministic fakes into
    its orchestrator (kept as the real BunkerOrchestrator instance)."""
    runtime = BunkerRuntime(
        db_path=str(tmp_path / "data" / "memory" / "sessions.db"),
        audit_log_path=str(tmp_path / "data" / "audit" / "audit.jsonl"),
        base_dir=str(tmp_path / "data" / "documents"),
    )
    assert isinstance(runtime.orchestrator, BunkerOrchestrator)
    runtime.orchestrator.router = heuristic_router
    runtime.orchestrator.rag = _FakeRag()
    runtime.fake_agent = _FakeAgent()
    runtime.orchestrator.agent = runtime.fake_agent
    return runtime


def _build_app(runtime):
    return BunkerGradioApp(
        agent=runtime.adapter,
        privacy_dashboard=runtime.dashboard,
        session_store=runtime.session_store,
        context_manager=runtime.context_manager,
        permission_controller=runtime.permission_controller,
    )


# ---------------------------------------------------------------------------
# Adapter contract
# ---------------------------------------------------------------------------


def test_adapter_maps_orchestrator_dict_to_ui_tuple():
    """The adapter converts the orchestrator's dict result into (response, thoughts)."""

    class _DictOrchestrator:
        def run(self, message, session_id=""):
            return {
                "intent": "rag",
                "response": "hello",
                "grounded": True,
                "citations": 1,
                "queries": ["query one"],
                "notes": ["note one"],
            }

    adapter = BunkerOrchestratorAdapter(_DictOrchestrator())
    result = adapter.run("hi", "s1")

    assert isinstance(result, tuple) and len(result) == 2
    response, thoughts = result
    assert response == "hello"
    assert "`rag`" in thoughts
    assert "Grounded" in thoughts and "Citations" in thoughts
    assert "query one" in thoughts and "note one" in thoughts


def test_adapter_passes_through_tuple_results():
    """Legacy tuple-returning agents keep working through the adapter."""

    class _TupleOrchestrator:
        def run(self, message, session_id=""):
            return ("direct response", "direct thoughts")

    adapter = BunkerOrchestratorAdapter(_TupleOrchestrator())
    assert adapter.run("hi") == ("direct response", "direct thoughts")


# ---------------------------------------------------------------------------
# The mounted UI drives the shared orchestrator
# ---------------------------------------------------------------------------


def test_ui_handler_reaches_orchestrator_for_rag_and_agent(tmp_path):
    """The handler routes a document question to RAG and a tool request to the
    agent through the shared runtime's orchestrator, persisting every turn."""
    runtime = _build_runtime(tmp_path)
    app = _build_app(runtime)
    assert runtime.adapter.orchestrator is runtime.orchestrator

    rag_message = "Answer from the pdf: where is the Eiffel Tower?"
    history, thoughts, cleared = app.handle_message(rag_message, [], "")

    assert cleared == ""
    assert history[0][0] == rag_message
    assert history[0][1] == f"rag answer for: {rag_message}"
    assert "`rag`" in thoughts
    assert "query one" in thoughts or "Eiffel" in thoughts
    session_id = app.current_session_id
    assert session_id
    assert runtime.session_store.get_session(session_id) is not None

    agent_message = "draft an email to alice"
    history, thoughts, cleared = app.handle_message(agent_message, history, session_id)

    assert history[1][0] == agent_message
    assert history[1][1] == "agent answer"
    assert "`agent`" in thoughts
    assert "email_draft" in thoughts

    # The same shared SessionStore row owns every turn.
    assert app.current_session_id == session_id
    messages = runtime.session_store.get_messages(session_id)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]

    # The agent was invoked exactly once (turn 2) and received the RAG turn
    # as bounded prior context rebuilt from the shared SessionStore.
    assert len(runtime.fake_agent.calls) == 1
    agent_call = runtime.fake_agent.calls[0]
    assert agent_call["session_id"] == session_id
    assert agent_call["context"] == [
        {"role": "user", "content": rag_message},
        {"role": "assistant", "content": f"rag answer for: {rag_message}"},
    ]

    # The shared orchestrator threaded the whole conversation.
    assert [h["role"] for h in runtime.orchestrator.history] == [
        "user", "assistant", "user", "assistant",
    ]


def test_ui_handler_empty_message_is_short_circuited(tmp_path):
    """Blank messages never create a session row or touch the orchestrator."""
    runtime = _build_runtime(tmp_path)
    app = _build_app(runtime)

    history, thoughts, cleared = app.handle_message("   ", [], "")

    assert history == []
    assert thoughts == ""
    assert app.current_session_id is None
    assert runtime.session_store.get_stats()["total_sessions"] == 0


def test_ui_handler_degrades_on_orchestrator_failure():
    """A crashing orchestrator surfaces as a user-facing error tuple, never a
    raw exception — with no SessionStore the handler still returns cleanly."""

    class _BoomOrchestrator:
        def run(self, message, session_id=""):
            raise RuntimeError("AdapterParseError: LM response cannot be serialized")

    app = BunkerGradioApp(
        agent=BunkerOrchestratorAdapter(_BoomOrchestrator()),
        privacy_dashboard=object(),
        session_store=None,
        context_manager=object(),
        permission_controller=object(),
    )

    history, thoughts, cleared = app.handle_message("Write a file", [], "s1")

    assert thoughts == "Execution failed."
    assert "AdapterParseError: LM response cannot be serialized" in history[0][1]
    assert "❌" in history[0][1]
