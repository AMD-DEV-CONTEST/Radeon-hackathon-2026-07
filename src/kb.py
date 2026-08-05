"""
知识库检索引擎 (M5) — 向量检索 + BM25 兜底

设计:
  - 嵌入模型: bge-small-zh-v1.5 (~100MB, CPU 运行, 不占 GPU)
  - 向量存储: SQLite BLOB (float32 数组, 512 维)
  - 向量检索: numpy 余弦相似度 (in-process, 无需 sqlite-vec 扩展)
  - BM25 兜底: SQLite FTS5 (runbooks_fts 表)
  - 混合检索: 向量 top-k + BM25 top-k 合并去重, 向量优先

降级策略:
  1. bge-small 可用 → 向量检索 (语义匹配, 最优)
  2. bge-small 不可用 → BM25 (关键词匹配, 兜底)
  3. FTS5 不可用 → LIKE 模糊匹配 (最后兜底)

bge-small 依赖 (可选, 缺失自动降级):
  pip install sentence-transformers
  首次使用自动下载模型 (~100MB, 缓存到 ~/.cache/huggingface)
"""
import logging
import struct
import threading
import time

try:
    import numpy as np
except ImportError:  # numpy 缺失时 cosine_similarity 回退纯 Python
    np = None

logger = logging.getLogger(__name__)

# ---- 嵌入模型 (懒加载, 单例) ----

_embedding_model = None
_embedding_lock = threading.Lock()
_embedding_available = None  # None=未检测, True/False=已检测


def _try_load_embedding_model():
    """懒加载 bge-small-zh 嵌入模型 (CPU)

    Returns: model or None (不可用时)
    """
    global _embedding_model, _embedding_available
    if _embedding_available is not None:
        return _embedding_model
    with _embedding_lock:
        if _embedding_available is not None:
            return _embedding_model
        try:
            from sentence_transformers import SentenceTransformer
            # bge-small-zh-v1.5: 512维, ~100MB, CPU 友好
            model_name = "BAAI/bge-small-zh-v1.5"
            logger.info(f"Loading embedding model: {model_name} (CPU)...")
            t0 = time.time()
            _embedding_model = SentenceTransformer(
                model_name, device="cpu",
                # 离线环境可指定本地路径:
                # model_kwargs={"local_files_only": True}
            )
            _embedding_available = True
            logger.info(f"Embedding model loaded in {time.time()-t0:.1f}s "
                        f"(dim={_embedding_model.get_sentence_embedding_dimension()})")
        except ImportError:
            logger.warning("sentence-transformers 未安装, 向量检索降级为 BM25。"
                           "安装: pip install sentence-transformers")
            _embedding_available = False
        except Exception as e:
            logger.warning(f"嵌入模型加载失败 ({e}), 降级为 BM25")
            _embedding_available = False
    return _embedding_model


def is_vector_search_available() -> bool:
    """检查向量检索是否可用 (bge 模型是否加载成功)"""
    return _try_load_embedding_model() is not None


# ---- 向量编码 / 序列化 ----

def encode_text(text: str) -> bytes:
    """将文本编码为 float32 向量 BLOB

    Returns: bytes (float32 little-endian 数组), 或 None (模型不可用)
    """
    model = _try_load_embedding_model()
    if model is None or not text.strip():
        return None
    try:
        # bge 模型推荐 query 加前缀 "为这个句子生成表示以用于检索相关文章："
        # 但为简化, 直接编码 (效果略有损失, 但够用)
        vec = model.encode(text, normalize_embeddings=True)
        # 序列化为 float32 bytes
        return struct.pack(f'{len(vec)}f', *vec)
    except Exception as e:
        logger.error(f"encode_text failed: {e}")
        return None


def decode_embedding(blob: bytes) -> list:
    """将 BLOB 解码为 float32 列表"""
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


def cosine_similarity(a: list, b: list) -> float:
    """计算两个向量的余弦相似度 (已归一化则等于点积)"""
    if not a or not b or len(a) != len(b):
        return 0.0
    # 已归一化: dot product。numpy 可用时向量化 (100x+ 快于纯 Python 循环)
    if np is not None:
        return float(np.dot(np.asarray(a, dtype=np.float32),
                            np.asarray(b, dtype=np.float32)))
    return sum(x * y for x, y in zip(a, b))


