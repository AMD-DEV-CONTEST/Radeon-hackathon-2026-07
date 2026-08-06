# -*- coding: utf-8 -*-
"""
rag/retriever.py — 药品目录检索器

实现《设计文档.md》第 6.3 节的检索策略：
  1. 精确/模糊名称匹配（规范化后比对 drug_name / generic_name），命中则高置信直接返回；
  2. 语义召回：未精确命中时，用本地 bge embedding + Chroma 相似度检索 top_k；
  3. 阈值过滤：最高分低于阈值且未命中商保创新药目录 → 判定为「目录外」(in_catalog=false)。

底层向量库为 Chroma（余弦空间），embedding 为本地 sentence-transformers（bge），
均本地执行、不调用远程 API。
"""

import os
import re
import json
import threading
from functools import lru_cache

import rag  # noqa: F401  触发 HF_ENDPOINT 设置与 sys.path 注入
import config as cfg

# 无封顶的哨兵值（Chroma metadata 不允许 None）
NO_CAP = -1.0

# Rerank / BM25 依赖懒加载（缺失时优雅降级到纯向量检索）
try:
    import jieba
    _HAS_JIEBA = True
except Exception:
    jieba = None
    _HAS_JIEBA = False

_rank_bm25 = None
_cross_encoder = None
_cross_lock = threading.Lock()


# ----------------------------------------------------------------------------
# 名称规范化与目录加载
# ----------------------------------------------------------------------------
def normalize_name(name: str) -> str:
    """去除空格、括号及规格/剂量尾巴，便于精确匹配。"""
    if not name:
        return ""
    s = str(name)
    # 去掉规格/剂量片段，如 0.25g*24粒、100mg、250ml 等
    s = re.sub(r"\d+(\.\d+)?\s*(mg|g|ml|ug|µg|iu|万单位|单位|粒|片|支|袋|瓶|盒|丸|贴|ml/支)", "", s, flags=re.I)
    s = re.sub(r"[\s\(\)（）\[\]【】*×xX:：,，。\-—/]", "", s)
    return s.strip().lower()


def load_catalog(path: str = None) -> list:
    """读取药品目录 JSON，返回 drugs 列表。"""
    path = path or cfg.DRUG_CATALOG_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("drugs", [])
    return data  # 兼容纯数组格式


def doc_text(entry: dict) -> str:
    """将可检索字段拼成文档文本（用于建库与语义检索）。"""
    parts = [entry.get("drug_name", ""), entry.get("generic_name", ""),
             entry.get("spec", ""), entry.get("dosage_form", "")]
    return " ".join(p for p in parts if p).strip()


def to_metadata(entry: dict) -> dict:
    """将目录条目转为 Chroma 可存的 metadata（无 None）。"""
    cap = entry.get("cap", None)
    return {
        "drug_name": entry.get("drug_name", "") or "",
        "generic_name": entry.get("generic_name", "") or "",
        "spec": entry.get("spec", "") or "",
        "dosage_form": entry.get("dosage_form", "") or "",
        "category": entry.get("category", "") or "",
        "commercial_innovative": bool(entry.get("commercial_innovative", False)),
        "self_pay_1": float(entry.get("self_pay_1", 0.0) or 0.0),
        "self_pay_2": float(entry.get("self_pay_2", 0.0) or 0.0),
        "reimburse_ratio": float(entry.get("reimburse_ratio", 0.0) or 0.0),
        "cap": float(cap) if cap is not None else NO_CAP,
        "note": entry.get("note", "") or "",
        "catalog_source": entry.get("catalog_source", "") or "",
    }


def _metadata_to_match(md: dict, score: float, in_catalog: bool) -> dict:
    """将 Chroma metadata 还原为对外的 match 结构（cap 哨兵还原为 None）。"""
    cap = md.get("cap", NO_CAP)
    return {
        "matched_name": md.get("drug_name", ""),
        "generic_name": md.get("generic_name", ""),
        "spec": md.get("spec", ""),
        "dosage_form": md.get("dosage_form", ""),
        "category": md.get("category", ""),
        "commercial_innovative": bool(md.get("commercial_innovative", False)),
        "self_pay_1": float(md.get("self_pay_1", 0.0)),
        "self_pay_2": float(md.get("self_pay_2", 0.0)),
        "reimburse_ratio": float(md.get("reimburse_ratio", 0.0)),
        "cap": None if cap == NO_CAP else float(cap),
        "note": md.get("note", ""),
        "catalog_source": md.get("catalog_source", ""),
        "score": round(float(score), 4),
        "in_catalog": in_catalog,
    }


# ----------------------------------------------------------------------------
# Embedding 模型（进程内单例，懒加载）
# ----------------------------------------------------------------------------
_embed_lock = threading.Lock()
_embedder = None


def get_embedder():
    """懒加载并缓存 SentenceTransformer 实例。"""
    global _embedder
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(cfg.EMBEDDING_MODEL, device=cfg.EMBEDDING_DEVICE)
    return _embedder


