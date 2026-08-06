from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from ...exceptions import ValidationError
from . import models  # noqa: F401

CURRENT_SCHEMA_VERSION = 25


def get_user_version(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql("PRAGMA user_version").scalar_one())


def set_user_version(engine: Engine, version: int) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(f"PRAGMA user_version={version}")


def bootstrap_current_schema(engine: Engine) -> int:
    SQLModel.metadata.create_all(engine)
    _ensure_v15_triggers(engine)
    _ensure_v16_knowledge_fts(engine)
    set_user_version(engine, CURRENT_SCHEMA_VERSION)
    return CURRENT_SCHEMA_VERSION


def migrate_v1_to_v2(engine: Engine) -> int:
    with engine.begin() as connection:
        dataset_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(dataset)").all()
        }
        if "derived_from_dataset_id" not in dataset_columns:
            connection.exec_driver_sql(
                "ALTER TABLE dataset ADD COLUMN derived_from_dataset_id VARCHAR"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_derived_from_dataset_id "
            "ON dataset (derived_from_dataset_id)"
        )
        connection.exec_driver_sql("PRAGMA user_version=2")
    return 2


def migrate_v2_to_v3(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "agent_message" not in table_names:
            connection.exec_driver_sql("PRAGMA user_version=3")
            return 3
        agent_message_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(agent_message)").all()
        }
        if "status" not in agent_message_columns:
            connection.exec_driver_sql(
                "ALTER TABLE agent_message ADD COLUMN status VARCHAR"
            )
            connection.exec_driver_sql(
                "UPDATE agent_message SET status='completed' WHERE status IS NULL"
            )
        if "updated_at" not in agent_message_columns:
            connection.exec_driver_sql(
                "ALTER TABLE agent_message ADD COLUMN updated_at DATETIME"
            )
            connection.exec_driver_sql(
                "UPDATE agent_message SET updated_at=created_at WHERE updated_at IS NULL"
            )
        if "finalized_at" not in agent_message_columns:
            connection.exec_driver_sql(
                "ALTER TABLE agent_message ADD COLUMN finalized_at DATETIME"
            )
            connection.exec_driver_sql(
                "UPDATE agent_message SET finalized_at=created_at WHERE finalized_at IS NULL"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_message_status "
            "ON agent_message (status)"
        )
        connection.exec_driver_sql("PRAGMA user_version=3")
    return 3


def migrate_v3_to_v4(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "agent_message" not in table_names:
            connection.exec_driver_sql("PRAGMA user_version=4")
            return 4
        agent_message_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(agent_message)").all()
        }
        if "status" in agent_message_columns:
            status_pairs = {
                "IN_PROGRESS": "in_progress",
                "COMPLETED": "completed",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }
            for old_value, new_value in status_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE agent_message SET status=? WHERE status=?",
                    (new_value, old_value),
                )
        connection.exec_driver_sql("PRAGMA user_version=4")
    return 4


