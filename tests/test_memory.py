import pytest
import sqlite3
import os
import types

from src.memory import SessionStore, ContextManager
from src.agent.orchestrator import BunkerOrchestrator, heuristic_router
from src.ui.gradio_app import BunkerGradioApp

@pytest.fixture
def session_store():
    # Use in-memory SQLite for tests
    return SessionStore(db_path=":memory:")

def test_session_store_create(session_store):
    """create_session returns a session_id string"""
    session_id = session_store.create_session("Test Session")
    assert isinstance(session_id, str)
    assert len(session_id) > 0

def test_session_store_create_with_explicit_id(session_store):
    """create_session honours an explicit session_id (used by the UI's first message)."""
    session_id = session_store.create_session("Explicit", session_id="fixed-id-123")
    assert session_id == "fixed-id-123"
    session = session_store.get_session("fixed-id-123")
    assert session is not None
    assert session["title"] == "Explicit"

def test_session_store_get(session_store):
    """get_session returns dict with expected fields"""
    session_id = session_store.create_session("Test Session")
    session = session_store.get_session(session_id)
    assert isinstance(session, dict)
    assert session["id"] == session_id
    assert session["title"] == "Test Session"

def test_session_store_list(session_store):
    """list_sessions returns list"""
    session_store.create_session("Session 1")
    session_store.create_session("Session 2")
    sessions = session_store.list_sessions()
    assert isinstance(sessions, list)
    assert len(sessions) == 2

def test_session_store_add_message(session_store):
    """add_message returns message_id"""
    session_id = session_store.create_session("Test Session")
    msg_id = session_store.add_message(session_id, "user", "Hello")
    assert isinstance(msg_id, int) or isinstance(msg_id, str)

def test_session_store_get_messages(session_store):
    """get_messages returns ordered list"""
    session_id = session_store.create_session("Test")
    session_store.add_message(session_id, "user", "Hi")
    session_store.add_message(session_id, "assistant", "Hello")
    messages = session_store.get_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"

def test_session_store_delete(session_store):
    """delete_session removes session and messages"""
    session_id = session_store.create_session("Test")
    session_store.add_message(session_id, "user", "Hi")
    session_store.delete_session(session_id)
    assert session_store.get_session(session_id) is None
    assert len(session_store.get_messages(session_id)) == 0

def test_session_store_stats(session_store):
    """get_stats returns total_sessions and total_messages"""
    s1 = session_store.create_session("S1")
    session_store.add_message(s1, "user", "msg1")
    stats = session_store.get_stats()
    assert stats["total_sessions"] == 1
    assert stats["total_messages"] == 1

@pytest.fixture
def context_manager():
    return ContextManager()

def test_context_manager_build_context(context_manager):
    """build_context returns list of role/content dicts"""
    messages = [{"role": "user", "content": "Hi", "timestamp": 123}]
    context = context_manager.build_context(messages)
    assert isinstance(context, list)
    assert "role" in context[0]
    assert "content" in context[0]

def test_context_manager_token_count(context_manager):
    """count_tokens returns int"""
    text = "This is a test sentence."
    count = context_manager.count_tokens(text)
    assert isinstance(count, int)
    assert count > 0

def test_context_manager_trim_on_limit(context_manager):
    """context trimmed when over max_tokens"""
    context_manager.max_tokens = 10
    # Create messages that exceed 10 tokens
    messages = [
        {"role": "user", "content": "A " * 5},
        {"role": "assistant", "content": "B " * 10}
    ]
    trimmed = context_manager.build_context(messages)
    assert len(trimmed) < len(messages) or len(trimmed[0]["content"]) < len(messages[0]["content"]) * 5
    total_tokens = sum(context_manager.count_tokens(m["content"]) for m in trimmed)
    assert total_tokens <= 10


@pytest.fixture
def file_session_store(tmp_path):
    """A file-backed SessionStore under the app's local data directory."""
    return SessionStore(db_path=str(tmp_path / "data" / "memory" / "sessions.db"))


def test_context_manager_trims_persisted_session(file_session_store):
    """Builds a bounded context from a persisted session, trimming the oldest
    messages until the configured token limit is respected while keeping the
    most recent turn."""
    session_id = file_session_store.create_session("Trim")
    for i in range(10):
        file_session_store.add_message(session_id, "user", f"turn {i}: " + "x" * 400)
        file_session_store.add_message(session_id, "assistant", f"turn {i}: " + "y" * 400)

    context_manager = ContextManager(session_store=file_session_store, max_tokens=200, chars_per_token=4.0)
    context = context_manager.build_context(session_id)

    assert context, "expected a non-empty trimmed context"
    total_tokens = sum(context_manager.count_tokens(m["content"]) for m in context)
    assert total_tokens <= 200
    # The most recent assistant message always survives trimming.
    assert context[-1]["content"] == "turn 9: " + "y" * 400


