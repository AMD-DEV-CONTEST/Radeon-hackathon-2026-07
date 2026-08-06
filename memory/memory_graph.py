"""Conversation memory layer using Neo4j graph database.

Schema:
  (Session {id, created_at, topic})
  (Message {id, role, content, timestamp})
  (Entity {name, type: "person"|"movie"|"topic"})
  (Fact {key, value})

Relationships:
  (Session)-[:HAS_MESSAGE]->(Message)
  (Message)-[:MENTIONS]->(Entity)
  (Session)-[:ABOUT]->(Entity)
  (Message)-[:NEXT]->(Message)

Tools:
  store_message()  -- persist a conversation turn
  get_recent_memory() -- read last N messages
  search_memory()  -- keyword search across sessions
  extract_entities() -- LLM-based entity extraction
  store_fact() / get_facts() -- user preference storage
"""

import logging
import time

from database.neo4j_client import DatabaseError, Neo4jClient
from utils.timing import timing

logger = logging.getLogger(__name__)


# ─── Message Storage ─────────────────────────────────────────────


@timing(name="store_message")
def store_message(session_id: str, role: str, content: str) -> dict:
    """Store a message in the conversation graph.

    Args:
        session_id: Unique session identifier.
        role: "user" or "assistant".
        content: Message text.
    """
    msg_id = f"{session_id}:{role}:{int(time.time() * 1000)}"

    # Ensure session exists
    Neo4jClient.get_driver().execute_query(
        "MERGE (s:Session {id: $sid}) ON CREATE SET s.created_at = timestamp()",
        {"sid": session_id},
    )

    # Create message node
    Neo4jClient.get_driver().execute_query(
        "CREATE (m:Message {id: $mid, role: $role, content: $content, timestamp: timestamp()})",
        {"mid": msg_id, "role": role, "content": content},
    )

    # Link session → message
    Neo4jClient.get_driver().execute_query(
        "MATCH (s:Session {id: $sid}), (m:Message {id: $mid}) CREATE (s)-[:HAS_MESSAGE]->(m)",
        {"sid": session_id, "mid": msg_id},
    )

    # Messages are already ordered by timestamp via HAS_MESSAGE
    # NEXT chain is optional; skip for simplicity

    logger.debug("Stored message: %s", msg_id)
    return {"id": msg_id, "role": role}


# ─── Memory Retrieval ────────────────────────────────────────────


@timing(name="get_recent_memory")
def get_recent_memory(session_id: str, n: int = 10) -> list[dict]:
    """Retrieve the last N messages for a session."""
    try:
        result = Neo4jClient.execute(
            "MATCH (s:Session {id: $sid})-[:HAS_MESSAGE]->(m:Message) "
            "RETURN m.role AS role, m.content AS content, m.timestamp AS timestamp "
            "ORDER BY m.timestamp DESC LIMIT $n",
            {"sid": session_id, "n": n},
        )
        return list(reversed(result))
    except DatabaseError:
        return []


@timing(name="search_memory")
def search_memory(query: str, limit: int = 5) -> list[dict]:
    """Keyword search across all sessions."""
    try:
        result = Neo4jClient.execute(
            "MATCH (m:Message) "
            "WHERE m.content CONTAINS $q "
            "RETURN m.content AS content, m.role AS role, m.timestamp AS timestamp "
            "ORDER BY m.timestamp DESC LIMIT $n",
            {"q": query, "n": limit},
        )
        return result
    except DatabaseError:
        return []


@timing(name="get_session_summary")
def get_session_summary(session_id: str) -> str:
    """Get a summary of the current session for context injection."""
    messages = get_recent_memory(session_id, n=20)
    if not messages:
        return ""

    lines = ["## 对话记忆", ""]
    for msg in messages:
        role_label = "用户" if msg["role"] == "user" else "助手"
        content = msg.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"- **{role_label}**: {content}")

    # Add facts
    facts = get_facts(session_id)
    if facts:
        lines.append("")
        lines.append("## 已知信息")
        for f in facts:
            lines.append(f"- {f['key']}: {f['value']}")

    return "\n".join(lines)


