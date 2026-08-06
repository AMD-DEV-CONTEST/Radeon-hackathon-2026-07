"""Interpret database query results into natural language."""

from openai import OpenAI

from config.settings import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_LLM_MODEL,
)
from utils.logger import setup_logging
from utils.timing import timing

logger = setup_logging(__name__)

INTERPRETER_SYSTEM_PROMPT = """你是一个数据解释助手。根据用户的原始问题和数据库查询结果，生成简洁友好的中文回答。

## 规则
1. 用口语化的中文回答，适合语音输出
2. 突出关键信息，不要罗列所有数据
3. 如果结果为空，告诉用户没有找到相关数据
4. 回答简洁，控制在 2-4 句话以内
5. 不要使用 Markdown 格式
"""


@timing(name="result_interpreter")
def interpret_result(db_result: list[dict], user_query: str) -> str:
    """Convert raw database results into natural language.

    Args:
        db_result: List of result rows from the database.
        user_query: The original user question.

    Returns:
        Natural language answer string.
    """
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return _rule_based_interpret(db_result, user_query)

    if not db_result:
        return "抱歉，没有找到与您问题相关的数据。"

    # Limit data size for the prompt
    result_str = _format_data(db_result[:20])

    client = OpenAI(
        api_key=QWEN_API_KEY,
        base_url=QWEN_BASE_URL,
    )

    user_prompt = f"""用户问题：{user_query}

查询结果：
{result_str}

请用简洁的中文回答："""

    try:
        response = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {"role": "system", "content": INTERPRETER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        answer = response.choices[0].message.content.strip()
        logger.info("Interpreted result: %s", answer[:120])
        return answer
    except Exception as e:
        logger.error("Result interpretation failed: %s", e)
        return _rule_based_interpret(db_result, user_query)


def _format_data(data: list[dict]) -> str:
    """Format result data for LLM prompt."""
    if not data:
        return "(空)"
    lines = []
    for i, row in enumerate(data[:20], 1):
        items = [f"{k}: {v}" for k, v in row.items()]
        lines.append(f"{i}. {', '.join(items)}")
    return "\n".join(lines)


def _rule_based_interpret(data: list[dict], _user_query: str) -> str:
    """Fallback rule-based interpreter for testing without API key."""
    if not data:
        return "抱歉，没有找到相关数据。"

    count = len(data)
    if count == 1:
        items = ", ".join(f"{k}: {v}" for k, v in data[0].items())
        return f"查询结果：{items}。"

    # Collect unique values for common column names
    sample = data[:5]
    result_parts = []
    for row in sample:
        parts = []
        for k, v in row.items():
            if isinstance(v, (str, int, float)):
                parts.append(str(v))
        if parts:
            result_parts.append("、".join(parts))

    summary = "，".join(result_parts[:3])
    if count > len(sample):
        return f"共找到 {count} 条结果，包括：{summary} 等。"
    return f"找到以下结果：{summary}。"
