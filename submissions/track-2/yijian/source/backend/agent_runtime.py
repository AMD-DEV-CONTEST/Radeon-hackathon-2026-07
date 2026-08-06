# -*- coding: utf-8 -*-
"""弈鉴问棋 Agent 的有界规划、工具投影、检索与显式本地记忆。

本模块不计算棋力，也不接受客户端坐标。规划只使用枚举目标；坐标、数值、
规则和变化均由服务端已经重建的 teaching-context 证据投影。任何记忆写入都
要求用户通过独立接口明确确认，模型规划本身没有写权限。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from copy import deepcopy
from pathlib import Path

import classical_go
from terminology import TERMS


PLAN_SCHEMA = "agent-plan-v1"
TRACE_SCHEMA = "agent-trace-v1"
TOOL_RESULT_SCHEMA = "agent-tool-results-v1"
KNOWLEDGE_SCHEMA = "yijian-local-knowledge-v1"

ALLOWED_TARGETS = {"actual", "best", "comparison", "position"}
ALLOWED_TOOLS = {
    "inspect_position",
    "compare_moves",
    "analyze_variations",
    "retrieve_principles",
    "recall_lessons",
    "remember_lesson",
}
TOOL_TARGETS = {
    "inspect_position": ALLOWED_TARGETS,
    "compare_moves": {"actual", "best", "comparison"},
    "analyze_variations": {"actual", "best", "comparison", "position"},
    "retrieve_principles": ALLOWED_TARGETS,
    "recall_lessons": {"actual", "best", "comparison", "position"},
    "remember_lesson": {"actual", "best", "comparison", "position"},
}
ALLOWED_FOCUS = {
    "move_order",
    "group_safety",
    "liberties",
    "connection",
    "cutting",
    "sente",
    "territory_influence",
    "thickness",
    "ko_resources",
    "joseki_direction",
    "opening_priority",
    "endgame_value",
    "evidence_boundary",
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
SESSION_RE = re.compile(r"^[0-9a-f]{32}$")
COORDINATE_RE = re.compile(r"\b[A-HJ-T](?:[1-9]|1[0-9])\b", re.I)
NUMBER_RE = re.compile(r"\d")
LESSON_RE = re.compile(r"^[0-9a-f]{32}$")


class AgentProtocolError(ValueError):
    """规划或工具请求违反服务端 Agent 契约。"""


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_plan(value: dict) -> dict:
    """严格验证 Planner 输出；未知字段、坐标和数字全部拒绝。"""
    if not isinstance(value, dict):
        raise AgentProtocolError("规划必须是JSON对象")
    if set(value) != {"schemaVersion", "questionTarget", "steps", "focus", "confidence"}:
        raise AgentProtocolError("规划字段不符合agent-plan-v1")
    if value.get("schemaVersion") != PLAN_SCHEMA:
        raise AgentProtocolError("规划版本不受支持")
    target = value.get("questionTarget")
    if target not in ALLOWED_TARGETS:
        raise AgentProtocolError("问题目标不合法")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        raise AgentProtocolError("工具步骤必须为1至3项")
    normalized_steps = []
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"tool", "target"}:
            raise AgentProtocolError("工具步骤只允许tool和target")
        tool = step.get("tool")
        step_target = step.get("target")
        if tool not in ALLOWED_TOOLS:
            raise AgentProtocolError("工具不在白名单")
        serialized = json.dumps(step, ensure_ascii=False)
        if COORDINATE_RE.search(serialized) or NUMBER_RE.search(serialized):
            raise AgentProtocolError("Planner不得输出坐标或数字")
        if step_target not in TOOL_TARGETS[tool]:
            raise AgentProtocolError("工具目标不合法")
        key = (tool, step_target)
        if key not in seen:
            normalized_steps.append({"tool": tool, "target": step_target})
            seen.add(key)
    focus = value.get("focus")
    if not isinstance(focus, list) or not 1 <= len(focus) <= 4:
        raise AgentProtocolError("focus必须为1至4个枚举")
    if any(item not in ALLOWED_FOCUS for item in focus):
        raise AgentProtocolError("focus包含未知枚举")
    confidence = value.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        raise AgentProtocolError("confidence不合法")
    return {
        "schemaVersion": PLAN_SCHEMA,
        "questionTarget": target,
        "steps": normalized_steps,
        "focus": list(dict.fromkeys(focus)),
        "confidence": confidence,
    }


def deterministic_plan(
    question: str,
    question_target: str,
    *,
    memory_enabled: bool = False,
) -> dict:
    """模型不可用时的保守计划；它仍只规划，绝不生成棋力事实。"""
    target = question_target if question_target in ALLOWED_TARGETS else "position"
    text = str(question or "")
    steps: list[dict] = []

    def add(tool: str, step_target: str = target) -> None:
        item = {"tool": tool, "target": step_target}
        if item not in steps and len(steps) < 3:
            steps.append(item)

    compare_markers = ("为什么", "不好", "更好", "区别", "比较", "首选", "实战")
    variation_markers = (
        "变化", "后续", "对杀", "死活", "打劫", "劫材", "强制", "次序", "先手",
    )
    principle_markers = (
        "棋理", "厚薄", "取舍", "外势", "实地", "定式", "布局", "官子", "便宜",
    )
    memory_markers = ("以前", "上次", "记得", "我的问题", "同类错误")
    remember_markers = ("记住这条", "保存这条", "记住这个", "保存这个")
    if any(marker in text for marker in remember_markers):
        add("remember_lesson", target)
    if target in {"actual", "best", "comparison"} and any(
        marker in text for marker in compare_markers
    ):
        add("compare_moves", "comparison" if target == "comparison" else target)
    else:
        add("inspect_position", target)
    if any(marker in text for marker in variation_markers) or (
        target in {"actual", "best", "comparison"}
        and any(marker in text for marker in ("为什么", "不好", "问题严重"))
    ):
        add("analyze_variations", target)
    if any(marker in text for marker in principle_markers):
        add("retrieve_principles", target)
    if memory_enabled and any(marker in text for marker in memory_markers):
        add("recall_lessons", target)
    if len(steps) == 1 and target in {"actual", "best", "comparison"}:
        add("compare_moves", target)

    focus = ["evidence_boundary"]
    focus_rules = (
        (("对杀", "气", "打吃"), "liberties"),
        (("连接", "联络", "切断"), "connection"),
        (("先手", "次序", "急点"), "move_order"),
        (("厚", "薄", "弱棋"), "thickness"),
        (("劫", "劫材"), "ko_resources"),
        (("实地", "外势", "取舍"), "territory_influence"),
        (("定式",), "joseki_direction"),
        (("布局", "角", "边", "大场"), "opening_priority"),
        (("官子", "便宜", "目数"), "endgame_value"),
    )
    for markers, label in focus_rules:
        if any(marker in text for marker in markers) and label not in focus:
            focus.insert(0, label)
        if len(focus) >= 4:
            break
    return validate_plan({
        "schemaVersion": PLAN_SCHEMA,
        "questionTarget": target,
        "steps": steps,
        "focus": focus,
        "confidence": "medium",
    })


def merge_required_tools(plan: dict, question: str) -> dict:
    """服务端只补安全必需工具，不允许模型删除关键比较或变化核对。"""
    plan = validate_plan(plan)
    target = plan["questionTarget"]
    required = deterministic_plan(question, target)
    steps = list(plan["steps"])
    existing = {(item["tool"], item["target"]) for item in steps}
    for item in required["steps"]:
        key = (item["tool"], item["target"])
        if key not in existing and len(steps) < 3:
            steps.append(item)
            existing.add(key)
    return validate_plan({**plan, "steps": steps})


def needs_variation_evidence(plan: dict) -> bool:
    return any(
        step["tool"] == "analyze_variations"
        for step in validate_plan(plan)["steps"]
    )


def _candidate(position: dict, target: str) -> dict:
    candidates = position.get("moveCandidates")
    candidates = candidates if isinstance(candidates, dict) else {}
    value = candidates.get(target)
    return deepcopy(value) if isinstance(value, dict) else {}


def _inspect_position(position: dict, target: str) -> dict:
    candidates = position.get("moveCandidates")
    candidates = candidates if isinstance(candidates, dict) else {}
    if target == "comparison":
        selected = {name: _candidate(position, name) for name in ("actual", "best")}
    elif target in {"actual", "best"}:
        selected = {target: _candidate(position, target)}
    else:
        selected = {}
    return {
        "sourceLayer": "rules_and_server_geometry",
        "turn": int(position.get("turn") or 0),
        "phase": position.get("phase"),
        "toPlay": position.get("toPlay"),
        "candidates": selected,
        "sameMove": bool(candidates.get("sameMove")),
    }


def _compare_moves(position: dict, evidence: dict, target: str) -> dict:
    return {
        "sourceLayer": "katago_rules_and_heuristics_separated",
        "target": target,
        "actual": _candidate(position, "actual"),
        "best": _candidate(position, "best"),
        "decisionRelation": deepcopy(
            evidence.get("decisionRelation")
            or position.get("decisionRelation")
            or {}
        ),
        "analysis": {
            "source": evidence.get("source"),
            "demo": bool(evidence.get("demo")),
            "bestMove": evidence.get("bestMove"),
            "playerWinrateDelta": evidence.get("playerWinrateDelta"),
            "playerScoreDelta": evidence.get("playerScoreDelta"),
        },
    }


def _variation_result(evidence: dict) -> dict:
    value = evidence.get("variationEvidence")
    if not isinstance(value, dict):
        return {
            "sourceLayer": "katago_and_rules",
            "status": "not_available",
            "claimBoundary": {"notDirectlyProven": [
                "forced_reply", "life_and_death", "thickness",
            ]},
        }
    return {
        "sourceLayer": "katago_and_rules",
        "status": value.get("status"),
        "schemaVersion": value.get("schemaVersion"),
        "branches": deepcopy(value.get("branches") or {}),
        "tacticalSemantics": deepcopy(value.get("tacticalSemantics") or {}),
        "claimBoundary": deepcopy(value.get("claimBoundary") or {}),
    }


def _knowledge_documents() -> list[dict]:
    documents = []
    for principle in classical_go.PRINCIPLES:
        documents.append({
            "sourceId": principle["id"],
            "kind": "public_classical_heuristic",
            "title": principle["maxim"],
            "tags": list(principle.get("tags") or ()),
            "text": principle["gloss"],
            "metadata": {
                "work": principle["work"],
                "sourceUrl": principle["sourceUrl"],
                "confidence": "heuristic",
            },
        })
    for entry in TERMS:
        documents.append({
            "sourceId": entry["id"],
            "kind": "project_terminology_heuristic",
            "title": entry["term"],
            "tags": [entry["category"], *entry.get("aliases", [])],
            "text": entry["standard"],
            "metadata": {
                "category": entry["category"],
                "confidence": "heuristic",
            },
        })
    return documents


def _knowledge_corpus_hash(documents: list[dict]) -> str:
    return _canonical_hash({"schemaVersion": KNOWLEDGE_SCHEMA, "items": documents})


def _init_knowledge_index(connection: sqlite3.Connection) -> bool:
    """把公版棋理与原创术语写入本地 FTS5；不索引用户棋谱或回答。"""
    try:
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS mentor_knowledge_fts USING fts5(
                source_id UNINDEXED,
                kind UNINDEXED,
                title,
                tags,
                text,
                metadata_json UNINDEXED,
                tokenize='unicode61'
            )
        """)
    except sqlite3.OperationalError:
        return False
    connection.execute("""
        CREATE TABLE IF NOT EXISTS mentor_knowledge_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    documents = _knowledge_documents()
    corpus_hash = _knowledge_corpus_hash(documents)
    current = connection.execute(
        "SELECT value FROM mentor_knowledge_meta WHERE key='corpus_hash'"
    ).fetchone()
    if current and current[0] == corpus_hash:
        return True
    connection.execute("DELETE FROM mentor_knowledge_fts")
    for item in documents:
        connection.execute(
            """INSERT INTO mentor_knowledge_fts
               (source_id,kind,title,tags,text,metadata_json)
               VALUES (?,?,?,?,?,?)""",
            (
                item["sourceId"], item["kind"], item["title"],
                " ".join(item["tags"]), item["text"],
                json.dumps(item["metadata"], ensure_ascii=False, sort_keys=True),
            ),
        )
    connection.execute(
        """INSERT INTO mentor_knowledge_meta(key,value) VALUES('corpus_hash',?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (corpus_hash,),
    )
    return True


def _retrieval_haystack(question: str, position: dict) -> str:
    candidates = position.get("moveCandidates")
    candidates = candidates if isinstance(candidates, dict) else {}
    haystack = str(question or "")
    for name in ("actual", "best"):
        item = candidates.get(name)
        if not isinstance(item, dict):
            continue
        haystack += " " + json.dumps(item, ensure_ascii=False, sort_keys=True)
    return haystack


def _fts_query(haystack: str) -> str:
    vocabulary = set()
    for item in _knowledge_documents():
        vocabulary.update(item["tags"])
        vocabulary.add(item["title"])
    matched = sorted(
        {token for token in vocabulary if token and token in haystack},
        key=lambda value: (-len(value), value),
    )[:16]
    if not matched:
        matched = [
            token for token in re.split(r"[^\w\u4e00-\u9fff]+", haystack)
            if len(token) >= 2
        ][:8]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in matched)