def migrate_v4_to_v5(engine: Engine) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS dataset_column_selection (
                id VARCHAR NOT NULL PRIMARY KEY,
                dataset_id VARCHAR NOT NULL,
                feature_columns JSON NOT NULL,
                target_columns JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES dataset (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_column_selection_dataset_id "
            "ON dataset_column_selection (dataset_id)"
        )
        connection.exec_driver_sql("PRAGMA user_version=5")
    return 5


def migrate_v5_to_v6(engine: Engine) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_turn_completion_guard (
                id VARCHAR NOT NULL PRIMARY KEY,
                turn_id VARCHAR NOT NULL,
                attempt_index INTEGER NOT NULL,
                input JSON NOT NULL,
                output JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(turn_id) REFERENCES agent_turn (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_turn_completion_guard_turn_id "
            "ON agent_turn_completion_guard (turn_id)"
        )
        connection.exec_driver_sql("PRAGMA user_version=6")
    return 6


def migrate_v6_to_v7(engine: Engine) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS dataset_column_binding (
                id VARCHAR NOT NULL PRIMARY KEY,
                dataset_id VARCHAR NOT NULL,
                role_bindings JSON NOT NULL,
                model_key VARCHAR,
                model_family VARCHAR,
                model_task_kind VARCHAR,
                schema_version INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES dataset (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_column_binding_dataset_id "
            "ON dataset_column_binding (dataset_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_column_binding_model_key "
            "ON dataset_column_binding (model_key)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_column_binding_model_family "
            "ON dataset_column_binding (model_family)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_column_binding_model_task_kind "
            "ON dataset_column_binding (model_task_kind)"
        )

        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "dataset_column_selection" in table_names:
            rows = connection.exec_driver_sql(
                """
                SELECT id, dataset_id, feature_columns, target_columns, created_at
                FROM dataset_column_selection
                """
            ).all()
            for row in rows:
                feature_columns = _json_list(row[2])
                target_columns = _json_list(row[3])
                role_bindings: list[dict[str, object]] = []
                if feature_columns:
                    role_bindings.append(
                        {
                            "role": "feature",
                            "columns": feature_columns,
                            "role_kind": "many_columns",
                            "required": True,
                            "metadata": {},
                        }
                    )
                if len(target_columns) == 1:
                    role_bindings.append(
                        {
                            "role": "target",
                            "columns": target_columns,
                            "role_kind": "single_column",
                            "required": True,
                            "metadata": {},
                        }
                    )
                elif target_columns:
                    role_bindings.append(
                        {
                            "role": "target",
                            "columns": target_columns,
                            "role_kind": "many_columns",
                            "required": True,
                            "metadata": {},
                        }
                    )
                connection.exec_driver_sql(
                    """
                    INSERT OR REPLACE INTO dataset_column_binding (
                        id,
                        dataset_id,
                        role_bindings,
                        model_key,
                        model_family,
                        model_task_kind,
                        schema_version,
                        created_at
                    )
                    VALUES (?, ?, ?, NULL, NULL, NULL, 1, ?)
                    """,
                    (row[0], row[1], json.dumps(role_bindings), row[4]),
                )
            connection.exec_driver_sql("DROP TABLE dataset_column_selection")
        connection.exec_driver_sql("PRAGMA user_version=7")
    return 7


def migrate_v7_to_v8(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "ml_task" in table_names:
            connection.exec_driver_sql(
                "UPDATE ml_task SET task_type='apply' WHERE task_type='inference'"
            )
        if "ml_task_artifact" in table_names:
            connection.exec_driver_sql(
                "UPDATE ml_task_artifact SET artifact_kind='apply_result' WHERE artifact_kind='inference_result'"
            )
        connection.exec_driver_sql("PRAGMA user_version=8")
    return 8


def migrate_v8_to_v9(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "ml_task" in table_names:
            task_rows = connection.exec_driver_sql(
                "SELECT id, request_payload, result_payload FROM ml_task"
            ).all()
            for row in task_rows:
                request_payload = _migrate_evaluation_payload(_json_object(row[1]))
                result_payload = _migrate_evaluation_payload(_json_object(row[2]))
                connection.exec_driver_sql(
                    """
                    UPDATE ml_task
                    SET request_payload=?, result_payload=?
                    WHERE id=?
                    """,
                    (
                        json.dumps(request_payload),
                        json.dumps(result_payload) if row[2] is not None else None,
                        row[0],
                    ),
                )

        if "trained_model" in table_names:
            rows = connection.exec_driver_sql(
                """
                SELECT
                    id,
                    dataset_id,
                    ml_task_id,
                    model_key,
                    problem_kind,
                    artifact_path,
                    metadata_payload,
                    created_at,
                    updated_at
                FROM trained_model
                """
            ).all()
            connection.exec_driver_sql("DROP TABLE trained_model")
            connection.exec_driver_sql(
                """
                CREATE TABLE trained_model (
                    id VARCHAR NOT NULL PRIMARY KEY,
                    dataset_id VARCHAR,
                    ml_task_id VARCHAR NOT NULL,
                    model_key VARCHAR NOT NULL,
                    problem_kind VARCHAR,
                    artifact_path VARCHAR NOT NULL,
                    metadata_payload JSON NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(dataset_id) REFERENCES dataset (id),
                    FOREIGN KEY(ml_task_id) REFERENCES ml_task (id)
                )
                """
            )
            for row in rows:
                problem_kind = str(row[4]) if row[4] is not None else ""
                normalized_problem_kind = None if problem_kind == "analysis" else (problem_kind or None)
                metadata_payload = _json_object(row[6])
                metadata_payload.setdefault(
                    "evaluation_kind",
                    _evaluation_kind_for_problem_kind(problem_kind),
                )
                connection.exec_driver_sql(
                    """
                    INSERT INTO trained_model (
                        id,
                        dataset_id,
                        ml_task_id,
                        model_key,
                        problem_kind,
                        artifact_path,
                        metadata_payload,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        normalized_problem_kind,
                        row[5],
                        json.dumps(metadata_payload),
                        row[7],
                        row[8],
                    ),
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trained_model_dataset_id "
                "ON trained_model (dataset_id)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_trained_model_ml_task_id "
                "ON trained_model (ml_task_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trained_model_model_key "
                "ON trained_model (model_key)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trained_model_problem_kind "
                "ON trained_model (problem_kind)"
            )
        connection.exec_driver_sql("PRAGMA user_version=9")
    return 9


def migrate_v9_to_v10(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "ml_task" in table_names:
            inspect_task_ids = [
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT id FROM ml_task WHERE task_type IN ('INSPECT_DATASET', 'inspect_dataset')"
                ).all()
            ]
            if inspect_task_ids and "dataset" in table_names:
                dataset_columns = {
                    str(row[1])
                    for row in connection.exec_driver_sql("PRAGMA table_info(dataset)").all()
                }
                if "ml_task_id" in dataset_columns:
                    for task_id in inspect_task_ids:
                        connection.exec_driver_sql(
                            "UPDATE dataset SET ml_task_id=NULL WHERE ml_task_id=?",
                            (task_id,),
                        )
            if inspect_task_ids and "ml_task_artifact" in table_names:
                for task_id in inspect_task_ids:
                    connection.exec_driver_sql(
                        "DELETE FROM ml_task_artifact WHERE ml_task_id=?",
                        (task_id,),
                    )
            for task_id in inspect_task_ids:
                connection.exec_driver_sql("DELETE FROM ml_task WHERE id=?", (task_id,))

            task_type_pairs = {
                "FIT": "fit",
                "HYPERPARAMETER_TUNING": "hyperparameter_tuning",
                "EVALUATE": "evaluate",
                "APPLY": "apply",
                "INFERENCE": "apply",
                "inference": "apply",
            }
            for old_value, new_value in task_type_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE ml_task SET task_type=? WHERE task_type=?",
                    (new_value, old_value),
                )

            status_pairs = {
                "PENDING": "pending",
                "RUNNING": "running",
                "SUCCEEDED": "succeeded",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }
            for old_value, new_value in status_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE ml_task SET status=? WHERE status=?",
                    (new_value, old_value),
                )

        if "ml_task_artifact" in table_names:
            artifact_kind_pairs = {
                "MODEL": "model",
                "HOLDOUT_DATA": "holdout_data",
                "TRAINING_REPORT": "training_report",
                "EVALUATION_REPORT": "evaluation_report",
                "APPLY_RESULT": "apply_result",
                "INFERENCE_RESULT": "apply_result",
                "inference_result": "apply_result",
                "EXPORT_FILE": "export_file",
                "OTHER": "other",
            }
            for old_value, new_value in artifact_kind_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE ml_task_artifact SET artifact_kind=? WHERE artifact_kind=?",
                    (new_value, old_value),
                )

        connection.exec_driver_sql("PRAGMA user_version=10")
    return 10


def migrate_v10_to_v11(engine: Engine) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_provider_request (
                id VARCHAR NOT NULL PRIMARY KEY,
                thread_id VARCHAR NOT NULL,
                turn_id VARCHAR NOT NULL,
                run_id VARCHAR,
                provider_name VARCHAR,
                model VARCHAR,
                request_kind VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                input_message_ids JSON NOT NULL,
                output_message_ids JSON NOT NULL,
                usage_payload JSON,
                created_at DATETIME NOT NULL,
                completed_at DATETIME,
                FOREIGN KEY(thread_id) REFERENCES agent_thread (id),
                FOREIGN KEY(turn_id) REFERENCES agent_turn (id),
                FOREIGN KEY(run_id) REFERENCES agent_run (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_thread_id "
            "ON agent_provider_request (thread_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_turn_id "
            "ON agent_provider_request (turn_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_run_id "
            "ON agent_provider_request (run_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_provider_name "
            "ON agent_provider_request (provider_name)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_model "
            "ON agent_provider_request (model)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_request_kind "
            "ON agent_provider_request (request_kind)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_agent_provider_request_status "
            "ON agent_provider_request (status)"
        )
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if {"agent_thread", "agent_turn", "agent_message"}.issubset(table_names):
            thread_rows = connection.exec_driver_sql(
                """
                SELECT id, system_prompt, created_at
                FROM agent_thread
                """
            ).all()
            for thread_row in thread_rows:
                thread_id = str(thread_row[0])
                has_system_message = connection.exec_driver_sql(
                    """
                    SELECT 1
                    FROM agent_message
                    WHERE thread_id=? AND kind IN ('SYSTEM', 'system')
                    LIMIT 1
                    """,
                    (thread_id,),
                ).first()
                if has_system_message is not None:
                    continue
                first_turn = connection.exec_driver_sql(
                    """
                    SELECT id, created_at
                    FROM agent_turn
                    WHERE thread_id=?
                    ORDER BY sequence_index
                    LIMIT 1
                    """,
                    (thread_id,),
                ).first()
                if first_turn is None:
                    continue
                timestamp = first_turn[1] or thread_row[2]
                system_prompt = str(thread_row[1] or models.DEFAULT_AGENT_THREAD_SYSTEM_PROMPT)
                connection.exec_driver_sql(
                    "UPDATE agent_message SET sequence_index=sequence_index + 1 WHERE thread_id=?",
                    (thread_id,),
                )
                connection.exec_driver_sql(
                    """
                    INSERT INTO agent_message (
                        id,
                        thread_id,
                        turn_id,
                        sequence_index,
                        kind,
                        ui_author,
                        content_blocks,
                        provider_payload,
                        status,
                        created_at,
                        updated_at,
                        finalized_at
                    )
                    VALUES (?, ?, ?, 0, 'SYSTEM', 'SYSTEM', ?, '{}', 'completed', ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        thread_id,
                        first_turn[0],
                        json.dumps([{"type": "text", "text": system_prompt}]),
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
        connection.exec_driver_sql("PRAGMA user_version=11")
    return 11


def migrate_v11_to_v12(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "agent_message" in table_names:
            kind_pairs = {
                "system": "SYSTEM",
                "user": "USER",
                "assistant": "ASSISTANT",
                "tool_call": "TOOL_CALL",
                "tool_call_result": "TOOL_CALL_RESULT",
            }
            for old_value, new_value in kind_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE agent_message SET kind=? WHERE kind=?",
                    (new_value, old_value),
                )

            author_pairs = {
                "system": "SYSTEM",
                "user": "USER",
                "assistant": "ASSISTANT",
                "tool": "TOOL",
            }
            for old_value, new_value in author_pairs.items():
                connection.exec_driver_sql(
                    "UPDATE agent_message SET ui_author=? WHERE ui_author=?",
                    (new_value, old_value),
                )

        connection.exec_driver_sql("PRAGMA user_version=12")
    return 12


def migrate_v12_to_v13(engine: Engine) -> int:
    with engine.begin() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "agent_thread" in table_names:
            thread_columns = {
                str(row[1])
                for row in connection.exec_driver_sql("PRAGMA table_info(agent_thread)").all()
            }
            if "selected_fq_model_key" not in thread_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE agent_thread ADD COLUMN selected_fq_model_key VARCHAR"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_agent_thread_selected_fq_model_key "
                "ON agent_thread (selected_fq_model_key)"
            )
        connection.exec_driver_sql("PRAGMA user_version=13")
    return 13


def migrate_v13_to_v14(engine: Engine) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS dataset_import (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                original_path VARCHAR NOT NULL,
                original_file_name VARCHAR NOT NULL,
                source_format VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(project_id) REFERENCES project (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_import_project_id "
            "ON dataset_import (project_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_import_source_format "
            "ON dataset_import (source_format)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_import_status "
            "ON dataset_import (status)"
        )

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS dataset_workbook (
                id VARCHAR NOT NULL PRIMARY KEY,
                import_id VARCHAR NOT NULL,
                sheet_count INTEGER NOT NULL,
                engine VARCHAR,
                metadata_payload JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(import_id) REFERENCES dataset_import (id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_workbook_import_id "
            "ON dataset_workbook (import_id)"
        )

        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        }
        if "dataset" in table_names:
            dataset_columns = {
                str(row[1])
                for row in connection.exec_driver_sql("PRAGMA table_info(dataset)").all()
            }
            new_columns = {
                "import_id": "VARCHAR",
                "workbook_id": "VARCHAR",
                "sheet_name": "VARCHAR",
                "sheet_index": "INTEGER",
            }
            for column_name, column_type in new_columns.items():
                if column_name not in dataset_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE dataset ADD COLUMN {column_name} {column_type}"
                    )
            for column_name in new_columns:
                connection.exec_driver_sql(
                    f"CREATE INDEX IF NOT EXISTS ix_dataset_{column_name} "
                    f"ON dataset ({column_name})"
                )
        connection.exec_driver_sql("PRAGMA user_version=14")
    return 14


def _table_names(connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).all()
    }


def _table_columns(connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
    }


def _require_legacy_shape(connection) -> None:
    required = {
        "agent_thread": {"id", "title", "system_prompt", "selected_fq_model_key", "created_at", "updated_at"},
        "agent_turn": {"id", "thread_id", "sequence_index", "status", "user_message_id", "created_at", "ended_at", "updated_at"},
        "agent_message": {
            "id", "thread_id", "turn_id", "sequence_index", "kind", "ui_author",
            "content_blocks", "provider_payload", "status", "created_at", "updated_at", "finalized_at",
        },
        "agent_run": {"id", "thread_id", "turn_id", "status", "provider_name", "started_at", "finished_at", "error_summary", "usage_payload"},
        "agent_tool_call": {
            "id", "thread_id", "turn_id", "request_message_id", "result_message_id", "tool_name",
            "status", "arguments_payload", "result_payload", "error_summary", "created_at", "updated_at",
        },
        "agent_turn_completion_guard": {"id", "turn_id", "attempt_index", "input", "output", "created_at"},
        "agent_provider_request": {
            "id", "thread_id", "turn_id", "run_id", "provider_name", "model", "request_kind", "status",
            "input_message_ids", "output_message_ids", "usage_payload", "created_at", "completed_at",
        },
        "artifact": {
            "id", "thread_id", "turn_id", "message_id", "tool_call_id", "kind", "title", "absolute_path",
            "mime_type", "summary", "preview_payload", "metadata_payload", "ready_to_open", "created_at",
        },
    }
    tables = _table_names(connection)
    missing_tables = sorted(set(required) - tables)
    if missing_tables:
        raise ValidationError(
            "Unsupported v14 database: missing required tables " + ", ".join(missing_tables)
        )
    for table_name, columns in required.items():
        missing_columns = sorted(columns - _table_columns(connection, table_name))
        if missing_columns:
            raise ValidationError(
                f"Unsupported v14 database: {table_name} is missing columns {', '.join(missing_columns)}"
            )


def _require_knowledge_source_shape(connection, version: int) -> None:
    """Reject incomplete databases before advancing a deployed Knowledge edge."""

    required: dict[str, set[str]] = {
        "conversation_thread": {
            "id",
            "title",
            "system_prompt",
            "selected_fq_model_key",
            "created_at",
            "updated_at",
        },
        "conversation_message": {
            "id",
            "thread_id",
            "sequence_index",
            "kind",
            "content_payload",
            "created_at",
        },
        "artifact": {
            "id",
            "kind",
            "title",
            "absolute_path",
            "metadata_payload",
            "ready_to_open",
            "created_at",
        },
    }
    if version >= 16:
        required.update(
            {
                "knowledge_document": {
                    "id",
                    "library_id",
                    "title",
                    "source_artifact_id",
                    "canonical_generation_id",
                    "active",
                    "created_at",
                    "updated_at",
                },
                "knowledge_unit": {
                    "id",
                    "document_id",
                    "canonical_generation_id",
                    "ordinal",
                    "text",
                    "search_text",
                    "locator_payload",
                    "created_at",
                },
                "knowledge_unit_fts": {"unit_id", "title", "search_text"},
                "knowledge_import": {
                    "id",
                    "library_id",
                    "original_file_name",
                    "source_format",
                    "source_sha256",
                    "status",
                    "document_id",
                    "source_artifact_id",
                    "canonical_path",
                    "reused_existing",
                    "error_code",
                    "error_summary",
                    "created_at",
                    "updated_at",
                },
            }
        )
    if version >= 17:
        required["knowledge_document"].update(
            {"source_sha256", "source_format", "canonical_path"}
        )
    if version >= 18:
        required["knowledge_vector_generation"] = {
            "id",
            "library_id",
            "corpus_fingerprint",
            "profile_fingerprint",
            "provider_key",
            "model",
            "dimensions",
            "distance_metric",
            "relative_path",
            "unit_count",
            "created_at",
        }
    if version >= 19:
        required["knowledge_document"].update(
            {"retrieval_generation_id", "retrieval_status"}
        )
        required["knowledge_import"].update(
            {
                "phase",
                "attempt_number",
                "retry_of",
                "planned_document_id",
                "canonical_generation_id",
                "envelope_sha256",
                "content_ir_sha256",
                "retryable",
                "cancel_requested",
            }
        )
        required["knowledge_canonical_generation"] = {
            "id",
            "document_id",
            "import_id",
            "source_artifact_id",
            "library_id",
            "source_sha256",
            "source_format",
            "media_type",
            "display_name",
            "envelope_sha256",
            "content_ir_sha256",
            "relative_path",
            "schema_version",
            "pipeline_payload",
            "warnings_payload",
            "compatibility_state",
            "created_at",
        }
        required["knowledge_derivation"] = {
            "id",
            "document_id",
            "canonical_generation_id",
            "import_id",
            "status",
            "phase",
            "attempt_number",
            "retry_of",
            "error_code",
            "error_summary",
            "retryable",
            "created_at",
            "updated_at",
        }
    if version >= 21:
        required["knowledge_index_task"] = {
            "id",
            "library_id",
            "index_kinds_payload",
            "trigger",
            "status",
            "phase",
            "profile_fingerprint",
            "corpus_fingerprint",
            "vector_generation_id",
            "error_code",
            "error_summary",
            "created_at",
            "updated_at",
        }
    if version >= 22:
        required["knowledge_document"].update(
            {
                "retrieval_projection_version",
                "retrieval_content_fingerprint",
                "retrieval_unit_count",
            }
        )
        required["knowledge_vector_generation"].add(
            "corpus_fingerprint_schema"
        )

    tables = _table_names(connection)
    missing_tables = sorted(set(required) - tables)
    if missing_tables:
        raise ValidationError(
            f"Unsupported v{version} database: missing required tables "
            + ", ".join(missing_tables)
        )
    for table_name, columns in required.items():
        missing_columns = sorted(columns - _table_columns(connection, table_name))
        if missing_columns:
            raise ValidationError(
                f"Unsupported v{version} database: {table_name} is missing columns "
                + ", ".join(missing_columns)
            )


def _content_text(value: object) -> str | None:
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    if not isinstance(parsed, list):
        return None
    parts = [
        str(block.get("text", ""))
        for block in parsed
        if isinstance(block, dict) and block.get("type") in {"text", "markdown"}
    ]
    text_value = "\n".join(part for part in parts if part)
    return text_value or None


def _provider_field(payload: object, key: str) -> str | None:
    parsed = _json_object(payload)
    value = parsed.get(key)
    return value if isinstance(value, str) and value else None


def _create_v15_tables(connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE conversation_thread (
            id VARCHAR NOT NULL PRIMARY KEY,
            title VARCHAR,
            system_prompt VARCHAR NOT NULL,
            selected_fq_model_key VARCHAR,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE conversation_message (
            id VARCHAR NOT NULL PRIMARY KEY,
            thread_id VARCHAR NOT NULL,
            sequence_index INTEGER NOT NULL,
            kind VARCHAR(20) NOT NULL,
            client_submission_id VARCHAR,
            content_payload JSON NOT NULL,
            text VARCHAR,
            reasoning VARCHAR,
            refusal VARCHAR,
            provider_call_id VARCHAR,
            tool_id VARCHAR,
            contract_version VARCHAR,
            arguments_payload JSON,
            scope_fingerprint VARCHAR,
            tool_call_message_id VARCHAR,
            result_status VARCHAR,
            value_payload JSON,
            error_summary VARCHAR,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(thread_id) REFERENCES conversation_thread (id),
            FOREIGN KEY(tool_call_message_id) REFERENCES conversation_message (id),
            UNIQUE(thread_id, sequence_index),
            UNIQUE(thread_id, client_submission_id),
            UNIQUE(tool_call_message_id)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER conversation_message_tool_result_guard
        BEFORE INSERT ON conversation_message
        WHEN NEW.kind = 'tool_result' AND (
            NEW.tool_call_message_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM conversation_message call
                WHERE call.id = NEW.tool_call_message_id
                  AND call.thread_id = NEW.thread_id
                  AND call.kind = 'tool_call'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'tool result must reference a same-thread tool call');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER conversation_message_final_immutable
        BEFORE UPDATE ON conversation_message
        WHEN OLD.kind <> 'pending_llm_sampling' OR NEW.kind <> 'pending_llm_sampling'
        BEGIN
            SELECT RAISE(ABORT, 'final conversation messages are immutable');
        END
        """
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ux_conversation_message_pending_thread "
        "ON conversation_message (thread_id) WHERE kind='pending_llm_sampling'"
    )
    for index_sql in (
        "CREATE INDEX ix_conversation_thread_title ON conversation_thread (title)",
        "CREATE INDEX ix_conversation_thread_selected_fq_model_key ON conversation_thread (selected_fq_model_key)",
        "CREATE INDEX ix_conversation_message_thread_id ON conversation_message (thread_id)",
        "CREATE INDEX ix_conversation_message_sequence_index ON conversation_message (sequence_index)",
        "CREATE INDEX ix_conversation_message_kind ON conversation_message (kind)",
        "CREATE INDEX ix_conversation_message_client_submission_id ON conversation_message (client_submission_id)",
        "CREATE INDEX ix_conversation_message_provider_call_id ON conversation_message (provider_call_id)",
        "CREATE INDEX ix_conversation_message_tool_id ON conversation_message (tool_id)",
        "CREATE INDEX ix_conversation_message_tool_call_message_id ON conversation_message (tool_call_message_id)",
        "CREATE INDEX ix_conversation_message_result_status ON conversation_message (result_status)",
    ):
        connection.exec_driver_sql(index_sql)

    connection.exec_driver_sql(
        """
        CREATE TABLE artifact_v15 (
            id VARCHAR NOT NULL PRIMARY KEY,
            kind VARCHAR(10) NOT NULL,
            title VARCHAR NOT NULL,
            absolute_path VARCHAR NOT NULL,
            mime_type VARCHAR,
            summary VARCHAR,
            preview_payload JSON,
            metadata_payload JSON NOT NULL,
            ready_to_open BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )


def _ensure_v15_triggers(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS conversation_message_tool_result_guard
            BEFORE INSERT ON conversation_message
            WHEN NEW.kind = 'tool_result' AND (
                NEW.tool_call_message_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM conversation_message call
                    WHERE call.id = NEW.tool_call_message_id
                      AND call.thread_id = NEW.thread_id
                      AND call.kind = 'tool_call'
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'tool result must reference a same-thread tool call');
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS conversation_message_final_immutable
            BEFORE UPDATE ON conversation_message
            WHEN OLD.kind <> 'pending_llm_sampling' OR NEW.kind <> 'pending_llm_sampling'
            BEGIN
                SELECT RAISE(ABORT, 'final conversation messages are immutable');
            END
            """
        )


def _copy_v14_rows(connection) -> None:
    connection.exec_driver_sql(
        """
        INSERT INTO artifact_v15 (
            id, kind, title, absolute_path, mime_type, summary,
            preview_payload, metadata_payload, ready_to_open, created_at
        )
        SELECT id, kind, title, absolute_path, mime_type, summary,
               preview_payload, metadata_payload, ready_to_open, created_at
        FROM artifact
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO conversation_thread (
            id, title, system_prompt, selected_fq_model_key, created_at, updated_at
        )
        SELECT id, title, system_prompt, selected_fq_model_key, created_at, updated_at
        FROM agent_thread
        """
    )
    tool_rows = {
        str(row[0]): row
        for row in connection.exec_driver_sql(
            "SELECT id, request_message_id, result_message_id, tool_name, status, arguments_payload, result_payload, error_summary "
            "FROM agent_tool_call"
        ).all()
    }
    result_rows = {
        str(row[0]): row
        for row in connection.exec_driver_sql(
            "SELECT id, thread_id, turn_id, sequence_index, content_blocks, provider_payload, status, created_at "
            "FROM agent_message WHERE kind IN ('tool_call_result','TOOL_CALL_RESULT')"
        ).all()
    }
    messages_by_thread: dict[str, list[tuple]] = {}
    for row in connection.exec_driver_sql(
        "SELECT id, thread_id, turn_id, sequence_index, kind, content_blocks, provider_payload, status, created_at "
        "FROM agent_message ORDER BY thread_id, sequence_index, id"
    ).all():
        messages_by_thread.setdefault(str(row[1]), []).append(row)

    for thread_id, messages in messages_by_thread.items():
        target_sequence = 0
        cut_until_user = False
        for row in messages:
            message_id, _thread, _turn, _old_sequence, raw_kind, blocks, payload, status, created_at = row
            kind = str(raw_kind).lower()
            if kind == "system":
                continue
            if kind in {"tool_call_result", "tool_result"}:
                continue
            if cut_until_user and kind != "user":
                continue
            if kind == "tool_call":
                tool = next((candidate for candidate in tool_rows.values() if str(candidate[1]) == str(message_id)), None)
                result = tool and result_rows.get(str(tool[2])) if tool else None
                terminal = tool and str(tool[4]).lower() in {"succeeded", "failed", "cancelled"}
                if tool is None or result is None or not terminal:
                    cut_until_user = True
                    continue
                tool_id = str(tool[3])
                arguments = _json_object(tool[5])
                provider_call_id = _provider_field(payload, "tool_call_id")
                provider_name = _provider_field(payload, "provider_name")
                call_payload = {"tool_name": tool_id}
                if provider_name:
                    call_payload["provider_name"] = provider_name
                connection.exec_driver_sql(
                    "INSERT INTO conversation_message (id, thread_id, sequence_index, kind, content_payload, provider_call_id, tool_id, arguments_payload, created_at) VALUES (?, ?, ?, 'tool_call', ?, ?, ?, ?, ?)",
                    (
                        str(message_id),
                        thread_id,
                        target_sequence,
                        json.dumps(call_payload),
                        provider_call_id,
                        tool_id,
                        json.dumps(arguments),
                        created_at,
                    ),
                )
                target_sequence += 1
                result_payload = _json_object(tool[6])
                result_status = str(tool[4]).lower()
                result_error = str(tool[7]) if tool[7] else None
                result_id = str(tool[2])
                connection.exec_driver_sql(
                    "INSERT INTO conversation_message (id, thread_id, sequence_index, kind, content_payload, tool_call_message_id, result_status, value_payload, error_summary, created_at) VALUES (?, ?, ?, 'tool_result', ?, ?, ?, ?, ?, ?)",
                    (result_id, thread_id, target_sequence, "{}", str(message_id), result_status, json.dumps(result_payload), result_error, result[7]),
                )
                target_sequence += 1
                continue

            target_kind = "user" if kind == "user" else "assistant" if kind == "assistant" else None
            if target_kind is None or str(status).lower() != "completed":
                continue
            raw_blocks = blocks if isinstance(blocks, str) else json.dumps(blocks or [])
            try:
                block_list = json.loads(raw_blocks)
            except json.JSONDecodeError:
                block_list = []
            parsed_blocks = json.dumps({"content_blocks": block_list if isinstance(block_list, list) else []})
            parsed_payload = _json_object(payload)
            submission_id = parsed_payload.get("client_submission_id") if target_kind == "user" else None
            connection.exec_driver_sql(
                "INSERT INTO conversation_message (id, thread_id, sequence_index, kind, client_submission_id, content_payload, text, reasoning, refusal, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(message_id), thread_id, target_sequence, target_kind, submission_id,
                    parsed_blocks,
                    _content_text(blocks) if target_kind == "assistant" else None,
                    _provider_field(payload, "reasoning_content") if target_kind == "assistant" else None,
                    _provider_field(payload, "refusal") if target_kind == "assistant" else None,
                    created_at,
                ),
            )
            target_sequence += 1
            cut_until_user = False


def migrate_v14_to_v15(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_legacy_shape(connection)
        if _table_names(connection) & {"conversation_thread", "conversation_message", "artifact_v15"}:
            raise ValidationError("Unsupported v14 database: target migration tables already exist")
        _create_v15_tables(connection)
        _copy_v14_rows(connection)
        connection.exec_driver_sql("DROP TABLE artifact")
        connection.exec_driver_sql("ALTER TABLE artifact_v15 RENAME TO artifact")
        connection.exec_driver_sql("CREATE INDEX ix_artifact_kind ON artifact (kind)")
        connection.exec_driver_sql("CREATE INDEX ix_artifact_title ON artifact (title)")
        connection.exec_driver_sql("CREATE INDEX ix_artifact_mime_type ON artifact (mime_type)")

        # Drop old children before parents. Null the optional edge that forms
        # the legacy Turn <-> Message foreign-key cycle before dropping either.
        connection.exec_driver_sql("DROP TABLE agent_provider_request")
        connection.exec_driver_sql("DROP TABLE agent_turn_completion_guard")
        connection.exec_driver_sql("DROP TABLE agent_tool_call")
        connection.exec_driver_sql("DROP TABLE agent_run")
        connection.exec_driver_sql("UPDATE agent_turn SET user_message_id=NULL")
        connection.exec_driver_sql("DROP TABLE agent_message")
        connection.exec_driver_sql("DROP TABLE agent_turn")
        connection.exec_driver_sql("DROP TABLE agent_thread")
        connection.exec_driver_sql("PRAGMA user_version=15")
    return 15


def _ensure_v16_knowledge_fts(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_unit_fts USING fts5("
            "unit_id UNINDEXED, title, search_text, tokenize='unicode61')"
        )


def migrate_v15_to_v16(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 15)
        _create_v16_knowledge_schema(connection)
        connection.exec_driver_sql("PRAGMA user_version=16")
    return 16


def migrate_v16_to_v17(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 16)
        columns = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(knowledge_document)")}
        if "source_sha256" not in columns:
            connection.exec_driver_sql("ALTER TABLE knowledge_document ADD COLUMN source_sha256 VARCHAR")
        if "source_format" not in columns:
            connection.exec_driver_sql("ALTER TABLE knowledge_document ADD COLUMN source_format VARCHAR")
        if "canonical_path" not in columns:
            connection.exec_driver_sql("ALTER TABLE knowledge_document ADD COLUMN canonical_path VARCHAR")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_document_source_sha256 "
            "ON knowledge_document (source_sha256)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_document_source_format "
            "ON knowledge_document (source_format)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_document_library_source_sha256 "
            "ON knowledge_document (library_id, source_sha256)"
        )
        connection.exec_driver_sql("PRAGMA user_version=17")
    return 17


def migrate_v17_to_v18(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 17)
        connection.exec_driver_sql(
            """
            CREATE TABLE knowledge_vector_generation (
                id VARCHAR NOT NULL PRIMARY KEY,
                library_id VARCHAR NOT NULL,
                corpus_fingerprint VARCHAR NOT NULL,
                profile_fingerprint VARCHAR NOT NULL,
                provider_key VARCHAR NOT NULL,
                model VARCHAR NOT NULL,
                dimensions INTEGER NOT NULL,
                distance_metric VARCHAR NOT NULL,
                relative_path VARCHAR NOT NULL,
                unit_count INTEGER NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_vector_generation_library_id "
            "ON knowledge_vector_generation (library_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_vector_generation_corpus_fingerprint "
            "ON knowledge_vector_generation (corpus_fingerprint)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_vector_generation_profile_fingerprint "
            "ON knowledge_vector_generation (profile_fingerprint)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_vector_generation_lookup "
            "ON knowledge_vector_generation "
            "(library_id, profile_fingerprint, corpus_fingerprint, created_at)"
        )
        connection.exec_driver_sql("PRAGMA user_version=18")
    return 18


def migrate_v18_to_v19(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 18)

        connection.exec_driver_sql(
            "ALTER TABLE knowledge_document ADD COLUMN retrieval_generation_id VARCHAR"
        )
        connection.exec_driver_sql(
            "ALTER TABLE knowledge_document ADD COLUMN retrieval_status "
            "VARCHAR NOT NULL DEFAULT 'pending'"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_retrieval_generation_id "
            "ON knowledge_document (retrieval_generation_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_retrieval_status "
            "ON knowledge_document (retrieval_status)"
        )
        connection.exec_driver_sql(
            """
            UPDATE knowledge_document
            SET retrieval_generation_id=canonical_generation_id,
                retrieval_status='ready'
            WHERE EXISTS (
                SELECT 1
                FROM knowledge_unit
                WHERE knowledge_unit.document_id=knowledge_document.id
                  AND knowledge_unit.canonical_generation_id=
                      knowledge_document.canonical_generation_id
            )
            """
        )

        import_columns = (
            ("phase", "VARCHAR NOT NULL DEFAULT 'queued'"),
            ("attempt_number", "INTEGER NOT NULL DEFAULT 1"),
            ("retry_of", "VARCHAR"),
            ("planned_document_id", "VARCHAR"),
            ("canonical_generation_id", "VARCHAR"),
            ("envelope_sha256", "VARCHAR"),
            ("content_ir_sha256", "VARCHAR"),
            ("retryable", "BOOLEAN NOT NULL DEFAULT 0"),
            ("cancel_requested", "BOOLEAN NOT NULL DEFAULT 0"),
        )
        for column_name, declaration in import_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE knowledge_import ADD COLUMN {column_name} {declaration}"
            )
        for column_name in (
            "phase",
            "retry_of",
            "planned_document_id",
            "canonical_generation_id",
        ):
            connection.exec_driver_sql(
                f"CREATE INDEX ix_knowledge_import_{column_name} "
                f"ON knowledge_import ({column_name})"
            )
        connection.exec_driver_sql(
            "UPDATE knowledge_import "
            "SET planned_document_id=document_id "
            "WHERE planned_document_id IS NULL AND document_id IS NOT NULL"
        )
        connection.exec_driver_sql(
            """
            UPDATE knowledge_import
            SET canonical_generation_id=(
                SELECT knowledge_document.canonical_generation_id
                FROM knowledge_document
                WHERE knowledge_document.id=knowledge_import.document_id
            )
            WHERE canonical_generation_id IS NULL AND document_id IS NOT NULL
            """
        )

        connection.exec_driver_sql(
            """
            CREATE TABLE knowledge_canonical_generation (
                id VARCHAR NOT NULL PRIMARY KEY,
                document_id VARCHAR NOT NULL,
                import_id VARCHAR,
                source_artifact_id VARCHAR,
                library_id VARCHAR NOT NULL,
                source_sha256 VARCHAR NOT NULL,
                source_format VARCHAR NOT NULL,
                media_type VARCHAR,
                display_name VARCHAR NOT NULL,
                envelope_sha256 VARCHAR NOT NULL,
                content_ir_sha256 VARCHAR NOT NULL,
                relative_path VARCHAR NOT NULL,
                schema_version INTEGER NOT NULL,
                pipeline_payload JSON NOT NULL,
                warnings_payload JSON NOT NULL,
                compatibility_state VARCHAR NOT NULL DEFAULT 'verified',
                created_at DATETIME NOT NULL,
                FOREIGN KEY(document_id) REFERENCES knowledge_document (id),
                FOREIGN KEY(import_id) REFERENCES knowledge_import (id),
                FOREIGN KEY(source_artifact_id) REFERENCES artifact (id)
            )
            """
        )
        for column_name in (
            "document_id",
            "import_id",
            "source_artifact_id",
            "library_id",
            "source_sha256",
            "source_format",
            "envelope_sha256",
            "content_ir_sha256",
            "compatibility_state",
        ):
            connection.exec_driver_sql(
                f"CREATE INDEX ix_knowledge_canonical_generation_{column_name} "
                f"ON knowledge_canonical_generation ({column_name})"
            )

        connection.exec_driver_sql(
            """
            CREATE TABLE knowledge_derivation (
                id VARCHAR NOT NULL PRIMARY KEY,
                document_id VARCHAR NOT NULL,
                canonical_generation_id VARCHAR NOT NULL,
                import_id VARCHAR,
                status VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                attempt_number INTEGER NOT NULL,
                retry_of VARCHAR,
                error_code VARCHAR,
                error_summary VARCHAR,
                retryable BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(document_id) REFERENCES knowledge_document (id),
                FOREIGN KEY(canonical_generation_id)
                    REFERENCES knowledge_canonical_generation (id),
                FOREIGN KEY(import_id) REFERENCES knowledge_import (id),
                FOREIGN KEY(retry_of) REFERENCES knowledge_derivation (id)
            )
            """
        )
        for column_name in (
            "document_id",
            "canonical_generation_id",
            "import_id",
            "status",
            "phase",
            "retry_of",
            "error_code",
        ):
            connection.exec_driver_sql(
                f"CREATE INDEX ix_knowledge_derivation_{column_name} "
                f"ON knowledge_derivation ({column_name})"
            )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_derivation_lookup "
            "ON knowledge_derivation "
            "(document_id, canonical_generation_id, created_at)"
        )
        connection.exec_driver_sql("PRAGMA user_version=19")
    return 19


def migrate_v19_to_v20(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 19)
        connection.exec_driver_sql(
            "UPDATE knowledge_import "
            "SET status='canonical_ready', phase='completed' "
            "WHERE status='succeeded'"
        )
        attempts = connection.exec_driver_sql(
            "SELECT id, planned_document_id "
            "FROM knowledge_import "
            "WHERE planned_document_id IS NOT NULL "
            "ORDER BY planned_document_id, attempt_number, created_at, id"
        ).fetchall()
        current_document_id: str | None = None
        ordinal = 0
        for import_id, planned_document_id in attempts:
            if planned_document_id != current_document_id:
                current_document_id = planned_document_id
                ordinal = 1
            else:
                ordinal += 1
            connection.exec_driver_sql(
                "UPDATE knowledge_import SET attempt_number=? WHERE id=?",
                (ordinal, import_id),
            )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_knowledge_import_planned_document_attempt "
            "ON knowledge_import (planned_document_id, attempt_number)"
        )
        connection.exec_driver_sql("PRAGMA user_version=20")
    return 20


def migrate_v20_to_v21(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 20)
        connection.exec_driver_sql(
            """
            CREATE TABLE knowledge_index_task (
                id VARCHAR NOT NULL PRIMARY KEY,
                library_id VARCHAR NOT NULL,
                index_kinds_payload JSON NOT NULL,
                trigger VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                profile_fingerprint VARCHAR,
                corpus_fingerprint VARCHAR,
                vector_generation_id VARCHAR,
                error_code VARCHAR,
                error_summary VARCHAR,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        for column_name in (
            "library_id",
            "trigger",
            "status",
            "phase",
            "profile_fingerprint",
            "corpus_fingerprint",
            "vector_generation_id",
            "error_code",
        ):
            connection.exec_driver_sql(
                f"CREATE INDEX ix_knowledge_index_task_{column_name} "
                f"ON knowledge_index_task ({column_name})"
            )
        connection.exec_driver_sql("PRAGMA user_version=21")
    return 21


def migrate_v21_to_v22(engine: Engine) -> int:
    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 21)
        connection.exec_driver_sql(
            "ALTER TABLE knowledge_document "
            "ADD COLUMN retrieval_projection_version INTEGER"
        )
        connection.exec_driver_sql(
            "ALTER TABLE knowledge_document "
            "ADD COLUMN retrieval_content_fingerprint VARCHAR"
        )
        connection.exec_driver_sql(
            "ALTER TABLE knowledge_document "
            "ADD COLUMN retrieval_unit_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_retrieval_projection_version "
            "ON knowledge_document (retrieval_projection_version)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_retrieval_content_fingerprint "
            "ON knowledge_document (retrieval_content_fingerprint)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE knowledge_vector_generation "
            "ADD COLUMN corpus_fingerprint_schema INTEGER NOT NULL DEFAULT 1"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_vector_generation_corpus_fingerprint_schema "
            "ON knowledge_vector_generation (corpus_fingerprint_schema)"
        )
        # Historical rows have no proof that they satisfy the current bounded
        # projection contract. Keep the derived bytes for cleanup, but make them
        # unreachable until service-owned re-derivation publishes v2 atomically.
        connection.exec_driver_sql(
            "UPDATE knowledge_document "
            "SET retrieval_generation_id=NULL, retrieval_status='pending', "
            "retrieval_projection_version=NULL, "
            "retrieval_content_fingerprint=NULL, retrieval_unit_count=0 "
            "WHERE active=1"
        )
        connection.exec_driver_sql("PRAGMA user_version=22")
    return 22


def migrate_v22_to_v23(engine: Engine) -> int:
    """Invalidate row-id-dependent v2 projections before deterministic v3 derivation."""

    with engine.begin() as connection:
        _require_knowledge_source_shape(connection, 22)
        connection.exec_driver_sql(
            "UPDATE knowledge_document "
            "SET retrieval_generation_id=NULL, retrieval_status='pending', "
            "retrieval_projection_version=NULL, "
            "retrieval_content_fingerprint=NULL, retrieval_unit_count=0 "
            "WHERE active=1"
        )
        connection.exec_driver_sql("PRAGMA user_version=23")
    return 23


def migrate_v23_to_v24(engine: Engine) -> int:
    """Add inert managed-installation records without coupling storage to AMD code."""

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS amd_target_enrollment (
                id VARCHAR NOT NULL PRIMARY KEY,
                host VARCHAR NOT NULL,
                user VARCHAR NOT NULL,
                port INTEGER NOT NULL,
                pinned_host_key VARCHAR NOT NULL,
                identity_file_reference VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS amd_installation (
                id VARCHAR NOT NULL PRIMARY KEY,
                placement VARCHAR NOT NULL,
                target_id VARCHAR,
                profile_id VARCHAR NOT NULL,
                profile_digest VARCHAR NOT NULL,
                desired_presence BOOLEAN NOT NULL,
                lifecycle_state VARCHAR NOT NULL,
                revision INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_amd_installation_id_placement UNIQUE (id, placement),
                FOREIGN KEY(target_id) REFERENCES amd_target_enrollment (id)
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS amd_component_generation (
                id VARCHAR NOT NULL PRIMARY KEY,
                installation_id VARCHAR NOT NULL,
                capability VARCHAR NOT NULL,
                manifest_digest VARCHAR NOT NULL,
                lifecycle_state VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                error_code VARCHAR,
                attestation_reference VARCHAR,
                revision INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_amd_component_generation_identity
                    UNIQUE (installation_id, capability, manifest_digest),
                FOREIGN KEY(installation_id) REFERENCES amd_installation (id)
            )
            """
        )
        for name, table, column in (
            ("ix_amd_target_enrollment_host", "amd_target_enrollment", "host"),
            ("ix_amd_installation_placement", "amd_installation", "placement"),
            ("ix_amd_installation_target_id", "amd_installation", "target_id"),
            ("ix_amd_installation_profile_id", "amd_installation", "profile_id"),
            ("ix_amd_installation_profile_digest", "amd_installation", "profile_digest"),
            ("ix_amd_installation_desired_presence", "amd_installation", "desired_presence"),
            ("ix_amd_installation_lifecycle_state", "amd_installation", "lifecycle_state"),
            ("ix_amd_component_generation_installation_id", "amd_component_generation", "installation_id"),
            ("ix_amd_component_generation_capability", "amd_component_generation", "capability"),
            ("ix_amd_component_generation_manifest_digest", "amd_component_generation", "manifest_digest"),
            ("ix_amd_component_generation_lifecycle_state", "amd_component_generation", "lifecycle_state"),
            ("ix_amd_component_generation_phase", "amd_component_generation", "phase"),
            ("ix_amd_component_generation_error_code", "amd_component_generation", "error_code"),
        ):
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
            )
        connection.exec_driver_sql("PRAGMA user_version=24")
    return 24


def migrate_v24_to_v25(engine: Engine) -> int:
    """Add the opaque Local WSL target reference for current Radeon rows.

    Existing AMD records deliberately remain untouched: their placement,
    target identity, profile, generation, and retirement fences keep exactly
    the meaning they had when written. New Local WSL rows alone use the new
    nullable reference.
    """

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE amd_installation "
            "ADD COLUMN local_wsl_distribution VARCHAR"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_amd_installation_local_wsl_distribution "
            "ON amd_installation (local_wsl_distribution)"
        )
        connection.exec_driver_sql("PRAGMA user_version=25")
    return 25


def _create_v16_knowledge_schema(connection) -> None:
    """Create the fixed historical v16 Knowledge shape without current metadata."""

    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS knowledge_document (
            id VARCHAR NOT NULL PRIMARY KEY,
            library_id VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            source_artifact_id VARCHAR,
            canonical_generation_id VARCHAR NOT NULL,
            active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(source_artifact_id) REFERENCES artifact (id)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS knowledge_unit (
            id VARCHAR NOT NULL PRIMARY KEY,
            document_id VARCHAR NOT NULL,
            canonical_generation_id VARCHAR NOT NULL,
            ordinal INTEGER NOT NULL,
            text VARCHAR NOT NULL,
            search_text VARCHAR NOT NULL,
            locator_payload JSON NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_knowledge_unit_generation_ordinal
                UNIQUE (document_id, canonical_generation_id, ordinal),
            FOREIGN KEY(document_id) REFERENCES knowledge_document (id)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS knowledge_import (
            id VARCHAR NOT NULL PRIMARY KEY,
            library_id VARCHAR NOT NULL,
            original_file_name VARCHAR NOT NULL,
            source_format VARCHAR NOT NULL,
            source_sha256 VARCHAR,
            status VARCHAR NOT NULL,
            document_id VARCHAR,
            source_artifact_id VARCHAR,
            canonical_path VARCHAR,
            reused_existing BOOLEAN NOT NULL,
            error_code VARCHAR,
            error_summary VARCHAR,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(document_id) REFERENCES knowledge_document (id),
            FOREIGN KEY(source_artifact_id) REFERENCES artifact (id)
        )
        """
    )
    indexes = (
        ("ix_knowledge_document_library_id", "knowledge_document", "library_id"),
        ("ix_knowledge_document_title", "knowledge_document", "title"),
        ("ix_knowledge_document_source_artifact_id", "knowledge_document", "source_artifact_id"),
        ("ix_knowledge_document_canonical_generation_id", "knowledge_document", "canonical_generation_id"),
        ("ix_knowledge_document_active", "knowledge_document", "active"),
        ("ix_knowledge_unit_document_id", "knowledge_unit", "document_id"),
        ("ix_knowledge_unit_canonical_generation_id", "knowledge_unit", "canonical_generation_id"),
        ("ix_knowledge_unit_ordinal", "knowledge_unit", "ordinal"),
        ("ix_knowledge_import_library_id", "knowledge_import", "library_id"),
        ("ix_knowledge_import_source_format", "knowledge_import", "source_format"),
        ("ix_knowledge_import_source_sha256", "knowledge_import", "source_sha256"),
        ("ix_knowledge_import_status", "knowledge_import", "status"),
        ("ix_knowledge_import_document_id", "knowledge_import", "document_id"),
        ("ix_knowledge_import_source_artifact_id", "knowledge_import", "source_artifact_id"),
        ("ix_knowledge_import_error_code", "knowledge_import", "error_code"),
    )
    for name, table, column in indexes:
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
        )
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_unit_fts USING fts5("
        "unit_id UNINDEXED, title, search_text, tokenize='unicode61')"
    )


def run_migrations(engine: Engine) -> int:
    current_version = get_user_version(engine)
    if current_version == 0:
        return bootstrap_current_schema(engine)
    if current_version == 1:
        current_version = migrate_v1_to_v2(engine)
    if current_version == 2:
        current_version = migrate_v2_to_v3(engine)
    if current_version == 3:
        current_version = migrate_v3_to_v4(engine)
    if current_version == 4:
        current_version = migrate_v4_to_v5(engine)
    if current_version == 5:
        current_version = migrate_v5_to_v6(engine)
    if current_version == 6:
        current_version = migrate_v6_to_v7(engine)
    if current_version == 7:
        current_version = migrate_v7_to_v8(engine)
    if current_version == 8:
        current_version = migrate_v8_to_v9(engine)
    if current_version == 9:
        current_version = migrate_v9_to_v10(engine)
    if current_version == 10:
        current_version = migrate_v10_to_v11(engine)
    if current_version == 11:
        current_version = migrate_v11_to_v12(engine)
    if current_version == 12:
        current_version = migrate_v12_to_v13(engine)
    if current_version == 13:
        current_version = migrate_v13_to_v14(engine)
    if current_version == 14:
        current_version = migrate_v14_to_v15(engine)
    if current_version == 15:
        current_version = migrate_v15_to_v16(engine)
    if current_version == 16:
        current_version = migrate_v16_to_v17(engine)
    if current_version == 17:
        current_version = migrate_v17_to_v18(engine)
    if current_version == 18:
        current_version = migrate_v18_to_v19(engine)
    if current_version == 19:
        current_version = migrate_v19_to_v20(engine)
    if current_version == 20:
        current_version = migrate_v20_to_v21(engine)
    if current_version == 21:
        current_version = migrate_v21_to_v22(engine)
    if current_version == 22:
        current_version = migrate_v22_to_v23(engine)
    if current_version == 23:
        current_version = migrate_v23_to_v24(engine)
    if current_version == 24:
        current_version = migrate_v24_to_v25(engine)
    if current_version == CURRENT_SCHEMA_VERSION:
        return current_version
    raise ValidationError(
        f"Local schema version {current_version} cannot be upgraded automatically to "
        f"schema v{CURRENT_SCHEMA_VERSION}. Preserve the runtime state and use the "
        "documented storage recovery flow."
    )


def _json_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item)]


def _json_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
    else:
        parsed = value
    if not isinstance(parsed, dict):
        return {}
    return dict(parsed)


def _evaluation_kind_for_problem_kind(problem_kind: object) -> str:
    if problem_kind == "regression":
        return "regression"
    if problem_kind == "classification":
        return "classification"
    if problem_kind in {"clustering", "anomaly_detection", "analysis"}:
        return "summary"
    return "none"


def _migrate_evaluation_payload(payload: dict[str, object]) -> dict[str, object]:
    problem_kind = payload.pop("problem_kind", None)
    evaluation_policy = payload.get("evaluation_policy")
    has_evaluation_contract = (
        problem_kind is not None
        or "evaluation_kind" in payload
        or isinstance(evaluation_policy, dict)
    )
    if not has_evaluation_contract:
        return payload
    if "evaluation_kind" not in payload:
        payload["evaluation_kind"] = _evaluation_kind_for_problem_kind(problem_kind)
    if isinstance(evaluation_policy, dict):
        policy_problem_kind = evaluation_policy.pop("problem_kind", problem_kind)
        if "evaluation_kind" not in evaluation_policy:
            evaluation_policy["evaluation_kind"] = _evaluation_kind_for_problem_kind(policy_problem_kind)
    return payload
