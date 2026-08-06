"""S3 知识管道（下手 = Knowledge Pipeline）—— 本地化 RAG，零重依赖。

设计纪律（见 ARCHITECTURE_GUARDRAILS.md R1/R2/R3）：
- 收敛而非新建：本文件升级自原 `kb.py` RAG 桩（已在 `_CAPABILITIES` 挂名 `kb`），
  不平行新建模块。
- 单一事实源：所有块持久化到 SQLite（默认 `~/.xai/knowledge.db`），内存 `self.chunks`
  仅为查询索引镜像，DB 是真相。
- 混合检索：BM25（稀疏，纯 Python 词袋，离线可用）+ 稠密向量（llama.cpp /v1/embeddings，
  不可用时优雅降级为 BM25-only）。
- 隐私：纯本地，不接 IMA / 腾讯云。

接口向后兼容：保留 `KnowledgeBase` / `Chunk` / `ingest` / `query` / `_vectorize`，
新增能力面方法 `search` / `stats` / `clear` 供大脑 / API 调用。
"""

from __future__ import annotations

import os
import re
import sqlite3
import json
import urllib.request as _ur
from dataclasses import dataclass, field
from typing import Optional


# 停用词（拉丁词）；CJK 单字停用字单独处理
_STOP = set("the a an of to and is are in on for with".split())
_STOP_CJK_CHAR = set("的了是在和与之及也都一个我们你们他们这那我你他它其或把被将已并等着过")

_DEFAULT_DB = os.path.join(os.path.expanduser("~"), ".xai", "knowledge.db")


def _tokenize(text: str) -> list[str]:
    """中英文混合分词：拉丁词按词，中文按字符单字+二元组。"""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    words = [w for w in words if w not in _STOP and len(w) > 1]
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    cjk_toks: list[str] = []
    for run in cjk_runs:
        for ch in run:
            if ch not in _STOP_CJK_CHAR:
                cjk_toks.append(ch)          # 单字
        for i in range(len(run) - 1):
            cjk_toks.append(run[i:i + 2])     # 二元组
    return words + cjk_toks


@dataclass
class Chunk:
    source: str
    text: str
    vec: dict[str, float] = field(default_factory=dict)   # BM25 词袋（兼容旧接口）
    emb: Optional[list[float]] = None                       # 稠密向量（可能 None）
    chunk_id: int = 0


