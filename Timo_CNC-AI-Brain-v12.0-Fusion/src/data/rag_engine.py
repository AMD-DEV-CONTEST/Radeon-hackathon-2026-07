"""轻量级RAG引擎 — "小刀切梨"版本
零外部依赖: Ollama Embedding API × SQLite × numpy
符合原则: 不装新模型, 不拉重型向量库, 不依赖GPU
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import json, sqlite3, hashlib, time, re
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import numpy as np
import urllib.request

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RAG_DB = DATA_DIR / "rag_store.db"
STEP_DIR = DATA_DIR / "step"
UPLOAD_DIR = DATA_DIR / "uploads"
DOCS_DIR = DATA_DIR / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL = "qwen2.5:1.5b"
EMBED_DIM = 1536
OLLAMA_URL = "http://localhost:11434/api/embeddings"


# ══════════════════════════════════════════════════════
# Embedding 层
# ══════════════════════════════════════════════════════

def _embed(text: str) -> Optional[List[float]]:
    """调用Ollama Embedding API。零额外依赖。"""
    try:
        data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("embedding")
    except Exception:
        return None


def _cosine_sim(a: List[float], b: List[float]) -> float:
    """余弦相似度。"""
    arr_a, arr_b = np.array(a), np.array(b)
    norm = np.linalg.norm(arr_a) * np.linalg.norm(arr_b)
    return float(np.dot(arr_a, arr_b) / norm) if norm > 0 else 0.0


# ══════════════════════════════════════════════════════
# 存储层 — SQLite (std only)
# ══════════════════════════════════════════════════════

def _get_db() -> sqlite3.Connection:
    """获取/创建 SQLite 数据库。"""
    conn = sqlite3.connect(str(RAG_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # 文档表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            title TEXT,
            doc_type TEXT,
            source_path TEXT,
            source_uri TEXT,
            tags TEXT,
            metadata TEXT,
            content TEXT,
            embedding BLOB,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    # 层级引索表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            name TEXT,
            item_type TEXT,
            parent_path TEXT,
            doc_id TEXT,
            level INTEGER,
            metadata TEXT,
            created_at TEXT
        )
    """)
    # FTS5全文搜索
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(doc_id, title, content, tags)")
    except Exception:
        pass
    return conn


# ══════════════════════════════════════════════════════
# 文档操作
# ══════════════════════════════════════════════════════