def _fts_principles(path: Path, haystack: str, limit: int) -> list[dict] | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        if not _init_knowledge_index(connection):
            return None
        query = _fts_query(haystack)
        if not query:
            return []
        rows = connection.execute(
            """SELECT source_id,kind,title,tags,text,metadata_json,bm25(mentor_knowledge_fts)
               FROM mentor_knowledge_fts
               WHERE mentor_knowledge_fts MATCH ?
               ORDER BY bm25(mentor_knowledge_fts), source_id
               LIMIT ?""",
            (query, max(1, min(int(limit), 5))),
        ).fetchall()
    result = []
    for source_id, kind, title, tags, text, metadata_json, score in rows:
        item = {
            "sourceId": source_id,
            "kind": kind,
            "title": title,
            "tags": tags.split(),
            "text": text,
            "textHash": _canonical_hash(text),
            "retrievalScore": round(float(score), 6),
        }
        item.update(json.loads(metadata_json))
        result.append(item)
    return result


def retrieve_principles(
    question: str,
    target: str,
    position: dict,
    limit: int = 3,
    *,
    database: Path | None = None,
) -> dict:
    """本地 FTS5/BM25 检索；结果只作启发式资料，不构成当前棋局事实。"""
    haystack = _retrieval_haystack(question, position)
    if database is not None:
        indexed = _fts_principles(database, haystack, limit)
        if indexed is not None:
            return {"backend": "sqlite_fts5_bm25", "items": indexed}

    rows: list[tuple[int, str, dict]] = []
    for principle in classical_go.PRINCIPLES:
        score = sum(3 for tag in principle.get("tags", ()) if tag in haystack)
        score += 2 if principle.get("maxim") in haystack else 0
        if score:
            rows.append((score, str(principle["id"]), {
                "sourceId": principle["id"],
                "kind": "public_classical_heuristic",
                "title": principle["maxim"],
                "tags": list(principle.get("tags") or ()),
                "text": principle["gloss"],
                "work": principle["work"],
                "sourceUrl": principle["sourceUrl"],
                "confidence": "heuristic",
            }))
    for entry in TERMS:
        tokens = [entry["term"], entry["category"], *entry.get("aliases", [])]
        score = sum(2 for token in tokens if token and token in haystack)
        if score:
            rows.append((score, str(entry["id"]), {
                "sourceId": entry["id"],
                "kind": "project_terminology_heuristic",
                "title": entry["term"],
                "tags": [entry["category"], *entry.get("aliases", [])],
                "text": entry["standard"],
                "category": entry["category"],
                "confidence": "heuristic",
            }))
    rows.sort(key=lambda item: (-item[0], item[1]))
    result = []
    seen = set()
    for _, source_id, item in rows:
        if source_id in seen:
            continue
        item["textHash"] = _canonical_hash(item["text"])
        result.append(item)
        seen.add(source_id)
        if len(result) >= max(1, min(int(limit), 5)):
            break
    return {"backend": "deterministic_lexical_fallback", "items": result}


