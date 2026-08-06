"""Generate Cypher queries from natural language using Qwen LLM."""

from openai import OpenAI

from config.settings import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_LLM_MODEL,
)
from utils.exception import CypherGenerationError
from utils.logger import setup_logging
from utils.timing import timing

logger = setup_logging(__name__)

CYPHER_SYSTEM_PROMPT = """你是一个 Neo4j Cypher 查询生成专家。根据用户的问题和图数据库 schema，生成正确的 Cypher 查询。

## 规则
1. 只生成 MATCH 查询，禁止 CREATE、DELETE、MERGE、SET、DROP 等写操作
2. 属性值直接写在查询中，使用单引号包裹（如 WHERE p.name = 'Keanu Reeves'）
3. 对于节点标签和关系类型，使用反引号包裹（如 `Person`）
4. 使用 RETURN 返回用户需要的字段
5. 如果用户的问题与查询无关，返回 "NOT_A_QUERY"
6. 不要使用 $参数化变量，直接在语句中写入具体值
7. 不要返回 Markdown 格式，只返回纯 Cypher 查询

## 输出格式
只返回 Cypher 查询语句，不要任何解释或 Markdown 标记。
如果无法生成查询，返回 "NOT_A_QUERY"。
"""


@timing(name="cypher_generator")
def generate_cypher(
    user_query: str,
    db_schema: str,
    conversation_history: list[str] | None = None,
) -> str:
    """Generate a Cypher query from natural language.

    Args:
        user_query: The user's question in natural language.
        db_schema: Formatted graph schema string.
        conversation_history: Previous Q&A pairs for context.

    Returns:
        A valid Cypher query string.

    Raises:
        CypherGenerationError: If query generation fails.
    """
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        logger.warning("No Qwen API key configured, using mock query generator")
        return _mock_generate(user_query, db_schema)

    client = OpenAI(
        api_key=QWEN_API_KEY,
        base_url=QWEN_BASE_URL,
    )

    # Build conversation context
    context = ""
    if conversation_history:
        context = "## 对话历史\n" + "\n".join(conversation_history[-6:]) + "\n\n"

    user_prompt = f"""{context}## 数据库 Schema
{db_schema}

## 用户问题
{user_query}

请生成 Cypher 查询："""

    try:
        response = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {"role": "system", "content": CYPHER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

        cypher = response.choices[0].message.content.strip()

        # Clean up markdown code blocks if present
        if cypher.startswith("```"):
            lines = cypher.split("\n")
            cypher = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        cypher = cypher.strip()

        if not cypher or cypher == "NOT_A_QUERY":
            return "NOT_A_QUERY"

        logger.info("Generated Cypher: %s", cypher[:120])
        return cypher

    except Exception as e:
        logger.error("Cypher generation failed: %s", e)
        raise CypherGenerationError(f"无法理解，请重试 ({e})") from e


def _mock_generate(user_query: str, _db_schema: str) -> str:
    """Fallback mock generator for testing without API key."""

    known_actors = {
        "keanu": "Keanu Reeves",
        "tom hanks": "Tom Hanks",
        "leonardo": "Leonardo DiCaprio",
        "dicaprio": "Leonardo DiCaprio",
        "matt damon": "Matt Damon",
        "al pacino": "Al Pacino",
        "robin wright": "Robin Wright",
    }

    query_lower = user_query.lower()

    def has_keyword(*words: str) -> bool:
        return any(w in query_lower for w in words)

    def match_actor() -> str | None:
        for key, name in known_actors.items():
            if key in query_lower:
                return name
        return None

    # Director queries (check first to avoid "导演过" matching actor pattern)
    if has_keyword("导演", "direct"):
        person = match_actor()
        if person:
            return (
                f"MATCH (p:Person {{name: '{person}'}})-[:DIRECTED]->(m:Movie) "
                "RETURN m.title AS title, m.released AS year"
            )
        return (
            "MATCH (p:Person)-[:DIRECTED]->(m:Movie) "
            "RETURN p.name AS director, collect(m.title) AS movies ORDER BY p.name"
        )

    # Actor queries
    if has_keyword("参演", "演过", "电影", "act", "出演"):
        person = match_actor()
        if person:
            return (
                f"MATCH (p:Person {{name: '{person}'}})-[:ACTED_IN]->(m:Movie) "
                "RETURN m.title AS title, m.released AS year"
            )
        return (
            "MATCH (p:Person)-[:ACTED_IN]->(m:Movie) "
            "RETURN p.name AS actor, m.title AS movie LIMIT 10"
        )

    # Chitchat / non-query
    if has_keyword("关系", "schema", "结构", "有哪些", "什么类型"):
        return "NOT_A_QUERY"

    # Default: recent movies
    return (
        "MATCH (m:Movie) RETURN m.title AS title, m.released AS year "
        "ORDER BY m.released DESC LIMIT 10"
    )
