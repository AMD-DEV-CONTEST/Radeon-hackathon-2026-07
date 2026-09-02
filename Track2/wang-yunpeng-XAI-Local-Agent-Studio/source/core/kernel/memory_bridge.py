"""XAI 记忆桥接 —— 从 engine_xai.py 上帝类外移（Phase E）。

承载：
- retrieve_memory_context(engine, text)：检索记忆 + 知识库作为上下文（单一事实源 memory_core，超时隔离防阻塞）
- retrieve_ranked_memories(engine, text, limit=10)：混合召回策略（子串40%+关键词40%+时间衰减20%），返回结构化排序结果
- safe_memory_core_write(engine, user_input, response, intent_type)：daemon 线程 fire-and-forget 写入 7 层记忆
- execute_memory_query(engine, text)：记忆查询（委托 intents.execute_memory_query）

行为零变更：所有逻辑原样平移，仅 self -> engine。
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from .intents import execute_memory_query as _intents_execute_memory_query


def retrieve_memory_context(engine, text: str) -> str:
    """检索记忆 + 知识库作为上下文（单一事实源：memory_core）。

    注意：memory_core.recall 在 MemOS 适配器 health_check 用无超时 subprocess 时
    可能永久阻塞，因此用线程超时隔离——超时则跳过记忆检索，不影响主对话返回。
    """
    parts: List[str] = []

    try:
        # project_manager.current() 仅做 SQLite 读，但可能因锁竞争/deadlock 卡死
        # （其他线程持锁做阻塞子类进程），故超时隔离，超时则当无项目。
        _pr: Dict[str, Any] = {}
        def _do_pm():
            try:
                _pr["p"] = engine.project_manager.current()
            except Exception as e:
                engine._log(f"proj_cur: {e}")
        _pt = threading.Thread(target=_do_pm, daemon=True)
        _pt.start()
        _pt.join(2.0)
        p = _pr.get("p") if not _pt.is_alive() else None
        pid = p.id if p else None

        # 线程超时隔离：避免记忆适配器阻塞导致整个对话挂死
        _res: Dict[str, Any] = {}
        def _do_recall():
            try:
                _res["entries"] = engine.memory_core.recall(text, limit=5, project_id=pid)
            except Exception as e:
                engine._log(f"mem_ctx_recall: {e}")
        _t = threading.Thread(target=_do_recall, daemon=True)
        _t.start()
        _t.join(4.0)  # 记忆检索最多等 4s
        if _t.is_alive():
            engine._log("mem_ctx_timeout")
        else:
            mc_entries = _res.get("entries")
            if mc_entries:
                lines = [f"[{e.layer}|{e.engine}] {e.value[:120]}" for e in mc_entries]
                parts.append("近期记忆:\n" + "\n".join(lines))
    except Exception as e:
        engine._log(f"mem_ctx_outer: {e}")

    # 显式召回 failure_correction 层（我们特有·Hermes 扩展）——读写闭环关键读侧：
    # 历史失败修正注入上下文，让模型在推理时主动规避同类错误（而非仅落盘无人读）。
    try:
        _fres: Dict[str, Any] = {}
        def _do_fail():
            try:
                _fres["f"] = engine.memory_core.query(layer="failure_correction", limit=3)
            except Exception as e:
                engine._log(f"mem_ctx_fail: {e}")
        _ft = threading.Thread(target=_do_fail, daemon=True)
        _ft.start()
        _ft.join(2.0)
        if not _ft.is_alive():
            fc = _fres.get("f")
            if fc:
                items = []
                for e in fc:
                    try:
                        d = json.loads(e.value)
                        items.append(
                            f"- [任务] {str(d.get('task', ''))[:80]} → "
                            f"[错误] {str(d.get('error', ''))[:120]} → "
                            f"[纠正] {str(d.get('correction', ''))[:120]}"
                        )
                    except Exception:
                        items.append(f"- {e.value[:160]}")
                if items:
                    parts.append(
                        "【历史失败修正记录】(避免重犯同类错误):\n" + "\n".join(items)
                    )
    except Exception as e:
        engine._log(f"mem_ctx_fail_outer: {e}")

    # 显式召回 reflection 层——自我反思记录注入上下文，帮助模型持续优化行为模式。
    try:
        _rres: Dict[str, Any] = {}
        def _do_refl():
            try:
                _rres["r"] = engine.memory_core.query(layer="reflection", limit=3)
            except Exception as e:
                engine._log(f"mem_ctx_reflection: {e}")
        _rt = threading.Thread(target=_do_refl, daemon=True)
        _rt.start()
        _rt.join(2.0)
        if not _rt.is_alive():
            rc = _rres.get("r")
            if rc:
                items = []
                for e in rc:
                    try:
                        d = json.loads(e.value)
                        items.append(
                            f"- [主题] {str(d.get('topic', ''))[:80]} → "
                            f"[洞察] {str(d.get('insight', ''))[:120]}"
                        )
                    except Exception:
                        items.append(f"- {e.value[:160]}")
                if items:
                    parts.append(
                        "【自我反思记录】(过往行为优化洞察):\n" + "\n".join(items)
                    )
    except Exception as e:
        engine._log(f"mem_ctx_reflection_outer: {e}")

    # 显式召回 user_profile 层——用户画像注入上下文，使模型更精准地适配用户偏好与习惯。
    try:
        _ures: Dict[str, Any] = {}
        def _do_profile():
            try:
                _ures["u"] = engine.memory_core.query(layer="user_profile", limit=3)
            except Exception as e:
                engine._log(f"mem_ctx_profile: {e}")
        _ut = threading.Thread(target=_do_profile, daemon=True)
        _ut.start()
        _ut.join(2.0)
        if not _ut.is_alive():
            up = _ures.get("u")
            if up:
                items = []
                for e in up:
                    try:
                        d = json.loads(e.value)
                        items.append(
                            f"- [特征] {str(d.get('trait', ''))[:80]} → "
                            f"[偏好] {str(d.get('preference', ''))[:120]}"
                        )
                    except Exception:
                        items.append(f"- {e.value[:160]}")
                if items:
                    parts.append(
                        "【用户画像】(历史偏好与习惯):\n" + "\n".join(items)
                    )
    except Exception as e:
        engine._log(f"mem_ctx_profile_outer: {e}")

    # 知识库目录自动纳入
    try:
        kb_dir = engine.openclaw.workspace_path("knowledge")
        if os.path.isdir(kb_dir):
            kb_files = [f for f in os.listdir(kb_dir) if f.endswith((".md", ".txt", ".py"))][:5]
            if kb_files:
                snippets = []
                for fname in kb_files:
                    p = os.path.join(kb_dir, fname)
                    try:
                        c = Path(p).read_text(encoding="utf-8", errors="ignore")[:300]
                        snippets.append(f"[{fname}] {c}")
                    except Exception as e:
                        engine._log(f"mem_ctx_kb_file: {e}")
                if snippets:
                    parts.append("本地知识库:\n" + "\n".join(snippets))
    except Exception as e:
        engine._log(f"mem_ctx_kb_outer: {e}")

    return "\n\n".join(parts)


def retrieve_ranked_memories(engine, text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """混合召回策略：子串匹配(40%) + 关键词加权(40%) + 时间衰减(20%)。

    不改 memory_core.recall() 接口，仅在 bridge 层做加权重排。
    返回 [{layer, key, value, score}, ...]，按 score 降序，硬限制 ≤ limit。
    """
    now = time.time()

    # 从 memory_core 拉取所有层的候选（超时隔离）
    _res: Dict[str, Any] = {}
    def _do_query():
        try:
            _res["entries"] = engine.memory_core.query(limit=200)
        except Exception as e:
            engine._log(f"ranked_mem_query: {e}")
    _t = threading.Thread(target=_do_query, daemon=True)
    _t.start()
    _t.join(3.0)
    entries = _res.get("entries")
    if not entries:
        return []

    # 归一化查询文本
    q_lower = text.lower().strip()
    if not q_lower:
        return []

    # 简单分词（纯规则，不引入 jieba）：按非字母数字汉字边界切分
    q_tokens = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', q_lower))
    if not q_tokens:
        q_tokens = {q_lower}

    scored: List[Dict[str, Any]] = []
    for e in entries:
        val = (getattr(e, "value", "") or "").lower()
        key = (getattr(e, "key", "") or "").lower()
        combined = key + " " + val
        created_at = getattr(e, "created_at", 0.0) or 0.0

        # 1) 子串匹配得分 (40%)：query 在 key+value 中出现次数归一化
        substr_count = combined.count(q_lower)
        substr_score = min(1.0, substr_count / max(len(combined.split()), 1)) if q_lower else 0.0

        # 2) 关键词 TF 加权得分 (40%)
        val_tokens = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', combined))
        intersect = q_tokens & val_tokens
        kw_score = len(intersect) / max(len(q_tokens), 1) if q_tokens else 0.0

        # 3) 时间衰减得分 (20%)：0.95^(hours_ago)
        hours_ago = (now - created_at) / 3600.0 if created_at > 0 else 24.0
        time_score = math.pow(0.95, max(0, hours_ago))

        # 综合得分
        final_score = 0.4 * substr_score + 0.4 * kw_score + 0.2 * time_score
        scored.append({
            "layer": getattr(e, "layer", ""),
            "key": getattr(e, "key", ""),
            "value": getattr(e, "value", "")[:500],
            "score": round(final_score, 4),
        })

    # 排序 + 去重（按 key 去重，保留最高分） + 硬限制
    scored.sort(key=lambda x: x["score"], reverse=True)
    seen_keys = set()
    deduped = []
    for item in scored:
        if item["key"] not in seen_keys:
            seen_keys.add(item["key"])
            deduped.append(item)
        if len(deduped) >= limit:
            break

    return deduped


def _tokenize_semantic(text: str) -> List[str]:
    """语义分词：英文/数字按词，中文按单字 + 二元字切分（捕捉语义邻近）。

    不引入 jieba 等重依赖；中文二元字在 TF-IDF 向量空间里对近义/同根词有较好召回。
    """
    text = (text or "").lower()
    tokens: List[str] = []
    for m in re.findall(r"[a-z0-9]+", text):
        tokens.append(m)
    zh = re.findall(r"[一-鿿]", text)
    tokens.extend(zh)
    for i in range(len(zh) - 1):
        tokens.append(zh[i] + zh[i + 1])
    return tokens


def _tfidf_vectors(query_tokens: List[str], docs_tokens: List[List[str]]):
    """构建 TF-IDF 向量（query + 各 doc）。返回 (q_vec, [doc_vec, ...])。"""
    N = len(docs_tokens) + 1
    df: Dict[str, int] = {}
    for dt in docs_tokens:
        for t in set(dt):
            df[t] = df.get(t, 0) + 1

    def _vec(tokens: List[str]):
        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {t: c * (math.log(N / (df.get(t, 0) + 1)) + 1) for t, c in tf.items()}

    return _vec(query_tokens), [_vec(d) for d in docs_tokens]


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    num = sum(a[t] * b[t] for t in (set(a) & set(b)))
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


def retrieve_ranked_memories_semantic(engine, text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """语义向量召回（TF-IDF char-bigram + 余弦相似度，向量空间模型）。

    相比 retrieve_ranked_memories 的「子串+关键词+时间衰减」词面匹配，本函数用
    向量余弦衡量语义邻近度，对同义/近义/词序扰动更鲁棒。无外部 embedding 依赖。
    返回结构同 retrieve_ranked_memories: [{layer, key, value, score}, ...]。
    """
    now = time.time()
    _res: Dict[str, Any] = {}
    def _do_query():
        try:
            _res["entries"] = engine.memory_core.query(limit=200)
        except Exception as e:
            engine._log(f"semantic_query: {e}")
    _t = threading.Thread(target=_do_query, daemon=True)
    _t.start(); _t.join(3.0)
    entries = _res.get("entries")
    if not entries:
        return []

    qt = _tokenize_semantic(text)
    docs: List[List[str]] = []
    meta: List[Any] = []
    for e in entries:
        val = getattr(e, "value", "") or ""
        key = getattr(e, "key", "") or ""
        docs.append(_tokenize_semantic(key + " " + val))
        meta.append(e)

    qv, dvecs = _tfidf_vectors(qt, docs)
    scored: List[Dict[str, Any]] = []
    for i, dv in enumerate(dvecs):
        e = meta[i]
        sim = _cosine(qv, dv)
        created_at = getattr(e, "created_at", 0.0) or 0.0
        hours_ago = (now - created_at) / 3600.0 if created_at > 0 else 24.0
        time_score = math.pow(0.95, max(0, hours_ago))
        final = 0.85 * sim + 0.15 * time_score
        scored.append({
            "layer": getattr(e, "layer", ""),
            "key": getattr(e, "key", ""),
            "value": (getattr(e, "value", "") or "")[:500],
            "score": round(final, 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    seen_keys = set()
    deduped = []
    for item in scored:
        if item["key"] not in seen_keys:
            seen_keys.add(item["key"])
            deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def safe_memory_core_write(engine, user_input: str, response: str, intent_type: str, engine_tag: str = "xai") -> None:
    """安全写入 7 层记忆核心，异常/阻塞保护绝不拖慢主对话。

    记忆写入（project_manager.current / memory_core.store）在适配器 health_check
    或 SQLite 锁竞争时可能永久阻塞，因此放到 daemon 线程 fire-and-forget，
    主对话直接 yield done，不被记忆写入拖慢。
    engine_tag: 标记来源引擎，如 "xai"（Hermes）或 "grok_build"（Grok 外脑）。
    """
    def _do_write():
        try:
            p = engine.project_manager.current()
            pid = p.id if p else "default"
            engine.memory_core.store(
                layer="short_term",
                key=f"chat:{int(__import__('time').time()):.0f}",
                value=f"[用户] {user_input[:500]}\n[助手] {response[:1000]}",
                engine=engine_tag,
                importance=0.4 if intent_type != "general" else 0.2,
                meta={"intent": intent_type, "project_id": pid, "user_input_len": len(user_input)},
                project_id=pid,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"memory_core 写入失败（已忽略）: {e}")
    th = threading.Thread(target=_do_write, daemon=True)
    th.start()
    th.join(3.0)  # 最多等 3s，超时则放弃本次写入，不影响对话


def execute_memory_query(engine, text: str):
    """记忆查询：委托 intents.execute_memory_query（保持原 /recall 行为）。"""
    yield from _intents_execute_memory_query(engine, text)
