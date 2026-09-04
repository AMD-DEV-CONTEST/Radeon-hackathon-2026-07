# -*- coding: utf-8 -*-
"""RAG 模块：文档入库 + 混合检索。

检索管线（业界标准，全本地离线）：
  查询改写 (LLM, 可选)
    → 向量检索 (ChromaDB, 语义)  +  BM25 (关键词)
    → 分数融合 (Reciprocal Rank Fusion)
    → 近重复去重（>95% 字符级相同片段丢弃）
    → cross-encoder 重排 (bge-reranker, 可选，极显著提升 Top-k 精度)
    → 自适应候选池（剔除重排分过弱的填充）
    → 上下文压缩（裁剪到与查询相关的句子，返回结构不变）
    → 返回带来源与得分的片段列表

设计动机：
- 纯向量检索对"专有名词 / 缩写 / 精确术语"召回差；BM25 补足精确匹配。
- cross-encoder 对 (query, doc) 联合打分，精度远高于 bi-encoder 距离，
  是 RAG 精度提升性价比最高的单点手段。
- 上下文压缩 / 去重 / 自适应池为确定性实现（无额外 embedding 调用），
  让送给 LLM 的上下文更紧、更聚焦、更少冗余。
"""
import json
import os
import hashlib
import re
import sys
import threading
from typing import List, Optional, Tuple

import yaml

from .parser import read_document, chunk_text
from .llm import LLMBackend


def _log(msg: str):
    """Windows GBK 控制台下打印中文文件名可能 UnicodeEncodeError，安全降级。"""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "backslashreplace").decode("utf-8", "backslashreplace"), flush=True)

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

RAG = CFG.get("rag", {})
CHUNK = RAG.get("chunk_size", 512)
OVERLAP = RAG.get("chunk_overlap", 64)
TOP_K = RAG.get("top_k", 4)
DOCS_DIR = RAG.get("docs_dir", "./data/docs")
DB_DIR = RAG.get("db_dir", "./data/vector_db")
ALLOWED = RAG.get("allowed_ext", [".pdf", ".docx", ".md", ".txt", ".csv", ".json", ".pptx", ".xlsx"])
HYBRID = RAG.get("hybrid", True)
BM25_WEIGHT = RAG.get("bm25_weight", 0.4)
RERANK = RAG.get("rerank", True)
RERANK_MODEL = RAG.get("rerank_model", "BAAI/bge-reranker-base")
RETRIEVAL_TOP_K = RAG.get("retrieval_top_k", 16)
QUERY_EXPANSION = RAG.get("query_expansion", True)
COMPRESSION = RAG.get("compression", True)                # 上下文压缩
COMPRESSION_THRESHOLD = RAG.get("compression_threshold", 0.12)  # 句子保留重叠阈值
ADAPTIVE_TOP_K = RAG.get("adaptive_top_k", True)          # 自适应候选池
DEDUP = RAG.get("dedup", True)                            # 近重复去重

_CORPUS_FILE = os.path.join(DB_DIR, "_corpus.json")

# 多 Agent 并行时，多个子 Agent 共享同一个 RAGStore 实例、同一份 ChromaDB collection
# 与同一份 cross-encoder 模型。ChromaDB 底层 hnswlib 与 torch 的原生代码不是线程安全的：
# 并发 collection.get/query/add 或并发 cross-encoder 推理会偶发段错误（exit 139）。
# 因此用一把可重入的进程级锁，把所有触碰这些原生资源的路径串行化：
#   - search()（向量查询 + BM25 + cross-encoder 重排）
#   - _load_corpus()（collection.get 全量拉取）—— 注意前端 /api/documents 轮询也会走到这里，
#     若不串行化，会与研究者并发的 collection.query 在 hnswlib 内部竞争同一内存结构
#   - add_document() / remove_document()
# LLM 推理（最耗时部分）走 Ollama 服务、天然并发，检索串行只增加毫秒级等待。
# 用 RLock 而非 Lock：search() 内部会再调用 _load_corpus()，可重入避免自我死锁。
_RETRIEVE_LOCK = threading.RLock()

