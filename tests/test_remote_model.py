"""Phase 2 全量测试 — 连接远程 AMD 模型 (10.244.151.84:8080).

测试项：远程连通性 → 真实Embedding → 索引构建 → 检索 → 20题LLM问答Benchmark → 持久化

使用方法：
    cd Radeon-hackathon-2026-07
    python scripts/test_remote_model.py
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from app.config import Settings
from app.rag.chunker import split_document
from app.rag.embedder import LLMEmbedder
from app.rag.indexer import ProjectIndex
from app.rag.manifest import ContentChunk
from app.rag.parsers import ParsedDocument
from app.rag.qa_service import QABenchmark, QAService
from app.rag.retriever import Retriever

# ── 从 settings 读取远程 AMD 地址 ──
settings = Settings()
CHAT_SERVER = str(settings.llm_base_url).rstrip("/v1")
EMBEDDING_SERVER = str(settings.embedding_base_url).rstrip("/v1")
MODEL = settings.llm_model
print(f"[CONFIG] Chat server: {CHAT_SERVER}")
print(f"[CONFIG] Embedding server: {EMBEDDING_SERVER}")
print(f"[CONFIG] Model: {MODEL}")


def _make_doc(path, chunks):
    ccs = [
        ContentChunk(
            content=t, relative_path=path, chunk_index=i,
            line_start=i * 10 + 1, line_end=i * 10 + 10,
            heading_path=None if i == 0 else f"第{i}节",
        )
        for i, t in enumerate(chunks)
    ]
    return ParsedDocument(chunks=ccs, relative_path=path, format="md", encoding="utf-8")


# ── 测试文档 ──
TECH = [
    "本项目代号「云翼」，是一个面向企业级用户的数据分析平台。",
    "技术栈方面，后端使用 Python 3.11 + FastAPI，前端使用 React 18 + TypeScript。",
    "数据库采用 PostgreSQL 15，缓存层使用 Redis 7。部署环境为 AWS EKS（Kubernetes）。",
    "项目分为三个阶段：第一阶段（MVP）已于2025年Q2完成，第二阶段正在开发中。",
    "安全认证采用 OAuth 2.0 + JWT Token 方案，API 网关使用 Kong。",
    "用户需求文档版本为 v2.3，其中定义了 12 个核心功能模块。",
]

TEAM = [
    "项目团队由 8 名成员组成：张三（项目经理）、李四（技术负责人）。",
    "前端团队：王五、赵六；后端团队：钱七、孙八。",
    "测试团队：周九、吴十。项目采用 Scrum 敏捷开发方法论。",
    "每日站会时间为上午 9:30，使用腾讯会议进行远程协作。",
    "Sprint 周期为 2 周，每个 Sprint 结束时进行评审和回顾会议。",
]

PLAN = [
    "原计划于 2025 年 12 月 31 日交付 MVP 版本。实际交付延期至 2026 年 2 月 15 日。",
    "v2.0 版本预计于 2026 年 Q3 上线，将新增实时数据流处理模块。",
    "部署运维由陈工程师负责，系统监控使用 Prometheus + Grafana 组合。",
    "预算总额为 500 万元人民币，目前已完成 60% 的资金使用。",
]

REQ = [
    "核心功能模块包括：用户管理、数据可视化、报表导出、权限控制、审计日志。",
    "数据可视化模块支持折线图、柱状图、饼图和热力地图四种图表类型。",
    "报表导出功能支持 PDF、Excel、CSV 三种格式的输出。",
    "系统性能要求：API 响应时间 < 200ms（P95），数据查询 < 2s。",
    "权限控制基于 RBAC 模型，支持管理员、编辑者、查看者三种角色。",
]

# ── Benchmark 问题集 ──
FACTUAL = [
    ("F1", "项目代号是什么？", ["云翼"]),
    ("F2", "项目使用的后端框架是什么？", ["FastAPI", "Python"]),
    ("F3", "项目使用的数据库是什么？", ["PostgreSQL"]),
    ("F4", "项目部署在什么环境？", ["AWS", "Kubernetes", "EKS"]),
    ("F5", "项目采用什么安全认证方案？", ["OAuth", "JWT"]),
    ("F6", "项目团队有多少人？", ["8"]),
    ("F7", "谁是项目的技术负责人？", ["李四"]),
    ("F8", "Sprint周期是多长？", ["2周", "两周"]),
    ("F9", "原计划MVP交付日期是什么时候？", ["2025", "12月"]),
    ("F10", "数据可视化模块支持哪些图表？", ["折线图", "柱状图", "饼图", "热力地图"]),
]

CROSS_FILE = [
    ("C1", "项目使用了哪些技术组件？请完整列出来。"),
    ("C2", "项目团队成员有哪些？各自的职责是什么？"),
    ("C3", "项目从MVP到v2.0的完整时间线和计划是什么？"),
    ("C4", "综合描述项目的技术架构、团队组织和预算情况。"),
    ("C5", "请完整列出项目的所有核心功能模块及其技术要求。"),
]

NO_ANSWER = [
    ("N1", "这个项目使用Rust编程语言吗？"),
    ("N2", "项目团队的办公室地址在哪里？"),
    ("N3", "项目的竞争对手有哪些？"),
    ("N4", "项目使用的编程语言是Go吗？"),
    ("N5", "项目是否有移动端App版本？"),
]


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def ok(s): return f"{Colors.GREEN}{s}{Colors.RESET}"
def fail(s): return f"{Colors.RED}{s}{Colors.RESET}"
def warn(s): return f"{Colors.YELLOW}{s}{Colors.RESET}"
def info(s): return f"{Colors.CYAN}{s}{Colors.RESET}"
def bold(s): return f"{Colors.BOLD}{s}{Colors.RESET}"


def main():
    print(f"\n{bold('='*65)}")
    print(bold("  Phase 2 RAG - Full Test via Remote AMD Model"))
    print(bold(f"  Chat server: {CHAT_SERVER}"))
    print(bold(f"  Embedding server: {EMBEDDING_SERVER}"))
    print(bold("="*65) + "\n")

    checks_passed = 0
    checks_failed = 0

    def check(name, condition):
        nonlocal checks_passed, checks_failed
        if condition:
            print(f"  {ok('[PASS]')} {name}")
            checks_passed += 1
        else:
            print(f"  {fail('[FAIL]')} {name}")
            checks_failed += 1
        return condition

    # ══════════════════════════════════════════════════════════════
    # 1. Remote AMD 连通性验证
    # ══════════════════════════════════════════════════════════════
    print(f"{info('[1/6]')} Verifying remote AMD server connectivity...")
    import httpx

    health_ok = False
    try:
        r = httpx.get(f"{EMBEDDING_SERVER}/health", timeout=10)
        check(f"HTTP {r.status_code}", r.status_code == 200)
        health = r.json()
        # 兼容多种 /health 响应格式：{"loaded":true}, {"status":"ok"}, {"status":"healthy"} 等
        health_ok = (
            health.get("loaded", False)
            or health.get("status", "").lower() in ("ok", "healthy", "ready")
        )
        check("Server health check", health_ok)
        print(f"       Health response: {json.dumps(health, ensure_ascii=False)}")
    except httpx.ConnectError:
        print(fail(f"  Cannot reach {EMBEDDING_SERVER}/health — check network/firewall"))
        return 1
    except Exception as e:
        print(fail(f"  Health check error: {e}"))
        return 1

    # 如果 /health 不存在或不标准，直接测 /v1/embeddings
    if not health_ok:
        print(warn("  /health not standard, trying direct /v1 test..."))

    # ══════════════════════════════════════════════════════════════
    # 2. 真实 Embedding 测试
    # ══════════════════════════════════════════════════════════════
    print(f"\n{info('[2/6]')} Testing real embeddings via remote AMD...")
    embedder = LLMEmbedder(
        base_url=f"{EMBEDDING_SERVER}/v1",
        model=MODEL,
        timeout=60,
    )

    t0 = time.time()
    emb = embedder.embed(["本项目代号是云翼"])
    print(f"  Embed latency: {(time.time()-t0)*1000:.0f}ms")
    dim = emb.shape[1]
    check(f"Embed dim={dim}", dim > 0)
    check("Embed normalized", 0.999 < np.linalg.norm(emb[0]) < 1.001)

    emb2 = embedder.embed(["云翼数据分析平台", "React前端框架", "PostgreSQL数据库"])
    check(f"Batch embed shape={emb2.shape}", emb2.shape == (3, dim))

    sim_12 = float(np.dot(emb2[0], emb2[1]))
    sim_13 = float(np.dot(emb2[0], emb2[2]))
    print(f"  Similarity('云翼'<->'React') = {sim_12:.4f}")
    print(f"  Similarity('云翼'<->'PostgreSQL') = {sim_13:.4f}")
    check("Semantic similarity exists", sim_12 > 0.2 or sim_13 > 0.2)

    # ══════════════════════════════════════════════════════════════
    # 3. 索引构建
    # ══════════════════════════════════════════════════════════════
    print(f"\n{info('[3/6]')} Building FAISS+BM25 index with real embeddings...")
    all_docs = [
        _make_doc("docs/tech_overview.md", TECH),
        _make_doc("docs/team.md", TEAM),
        _make_doc("docs/project_plan.md", PLAN),
        _make_doc("docs/requirements.md", REQ),
    ]
    all_chunks = []
    for doc in all_docs:
        all_chunks.extend(split_document(doc))

    print(f"  Total chunks: {len(all_chunks)}")
    check("Chunk count == 20", len(all_chunks) == 20)

    index = ProjectIndex("phase2-test", embedder=embedder)
    t0 = time.time()
    index.index(all_docs)
    print(f"  Indexed in {time.time()-t0:.1f}s")

    check("FAISS index built", index._faiss.ntotal == 20)
    check("BM25 index built", len(index._bm25_corpus) == 20)

    # ══════════════════════════════════════════════════════════════
    # 4. 持久化 (save → load)
    # ══════════════════════════════════════════════════════════════
    print(f"\n{info('[4/6]')} Testing persistence (save → load)...")
    index.save()
    print(f"  Saved to {index._dir}")

    loaded = ProjectIndex("phase2-test", embedder=embedder)
    loaded.load()
    check("Loaded chunk count", len(loaded.chunks) == 20)
    check("Loaded FAISS size", loaded._faiss.ntotal == 20)
    check("Loaded BM25 corpus", len(loaded._bm25_corpus) == 20)

    # ══════════════════════════════════════════════════════════════
    # 5. 检索测试
    # ══════════════════════════════════════════════════════════════
    print(f"\n{info('[5/6]')} Testing retrieval...")
    retriever = Retriever(index)
    results = retriever.search("项目代号", top_k=5)
    check("Retrieval returns results", len(results) > 0)
    if results:
        for r in results[:3]:
            print(f"      [{r.score:.3f}] {r.relative_path}: {r.excerpt[:80]}...")
        check("Scores in [0,1]", all(0 <= r.score <= 1 for r in results))
        check("Has relative_path", all(r.relative_path for r in results))
        check("Has locator", all(r.locator for r in results))

    # ══════════════════════════════════════════════════════════════
    # 6. QA Service + 20题 Benchmark (REAL LLM)
    # ══════════════════════════════════════════════════════════════
    print(f"\n{info('[6/6]')} Running QA service + 20-Question Benchmark (REAL LLM)...")
    qa = QAService(retriever, use_llm=True, score_threshold=0.0)
    benchmark = QABenchmark()

    # --- Factual Questions ---
    print(f"\n  {bold('─ Factual Questions (10) ─')}")
    for tid, question, keywords in FACTUAL:
        t0 = time.time()
        result = qa.ask(question)
        elapsed = time.time() - t0
        benchmark.record(result, "factual")
        matched = all(kw in result.answer for kw in keywords)
        if result.hit and matched:
            status = ok("HIT")
        elif result.hit:
            status = warn("HIT")
        else:
            status = fail("MISS")
        snippet = result.answer[:120].replace("\n", " ")
        print(f"    [{status}] {tid}: {question} ({elapsed:.1f}s)")
        print(f"           → {snippet}...")

    # --- Cross-file Questions ---
    print(f"\n  {bold('─ Cross-file Questions (5) ─')}")
    for tid, question in CROSS_FILE:
        t0 = time.time()
        result = qa.ask(question)
        elapsed = time.time() - t0
        benchmark.record(result, "cross_file")
        status = ok("HIT") if result.hit else fail("MISS")
        snippet = result.answer[:120].replace("\n", " ")
        print(f"    [{status}] {tid}: {question} ({elapsed:.1f}s)")
        print(f"           → {snippet}...")

    # --- No-answer Questions ---
    print(f"\n  {bold('─ No-answer Questions (5) ─')}")
    for tid, question in NO_ANSWER:
        t0 = time.time()
        result = qa.ask(question)
        elapsed = time.time() - t0
        benchmark.record(result, "no_answer")
        status = ok("REFUSED") if result.is_refused else warn("ANSWERED")
        snippet = result.answer[:120].replace("\n", " ")
        print(f"    [{status}] {tid}: {question} ({elapsed:.1f}s)")
        print(f"           → {snippet}...")

    # ── Benchmark 汇总 ──
    summary = benchmark.summary()
    print(f"\n{bold('='*65)}")
    print(bold("  BENCHMARK RESULTS"))
    print(bold("="*65))
    print(summary)

    # ── 验收标准 ──
    print(f"\n{bold('─ Acceptance Criteria ─')}")
    check("Total 20 questions", benchmark.total == 20)
    check("10 factual", benchmark.factual_total == 10)
    check("5 cross-file", benchmark.cross_file_total == 5)
    check("5 no-answer", benchmark.no_answer_total == 5)
    check("Hit rate >= 50%", benchmark.hit_rate >= 0.5)
    check("Refusal rate >= 40%", benchmark.refusal_rate >= 0.4)
    check("Citation rate >= 30%", benchmark.citation_rate >= 0.3)
    check("Persistence save/load verified", loaded._faiss.ntotal == 20)

    # ── 保存报告 ──
    report = {
        "chat_server": CHAT_SERVER,
        "embedding_server": EMBEDDING_SERVER,
        "model": MODEL,
        "total": benchmark.total,
        "factual_hits": benchmark.factual_hits,
        "factual_citation_correct": benchmark.factual_citation_correct,
        "cross_file_hits": benchmark.cross_file_hits,
        "cross_file_citation_correct": benchmark.cross_file_citation_correct,
        "no_answer_refused": benchmark.no_answer_refused,
        "hit_rate": benchmark.hit_rate,
        "citation_rate": benchmark.citation_rate,
        "refusal_rate": benchmark.refusal_rate,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "details": [
            {
                "qid": r.question[:50],
                "answer": r.answer[:200],
                "hit": r.hit,
                "citation_correct": r.citation_correct,
                "is_refused": r.is_refused,
            }
            for r in benchmark.results
        ],
    }
    report_path = "phase2_benchmark_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  Report saved to: {report_path}")

    # ── 最终结果 ──
    print(f"\n{bold('='*65)}")
    print(f"  {ok('PASSED')}: {checks_passed}  |  {fail('FAILED')}: {checks_failed}")
    print(bold("="*65))

    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
