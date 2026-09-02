"""S3 知识管道契约测试（离线可跑，不依赖 embedding 服务）。

验证收敛纪律：升级后的 KnowledgeBase 兼容旧接口（ingest/query），
且新增能力面（search/stats/clear）+ Adapter 防腐层 + 混合检索可用。
"""

import os
import tempfile

from core.kb import KnowledgeBase, Chunk
from core.adapters.knowledge_adapter import KnowledgeAdapter


def _make_corpus(base: str) -> list[str]:
    a = os.path.join(base, "rag.md")
    b = os.path.join(base, "code.md")
    with open(a, "w", encoding="utf-8") as f:
        f.write("# RAG 检索\n知识库检索系统用于私有知识管理，支持文档摄入与语义搜索。")
    with open(b, "w", encoding="utf-8") as f:
        f.write("# 代码工程\nGrok Build 负责代码生成与软件工程，支持 apply_patch 与子代理编排。")
    return [a, b]


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_ingest_and_persist():
    db = _tmp_db()
    with tempfile.TemporaryDirectory() as d:
        paths = _make_corpus(d)
        kb = KnowledgeBase(db_path=db, use_dense=False)
        n = kb.ingest(paths)
        assert n >= 2, f"应摄入至少 2 块，实际 {n}"
        # 持久化：新建实例从 DB 加载
        kb2 = KnowledgeBase(db_path=db, use_dense=False)
        assert len(kb2.chunks) == len(kb.chunks), "重启后应从 DB 恢复块"
        kb.close(); kb2.close()


def test_hybrid_search_offline_bm25():
    db = _tmp_db()
    with tempfile.TemporaryDirectory() as d:
        paths = _make_corpus(d)
        kb = KnowledgeBase(db_path=db, use_dense=False)
        kb.ingest(paths)
        hits = kb.search("知识库检索系统", top_k=3)
        assert hits, "BM25 离线应返回命中"
        assert any("rag.md" in h["source"] for h in hits), "应命中 RAG 文档"
        assert all(0.0 < h["score"] <= 1.0 for h in hits)
        kb.close()


def test_backward_compat_query():
    """旧接口 query 仍可用（workflow_bridge._run_kb 依赖）。"""
    db = _tmp_db()
    with tempfile.TemporaryDirectory() as d:
        paths = _make_corpus(d)
        kb = KnowledgeBase(db_path=db, use_dense=False)
        kb.ingest(paths)
        res = kb.query("代码工程 Grok Build", top_k=2)
        assert isinstance(res, list) and res, "query 应返回非空列表"
        assert isinstance(res[0][0], Chunk) and isinstance(res[0][1], float)
        kb.close()


def test_stats_and_clear():
    db = _tmp_db()
    with tempfile.TemporaryDirectory() as d:
        paths = _make_corpus(d)
        kb = KnowledgeBase(db_path=db, use_dense=False)
        kb.ingest(paths)
        st = kb.stats()
        assert st["total_chunks"] >= 2 and st["sources"] == 2
        cleared = kb.clear()
        assert cleared >= 2
        assert kb.stats()["total_chunks"] == 0
        kb.close()


def test_adapter_dispatch():
    """Adapter 防腐层：引擎只经 execute(op=...) 操作知识管道。"""
    db = _tmp_db()
    with tempfile.TemporaryDirectory() as d:
        paths = _make_corpus(d)
        ad = KnowledgeAdapter(db_path=db)
        r = ad.execute({"op": "ingest", "paths": paths})
        assert r.ok and r.meta["ingested"] >= 2
        r2 = ad.execute({"op": "search", "query": "语义搜索", "top_k": 2})
        assert r2.ok and len(r2.meta["hits"]) >= 1
        r3 = ad.execute({"op": "stats"})
        assert r3.ok and r3.meta["stats"]["total_chunks"] >= 2
        r4 = ad.execute({"op": "unknown"})
        assert not r4.ok
        ad.close()