# ─── Entity Extraction ───────────────────────────────────────────


@timing(name="extract_entities")
def extract_entities(text: str) -> list[dict]:
    """Extract named entities (people, movies, topics) from text using LLM.

    Returns list of {"name": str, "type": str}.
    """
    from openai import OpenAI

    from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL

    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return _rule_based_entity_extract(text)

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    prompt = f"""从以下文本中提取实体（人名、电影名、话题）。返回 JSON 格式。

文本：{text}

格式：[{{"name": "实体名称", "type": "person|movie|topic"}}]
只返回 JSON 数组，不要其他文字。"""

    try:
        resp = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        import json

        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
        entities = json.loads(raw)
        return [e for e in entities if isinstance(e, dict) and "name" in e]
    except Exception as e:
        logger.warning("Entity extraction failed: %s", e)
        return []


def _rule_based_entity_extract(text: str) -> list[dict]:
    """Fallback: keyword-based entity extraction for movie database."""
    entities = []
    known_people = [
        "Keanu Reeves",
        "Tom Hanks",
        "Leonardo DiCaprio",
        "Christopher Nolan",
        "Marlon Brando",
        "Al Pacino",
        "Robin Wright",
        "Matt Damon",
        "Michael Caine",
        "Anne Hathaway",
        "Carrie-Anne Moss",
        "Laurence Fishburne",
        "Sally Field",
        "Robert Zemeckis",
        "Francis Ford Coppola",
    ]
    known_movies = [
        "The Matrix",
        "Forrest Gump",
        "Inception",
        "Interstellar",
        "The Godfather",
        "Cast Away",
    ]

    for person in known_people:
        if person.lower() in text.lower():
            entities.append({"name": person, "type": "person"})
    for movie in known_movies:
        if movie.lower() in text.lower():
            entities.append({"name": movie, "type": "movie"})

    return entities


# ─── Entity Storage ──────────────────────────────────────────────


@timing(name="store_entities")
def store_entities(session_id: str, entities: list[dict]) -> None:
    """Store extracted entities and link to session."""
    for entity in entities:
        name = entity.get("name", "")
        etype = entity.get("type", "topic")
        if not name:
            continue
        # Merge entity node
        Neo4jClient.get_driver().execute_query(
            "MERGE (e:Entity {name: $name, type: $type})",
            {"name": name, "type": etype},
        )
        # Link session to entity
        Neo4jClient.get_driver().execute_query(
            "MATCH (s:Session {id: $sid}), (e:Entity {name: $name}) MERGE (s)-[:ABOUT]->(e)",
            {"sid": session_id, "name": name},
        )
    logger.debug("Stored %d entities", len(entities))


# ─── Facts (User Preferences) ────────────────────────────────────


@timing(name="store_fact")
def store_fact(session_id: str, key: str, value: str) -> None:
    """Store a learned fact about the user."""
    Neo4jClient.get_driver().execute_query(
        "MERGE (f:Fact {key: $key, session_id: $sid}) SET f.value = $value",
        {"key": key, "value": value, "sid": session_id},
    )


@timing(name="get_facts")
def get_facts(session_id: str) -> list[dict]:
    """Retrieve stored facts for a session."""
    try:
        result = Neo4jClient.execute(
            "MATCH (f:Fact {session_id: $sid}) RETURN f.key AS key, f.value AS value",
            {"sid": session_id},
        )
        return result
    except DatabaseError:
        return []


# ─── Cleanup ─────────────────────────────────────────────────────


def clean_old_sessions(max_age_days: int = 30) -> int:
    """Remove sessions older than max_age_days. Returns count of deleted sessions."""
    driver = Neo4jClient.get_driver()
    result = driver.execute_query(
        "MATCH (s:Session) "
        "WHERE s.created_at < (timestamp() - $age) "
        "DETACH DELETE s "
        "RETURN count(s) AS deleted",
        {"age": max_age_days * 24 * 3600 * 1000},
    )
    count = result.records[0]["deleted"]
    logger.info("Cleaned %d old sessions", count)
    return count
