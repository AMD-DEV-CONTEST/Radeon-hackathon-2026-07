from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import select

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.storage import StorageBootstrapService
from xenix.services.storage.layout import database_path, knowledge_indexes_root
from xenix.services.storage.migrations import CURRENT_SCHEMA_VERSION, get_user_version
from xenix.services.storage.models import (
    ArtifactKind,
    ArtifactRow,
    ConversationMessageKind,
    ConversationMessageRow,
)


def _table_columns(context, table_name: str) -> set[str]:
    with context.engine.connect() as connection:
        return {
            str(row[1])
            for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
        }


def _target_shape(context) -> tuple[set[str], set[str], bool]:
    inspector = inspect(context.engine)
    return (
        _table_columns(context, "conversation_message"),
        {index["name"] for index in inspector.get_indexes("conversation_message")},
        not inspector.get_foreign_keys("artifact"),
    )


def _create_v14_fixture(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.executescript(
            """
            CREATE TABLE agent_thread (
                id VARCHAR NOT NULL PRIMARY KEY,
                title VARCHAR,
                system_prompt VARCHAR NOT NULL,
                selected_fq_model_key VARCHAR,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE agent_turn (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL REFERENCES agent_thread(id),
                sequence_index INTEGER NOT NULL,
                status VARCHAR,
                user_message_id VARCHAR REFERENCES agent_message(id),
                created_at DATETIME NOT NULL,
                ended_at DATETIME,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE agent_message (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL REFERENCES agent_thread(id),
                turn_id VARCHAR REFERENCES agent_turn(id),
                sequence_index INTEGER NOT NULL,
                kind VARCHAR,
                ui_author VARCHAR,
                content_blocks JSON NOT NULL,
                provider_payload JSON NOT NULL,
                status VARCHAR,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                finalized_at DATETIME
            );
            CREATE TABLE agent_run (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL REFERENCES agent_thread(id),
                turn_id VARCHAR NOT NULL REFERENCES agent_turn(id),
                status VARCHAR,
                provider_name VARCHAR,
                started_at DATETIME NOT NULL,
                finished_at DATETIME,
                error_summary VARCHAR,
                usage_payload JSON
            );
            CREATE TABLE agent_tool_call (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL REFERENCES agent_thread(id),
                turn_id VARCHAR NOT NULL REFERENCES agent_turn(id),
                request_message_id VARCHAR NOT NULL REFERENCES agent_message(id),
                result_message_id VARCHAR REFERENCES agent_message(id),
                tool_name VARCHAR,
                status VARCHAR,
                arguments_payload JSON NOT NULL,
                result_payload JSON,
                error_summary VARCHAR,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE agent_turn_completion_guard (
                id VARCHAR NOT NULL PRIMARY KEY,
                turn_id VARCHAR NOT NULL REFERENCES agent_turn(id),
                attempt_index INTEGER,
                input JSON NOT NULL,
                output JSON NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE agent_provider_request (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL REFERENCES agent_thread(id),
                turn_id VARCHAR NOT NULL REFERENCES agent_turn(id),
                run_id VARCHAR REFERENCES agent_run(id),
                provider_name VARCHAR,
                model VARCHAR,
                request_kind VARCHAR,
                status VARCHAR,
                input_message_ids JSON NOT NULL,
                output_message_ids JSON NOT NULL,
                usage_payload JSON,
                created_at DATETIME NOT NULL,
                completed_at DATETIME
            );
            CREATE TABLE artifact (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR REFERENCES agent_thread(id),
                turn_id VARCHAR REFERENCES agent_turn(id),
                message_id VARCHAR REFERENCES agent_message(id),
                tool_call_id VARCHAR REFERENCES agent_tool_call(id),
                kind VARCHAR(10) NOT NULL,
                title VARCHAR NOT NULL,
                absolute_path VARCHAR NOT NULL,
                mime_type VARCHAR,
                summary VARCHAR,
                preview_payload JSON,
                metadata_payload JSON NOT NULL,
                ready_to_open BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            );
            """
        )
        now = "2026-01-01T00:00:00"
        connection.execute(
            "INSERT INTO agent_thread VALUES (?, ?, ?, ?, ?, ?)",
            ("thread-1", "Legacy", "You are Xenix.", "model-a", now, now),
        )
        messages = [
            ("user-1", "user", "user", [{"type": "text", "text": "start"}], {}, "completed"),
            ("call-1", "tool_call", "tool", [{"type": "tool_call", "tool_name": "data.query"}], {"tool_call_id": "provider-call-1", "provider_name": "data_query"}, "completed"),
            ("result-1", "tool_call_result", "tool", [], {}, "completed"),
            ("call-2", "tool_call", "tool", [{"type": "tool_call", "tool_name": "data.query"}], {"tool_call_id": "provider-call-2"}, "completed"),
            ("assistant-cut", "assistant", "assistant", [{"type": "text", "text": "must be discarded"}], {}, "completed"),
            ("user-2", "user", "user", [{"type": "text", "text": "continue"}], {"client_submission_id": "submission-2"}, "completed"),
        ]
        for index, (message_id, kind, author, blocks, payload, status) in enumerate(messages):
            connection.execute(
                "INSERT INTO agent_message VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (message_id, "thread-1", "turn-1", index, kind, author, json.dumps(blocks), json.dumps(payload), status, now, now, now),
            )
        connection.execute(
            "INSERT INTO agent_turn VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("turn-1", "thread-1", 0, "ended", "user-1", now, now, now),
        )
        connection.execute(
            "INSERT INTO agent_tool_call VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("tool-call-1", "thread-1", "turn-1", "call-1", "result-1", "data.query", "succeeded", '{"rows": 2}', '{"rows": 2}', None, now, now),
        )
        connection.execute(
            "INSERT INTO agent_tool_call VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("tool-call-2", "thread-1", "turn-1", "call-2", None, "data.query", "requested", '{}', None, None, now, now),
        )
        connection.execute(
            "INSERT INTO artifact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("artifact-1", "thread-1", "turn-1", "result-1", "tool-call-1", "FILE", "Output", "C:/output.csv", "text/csv", "summary", '{"preview":true}', '{"domain":"fact"}', 1, now),
        )
        connection.execute("PRAGMA user_version=14")


def test_fresh_bootstrap_creates_v25_target_schema(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    context = StorageBootstrapService().initialize(paths)

    assert context.schema_version == CURRENT_SCHEMA_VERSION == 25
    assert get_user_version(context.engine) == 25
    inspector = inspect(context.engine)
    tables = set(inspector.get_table_names())
    assert {"conversation_thread", "conversation_message", "artifact"}.issubset(tables)
    assert {
        "knowledge_document",
        "knowledge_unit",
        "knowledge_unit_fts",
        "knowledge_import",
        "knowledge_vector_generation",
        "knowledge_canonical_generation",
        "knowledge_derivation",
        "knowledge_index_task",
    }.issubset(tables)
    assert {
        "amd_target_enrollment",
        "amd_installation",
        "amd_component_generation",
    }.issubset(tables)
    assert "local_wsl_distribution" in _table_columns(context, "amd_installation")
    assert not tables.intersection({"agent_thread", "agent_turn", "agent_message", "agent_run", "agent_tool_call"})
    assert _table_columns(context, "artifact") == {
        "id", "kind", "title", "absolute_path", "mime_type", "summary",
        "preview_payload", "metadata_payload", "ready_to_open", "created_at",
    }
    assert not inspector.get_foreign_keys("artifact")
    indexes = {index["name"] for index in inspector.get_indexes("conversation_message")}
    assert "ux_conversation_message_pending_thread" in indexes
    with context.engine.connect() as connection:
        triggers = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).all()
        }
    assert {"conversation_message_tool_result_guard", "conversation_message_final_immutable"}.issubset(triggers)
    fresh_shape = _target_shape(context)
    assert "tool_call_message_id" in fresh_shape[0]
    assert "ux_conversation_message_pending_thread" in fresh_shape[1]
    assert fresh_shape[2]
    assert knowledge_indexes_root(paths).is_dir()
    assert {"retrieval_generation_id", "retrieval_status"}.issubset(
        _table_columns(context, "knowledge_document")
    )
    assert {
        "phase",
        "attempt_number",
        "retry_of",
        "planned_document_id",
        "canonical_generation_id",
        "envelope_sha256",
        "content_ir_sha256",
        "retryable",
        "cancel_requested",
    }.issubset(_table_columns(context, "knowledge_import"))
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("knowledge_import")
    } == {"uq_knowledge_import_planned_document_attempt"}