# cross-encoder 模型很重，多个 RAGStore 实例（多 Agent 并行时每个子 Agent 各持有一个）
# 若各自加载会同时占用 N 份 GPU/内存。这里做模块级共享单例，全局只加载一份。
_SHARED_RERANKER = None
_SHARED_ST_MODEL = None


def _split_words(text: str) -> List[str]:
    """中英文分词：中文按字/双字滑动窗口，英文按词，用于 BM25。"""
    text = text.lower()
    # 中文片段：2-gram 滑窗 + 单字，英文：词
    tokens = []
    tokens += re.findall(r"[a-z0-9_]+", text)
    cjk = re.sub(r"[^一-鿿]", "", text)
    tokens += [cjk[i:i + 2] for i in range(0, max(0, len(cjk) - 1))]
    if len(cjk) == 1:
        tokens.append(cjk)
    return tokens


# ------------------------------------------------------------- 上下文压缩 / 去重
# 字符级归一化（复用 verify.py 的归一化思想）：去标点/空白/emoji，只留字母数字与中文。
# 全部为确定性实现（无额外 embedding / LLM 调用），快且稳定。
_CHAR_NORM_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")


def _char_normalize(text: str) -> str:
    return _CHAR_NORM_RE.sub("", text).lower()


def _char_ngrams(text: str, n: int = 3) -> set:
    """字符级 n-gram 集合；中文检索无需分词，3-gram 对改写/同义鲁棒。"""
    t = _char_normalize(text)
    if len(t) < n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def _split_sentences(text: str) -> List[str]:
    """按中英句读（。！？!?；;）与换行切句，保留标点去掉空白。"""
    return [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]


def _sentence_overlap(sent: str, query_ngrams: set) -> float:
    """单句与查询的字符 3-gram 重叠率（0~1）。"""
    sn = _char_ngrams(sent)
    if not sn or not query_ngrams:
        return 0.0
    return len(sn & query_ngrams) / len(sn)


def _compress_chunk(query: str, chunk: str, threshold: float) -> Tuple[str, bool]:
    """上下文压缩：把片段裁剪到与查询相关的句子。

    规则（保守，宁可少裁也不丢关键内容）：
    - 始终保留前 2 句（话题句 + 首内容句），保证上下文连贯；
    - 保留与查询存在任意字符 3-gram 重叠的句子（ov > 0），或重叠率 >= threshold 的句子；
    - 最低内容保证：若压缩后不足原文 35%，依次补回剩余句子直到达标——
      避免复杂长查询把片段裁成只剩标题（曾导致子 Agent 无真实上下文、grounding 崩坏）。
    返回 (压缩后文本, 是否发生裁剪)。片段 <160 字符时原样返回（no-op）。
    """
    text = chunk.strip()
    if len(text) < 160:          # 短片段不值得压缩
        return text, False
    qn = _char_ngrams(query)
    if not qn:
        return text, False
    sentences = _split_sentences(text)
    if len(sentences) <= 2:
        return text, False
    kept = []
    for i, s in enumerate(sentences):
        ov = _sentence_overlap(s, qn)
        if i < 2 or ov > 0 or ov >= threshold:
            kept.append(s)
    orig_len = len(_char_normalize(text))
    kept_len = len(_char_normalize("".join(kept)))
    # 最低内容保证：压缩后至少保留原文 35%
    target = orig_len * 0.35
    if kept_len < target:
        for s in sentences:
            if s in kept:
                continue
            kept.append(s)
            kept_len = len(_char_normalize("".join(kept)))
            if kept_len >= target:
                break
    changed = orig_len > 0 and kept_len < orig_len
    return "\n".join(kept), changed


def _is_near_dup(a: str, b: str) -> bool:
    """近似重复判定：归一化后长度差 ≤5%（>95% 字符级一致）且前 60 个字符相同。"""
    na, nb = _char_normalize(a), _char_normalize(b)
    if not na or not nb:
        return False
    if min(len(na), len(nb)) / max(len(na), len(nb)) < 0.95:
        return False
    return na[:60] == nb[:60]


