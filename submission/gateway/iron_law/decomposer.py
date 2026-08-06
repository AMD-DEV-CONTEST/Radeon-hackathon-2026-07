"""
ILS v2.3 - Vectorized Dynamic Task Decomposition Engine (Task Decomposer)

Core flow:
  1. Embed the incoming goal via SiliconFlow BGE-large-zh-v1.5
  2. Search decomposition_patterns table for top-k similar past decompositions
  3. If high-confidence match (sim >= 0.85) found, adapt the cached DAG
  4. Otherwise, generate a fresh decomposition via LLM (DeepSeek)
  5. Normalize and validate the resulting DAG
  6. On successful task completion, persist the pattern + embedding back to DB
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]

logger = logging.getLogger("iron_law.decomposer")

# -- Config ---------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

SIMILARITY_THRESHOLD_HIGH = float(os.environ.get("DECOMPOSER_SIM_HIGH", "0.85"))
SIMILARITY_THRESHOLD_LOW = float(os.environ.get("DECOMPOSER_SIM_LOW", "0.60"))
MAX_PATTERNS_RETURN = int(os.environ.get("DECOMPOSER_TOP_K", "5"))


# -- Embedding ------------------------------------------------------------

def embed_text(text: str) -> list[float]:
    """Compute embedding vector via SiliconFlow embedding API."""
    if not EMBEDDING_API_KEY:
        raise RuntimeError("EMBEDDING_API_KEY not configured")

    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": text[:2000],
        "encoding_format": "float",
    }).encode()
    req = urllib.request.Request(
        EMBEDDING_BASE_URL + "/embeddings",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + EMBEDDING_API_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    vec = data["data"][0]["embedding"]
    if len(vec) != EMBEDDING_DIMENSIONS:
        logger.warning("Embedding dim mismatch: got %d, expected %d", len(vec), EMBEDDING_DIMENSIONS)
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy dependency)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# -- DB helpers -----------------------------------------------------------

def _connect():
    if psycopg is None:
        raise RuntimeError("psycopg not installed")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def search_similar_patterns(
    embedding: list[float],
    project: str = "default",
    top_k: int = MAX_PATTERNS_RETURN,
) -> list[dict[str, Any]]:
    """
    Retrieve decomposition_patterns ranked by cosine similarity.
    Filters by project. Returns top-k with similarity scores.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, intent_pattern, project, dag, embedding,
                   hit_count, success_count, failure_count,
                   last_hit_at, created_at, updated_at
            FROM decomposition_patterns
            WHERE project = %s AND array_length(embedding, 1) > 0
            ORDER BY hit_count DESC
            LIMIT 100
            """,
            (project,),
        ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        row_emb = row["embedding"]
        if not row_emb or len(row_emb) == 0:
            continue
        sim = cosine_similarity(embedding, row_emb)
        if sim >= SIMILARITY_THRESHOLD_LOW:
            entry = dict(row)
            entry["similarity"] = round(sim, 4)
            entry["id"] = str(entry["id"])
            del entry["embedding"]
            scored.append(entry)

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def store_pattern(
    intent_pattern: str,
    dag: list[dict[str, Any]],
    embedding: list[float],
    project: str = "default",
    pattern_id: str | None = None,
) -> str:
    """Persist a new decomposition pattern with its embedding."""
    pid = pattern_id or str(uuid4())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO decomposition_patterns
                (id, intent_pattern, project, dag, embedding,
                 hit_count, success_count, failure_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 0, 0, 0, now(), now())
            ON CONFLICT (id) DO UPDATE SET
                intent_pattern = EXCLUDED.intent_pattern,
                dag = EXCLUDED.dag,
                embedding = EXCLUDED.embedding,
                updated_at = now()
            """,
            (pid, intent_pattern, project, Jsonb(dag), embedding),
        )
        conn.commit()
    logger.info("Stored decomposition pattern %s (project=%s)", pid[:8], project)
    return pid


def update_pattern_stats(pattern_id: str, success: bool) -> None:
    """Increment hit_count and success/failure counters for a pattern."""
    with _connect() as conn:
        col = "success_count" if success else "failure_count"
        conn.execute(
            """
            UPDATE decomposition_patterns
            SET hit_count = hit_count + 1,
                """ + col + " = " + col + """ + 1,
                last_hit_at = now(),
                updated_at = now()
            WHERE id = %s
            """,
            (pattern_id,),
        )
        conn.commit()


