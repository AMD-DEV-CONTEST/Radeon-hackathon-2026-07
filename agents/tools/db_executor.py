"""Execute Cypher queries against Neo4j database."""

from database.neo4j_client import (
    DatabaseError,
    Neo4jClient,
    QueryTimeoutError,
    ReadOnlyViolationError,
)
from utils.logger import setup_logging
from utils.timing import timing

logger = setup_logging(__name__)


@timing(name="db_executor")
def execute_db(cypher_query: str) -> dict:
    """Execute a read-only Cypher query and return results.

    Args:
        cypher_query: The Cypher query to execute.

    Returns:
        dict with keys:
            - success: bool
            - data: list of dicts (if successful)
            - error: str (if failed)
    """
    if not cypher_query or cypher_query == "NOT_A_QUERY":
        return {"success": False, "error": "No query to execute", "data": None}

    try:
        results = Neo4jClient.execute(cypher_query)
        logger.info("Query returned %d rows", len(results))
        return {"success": True, "data": results, "error": None}
    except ReadOnlyViolationError as e:
        logger.warning("Blocked write query: %s", e)
        return {"success": False, "error": str(e), "data": None}
    except QueryTimeoutError as e:
        logger.error("Query timeout: %s", e)
        return {"success": False, "error": str(e), "data": None}
    except DatabaseError as e:
        logger.error("Database error: %s", e)
        return {"success": False, "error": str(e), "data": None}