def _dedup_candidates(cand: List[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
    """重排前近重复去重：保留首个出现的片段，丢弃与已保留片段 >95% 字符级相同的。"""
    kept_texts: List[str] = []
    out = []
    for t, src, score in cand:
        if any(_is_near_dup(t, k) for k in kept_texts):
            continue
        kept_texts.append(t)
        out.append((t, src, score))
    return out


class RAGStore:
    def __init__(self, llm: LLMBackend):
        self.llm = llm
        self.db_dir = DB_DIR
        os.makedirs(DOCS_DIR, exist_ok=True)
        os.makedirs(self.db_dir, exist_ok=True)
        self.collection = self._get_or_create()
        # 延迟加载（首次 search 时构建，避免大知识库卡启动）
        self._corpus: Optional[dict] = None
        self._bm25: object = None
        self._reranker = None
        self._st_model = None
        self.last_meta: Optional[dict] = None

    # ------------------------------------------------------------------ 入库
    def _get_or_create(self):
        import chromadb
        client = chromadb.PersistentClient(path=self.db_dir)
        return client.get_or_create_collection("docs", metadata={"hnsw:space": "cosine"})

    def _doc_hash(self, path: str) -> str:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def add_document(self, path: str) -> int:
        """解析 + 切片 + embedding 入库。返回 chunk 数（幂等）。

        性能关键：解析与 embedding（最耗时，走 Ollama）在 _RETRIEVE_LOCK 外执行，
        这样导入大文件时不会阻塞并发的检索 / 前端轮询；只有最终校验幂等与
        collection.add（触碰 ChromaDB 原生资源）才持锁。
        """
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        text = read_document(path)
        if not text:
            _log(f"[warn] {path} 解析出空文本")
            return 0
        chunks = chunk_text(text, CHUNK, OVERLAP)
        doc_id = self._doc_hash(path)
        # 锁外预计算 embedding（耗时部分并发进行）
        embs = [self.llm.embed(c) for c in chunks]
        metadatas = [{"doc": os.path.basename(path), "chunk": i} for i in range(len(chunks))]
        ids = [f"{doc_id}#{i}" for i in range(len(chunks))]
        with _RETRIEVE_LOCK:
            if self.collection.get(ids=[doc_id])["ids"]:
                _log(f"[skip] {os.path.basename(path)} 已入库")
                return 0
            self.collection.add(ids=ids, documents=chunks, metadatas=metadatas,
                                embeddings=embs)
            # 失效缓存（corpus / bm25 需要重建）
            self._corpus = None
            self._bm25 = None
            _log(f"[ok] {os.path.basename(path)} -> {len(chunks)} chunks")
            return len(chunks)

    def index_dir(self, dir_path: Optional[str] = None) -> int:
        dir_path = dir_path or DOCS_DIR
        total = 0
        for fname in sorted(os.listdir(dir_path)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in ALLOWED:
                total += self.add_document(os.path.join(dir_path, fname))
        return total

    # ------------------------------------------------------------- 语料/BM25
    def _load_corpus(self) -> dict:
        """载入全量语料 {id: {text, doc, chunk}}，供 BM25 与全文回退。

        整个 collection.get 循环都必须在 _RETRIEVE_LOCK 内执行：前端 /api/documents
        轮询与多 Agent 研究者的 collection.query 会并发走到这里，hnswlib 并发读会段错误。
        search() 内部也会调用本方法，RLock 可重入所以不构成死锁。
        """
        with _RETRIEVE_LOCK:
            if self._corpus is not None:
                return self._corpus
            corpus = {}
            # 优先读 sidecar 缓存（避免启动时全量拉取）
            if os.path.exists(_CORPUS_FILE):
                try:
                    corpus = json.load(open(_CORPUS_FILE, encoding="utf-8"))
                except Exception:
                    corpus = {}
            # 拉取增量（collection 里没有的都补上）
            offset = 0
            while True:
                got = self.collection.get(limit=500, offset=offset,
                                          include=["documents", "metadatas"])
                ids = got.get("ids", [])
                if not ids:
                    break
                for i, cid in enumerate(ids):
                    if cid not in corpus:
                        corpus[cid] = {
                            "text": (got.get("documents") or [])[i],
                            "doc": (got.get("metadatas") or [{}])[i].get("doc", "?"),
                            "chunk": (got.get("metadatas") or [{}])[i].get("chunk", 0),
                        }
                offset += len(ids)
            self._corpus = corpus
            try:
                json.dump(corpus, open(_CORPUS_FILE, "w", encoding="utf-8"),
                          ensure_ascii=False)
            except Exception:
                pass
        return self._corpus

    def _get_bm25(self):
        if self._bm25 is None:
            from rank_bm25 import BM25Okapi
            corpus = self._load_corpus()
            tokenized = [_split_words(v["text"]) for v in corpus.values()]
            self._bm25 = BM25Okapi(tokenized)
        return self._bm25

    def _bm25_search(self, query: str, top_k: int = RETRIEVAL_TOP_K):
        """BM25 检索 -> [(corpus_id, score)]。语料为空返回 []。"""
        corpus = self._load_corpus()
        if not corpus:
            return []
        bm25 = self._get_bm25()
        scores = bm25.get_scores(_split_words(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out = []
        for idx in order:
            if scores[idx] <= 0:
                break
            cid = list(corpus.keys())[idx]
            out.append((cid, float(scores[idx])))
            if len(out) >= top_k:
                break
        return out

    # --------------------------------------------------------------- 检索
    def _prep_queries(self, query: str) -> List[str]:
        """查询改写在锁外执行：LLM 调用最耗时，多 Agent 研究者应并发改写，
        而不是在 _RETRIEVE_LOCK 内串行排队（违背"推理并发、检索只串行毫秒级"的设计）。"""
        try:
            return self._expand_query(query) if QUERY_EXPANSION else [query]
        except Exception:
            return [query]

    def search(self, query: str, top_k: int = TOP_K) -> List[Tuple[str, str, float]]:
        """混合检索 -> [(text, source, score)]。

        管线：查询改写（可选，锁外并发）→ 向量∪BM25 → RRF 融合 → 近重复去重 →
        cross-encoder 重排 → 自适应候选池 → 上下文压缩。
        返回结构保持 (text, source, score) 不变（压缩对调用方透明）。
        任何环节降级都不会中断（纯向量是保底）。
        """
        queries = self._prep_queries(query)
        # 串行化共享原生资源（ChromaDB/hnsw、cross-encoder），见 _RETRIEVE_LOCK 注释
        with _RETRIEVE_LOCK:
            return self._search_unlocked(query, top_k, queries)

    def search_with_meta(self, query: str, top_k: int = TOP_K) -> Tuple[List[Tuple[str, str, float]], dict]:
        """混合检索 + 检索元信息 -> (results, meta)。

        meta = {confidence: 0~1, top_score: float, compression_applied: bool,
                sources: [文档名去重]}。
        confidence = min(top_score, 1)。同样在 _RETRIEVE_LOCK 内完成。
        """
        queries = self._prep_queries(query)
        with _RETRIEVE_LOCK:
            results, meta = self._search_with_meta_unlocked(query, top_k, queries)
            self.last_meta = meta
            return results, meta

    def _search_unlocked(self, query: str, top_k: int = TOP_K,
                         queries: Optional[List[str]] = None) -> List[Tuple[str, str, float]]:
        results, _ = self._search_with_meta_unlocked(query, top_k, queries)
        return results

    def _search_with_meta_unlocked(self, query: str, top_k: int = TOP_K,
                                   queries: Optional[List[str]] = None):
        """完整检索管线（必须在 _RETRIEVE_LOCK 内调用，共享原生资源串行化）。

        查询改写结果由调用方在锁外计算好传入（LLM 调用并发进行，不占用锁）。
        """
        if queries is None:
            queries = [query]

        # 1. 各检索源打分
        vec_hits: dict = {}     # cid -> {"rank":..., "score":...}
        bm_hits: dict = {}
        for q in queries:
            for cid, score in self._vector_search(q, RETRIEVAL_TOP_K):
                vec_hits[cid] = max(vec_hits.get(cid, 0), score)
            for cid, score in self._bm25_search(q, RETRIEVAL_TOP_K):
                bm_hits[cid] = max(bm_hits.get(cid, 0), score)

        meta = {"confidence": 0.0, "top_score": 0.0,
                "compression_applied": False, "sources": []}
        fused = self._rrf_fuse([vec_hits, bm_hits], weights=[1 - BM25_WEIGHT, BM25_WEIGHT])
        if not fused:
            return [], meta

        # 2. 重排候选池
        corpus = self._load_corpus()
        cand = [(corpus[cid]["text"], corpus[cid]["doc"], score)
                for cid, score in fused[:RETRIEVAL_TOP_K] if cid in corpus]

        # 3. 近重复去重（重排前，丢弃 >95% 字符级相同的片段）
        if DEDUP and len(cand) > 1:
            try:
                cand = _dedup_candidates(cand)
            except Exception as e:
                _log(f"[warn] near-dup dedup failed: {e}")

        # 4. cross-encoder 重排（可选，失败回退到 RRF 序）
        reranked = False
        if RERANK and len(cand) >= 2:
            cand, reranked = self._rerank(query, cand)

        # 5. 自适应候选池：剔除重排分过弱的填充，不让弱结果稀释上下文。
        #    只在检索置信度高（top_score >= 0.5）时才收紧，且始终保底 2 条证据——
        #    弱检索时保留全部 top_k，避免证据不足导致 Agent 误判"知识库无此内容"。
        if ADAPTIVE_TOP_K and reranked and cand:
            try:
                top_score = max(s for _, _, s in cand)
                if top_score >= 0.5:
                    thr = max(0.5 * top_score, 0.15)
                    kept = [c for c in cand if c[2] >= thr]
                    if not kept:          # 全弱分（如全负 logits）时保底最强一条
                        kept = cand[:1]
                    if len(kept) < 2 and len(cand) >= 2:
                        kept = sorted(cand, key=lambda c: -c[2])[:2]
                    cand = kept
            except Exception as e:
                _log(f"[warn] adaptive top-k failed: {e}")

        results = cand[:top_k]

        # 6. 上下文压缩：只保留与查询相关的句子（压缩对返回结构透明）
        if COMPRESSION and results:
            try:
                compressed = []
                applied = False
                for t, src, score in results:
                    ct, changed = _compress_chunk(query, t, COMPRESSION_THRESHOLD)
                    applied = applied or changed
                    compressed.append((ct, src, score))
                results = compressed
                meta["compression_applied"] = applied
            except Exception as e:
                _log(f"[warn] contextual compression failed: {e}")

        # 7. 检索元信息
        meta["top_score"] = max((s for _, _, s in results), default=0.0)
        meta["confidence"] = min(meta["top_score"], 1.0)
        for _, src, _ in results:
            if src not in meta["sources"]:
                meta["sources"].append(src)
        return results, meta

    def _vector_search(self, query: str, top_k: int = RETRIEVAL_TOP_K):
        """纯向量检索 -> [(cid, similarity)]"""
        try:
            q_emb = self.llm.embed(query)
            res = self.collection.query(query_embeddings=[q_emb], n_results=min(top_k, 50))
            ids = res.get("ids", [[]])[0]
            dists = res.get("distances", [[]])[0]
            return [(cid, 1 - d) for cid, d in zip(ids, dists)]
        except Exception as e:
            _log(f"[warn] vector search failed: {e}")
            return []

    def _expand_query(self, query: str) -> List[str]:
        """轻量查询改写：一次小 LLM 调用，产出同义/更精确的检索词变体。"""
        try:
            resp = self.llm.chat([
                {"role": "system", "content":
                    "你是检索查询改写器。把用户问题改写成 2 个更利于检索的查询（保留原意、补全专有名词/缩写）。"
                    "只输出 JSON 数组，例如 [\"原始问题\", \"改写1\", \"改写2\"]。"},
                {"role": "user", "content": query},
            ], temperature=0.1, max_tokens=160)
            text = resp["content"].strip().strip("`")
            m = re.search(r"\[.*\]", text, re.S)
            arr = json.loads(m.group(0)) if m else None
            if isinstance(arr, list):
                arr = [str(x) for x in arr if str(x).strip()]
                # 改写得离谱的丢弃（长度/重叠过滤）
                base = _split_words(query)
                good = [q for q in arr
                        if len(q) <= max(60, len(query) * 2)
                        and len(_split_words(q)) >= len(base) * 0.5]
                if good:
                    return good[:3]
            return [query]
        except Exception:
            return [query]

    def _rrf_fuse(self, rank_lists: List[dict], weights: Optional[List[float]] = None,
                  k: int = 60) -> List[Tuple[str, float]]:
        """Reciprocal Rank Fusion：多路结果按排名加权融合。"""
        if weights is None:
            weights = [1.0] * len(rank_lists)
        score: dict = {}
        for lst, w in zip(rank_lists, weights):
            ranked = sorted(lst.items(), key=lambda kv: -kv[1])
            for i, (cid, _) in enumerate(ranked):
                score[cid] = score.get(cid, 0.0) + w / (k + i)
        fused = sorted(score.items(), key=lambda kv: -kv[1])
        return fused

    def _rerank(self, query: str, cand: List[Tuple[str, str, float]]) -> Tuple[List[Tuple[str, str, float]], bool]:
        """cross-encoder 重排：(query, doc) 联合打分，按分排序。

        Returns: (重排后候选, 是否成功)。失败时原样返回候选 + False，
        供上层决定是否应用自适应候选池（只在真实重排分上生效）。
        """
        global _SHARED_RERANKER
        try:
            if _SHARED_RERANKER is None:
                from sentence_transformers import CrossEncoder
                _SHARED_RERANKER = CrossEncoder(RERANK_MODEL, max_length=512)
            self._reranker = _SHARED_RERANKER
            pairs = [(query, t) for t, _, _ in cand]
            scores = self._reranker.predict(pairs, show_progress_bar=False)
            # 保留原始 RRF 分作 tie-break；转原生 float（numpy 标量不 JSON 安全）
            scored = sorted(zip(cand, scores), key=lambda x: -x[1])
            return [(t, src, round(float(score), 4)) for (t, src, _), score in scored], True
        except Exception as e:
            _log(f"[warn] rerank unavailable, use fused order: {e}")
            return cand, False

    # ----------------------------------------------------------- 其他查询
    def list_documents(self) -> List[dict]:
        """列出知识库中的文档及片段统计。"""
        corpus = self._load_corpus()
        stats: dict = {}
        for v in corpus.values():
            d = v["doc"]
            stats[d] = stats.get(d, 0) + 1
        return [{"doc": d, "chunks": c} for d, c in sorted(stats.items())]

    def doc_count(self) -> int:
        return len(self.list_documents())

    def chunk_count(self) -> int:
        return len(self._load_corpus())

    def remove_document(self, doc: str) -> int:
        """按文档名删除（返回删除的片段数）。"""
        with _RETRIEVE_LOCK:
            corpus = self._load_corpus()
            doomed = [cid for cid, v in corpus.items() if v["doc"] == doc]
            if doomed:
                self.collection.delete(ids=doomed)
            self._corpus = None
            self._bm25 = None
            try:
                os.remove(_CORPUS_FILE)
            except OSError:
                pass
            return len(doomed)

    def get_document(self, doc: str, limit: int = 2000) -> str:
        """读取某文档的原始文本（合并片段，去重）。"""
        corpus = self._load_corpus()
        parts = sorted(
            (v for v in corpus.values() if v["doc"] == doc),
            key=lambda v: v["chunk"],
        )
        seen, text = set(), []
        for v in parts:
            t = v["text"]
            if t not in seen:
                seen.add(t)
                text.append(t)
        full = "\n".join(text)
        return full[:limit]


if __name__ == "__main__":
    from .llm import LLMBackend
    store = RAGStore(LLMBackend())
    print("== 入库演示 ==")
    store.index_dir()
    print("== 混合检索演示 ==")
    for t, s, sc in store.search("项目背景"):
        print(f"[{sc}] ({s}) {t[:80]}")