class KnowledgeBase:
    def __init__(self, db_path: str = _DEFAULT_DB, use_dense: bool = True):
        self.db_path = db_path
        self._use_dense = use_dense
        self.chunks: list[Chunk] = []
        self._built = False
        self._init_db()
        self._load()

    # ---- 持久化（单一事实源） ----
    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS docs(
                id INTEGER PRIMARY KEY, source TEXT, ingested_at TEXT);
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY, doc_id INTEGER, source TEXT, text TEXT,
                tokens_json TEXT, emb_json TEXT,
                FOREIGN KEY(doc_id) REFERENCES docs(id));
            CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunks(doc_id);
        """)
        self._conn.commit()

    def _load(self):
        """DB → 内存索引镜像。"""
        self.chunks = []
        cur = self._conn.execute(
            "SELECT id, source, text, tokens_json, emb_json FROM chunks ORDER BY id")
        for cid, src, text, tj, ej in cur.fetchall():
            emb = json.loads(ej) if ej else None
            self.chunks.append(Chunk(
                source=src, text=text,
                vec={t: 1.0 for t in json.loads(tj)},
                emb=emb, chunk_id=cid))
        self._built = bool(self.chunks)

    # ---- 摄入 ----
    def ingest(self, paths: list[str]) -> int:
        """摄入文件或目录，返回新增块数。"""
        files: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, fs in os.walk(p):
                    for fn in fs:
                        if fn.lower().endswith((".md", ".txt", ".py", ".rs",
                                                ".json", ".csv", ".log")):
                            files.append(os.path.join(root, fn))
            elif os.path.isfile(p):
                files.append(p)
        before = len(self.chunks)
        for fp in files:
            try:
                text = self._read(fp)
            except Exception:
                continue
            for ch in self._chunk(text):
                ch.source = fp
                ch.vec = self._vectorize(ch.text)
                ch.emb = self._embed_text(ch.text) if self._use_dense else None
                self._persist_chunk(fp, ch)
                self.chunks.append(ch)
        self._built = bool(self.chunks)
        return len(self.chunks) - before

    def _persist_chunk(self, source: str, ch: Chunk):
        cur = self._conn.execute(
            "INSERT INTO docs(source, ingested_at) VALUES(?, datetime('now'))",
            (source,))
        doc_id = cur.lastrowid
        self._conn.execute(
            "INSERT INTO chunks(doc_id, source, text, tokens_json, emb_json) "
            "VALUES(?,?,?,?,?)",
            (doc_id, source, ch.text, json.dumps(list(ch.vec.keys()), ensure_ascii=False),
             json.dumps(ch.emb, ensure_ascii=False) if ch.emb else None))
        self._conn.commit()

    def _read(self, fp: str) -> str:
        if fp.lower().endswith(".pdf"):
            return f"[PDF 文件 {os.path.basename(fp)}，需要 pdf 解析器才能读正文]"
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def _chunk(self, text: str, size: int = 600, overlap: int = 80) -> list[Chunk]:
        if not text.strip():
            return []
        step = max(1, size - overlap)
        return [Chunk(source="", text=text[i:i + size])
                for i in range(0, len(text), step)]

    # ---- 向量化 ----
    def _vectorize(self, text: str) -> dict[str, float]:
        """BM25 词袋（稀疏，离线可用，兼容旧接口）。"""
        toks = _tokenize(text)
        vec: dict[str, float] = {}
        for t in toks:
            vec[t] = vec.get(t, 0.0) + 1.0
        return vec

    _DENSE_ENDPOINT = "http://127.0.0.1:11435/v1/embeddings"
    _DENSE_MODEL = "nomic-embed-text"

    @staticmethod
    def _embed_text(text: str) -> Optional[list[float]]:
        """用 Ollama /v1/embeddings 取稠密向量；不可用返回 None（优雅降级）。

        端点默认 11435（避免与 11434 llama.cpp 聊天服务冲突）。
        需运行 `OLLAMA_HOST=127.0.0.1:11435 ollama serve` + `ollama pull nomic-embed-text`。
        """
        try:
            body = json.dumps({
                "model": KnowledgeBase._DENSE_MODEL,
                "input": text[:800],
            }).encode("utf-8")
            req = _ur.Request(KnowledgeBase._DENSE_ENDPOINT, data=body,
                              headers={"Content-Type": "application/json"})
            with _ur.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data["data"][0]["embedding"]
        except Exception:
            return None

    @staticmethod
    def _cosine(a, b) -> float:
        """余弦相似度，支持 dict(BM25) 或 list(稠密)。"""
        if isinstance(a, dict) and isinstance(b, dict):
            keys = set(a) | set(b)
            dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
            na = sum(v * v for v in a.values()) ** 0.5
            nb = sum(v * v for v in b.values()) ** 0.5
        elif isinstance(a, list) and isinstance(b, list):
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            na = (sum(x * x for x in a)) ** 0.5
            nb = (sum(y * y for y in b)) ** 0.5
        else:
            return 0.0
        return dot / (na * nb) if na and nb else 0.0

    # ---- 检索 ----
    def _bm25_scores(self, q_tokens: list[str]) -> list[float]:
        """对所有块算 BM25（IDF 来自当前语料）。"""
        if not self.chunks:
            return []
        # 空查询：返回与 chunks 等长的零向量，保持与 fused 循环对齐
        # （否则 _bm25_scores 返回 [] 而 fused 用 nb[i] 索引 chunks → IndexError）
        if not q_tokens:
            return [0.0] * len(self.chunks)
        n = len(self.chunks)
        df = {}
        for ch in self.chunks:
            for t in set(ch.vec.keys()):
                df[t] = df.get(t, 0) + 1
        scores = []
        for ch in self.chunks:
            score = 0.0
            for t in q_tokens:
                if t in ch.vec:
                    idf = (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)
                    tf = ch.vec[t]
                    score += idf * (tf * (1.2 + 1)) / (tf + 1.2)
            scores.append(score)
        return scores

    def search(self, q: str, top_k: int = 5) -> list[dict]:
        """混合检索：BM25 + 稠密余弦，归一化加权融合。返回结构化结果。"""
        if not self._built or not self.chunks:
            return []
        q_tokens = _tokenize(q)
        bm25 = self._bm25_scores(q_tokens)
        q_emb = self._embed_text(q[:800])
        dense = [self._cosine(q_emb, ch.emb) if (q_emb and ch.emb) else 0.0
                 for ch in self.chunks]

        def _norm(xs):
            mx = max(xs) if xs else 0.0
            return [x / mx for x in xs] if mx > 0 else xs

        nb, nd = _norm(bm25), _norm(dense)
        use_dense = any(d > 0 for d in nd)
        fused = []
        for i, ch in enumerate(self.chunks):
            s = 0.4 * nb[i] + (0.6 * nd[i] if use_dense else 0.0)
            if not use_dense:
                s = nb[i]
            if s > 0:
                fused.append((ch, s))
        fused.sort(key=lambda x: x[1], reverse=True)
        return [{"source": c.source, "text": c.text[:400],
                 "score": round(s, 4)} for c, s in fused[:top_k]]

    def query(self, q: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        """向后兼容接口：返回 (Chunk, score) 列表。"""
        out = []
        for r in self.search(q, top_k):
            out.append((self._chunk_to_obj(r), r["score"]))
        return out

    def _chunk_to_obj(self, r: dict) -> Chunk:
        return Chunk(source=r["source"], text=r["text"])

    # ---- 管理 ----
    def stats(self) -> dict:
        cur = self._conn.execute("SELECT COUNT(*) FROM chunks")
        total = cur.fetchone()[0]
        return {"total_chunks": total, "sources": self._source_count(),
                "dense_available": any(c.emb for c in self.chunks),
                "built": self._built}

    def _source_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(DISTINCT source) FROM chunks")
        return cur.fetchone()[0]

    def clear(self) -> int:
        n = len(self.chunks)
        self._conn.executescript(
            "DELETE FROM chunks; DELETE FROM docs;")
        self._conn.commit()
        self.chunks = []
        self._built = False
        return n

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