def init_memory_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS mentor_sessions (
                id TEXT PRIMARY KEY,
                memory_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS mentor_lessons (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                game_id TEXT NOT NULL DEFAULT '',
                turn INTEGER NOT NULL DEFAULT 0,
                context_id TEXT NOT NULL,
                position_hash TEXT NOT NULL,
                evidence_hash TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES mentor_sessions(id)
            )
        """)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mentor_lessons_session "
            "ON mentor_lessons(session_id, created_at DESC)"
        )


def create_session(path: Path, *, memory_enabled: bool = False) -> dict:
    init_memory_db(path)
    session_id = uuid.uuid4().hex
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO mentor_sessions(id,memory_enabled) VALUES (?,?)",
            (session_id, 1 if memory_enabled else 0),
        )
    return {"sessionId": session_id, "memoryEnabled": bool(memory_enabled)}


def _require_session(path: Path, session_id: str) -> tuple[str, bool]:
    if not SESSION_RE.fullmatch(str(session_id or "")):
        raise AgentProtocolError("sessionId不合法")
    init_memory_db(path)
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT id,memory_enabled FROM mentor_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
    if not row:
        raise AgentProtocolError("本地学习会话不存在")
    return str(row[0]), bool(row[1])


def set_memory_enabled(path: Path, session_id: str, enabled: bool) -> dict:
    _require_session(path, session_id)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE mentor_sessions SET memory_enabled=?,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (1 if enabled else 0, session_id),
        )
    return {"sessionId": session_id, "memoryEnabled": bool(enabled)}


def save_lesson(path: Path, value: dict) -> dict:
    """只供用户确认接口调用；Planner 和回答生成链路不得调用。"""
    session_id, enabled = _require_session(path, str(value.get("sessionId") or ""))
    if not enabled:
        raise AgentProtocolError("本地记忆尚未开启")
    title = str(value.get("title") or "").strip()[:120]
    summary = str(value.get("summary") or "").strip()[:800]
    if not title or not summary:
        raise AgentProtocolError("学习标题和总结不能为空")
    tags = [
        str(tag).strip()[:30]
        for tag in value.get("tags") or []
        if str(tag).strip()
    ][:8]
    lesson_id = uuid.uuid4().hex
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT INTO mentor_lessons
               (id,session_id,game_id,turn,context_id,position_hash,evidence_hash,
                title,summary,tags_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                lesson_id, session_id, str(value.get("gameId") or "")[:100],
                max(0, int(value.get("turn") or 0)),
                str(value.get("contextId") or "")[:100],
                str(value.get("positionHash") or "")[:100],
                str(value.get("evidenceHash") or "")[:100], title, summary,
                json.dumps(tags, ensure_ascii=False),
            ),
        )
    return {"saved": True, "id": lesson_id, "sessionId": session_id}


def list_lessons(path: Path, session_id: str, *, limit: int = 20) -> dict:
    _, enabled = _require_session(path, session_id)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """SELECT id,game_id,turn,context_id,position_hash,evidence_hash,
                      title,summary,tags_json,created_at
               FROM mentor_lessons WHERE session_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (session_id, max(1, min(int(limit), 100))),
        ).fetchall()
    return {
        "sessionId": session_id,
        "memoryEnabled": enabled,
        "items": [
            {
                "id": row[0], "gameId": row[1], "turn": row[2],
                "contextId": row[3], "positionHash": row[4],
                "evidenceHash": row[5], "title": row[6], "summary": row[7],
                "tags": json.loads(row[8] or "[]"), "createdAt": row[9],
            }
            for row in rows
        ],
    }