def store_task_embedding(task_id: str, goal: str, embedding: list[float]) -> None:
    """Cache the embedding for a task goal."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO task_embeddings (task_id, goal, embedding, created_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (task_id) DO UPDATE SET
                goal = EXCLUDED.goal,
                embedding = EXCLUDED.embedding
            """,
            (task_id, goal, embedding),
        )
        conn.commit()


def get_pattern(pattern_id: str) -> dict[str, Any] | None:
    """Fetch a single pattern by ID."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM decomposition_patterns WHERE id = %s",
            (pattern_id,),
        ).fetchone()
    if row:
        entry = dict(row)
        entry["id"] = str(entry["id"])
        return entry
    return None


def list_patterns(project: str = "default", limit: int = 50) -> list[dict[str, Any]]:
    """List all patterns for a project, ordered by hit_count."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, intent_pattern, project, dag, hit_count,
                   success_count, failure_count, last_hit_at, created_at
            FROM decomposition_patterns
            WHERE project = %s
            ORDER BY hit_count DESC
            LIMIT %s
            """,
            (project, limit),
        ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["id"] = str(entry["id"])
        result.append(entry)
    return result


# -- LLM Decomposition ----------------------------------------------------

DECOMPOSE_SYSTEM = """你是 UnionAgents 的任务分解引擎。
将用户的目标分解为具体的、可执行的子任务 DAG。

可用 Agent 类型:
- claude: 规划、代码审查、架构决策、文档
- reasonix: 文件编辑、代码实现、运行命令、测试
- codex: 复杂多文件实现、重构

输出 JSON 对象:
{
  "intent_pattern": "一句话概括这个需求的核心意图（<=30字）",
  "tasks": [
    {
      "title": "短标题（<=60字）",
      "task_type": "coding",
      "payload": { "instruction": "详细的 Agent 指令" },
      "required_capabilities": { "agent": "reasonix" },
      "dependencies": [],
      "acceptance_check": { "type": "command", "command": ["pytest", "-q"], "expected_exit_code": 0 },
      "estimated_hours": 0.5,
      "priority": 50
    }
  ]
}

规则:
- 每个任务必须原子化（一个 Agent、一个关注点）
- dependencies 用 0-based 索引引用数组中其他任务
- implementation 默认用 reasonix，review 默认用 claude
- 最多 8 个子任务
- 每个任务必须有 acceptance_check
- 每个任务估时不超过 1 小时
- intent_pattern 必须精炼，用于未来向量匹配
"""

ADAPT_SYSTEM = """你是 UnionAgents 的任务分解引擎。
基于一个历史成功分解模式，适配当前需求。

输入:
- current_goal: 当前需求
- reference_pattern: 一个相似的历史分解模式（含 DAG）

你可以:
1. 直接复用参考模式的 DAG（如果需求非常相似）
2. 基于参考模式微调（修改细节、调整依赖）
3. 大幅改写（仅保留结构思路）

输出 JSON 对象（格式同上）。
"""


def _llm_chat(system: str, user_msg: str) -> str:
    """Call DeepSeek LLM."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        DEEPSEEK_BASE + "/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + DEEPSEEK_API_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def _generate_fresh(goal: str, project: str) -> dict[str, Any]:
    """Generate a new decomposition from scratch via LLM."""
    user_msg = "目标: " + goal + "\n项目: " + project
    raw = _llm_chat(DECOMPOSE_SYSTEM, user_msg)
    return _parse_llm_json(raw)


def _adapt_pattern(goal: str, pattern: dict[str, Any]) -> dict[str, Any]:
    """Adapt an existing pattern for a new goal via LLM."""
    dag_json = json.dumps(pattern.get("dag", []), ensure_ascii=False, indent=2)
    user_msg = "current_goal: " + goal + "\n\nreference_pattern:\n" + dag_json
    raw = _llm_chat(ADAPT_SYSTEM, user_msg)
    return _parse_llm_json(raw)


# -- DAG Normalization -----------------------------------------------------