def embed_documents(texts):
    """文档向量化（不加查询前缀），归一化。返回 list[list[float]]。"""
    model = get_embedder()
    vecs = model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return vecs.tolist()


def embed_query(text: str):
    """查询向量化（加 bge 查询前缀），归一化。返回 list[float]。"""
    model = get_embedder()
    q = f"{cfg.BGE_QUERY_PREFIX}{text}" if cfg.BGE_QUERY_PREFIX else text
    vec = model.encode([q], normalize_embeddings=True, convert_to_numpy=True)[0]
    return vec.tolist()


# ----------------------------------------------------------------------------
# 混合检索辅助：BM25 分词 / RRF 融合 / Reranker
# ----------------------------------------------------------------------------
def _tokenize(text: str) -> list:
    """中文优先 jieba 分词，未安装则退化为基础切分。"""
    s = str(text or "")
    if _HAS_JIEBA:
        return [t for t in jieba.cut(s) if t.strip()]
    # 退化：按空白 + 药名常见分隔切分
    return [t for t in re.split(r"[\s,，。;；·\-—/()（）\[\]【】]+", s) if t.strip()]


def get_bm25():
    """懒加载 BM25 索引（基于目录 doc_text 语料）。"""
    global _rank_bm25
    if _rank_bm25 is None:
        with _cross_lock:
            if _rank_bm25 is None:
                from rank_bm25 import BM25Okapi
                entries = load_catalog()
                corpus = [_tokenize(doc_text(e)) for e in entries if doc_text(e)]
                _rank_bm25 = BM25Okapi(corpus)
    return _rank_bm25


def _rrf_fuse(ranked_lists: list, k: int = None) -> dict:
    """Reciprocal Rank Fusion：多路排序融合为 dict[doc_index] -> fused_score。

    ranked_lists: 每路为 [(doc_index, score)]，doc_index 为目录条目下标。
    """
    k = k if k is not None else cfg.RAG_RRF_K
    fused: dict = {}
    for ranked in ranked_lists:
        for rank, (idx, _score) in enumerate(ranked):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def get_reranker():
    """懒加载 CrossEncoder reranker。"""
    global _cross_encoder
    if _cross_encoder is None:
        with _cross_lock:
            if _cross_encoder is None:
                from sentence_transformers import CrossEncoder
                _cross_encoder = CrossEncoder(cfg.RAG_RERANK_MODEL, device=cfg.RAG_RERANK_DEVICE)
    return _cross_encoder


def rerank(query: str, candidates: list, top_k: int) -> list:
    """对 [entry] 候选做 CrossEncoder 重排，返回打分后的前 top_k 个 (entry, score)。

    分数经 sigmoid 归一化到 (0,1)，便于与 RAG_SCORE_THRESHOLD 统一比较。
    """
    import math
    if not candidates:
        return []
    texts = [doc_text(e) for e in candidates]
    model = get_reranker()
    pairs = [(query, t) for t in texts]
    raw = model.predict(pairs, show_progress_bar=False)
    scored = []
    for e, s in zip(candidates, raw):
        norm = 1.0 / (1.0 + math.exp(-float(s)))
        scored.append((e, norm))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ----------------------------------------------------------------------------