def recall_lessons(path: Path, session_id: str, question: str, *, limit: int = 3) -> list[dict]:
    payload = list_lessons(path, session_id, limit=100)
    if not payload["memoryEnabled"]:
        return []
    question_text = str(question or "")
    tokens = {
        token for token in re.split(r"[^\w\u4e00-\u9fff]+", question_text)
        if len(token) >= 2
    }
    scored = []
    for item in payload["items"]:
        text = " ".join([item["title"], item["summary"], *item["tags"]])
        score = sum(1 for token in tokens if token in text)
        score += sum(2 for tag in item["tags"] if tag and tag in question_text)
        scored.append((score, item["createdAt"], item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [deepcopy(row[2]) for row in scored[:max(1, min(int(limit), 5))] if row[0] > 0]


def clear_session(path: Path, session_id: str) -> dict:
    _require_session(path, session_id)
    with sqlite3.connect(path) as connection:
        deleted = connection.execute(
            "DELETE FROM mentor_lessons WHERE session_id=?", (session_id,)
        ).rowcount
    return {"cleared": True, "sessionId": session_id, "deleted": int(deleted)}


def delete_lesson(path: Path, session_id: str, lesson_id: str) -> dict:
    _require_session(path, session_id)
    if not LESSON_RE.fullmatch(str(lesson_id or "")):
        raise AgentProtocolError("lessonId不合法")
    with sqlite3.connect(path) as connection:
        deleted = connection.execute(
            "DELETE FROM mentor_lessons WHERE session_id=? AND id=?",
            (session_id, lesson_id),
        ).rowcount
    if not deleted:
        raise AgentProtocolError("学习记录不存在")
    return {
        "deleted": True,
        "sessionId": session_id,
        "lessonId": lesson_id,
    }


def execute_plan(
    plan: dict,
    *,
    question: str,
    position: dict,
    evidence: dict,
    memory_db: Path | None = None,
    session_id: str | None = None,
    memory_enabled: bool = False,
) -> dict:
    """执行白名单工具并生成不含思维链的安全轨迹。"""
    plan = validate_plan(plan)
    results = []
    trace = []
    for step in plan["steps"]:
        started = time.perf_counter()
        tool = step["tool"]
        target = step["target"]
        status = "completed"
        if tool == "inspect_position":
            result = _inspect_position(position, target)
        elif tool == "compare_moves":
            result = _compare_moves(position, evidence, target)
        elif tool == "analyze_variations":
            result = _variation_result(evidence)
            if result.get("status") != "ready":
                status = "not_available"
        elif tool == "retrieve_principles":
            retrieval = retrieve_principles(
                question, target, position, database=memory_db
            )
            result = {
                "sourceLayer": "retrieved_heuristics",
                "retrievalBackend": retrieval["backend"],
                "items": retrieval["items"],
            }
        elif tool == "recall_lessons":
            if not (memory_enabled and memory_db and session_id):
                result = {"sourceLayer": "explicit_local_memory", "items": []}
                status = "disabled"
            else:
                result = {
                    "sourceLayer": "explicit_local_memory",
                    "items": recall_lessons(memory_db, session_id, question),
                }
        else:  # remember_lesson
            result = {
                "sourceLayer": "explicit_local_memory",
                "writePerformed": False,
                "reason": "需要用户通过独立确认接口授权",
            }
            status = "approval_required"
        evidence_hash = _canonical_hash(result)
        results.append({
            "tool": tool,
            "target": target,
            "status": status,
            "evidenceHash": evidence_hash,
            "result": result,
        })
        trace.append({
            "tool": tool,
            "status": status,
            "durationMs": round((time.perf_counter() - started) * 1000),
            "evidenceHash": evidence_hash,
        })
    return {
        "schemaVersion": TOOL_RESULT_SCHEMA,
        "planHash": _canonical_hash(plan),
        "items": results,
        "agentTrace": {
            "schemaVersion": TRACE_SCHEMA,
            "planHash": _canonical_hash(plan),
            "items": trace,
        },
    }