def test_v14_upgrade_preserves_artifact_and_converts_complete_history(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    _create_v14_fixture(database_path(paths))
    context = StorageBootstrapService().initialize(paths)

    assert context.schema_version == 25
    with context.session_factory() as session:
        artifact = session.get(ArtifactRow, "artifact-1")
        assert artifact is not None
        assert artifact.kind is ArtifactKind.FILE
        assert artifact.metadata_payload == {"domain": "fact"}
        assert artifact.preview_payload == {"preview": True}
        messages = session.exec(select(ConversationMessageRow).order_by(ConversationMessageRow.sequence_index)).all()
    assert [message.id for message in messages] == ["user-1", "call-1", "result-1", "user-2"]
    assert [message.kind for message in messages] == [
        ConversationMessageKind.USER,
        ConversationMessageKind.TOOL_CALL,
        ConversationMessageKind.TOOL_RESULT,
        ConversationMessageKind.USER,
    ]
    assert messages[2].tool_call_message_id == "call-1"
    assert messages[1].provider_call_id == "provider-call-1"
    assert messages[1].content_payload == {"tool_name": "data.query", "provider_name": "data_query"}
    assert messages[-1].client_submission_id == "submission-2"
    with context.engine.connect() as connection:
        names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
    assert "artifact" in names
    assert not names.intersection({"agent_thread", "agent_turn", "agent_message", "agent_run", "agent_tool_call"})
    upgraded_shape = _target_shape(context)
    assert "tool_call_message_id" in upgraded_shape[0]
    assert "ux_conversation_message_pending_thread" in upgraded_shape[1]
    assert upgraded_shape[2]