# ---- 向量索引管理 ----

def ensure_embeddings(store):
    """确保所有 approved runbook 都有 embedding (缺失则编码)

    在 search_kb 首次调用时触发, 后续新增/修改 runbook 后也会触发。
    """
    pending = store.get_runbooks_for_embedding()
    if not pending:
        return
    model = _try_load_embedding_model()
    if model is None:
        return  # 模型不可用, 跳过
    logger.info(f"Encoding {len(pending)} runbooks without embedding...")
    for rb in pending:
        # 编码 title + content + tags 拼接 (tags 权重低, 放最后)
        text = f"{rb['title']}\n{rb['content']}\n{rb['tags']}"
        blob = encode_text(text)
        if blob:
            store.update_runbook_embedding(rb["id"], blob)
            logger.info(f"  encoded: {rb['id']} ({rb['title'][:30]})")


# ---- 混合检索 ----

def hybrid_search(store, query: str, limit: int = 5) -> list:
    """混合检索: 向量检索 + BM25 合并去重

    Args:
        store: Store 实例
        query: 查询文本
        limit: 返回条数上限
    Returns:
        list of dict: {id, title, content, tags, source, score, match_type}
        按 score 降序 (向量检索的 score 优先级更高)
    """
    if not query.strip():
        return []

    results = {}  # id -> result (去重)

    # 1. 向量检索 (如果可用)
    model = _try_load_embedding_model()
    if model is not None:
        try:
            query_vec = decode_embedding(encode_text(query))
            all_runbooks = store.get_all_runbook_embeddings()
            if query_vec and all_runbooks:
                scored = []
                for rb in all_runbooks:
                    rb_vec = decode_embedding(rb["embedding"])
                    score = cosine_similarity(query_vec, rb_vec)
                    scored.append((rb, score))
                # 取 top-N (limit * 2, 多取一些给合并去重)
                scored.sort(key=lambda x: x[1], reverse=True)
                for rb, score in scored[:limit * 2]:
                    results[rb["id"]] = {
                        "id": rb["id"], "title": rb["title"],
                        "content": rb["content"], "tags": rb["tags"],
                        "source": rb.get("source", ""),
                        "score": round(float(score), 4),
                        "match_type": "vector",
                    }
                logger.info(f"KB vector search: {len(results)} results for '{query[:50]}'")
        except Exception as e:
            logger.warning(f"Vector search failed ({e}), fallback to BM25")

    # 2. BM25 检索 (兜底或补充)
    try:
        fts_results = store.search_runbooks_fts(query, limit=limit * 2)
        for r in fts_results:
            if r["id"] not in results:
                # FTS5 bm25() 返回负值, 越负越相关 (db.py 按 score ASC 排序)
                bm25_score = r.get("score", 0)
                # 单调映射 |score|->(0,1): 越相关分越高, 且不会像 1+score 那样
                # 在 score<-1 时被钳到 0 (原实现的 bug: 最相关结果反而垫底)
                strength = -bm25_score if bm25_score < 0 else 0.0
                norm_score = strength / (1.0 + strength)
                results[r["id"]] = {
                    "id": r["id"], "title": r["title"],
                    "content": r["content"], "tags": r["tags"],
                    "source": r.get("source", ""),
                    "score": round(norm_score, 4),
                    "match_type": "bm25",
                }
        logger.info(f"KB BM25 search: added {len(fts_results)} results")
    except Exception as e:
        logger.warning(f"BM25 search failed: {e}")

    # 3. 排序: 向量优先 (score 高), BM25 次之
    # 向量 score 通常 0.5-1.0, BM25 norm 0-1.0, 同区间可直接比
    # 但向量更可信, 给 0.1 加成
    ranked = list(results.values())
    for r in ranked:
        if r["match_type"] == "vector":
            r["score"] = round(r["score"] + 0.1, 4)
    ranked.sort(key=lambda x: x["score"], reverse=True)

    return ranked[:limit]


# ---- 初始化 (启动时预加载模型, 可选) ----

def warmup():
    """预热: 启动时加载嵌入模型 (可选, 不调用则首次 search_kb 时加载)"""
    _try_load_embedding_model()
