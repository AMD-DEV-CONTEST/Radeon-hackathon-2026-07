from pathlib import Path

from xianglens.storage.sqlite_store import SQLiteStore


def test_memory_requires_approved_consent(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.initialize()
    thread = store.create_thread("ada")
    proposal = store.create_memory_proposal(
        thread_id=thread["id"],
        user_id="ada",
        text="Red is an intentional brand color.",
        memory_type="preference",
    )

    assert store.list_memories("ada") == []
    store.decide_consent(proposal["id"], "approve")
    memories = store.list_memories("ada")

    assert len(memories) == 1
    assert memories[0]["text"] == "Red is an intentional brand color."
    assert store.delete_memory(memories[0]["id"], "ada")
    assert store.list_memories("ada") == []


def test_rejected_consent_creates_no_memory(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.initialize()
    thread = store.create_thread("ada")
    proposal = store.create_memory_proposal(
        thread_id=thread["id"],
        user_id="ada",
        text="Do not retain this.",
        memory_type="preference",
    )
    store.decide_consent(proposal["id"], "reject")
    assert store.list_memories("ada") == []


def test_thread_deletion_removes_approved_memory_without_fk_failure(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.initialize()
    thread = store.create_thread("ada")
    proposal = store.create_memory_proposal(
        thread_id=thread["id"],
        user_id="ada",
        text="Red is an intentional brand color.",
        memory_type="preference",
    )
    store.decide_consent(proposal["id"], "approve")
    store.delete_thread(thread["id"])
    assert store.get_thread(thread["id"]) is None
    assert store.list_memories("ada") == []


def test_forget_user_removes_all_private_state(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.initialize()
    first = store.create_thread("ada")
    store.create_thread("ada")
    proposal = store.create_memory_proposal(
        thread_id=first["id"],
        user_id="ada",
        text="Red is an intentional brand color.",
        memory_type="preference",
    )
    store.decide_consent(proposal["id"], "approve")
    result = store.forget_user("ada")
    assert result["threads_deleted"] == 2
    assert result["memories_deleted"] == 1
    assert store.list_memories("ada") == []
