"""
SQL_ORACLE_LOCK_001 acceptance tests.

This lock gives Determinex a deterministic database oracle for BIRD/BIRD-Critic
style tasks: schema -> SQL -> execute -> compare -> repair trace -> signed
corpus row.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.corpus_manager import CorpusManager
from sql.sql_oracle import SqlExecutionResult, SqlOracle, SqlRepairTrace, normalize_rows


def _oracle() -> SqlOracle:
    oracle = SqlOracle()
    oracle.conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            total INTEGER NOT NULL
        );
        INSERT INTO users(id, name, active) VALUES (1, 'Ada', 1), (2, 'Grace', 0);
        INSERT INTO orders(id, user_id, total) VALUES (10, 1, 50), (11, 1, 25), (12, 2, 99);
        """
    )
    return oracle


class TestSqlSchemaLoader:
    def test_loads_tables(self):
        oracle = _oracle()
        schema = oracle.load_schema()
        assert schema.dialect == "sqlite"
        assert schema.tables == ["orders", "users"]

    def test_loads_columns(self):
        oracle = _oracle()
        schema = oracle.load_schema()
        names = {(c.table, c.name) for c in schema.columns}
        assert ("users", "name") in names
        assert ("orders", "total") in names

    def test_primary_key_metadata(self):
        oracle = _oracle()
        schema = oracle.load_schema()
        assert any(c.table == "users" and c.name == "id" and c.primary_key for c in schema.columns)


class TestSqlSafetyGate:
    def test_select_allowed(self):
        oracle = _oracle()
        assert oracle.is_safe_query("SELECT name FROM users") is True

    def test_with_allowed(self):
        oracle = _oracle()
        assert (
            oracle.is_safe_query("WITH active AS (SELECT * FROM users) SELECT name FROM active")
            is True
        )

    def test_drop_blocked(self):
        oracle = _oracle()
        assert oracle.is_safe_query("DROP TABLE users") is False

    def test_update_blocked(self):
        oracle = _oracle()
        assert oracle.is_safe_query("UPDATE users SET active = 0") is False

    def test_multi_statement_blocked(self):
        oracle = _oracle()
        assert oracle.is_safe_query("SELECT * FROM users; DROP TABLE users") is False

    def test_pragma_writable_schema_blocked(self):
        oracle = _oracle()
        assert oracle.is_safe_query("PRAGMA writable_schema=ON") is False


class TestSqlExecutionAndCompare:
    def test_executes_query(self):
        oracle = _oracle()
        result = oracle.execute("SELECT name FROM users WHERE active = 1")
        assert result.ok is True
        assert result.rows == [("Ada",)]

    def test_blocks_unsafe_execute(self):
        oracle = _oracle()
        result = oracle.execute("DELETE FROM users")
        assert result.ok is False
        assert result.error == "unsafe_sql_blocked"

    def test_reports_sql_error(self):
        oracle = _oracle()
        result = oracle.execute("SELECT missing FROM users")
        assert result.ok is False
        assert "missing" in result.error

    def test_normalizes_unordered_rows(self):
        assert normalize_rows([(2, "b"), (1, "a")]) == [("1", "a"), ("2", "b")]

    def test_ordered_compare_respects_order(self):
        oracle = _oracle()
        assert oracle.compare([(2,), (1,)], [(1,), (2,)], ordered=True) is False

    def test_unordered_compare_ignores_order(self):
        oracle = _oracle()
        assert oracle.compare([(2,), (1,)], [(1,), (2,)], ordered=False) is True


class TestSqlRepairTrace:
    def test_predicate_mutation_changes_query(self):
        oracle = _oracle()
        sql = "SELECT name FROM users WHERE active = 1"
        assert " != " in oracle.mutate_predicate(sql)

    def test_mutated_query_fails_expected_result(self):
        oracle = _oracle()
        expected = [("Ada",)]
        mutated = oracle.mutate_predicate("SELECT name FROM users WHERE active = 1")
        result = oracle.execute(mutated)
        assert result.ok is True
        assert oracle.compare(result.rows, expected) is False

    def test_repaired_query_matches_expected(self):
        oracle = _oracle()
        expected = [("Ada",)]
        result = oracle.execute("SELECT name FROM users WHERE active = 1")
        assert result.ok is True
        assert oracle.compare(result.rows, expected) is True

    def test_trace_payload_has_required_fields(self):
        oracle = _oracle()
        initial = oracle.execute("SELECT name FROM users WHERE active != 1")
        final = oracle.execute("SELECT name FROM users WHERE active = 1")
        trace = SqlRepairTrace(
            task_id="sql-trace-001",
            question="Which active users exist?",
            dialect="sqlite",
            initial_sql="SELECT name FROM users WHERE active != 1",
            repaired_sql="SELECT name FROM users WHERE active = 1",
            expected_rows=[("Ada",)],
            initial_result=initial,
            final_result=final,
        )
        payload = trace.to_corpus_payload()
        assert payload["language"] == "sql"
        assert payload["dialect"] == "sqlite"
        assert payload["verdict"] == "pass"


class TestSqlCorpusSigning:
    def test_sql_corpus_record_is_signed(self, tmp_path):
        oracle = _oracle()
        cm = CorpusManager(root=tmp_path / "corpus")
        trace = SqlRepairTrace(
            task_id="sql-sign-001",
            question="Which active users exist?",
            dialect="sqlite",
            initial_sql="SELECT name FROM users WHERE active != 1",
            repaired_sql="SELECT name FROM users WHERE active = 1",
            expected_rows=[("Ada",)],
            initial_result=oracle.execute("SELECT name FROM users WHERE active != 1"),
            final_result=oracle.execute("SELECT name FROM users WHERE active = 1"),
        )
        task_id = oracle.write_corpus_record(cm, trace)
        assert task_id == "sql-sign-001"

    def test_tampered_sql_record_fails_verification(self, tmp_path):
        oracle = _oracle()
        cm = CorpusManager(root=tmp_path / "corpus")
        trace = SqlRepairTrace(
            task_id="sql-sign-002",
            question="Which active users exist?",
            dialect="sqlite",
            initial_sql="SELECT name FROM users WHERE active != 1",
            repaired_sql="SELECT name FROM users WHERE active = 1",
            expected_rows=[("Ada",)],
            initial_result=oracle.execute("SELECT name FROM users WHERE active != 1"),
            final_result=oracle.execute("SELECT name FROM users WHERE active = 1"),
        )
        payload = trace.to_corpus_payload()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=trace.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="sql_oracle",
            payload=payload,
        )
        record["language"] = "python"
        assert cm.verify(record) is False

    def test_failed_final_verdict_payload(self):
        trace = SqlRepairTrace(
            task_id="sql-fail-001",
            question="bad query",
            dialect="sqlite",
            initial_sql="SELECT nope FROM users",
            repaired_sql="SELECT nope FROM users",
            expected_rows=[],
            initial_result=SqlExecutionResult(ok=False, error="no such column"),
            final_result=SqlExecutionResult(ok=False, error="no such column"),
        )
        assert trace.to_corpus_payload()["verdict"] == "fail"
