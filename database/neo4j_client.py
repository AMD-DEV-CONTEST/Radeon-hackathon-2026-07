"""Neo4j client wrapper with connection pool and read-only enforcement."""

import logging
from typing import Any

from neo4j import Driver, GraphDatabase, Result
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from config.settings import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)

# Allowed clauses for read-only enforcement
_ALLOWED_CLAUSES = {
    "MATCH",
    "RETURN",
    "WITH",
    "WHERE",
    "ORDER BY",
    "SKIP",
    "LIMIT",
    "UNWIND",
    "CALL",
    "YIELD",
    "OPTIONAL MATCH",
    "UNION",
    "UNION ALL",
}


class DatabaseError(Exception):
    """Custom exception for database errors."""


class QueryTimeoutError(DatabaseError):
    """Query exceeded time limit."""


class ReadOnlyViolationError(DatabaseError):
    """Write operation detected in read-only mode."""


class Neo4jClient:
    """Encapsulates Neo4j driver with connection pool and safety checks."""

    _driver: Driver | None = None

    @classmethod
    def get_driver(cls) -> Driver:
        """Return singleton driver instance."""
        if cls._driver is None:
            cls._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_pool_size=10,
                connection_acquisition_timeout=15,
            )
            logger.info("Neo4j driver initialized: %s", NEO4J_URI)
        return cls._driver

    @classmethod
    def close(cls) -> None:
        """Close the driver."""
        if cls._driver is not None:
            cls._driver.close()
            cls._driver = None
            logger.info("Neo4j driver closed")

    @classmethod
    def health_check(cls) -> bool:
        """Return True if database is reachable."""
        try:
            driver = cls.get_driver()
            driver.verify_connectivity()
            return True
        except (ServiceUnavailable, SessionExpired) as e:
            logger.warning("Neo4j health check failed: %s", e)
            return False

    @classmethod
    def _is_read_only(cls, query: str) -> bool:
        """Validate that the query contains only read operations."""
        stripped = query.strip().upper()
        for clause in _ALLOWED_CLAUSES:
            if stripped.startswith(clause):
                return True
        # Also check CALL (for schema introspection)
        if stripped.startswith("CALL") or stripped.startswith("SHOW"):
            return True
        return False

    @classmethod
    def execute(
        cls, query: str, params: dict[str, Any] | None = None, timeout: int = 10
    ) -> list[dict[str, Any]]:
        """Execute a read-only Cypher query and return results as list of dicts.

        Args:
            query: Cypher query string (MATCH only).
            params: Query parameters for safe parameterization.
            timeout: Max execution time in seconds.

        Returns:
            List of result rows as dictionaries.

        Raises:
            ReadOnlyViolationError: If query contains write operations.
            DatabaseError: On query syntax or execution errors.
            QueryTimeoutError: If query exceeds timeout.
        """
        if not cls._is_read_only(query):
            raise ReadOnlyViolationError(f"Write operation detected in query: {query[:80]}...")

        driver = cls.get_driver()
        params = params or {}

        try:
            with driver.session(database="neo4j") as session:
                result: Result = session.run(query, params, timeout=timeout)
                records = []
                for record in result:
                    row = {}
                    for key in record.keys():
                        value = record[key]
                        # Convert neo4j nodes/relationships to dicts for JSON serialization
                        row[key] = _serialize_value(value)
                    records.append(row)
                return records
        except Neo4jError as e:
            if "timeout" in str(e).lower():
                logger.error("Query timeout: %s", e)
                raise QueryTimeoutError(f"查询较慢，稍后重试 ({e})") from e
            logger.error("Database error: %s", e)
            raise DatabaseError(f"查询执行失败: {e}") from e

    @classmethod
    def execute_single(
        cls, query: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute a query expecting a single result row."""
        rows = cls.execute(query, params)
        return rows[0] if rows else None


def _serialize_value(value: Any) -> Any:
    """Convert Neo4j types to plain Python dicts/lists for JSON compat."""
    if value is None:
        return None
    if hasattr(value, "_properties"):
        # Neo4j Node or Relationship
        props = dict(value._properties)
        if hasattr(value, "labels"):
            # Node
            return {"_labels": list(value.labels), "_properties": props}
        else:
            # Relationship
            return {"_type": value.type, "_properties": props}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value