# 检索器
# ----------------------------------------------------------------------------
class DrugCatalogRetriever:
    """药品目录检索器：精确匹配 + 混合召回(BM25+向量) + Rerank + 阈值判定。"""

    def __init__(self, chroma_dir: str = None, collection: str = None,
                 top_k: int = None, score_threshold: float = None):
        self.chroma_dir = chroma_dir or cfg.CHROMA_DIR
        self.collection_name = collection or cfg.CHROMA_COLLECTION
        self.top_k = top_k or cfg.RAG_TOP_K
        self.score_threshold = score_threshold if score_threshold is not None else cfg.RAG_SCORE_THRESHOLD
        self._client = None
        self._collection = None
        # 精确匹配索引：normalize(name) -> entry（drug_name 与 generic_name 均入表）
        self._exact = {}
        self._build_exact_index()

    # ---- 精确匹配索引 ----
    def _build_exact_index(self):
        try:
            entries = load_catalog()
        except Exception:
            entries = []
        for e in entries:
            for key in (e.get("drug_name"), e.get("generic_name")):
                nk = normalize_name(key)
                if nk:
                    self._exact.setdefault(nk, e)

    # ---- Chroma 连接（懒加载）----
    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=self.chroma_dir)
            self._collection = self._client.get_collection(self.collection_name)
        return self._collection

    def _exact_lookup(self, drug_name: str):
        nq = normalize_name(drug_name)
        if not nq:
            return None
        if nq in self._exact:
            return self._exact[nq]
        # 包含关系：查询名包含某通用名（或反之）
        for nk, e in self._exact.items():
            if len(nk) >= 3 and (nk in nq or nq in nk):
                return e
        return None

    # ---- 向量召回（返回 [(entry, score)]）----
    def _vector_recall(self, drug_name: str, top_k: int = None):
        top_k = top_k or cfg.RAG_VECTOR_TOP_K
        try:
            q_emb = embed_query(drug_name)
            res = self.collection.query(
                query_embeddings=[q_emb],
                n_results=top_k,
                include=["metadatas", "distances"],
            )
        except Exception:
            return []
        metadatas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        out = []
        for md, dist in zip(metadatas, distances):
            score = max(0.0, 1.0 - float(dist))
            entry = self._md_to_entry(md)
            if entry is not None:
                out.append((entry, score))
        return out

    def _md_to_entry(self, md: dict):
        """将 Chroma metadata 还原为目录条目（按 drug_name+generic_name 反查）。"""
        name = md.get("drug_name", "")
        for e in load_catalog():
            if e.get("drug_name") == name:
                return e
        return None

    # ---- BM25 召回（返回 [(entry, score)]）----
    def _bm25_recall(self, drug_name: str, top_k: int = None):
        top_k = top_k or cfg.RAG_BM25_TOP_K
        if not cfg.RAG_HYBRID:
            return []
        try:
            bm = get_bm25()
            entries = load_catalog()
            scores = bm.get_scores(_tokenize(drug_name))
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            ranked = [i for i in ranked if scores[i] > 0.0][:top_k]
            return [(entries[i], float(scores[i])) for i in ranked]
        except Exception:
            return []

    # ---- Rerank（返回 [(entry, rerank_score)]）----
    def _rerank(self, drug_name: str, candidates: list, top_k: int = None):
        top_k = top_k or self.top_k
        if not candidates:
            return []
        if not cfg.RAG_RERANK:
            return list(candidates[:top_k])
        try:
            return rerank(drug_name, [e for e, _s in candidates], top_k)
        except Exception:
            return list(candidates[:top_k])

    # ---- 混合召回（BM25 + 向量 → RRF 融合）----
    def _hybrid_recall(self, drug_name: str, top_k: int = None):
        vec = self._vector_recall(drug_name)      # [(entry, score)]
        bm = self._bm25_recall(drug_name)          # [(entry, score)]

        # 按条目名对齐两路排名
        order = {}
        for e, _s in vec + bm:
            name = e.get("drug_name")
            if name and name not in order:
                order[name] = len(order)

        vec_ranked = [(order[e.get("drug_name")], s) for e, s in vec if e.get("drug_name") in order]
        bm_ranked = [(order[e.get("drug_name")], s) for e, s in bm if e.get("drug_name") in order]

        fused = _rrf_fuse([vec_ranked, bm_ranked])
        if not fused:
            return []

        name_to_entry = {e.get("drug_name"): e for e, _ in vec + bm}
        top_idx = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
        max_f = max(fused.values()) or 1.0
        results = []
        for idx, fscore in top_idx:
            name = [n for n, i in order.items() if i == idx]
            if name and name[0] in name_to_entry:
                results.append((name_to_entry[name[0]], fscore / max_f))
        return results

    def search(self, drug_name: str, top_k: int = None) -> dict:
        """检索药品目录，返回 {query, matches:[...]}。"""
        top_k = top_k or self.top_k

        # 第一层：精确/模糊名称匹配
        hit = self._exact_lookup(drug_name)
        if hit is not None:
            md = to_metadata(hit)
            in_catalog = md["category"] in ("甲类", "乙类")
            match = _metadata_to_match(md, score=1.0, in_catalog=in_catalog)
            match["match_type"] = "exact"
            return {"query": drug_name, "matches": [match]}

        # 第二层：混合召回（BM25 + 向量，RRF 融合）→ Rerank
        try:
            if cfg.RAG_HYBRID:
                candidates = self._hybrid_recall(drug_name, top_k=cfg.RAG_FUSION_K)
            else:
                candidates = self._vector_recall(drug_name, top_k=cfg.RAG_FUSION_K)
        except Exception as e:
            return {"query": drug_name, "matches": [], "error": f"检索失败: {e}"}

        reranked = self._rerank(drug_name, candidates, top_k=top_k)

        matches = []
        for entry, rscore in reranked:
            md = to_metadata(entry)
            # 第三层：阈值判定。低于阈值且非商保创新药 → 目录外
            in_catalog = (rscore >= self.score_threshold) and (md["category"] in ("甲类", "乙类"))
            m = _metadata_to_match(md, score=rscore, in_catalog=in_catalog)
            if cfg.RAG_RERANK:
                m["match_type"] = "rerank"
            elif cfg.RAG_HYBRID:
                m["match_type"] = "hybrid"
            else:
                m["match_type"] = "semantic"
            matches.append(m)

        return {"query": drug_name, "matches": matches}


@lru_cache(maxsize=1)
def get_retriever() -> "DrugCatalogRetriever":
    """进程内单例检索器。"""
    return DrugCatalogRetriever()


if __name__ == "__main__":
    # 简单自测：python -m rag.retriever 阿莫西林
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "阿莫西林胶囊"
    r = get_retriever()
    out = r.search(q)
    print(json.dumps(out, ensure_ascii=False, indent=2))