def index_document(doc_id: str, title: str, content: str,
                   doc_type: str = "text", source_path: str = "",
                   tags: List[str] = None, metadata: Dict = None) -> Dict:
    """索引一份文档 → 分块 → 向量化 → 存储。"""
    embedding = _embed(content[:2048])  # 截断防止超长
    if not embedding:
        return {"status": "error", "error": "Embedding失败, Ollama是否运行?"}

    conn = _get_db()
    now = datetime.now().isoformat()
    tags_str = ",".join(tags or [])
    meta_str = json.dumps(metadata or {}, ensure_ascii=False)
    embed_bytes = json.dumps(embedding).encode()

    conn.execute("""
        INSERT OR REPLACE INTO documents
        (doc_id, title, doc_type, source_path, tags, metadata, content, embedding, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (doc_id, title, doc_type, source_path, tags_str, meta_str, content[:5000], embed_bytes, now, now))

    # 同时更新FTS
    try:
        conn.execute("INSERT OR REPLACE INTO docs_fts(doc_id, title, content, tags) VALUES (?,?,?,?)",
                     (doc_id, title, content[:5000], tags_str))
    except Exception:
        pass

    conn.commit()
    conn.close()
    return {"status": "ok", "doc_id": doc_id, "embedding_dim": len(embedding)}


def _split_keywords(text: str) -> List[str]:
    """将查询拆分为关键词。"""
    # 拆: 空格/中文词边界
    parts = re.split(r'[\s,，:：]+', text.strip())
    words = []
    for p in parts:
        p = p.strip()
        if len(p) >= 1:
            words.append(p)
    return words


def search(query: str, top_k: int = 8, min_score: float = 0.25,
           filters: Dict = None) -> List[Dict]:
    """搜索 — 关键词先筛 + 语义重排。
    
    策略:
    1. 把查询拆成关键词
    2. 用SQLite LIKE匹配每个关键词 (交集的排前面)
    3. 再用向量语义给结果重排 (cosine similarity)
    4. 关键词命中>0时才fallback到纯语义
    """
    keywords = _split_keywords(query)
    if not keywords:
        return [{"info": "请输入搜索词"}]

    conn = _get_db()
    
    # 阶段1: 关键词LIKE筛选
    candidates = {}
    for kw in keywords:
        like = f"%{kw}%"
        rows = conn.execute(
            "SELECT * FROM documents WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?",
            (like, like, like)
        ).fetchall()
        for r in rows:
            doc_id = r["doc_id"]
            if doc_id not in candidates:
                candidates[doc_id] = {"row": r, "hits": 0}
            candidates[doc_id]["hits"] += 1
    
    # 按命中数排序
    sorted_candidates = sorted(candidates.values(), key=lambda x: -x["hits"])
    
    # 阶段2: 如果有关键词命中, 用语义重排top candidates
    q_embed = _embed(query) if sorted_candidates else None
    results = []
    
    if q_embed and sorted_candidates:
        scored = []
        for c in sorted_candidates[:30]:  # 只重排前30个
            try:
                d_embed = json.loads(c["row"]["embedding"].decode())
                score = _cosine_sim(q_embed, d_embed)
                scored.append((score, c))
            except Exception:
                pass
        scored.sort(key=lambda x: -x[0])
        for score, c in scored[:top_k]:
            r = c["row"]
            results.append({
                "score": round(score, 3),
                "hits": c["hits"],
                "doc_id": r["doc_id"],
                "title": r["title"],
                "doc_type": r["doc_type"],
                "source_path": r["source_path"],
                "tags": r["tags"].split(",") if r["tags"] else [],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                "content_preview": r["content"][:200] if r["content"] else "",
                "created_at": r["created_at"],
            })
    elif sorted_candidates:
        # 无embedding (Ollama不可用) → 纯关键词结果
        for c in sorted_candidates[:top_k]:
            r = c["row"]
            results.append({
                "score": 0.0, "hits": c["hits"],
                "doc_id": r["doc_id"], "title": r["title"],
                "doc_type": r["doc_type"], "source_path": r["source_path"],
                "tags": r["tags"].split(",") if r["tags"] else [],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                "content_preview": r["content"][:200] if r["content"] else "",
                "created_at": r["created_at"],
                "method": "keywords_only"
            })

    conn.close()

    if not results:
        # 兜底: 尝试语义全库扫描 (没有关键词匹配时)
        q_embed = _embed(query)
        if q_embed:
            conn = _get_db()
            rows = conn.execute("SELECT * FROM documents ORDER BY id DESC LIMIT 100").fetchall()
            conn.close()
            scored = []
            for r in rows:
                try:
                    d_embed = json.loads(r["embedding"].decode())
                    score = _cosine_sim(q_embed, d_embed)
                    if score >= min_score:
                        scored.append((score, r))
                except:
                    pass
            scored.sort(key=lambda x: -x[0])
            for score, r in scored[:top_k]:
                results.append({
                    "score": round(score, 3), "hits": 0,
                    "doc_id": r["doc_id"], "title": r["title"],
                    "doc_type": r["doc_type"], "source_path": r["source_path"],
                    "tags": r["tags"].split(",") if r["tags"] else [],
                    "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                    "content_preview": r["content"][:200] if r["content"] else "",
                    "created_at": r["created_at"],
                    "method": "semantic_only"
                })

    if not results:
        return [{"info": "无匹配结果, 请先上传文档"}]
    return results


# ══════════════════════════════════════════════════════
# 层级引索 (Registry) — "留出层级真实文件的引索入口"
# ══════════════════════════════════════════════════════

def register_item(path: str, name: str, item_type: str,
                  parent_path: str = "", doc_id: str = "",
                  metadata: Dict = None) -> Dict:
    """注册一个层级条目到引索树。"""
    conn = _get_db()
    now = datetime.now().isoformat()
    level = path.count("/") if path else 0
    meta_str = json.dumps(metadata or {}, ensure_ascii=False)

    conn.execute("""
        INSERT OR REPLACE INTO registry
        (path, name, item_type, parent_path, doc_id, level, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (path, name, item_type, parent_path, doc_id, level, meta_str, now))
    conn.commit()
    conn.close()
    return {"status": "ok", "path": path, "level": level}


def browse_registry(parent_path: str = "", item_type: str = "",
                    max_level: int = 5) -> List[Dict]:
    """浏览层级引索树。"""
    conn = _get_db()
    if parent_path:
        rows = conn.execute(
            "SELECT * FROM registry WHERE parent_path = ? AND level <= ? ORDER BY item_type, name",
            (parent_path, max_level)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM registry WHERE level <= ? ORDER BY level, parent_path, name", (max_level,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════
# 自动索引: 从已有数据源批量导入
# ══════════════════════════════════════════════════════

def auto_index_orders():
    """索引 orders.db 中的历史订单。"""
    try:
        conn = sqlite3.connect(str(DATA_DIR / "orders.db"))
        cursor = conn.execute("SELECT * FROM orders")
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        count = 0
        for r in rows:
            order = dict(zip(cols, r))
            doc_id = f"order_{order['order_id']}"
            content = (f"订单 {order['order_id']}: {order['customer_name']} 订购"
                       f" {order['part_name']} ({order['material']}) x{order['quantity']}件,"
                       f" 单价¥{order['final_price']/order['quantity']:.1f}, 总价¥{order['final_price']},"
                       f" 表面处理:{order['surface_treatment'] or '无'}, 精度:{order['tolerance'] or '一般'},"
                       f" 利润率:{order['profit_rate']*100:.0f}%")
            tags = [order['material'], order['part_name'].replace(' ',''), '订单',
                    order['customer_name'][:4], str(order['quantity'])]
            r2 = index_document(doc_id, f"{order['order_id']} {order['part_name']}",
                                content, doc_type="order",
                                tags=tags, metadata=order)
            if r2.get("status") == "ok":
                count += 1
                # 注册到引索树
                register_item(f"factory/{order['customer_name'][:4]}/{order['order_id']}",
                              f"{order['part_name']}(x{order['quantity']})",
                              "order", parent_path=f"factory/{order['customer_name'][:4]}",
                              doc_id=doc_id, metadata={"price": order['final_price']})

        return {"status": "ok", "orders_indexed": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def auto_index_step_files():
    """索引 data/step/ 目录中的STEP/STL文件。"""
    count = 0
    for ext in ["*.step", "*.stl"]:
        for f in STEP_DIR.glob(ext):
            size = f.stat().st_size
            doc_id = f"step_{f.stem}"
            name_parts = f.stem.split("_")
            part_type = name_parts[0] if name_parts else "unknown"
            content = f"STEP文件: {f.name} 类型:{part_type} 大小:{size}B"
            tags = [part_type, ext[1:]]
            r = index_document(doc_id, f.name, content, doc_type="step",
                               source_path=str(f), tags=tags)
            if r.get("status") == "ok":
                count += 1
                register_item(f"parts/{part_type}/{f.name}", f.name,
                              "step", parent_path=f"parts/{part_type}",
                              doc_id=doc_id, metadata={"size_bytes": size})
    return {"status": "ok", "steps_indexed": count}


def auto_index_audit():
    """索引审计日志 (关键决策)。"""
    try:
        conn = sqlite3.connect(str(DATA_DIR / "audit.db"))
        cursor = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        count = 0
        for r in rows:
            audit = dict(zip(cols, r))
            doc_id = f"audit_{audit['id']}"
            event = json.loads(audit['event_data']) if isinstance(audit['event_data'], str) else audit['event_data']
            content = f"决策记录: {audit['task_id']} 事件:{audit['event_type']} 数据:{json.dumps(event, ensure_ascii=False)[:300]}"
            r2 = index_document(doc_id, f"审计_{audit['id']}_{audit['event_type']}",
                                content, doc_type="audit",
                                tags=[audit['event_type'], '审计'],
                                metadata=event)
            if r2.get("status") == "ok":
                count += 1
        return {"status": "ok", "audit_indexed": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def auto_index_all():
    """全量自动索引。"""
    results = {
        "orders": auto_index_orders(),
        "step_files": auto_index_step_files(),
        "audit": auto_index_audit(),
    }
    return results


def get_stats() -> Dict:
    """RAG引擎状态。"""
    conn = _get_db()
    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    reg_count = conn.execute("SELECT COUNT(*) FROM registry").fetchone()[0]
    conn.close()
    return {
        "documents": doc_count,
        "registry_entries": reg_count,
        "embedding_model": EMBED_MODEL,
        "embedding_dim": EMBED_DIM,
        "storage": "SQLite (zero deps)",
        "ollama_required": True,
    }
