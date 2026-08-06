"""app/grading.py — normative grading contract (Todo 7, per docs/domain-contract.md §4).

The grading contract is transcribed VERBATIM from the domain contract — no design
freedom:
  - Versioned prompt GRADING_PROMPT_V1 with a FIXED output schema.
  - Rubric weights: every key_point weight 1.0.
  - The SERVER recomputes the authoritative score from *validated* matched key
    points; the model's `score`/`mastery_level` fields are advisory only.
  - Accepted misconceptions come from the unit's CHECKED-IN list.
  - FAIL-CLOSED: malformed or unavailable judgment -> attempt row status='failed',
    NO schedule update, session stays active, retryable error surfaces.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from . import llm
from .processing import normalize_key

GRADING_PROMPT_V1 = """你是学习单元的评分裁判。根据学习单元的内容和用户回忆回答，输出固定 JSON。

【学习单元】
内容：{content}
关键点（key_points，每条权重 1.0）：{key_points}
来源引用：{source_quote}
已接受的误解（accepted misconceptions，只有列出的才算误解）：{accepted_misconceptions}

【用户回忆】
{recall}

【判定规则】
1. matched_key_points 只能从上述 key_points 中选取（规范化一致才算匹配），每条权重 1.0。
2. 如果用户回忆命中 accepted misconceptions 中的任何一条，needs_retry 必须为 true，
   且该命中不得计入 matched_key_points。
3. score / mastery_level 仅供参考；服务端会依据 matched_key_points 重算权威分数。
4. 输出必须是合法 JSON，schema 如下：
{{"feedback": string, "score": int(0-5), "mastery_level": int(0-5),
  "needs_retry": bool, "matched_key_points": [string]}}
"""

OUTPUT_SCHEMA_KEYS = {"feedback", "score", "mastery_level", "needs_retry", "matched_key_points"}
RUBRIC_WEIGHT = 1.0  # every key_point weight 1.0 (contract-enumerated)


class GradingUnavailable(Exception):
    """Model unavailable (or LC_GRADER_STUB=unavailable) -> fail-closed."""


class GradingMalformed(Exception):
    """Judgment output failed schema validation -> fail-closed."""


def build_prompt(unit: dict, recall: str) -> str:
    return GRADING_PROMPT_V1.format(
        content=unit.get("content", ""),
        key_points=json.dumps(unit.get("key_points", []), ensure_ascii=False),
        source_quote=unit.get("source_quote", ""),
        accepted_misconceptions=json.dumps(unit.get("accepted_misconceptions", []), ensure_ascii=False),
        recall=recall,
    )


def call_grader(unit: dict, recall: str) -> dict:
    """Call the verified grading model and return a VALIDATED judgment dict.

    Raises GradingUnavailable (fail-closed) when LC_GRADER_STUB=unavailable or
    the local model call fails; raises GradingMalformed when the parsed output
    does not match the fixed schema.
    """
    if os.environ.get("LC_GRADER_STUB") == "unavailable":
        raise GradingUnavailable("grading model unavailable (LC_GRADER_STUB=unavailable)")

    system = "你是严谨的学习评测裁判。只输出符合 schema 的 JSON，不要输出其他内容。"
    user = build_prompt(unit, recall)
    resp = llm.batch_chat(system, user, max_tokens=512, json_mode=True)
    if not resp.get("ok"):
        raise GradingUnavailable(resp.get("error", "grading model call failed"))

    try:
        parsed = json.loads(resp["content"])
    except (json.JSONDecodeError, TypeError) as e:
        raise GradingMalformed(f"unparseable judgment JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise GradingMalformed("judgment is not a JSON object")
    missing = OUTPUT_SCHEMA_KEYS - set(parsed.keys())
    if missing:
        raise GradingMalformed(f"judgment missing schema keys: {sorted(missing)}")
    if not isinstance(parsed.get("matched_key_points"), list):
        raise GradingMalformed("matched_key_points must be a list")
    try:
        int(parsed["score"])
        int(parsed["mastery_level"])
    except (TypeError, ValueError) as e:
        raise GradingMalformed(f"score/mastery_level must be ints: {e}") from e
    return parsed


def authoritative_score(unit: dict, matched_key_points: list) -> int:
    """Server-recomputed authoritative score: sum of weights of VALIDATED matched
    key points, clamped to [0,5]. Model advisory score is ignored.

    Validation: a matched key point counts only if its normalized key matches a
    key point on the unit's checked-in list.
    """
    unit_keys = {normalize_key(kp) for kp in unit.get("key_points", [])}
    valid = [kp for kp in matched_key_points if normalize_key(kp) in unit_keys]
    return max(0, min(5, int(len(valid) * RUBRIC_WEIGHT)))


def misconception_hit(unit: dict, recall: str) -> Optional[str]:
    """First accepted misconception (checked-in list) hit by the recall, if any."""
    rn = normalize_key(recall)
    for mc in unit.get("accepted_misconceptions", []):
        if normalize_key(str(mc)) and normalize_key(str(mc)) in rn:
            return str(mc)
    return None