def test_context_manager_respects_max_messages_from_store(file_session_store):
    """build_context pulls at most max_messages recent messages from the store."""
    session_id = file_session_store.create_session("MaxMsgs")
    for i in range(10):
        file_session_store.add_message(session_id, "user", f"u{i}")
        file_session_store.add_message(session_id, "assistant", f"a{i}")

    context_manager = ContextManager(session_store=file_session_store, max_tokens=4096)
    context = context_manager.build_context(session_id, max_messages=4)

    # 20 messages total; the newest 4 survive (u8, a8, u9, a9).
    assert [m["content"] for m in context] == ["u8", "a8", "u9", "a9"]


class _FakeRag:
    def __call__(self, question):
        return types.SimpleNamespace(
            answer=f"doc answer for: {question}",
            grounded=True,
            citation_count=0,
            queries=[],
            notes=[],
        )


class _RecordingAgent:
    def __init__(self):
        self.calls = []

    def run(self, user_message, session_id="", context=None):
        self.calls.append({
            "user_message": user_message,
            "session_id": session_id,
            "context": [dict(m) for m in (context or [])],
        })
        return {"response": f"agent reply to: {user_message}", "trajectory": {}, "tool_calls": []}


class _TupleAdapter:
    """Mirror of src.main._GradioAgentAdapter: orchestrator dict -> (response, thoughts)."""

    def __init__(self, orchestrator):
        self._orchestrator = orchestrator

    def run(self, message, session_id=""):
        result = self._orchestrator.run(message, session_id)
        return result["response"], result["intent"]


def _build_ui(tmp_path):
    """Wire the live UI path: store-backed orchestrator behind the Gradio app."""
    store = SessionStore(db_path=str(tmp_path / "data" / "memory" / "sessions.db"))
    context_manager = ContextManager(session_store=store, max_tokens=4096, chars_per_token=4.0)
    recording_agent = _RecordingAgent()
    orchestrator = BunkerOrchestrator(
        rag=_FakeRag(),
        agent=recording_agent,
        router=heuristic_router,
        session_store=store,
        context_manager=context_manager,
    )
    ui = BunkerGradioApp(
        agent=_TupleAdapter(orchestrator),
        privacy_dashboard=object(),
        session_store=store,
        context_manager=context_manager,
        permission_controller=object(),
    )
    return ui, store, recording_agent


def test_gradio_handler_creates_session_and_persists_every_turn(tmp_path):
    """Live UI path: the first message creates a SessionStore row and every
    user/assistant message is written to SQLite."""
    ui, store, recording_agent = _build_ui(tmp_path)

    history, _, _ = ui.handle_message("draft an email to alice", [], "")
    session_id = ui.current_session_id

    assert session_id
    assert store.get_session(session_id) is not None
    assert store.get_session(session_id)["title"] == "Bunker Chat"

    messages = store.get_messages(session_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "draft an email to alice"
    assert messages[1]["content"] == "agent reply to: draft an email to alice"


def test_gradio_handler_followup_reuses_session_and_receives_prior_context(tmp_path):
    """The second message reuses the same persisted session and the agent is
    given the bounded prior context rebuilt from SQLite."""
    ui, store, recording_agent = _build_ui(tmp_path)

    history, _, _ = ui.handle_message("draft an email to alice", [], "")
    session_id = ui.current_session_id
    history, _, _ = ui.handle_message("save the file now", history, session_id)

    # Same persisted session for both turns; no orphan rows.
    assert ui.current_session_id == session_id
    assert len(store.list_sessions()) == 1

    messages = store.get_messages(session_id)
    assert len(messages) == 4
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2]["content"] == "save the file now"

    # Follow-up call received exactly the prior turn as context.
    assert recording_agent.calls[1]["session_id"] == session_id
    assert recording_agent.calls[1]["context"] == [
        {"role": "user", "content": "draft an email to alice"},
        {"role": "assistant", "content": "agent reply to: draft an email to alice"},
    ]
    # No duplicated history.
    assert sum(1 for m in recording_agent.calls[1]["context"] if m["role"] == "user") == 1


def test_gradio_memory_remains_local(tmp_path):
    """Multi-turn memory lives in a local SQLite file, not remote state."""
    ui, store, _ = _build_ui(tmp_path)

    history, _, _ = ui.handle_message("draft an email to alice", [], "")
    history, _, _ = ui.handle_message("save the file now", history, ui.current_session_id)

    assert str(store.db_path).startswith(str(tmp_path))
    assert os.path.isfile(store.db_path)
    # Messages are fully recoverable from the local DB alone.
    messages = store.get_messages(ui.current_session_id)
    assert len(messages) == 4
