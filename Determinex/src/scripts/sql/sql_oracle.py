"""
Deterministic SQL oracle for verifier-backed SQL repair traces.

The first backend is sqlite because it is stdlib, local, and deterministic.
It provides schema inspection, unsafe-query blocking, result normalization,
execution, comparison, controlled mutation, and signed corpus write helpers.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BLOCKED_SQL_RE = re.compile(
    r"\b(attach|detach|drop|delete|update|insert|alter|create|replace|pragma\s+writable_schema|vacuum)\b",
    re.I,
)


@dataclass
class SqlColumn:
    table: str
    name: str
    type: str
    not_null: bool
    primary_key: bool


@dataclass
class SqlSchema:
    dialect: str
    tables: list[str] = field(default_factory=list)
    columns: list[SqlColumn] = field(default_factory=list)


@dataclass
class SqlExecutionResult:
    ok: bool
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    error: str = ""


@dataclass
class SqlRepairTrace:
    task_id: str
    question: str
    dialect: str
    initial_sql: str
    repaired_sql: str
    expected_rows: list[tuple[Any, ...]]
    initial_result: SqlExecutionResult
    final_result: SqlExecutionResult
    mutation_type: str = "predicate_flip"
    source_benchmark: str = "sql_oracle"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "sql",
            "dialect": self.dialect,
            "mutation_type": self.mutation_type,
            "question": self.question[:500],
            "initial_sql": self.initial_sql[:1000],
            "repaired_sql": self.repaired_sql[:1000],
            "expected_rows": _json_safe_rows(self.expected_rows),
            "initial_ok": self.initial_result.ok,
            "initial_error": self.initial_result.error[:500],
            "final_ok": self.final_result.ok,
            "final_rows": _json_safe_rows(self.final_result.rows),
            "validator": "sqlite execute + normalized result comparator",
            "verdict": "pass" if self.final_result.ok else "fail",
            "task_id": self.task_id,
        }


class SqlOracle:
    def __init__(self, db_path: Path | str = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def load_schema(self) -> SqlSchema:
        tables = [
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        columns: list[SqlColumn] = []
        for table in tables:
            for cid, name, col_type, not_null, default, pk in self._conn.execute(
                f"PRAGMA table_info({table})"
            ):
                columns.append(
                    SqlColumn(
                        table=table,
                        name=name,
                        type=col_type or "",
                        not_null=bool(not_null),
                        primary_key=bool(pk),
                    )
                )
        return SqlSchema(dialect="sqlite", tables=tables, columns=columns)

    def is_safe_query(self, sql: str) -> bool:
        stripped = sql.strip()
        if not stripped.lower().startswith(("select", "with")):
            return False
        if ";" in stripped.rstrip(";"):
            return False
        return _BLOCKED_SQL_RE.search(stripped) is None

    def execute(self, sql: str) -> SqlExecutionResult:
        if not self.is_safe_query(sql):
            return SqlExecutionResult(ok=False, error="unsafe_sql_blocked")
        try:
            rows = self._conn.execute(sql).fetchall()
            return SqlExecutionResult(ok=True, rows=rows)
        except sqlite3.Error as exc:
            return SqlExecutionResult(ok=False, error=str(exc))

    def compare(
        self, actual: list[tuple[Any, ...]], expected: list[tuple[Any, ...]], ordered: bool = False
    ) -> bool:
        return normalize_rows(actual, ordered=ordered) == normalize_rows(expected, ordered=ordered)

    def mutate_predicate(self, sql: str) -> str:
        if " = " in sql:
            return sql.replace(" = ", " != ", 1)
        if "!=" in sql:
            return sql.replace("!=", "=", 1)
        return sql

    def write_corpus_record(self, corpus_manager: Any, trace: SqlRepairTrace) -> str:
        from agents.base_agent import CorpusType

        payload = trace.to_corpus_payload()
        input_hash = hashlib.blake2b(
            (trace.question + trace.initial_sql).encode(), digest_size=16
        ).hexdigest()
        output_hash = hashlib.blake2b(trace.repaired_sql.encode(), digest_size=16).hexdigest()
        record = corpus_manager._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=trace.task_id,
            input_hash=input_hash,
            output_hash=output_hash,
            source_benchmark=trace.source_benchmark,
            payload=payload,
        )
        corpus_manager._write_record(CorpusType.CODE_VERDICT, record)
        return trace.task_id


def normalize_rows(rows: list[tuple[Any, ...]], ordered: bool = False) -> list[tuple[str, ...]]:
    normalized = [tuple("" if v is None else str(v) for v in row) for row in rows]
    return normalized if ordered else sorted(normalized)


def _json_safe_rows(rows: list[tuple[Any, ...]]) -> list[list[Any]]:
    return [list(row) for row in rows]