def _normalize_dag(raw_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalize LLM output into a standard task DAG format.
    Resolves index-based dependencies to placeholder IDs and ensures required fields.
    """
    task_ids: list[str] = [str(uuid4()) for _ in raw_tasks]
    normalized: list[dict[str, Any]] = []

    for i, task in enumerate(raw_tasks):
        # Resolve index-based dependencies
        raw_deps = task.get("dependencies", [])
        resolved_deps: list[str] = []
        for dep in raw_deps:
            if isinstance(dep, int) and 0 <= dep < len(task_ids) and dep != i:
                resolved_deps.append(task_ids[dep])
            elif isinstance(dep, str):
                resolved_deps.append(dep)

        # Normalize required_capabilities
        caps = task.get("required_capabilities", {})
        if isinstance(caps, list):
            normalized_caps: dict[str, Any] = {}
            for item in caps:
                if isinstance(item, str) and ":" in item:
                    k, v = item.split(":", 1)
                    normalized_caps[k] = v
                elif isinstance(item, str):
                    normalized_caps[item] = True
            caps = normalized_caps

        # Default acceptance_check
        ac = task.get("acceptance_check")
        if not ac:
            ac = {"type": "command", "command": ["echo", "ok"], "expected_exit_code": 0}

        normalized.append({
            "id": task_ids[i],
            "title": task.get("title", "Subtask " + str(i + 1)),
            "description": task.get("payload", {}).get("instruction", ""),
            "task_type": task.get("task_type", "coding"),
            "payload": task.get("payload", {}),
            "required_capabilities": caps,
            "dependencies": resolved_deps,
            "acceptance_check": ac,
            "estimated_hours": task.get("estimated_hours", 0.5),
            "priority": task.get("priority", 50),
        })

    return normalized


# -- Main API --------------------------------------------------------------

def decompose(
    goal: str,
    project: str = "default",
    task_id: str | None = None,
    force_fresh: bool = False,
) -> dict[str, Any]:
    """
    Main entry point: vectorized dynamic task decomposition.

    1. Embed the goal
    2. Search for similar patterns
    3. If high-confidence match found, adapt; else generate fresh
    4. Normalize DAG
    5. Store embedding (and optionally the new pattern)
    """
    # 1. Embed
    try:
        embedding = embed_text(goal)
    except Exception as exc:
        logger.warning("Embedding failed, falling back to LLM-only: %s", exc)
        embedding = []

    # Cache embedding if task_id provided
    if task_id and embedding:
        try:
            store_task_embedding(task_id, goal, embedding)
        except Exception as exc:
            logger.warning("Failed to cache task embedding: %s", exc)

    # 2. Search similar patterns
    matched_pattern: dict[str, Any] | None = None
    similarity: float | None = None

    if not force_fresh and embedding:
        try:
            candidates = search_similar_patterns(embedding, project=project)
            if candidates and candidates[0]["similarity"] >= SIMILARITY_THRESHOLD_HIGH:
                matched_pattern = candidates[0]
                similarity = matched_pattern["similarity"]
                logger.info(
                    "High-confidence match: pattern=%s sim=%.3f",
                    matched_pattern["id"][:8], similarity,
                )
        except Exception as exc:
            logger.warning("Pattern search failed: %s", exc)

    # 3. Decompose
    if matched_pattern and similarity and similarity >= SIMILARITY_THRESHOLD_HIGH:
        try:
            result = _adapt_pattern(goal, matched_pattern)
            source = "adapted"
        except Exception as exc:
            logger.warning("Adaptation failed, falling back to fresh: %s", exc)
            result = _generate_fresh(goal, project)
            source = "fresh"
            matched_pattern = None
            similarity = None
    else:
        try:
            result = _generate_fresh(goal, project)
            source = "fresh"
        except Exception as exc:
            logger.error("LLM decomposition failed: %s", exc)
            raise

    # 4. Normalize
    raw_tasks = result.get("tasks", [])
    if not raw_tasks:
        raise ValueError("LLM returned empty task list")

    dag = _normalize_dag(raw_tasks)
    intent_pattern = result.get("intent_pattern", goal[:50])

    # 5. Store new pattern (only for fresh decompositions)
    stored = False
    if source == "fresh" and embedding:
        try:
            store_pattern(
                intent_pattern=intent_pattern,
                dag=[{k: v for k, v in t.items() if k != "id"} for t in dag],
                embedding=embedding,
                project=project,
            )
            stored = True
        except Exception as exc:
            logger.warning("Failed to store new pattern: %s", exc)

    return {
        "decomposition": dag,
        "source": source,
        "matched_pattern_id": matched_pattern["id"] if matched_pattern else None,
        "similarity": similarity,
        "intent_pattern": intent_pattern,
        "embedding_stored": stored,
    }


def record_decomposition_outcome(
    pattern_id: str,
    success: bool,
) -> None:
    """
    Update pattern stats after task group completes.
    Called from hooks.on_completion when the task originated from a decomposition.
    """
    try:
        update_pattern_stats(pattern_id, success)
        logger.info(
            "Pattern %s outcome: %s", pattern_id[:8], "success" if success else "failure"
        )
    except Exception as exc:
        logger.warning("Failed to update pattern stats: %s", exc)
