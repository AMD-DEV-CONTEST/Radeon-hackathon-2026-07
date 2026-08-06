import pytest
import sqlite3
import os

from src.memory import SessionStore, ContextManager

@pytest.fixture
def session_store():
    # Use in-memory SQLite for tests
    return SessionStore(db_path=":memory:")

def test_session_store_create(session_store):
    """create_session returns a session_id string"""
    session_id = session_store.create_session("Test Session")
    assert isinstance(session_id, str)
    assert len(session_id) > 0

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
