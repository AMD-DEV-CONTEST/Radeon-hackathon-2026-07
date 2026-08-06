"""
RAG Service — Lightweight case memory with pgvector semantic search.
Port 8010, called by iron_law/context.py.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag_service")

DATABASE_URL = os.environ.get("DATABASE_URL")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("SILICONFLOW_API_KEY", "")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))


# ── Embedding ──────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
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
    return data["data"][0]["embedding"]


# ── DB ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# ── Models ─────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    case_id: str
    title: str
    description: str = ""
    category: str = "general"
    tags: list[str] = []
    content: dict[str, Any] = {}
    metadata: dict[str, Any] = {}

class CaseSearch(BaseModel):
    query: str
    top_k: int = 3
    min_similarity: float = 0.4


# ── App ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RAG Service starting on port 8010")
    yield
    logger.info("RAG Service shutting down")

app = FastAPI(title="UAS RAG Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/cases", status_code=201)
async def create_case(case: CaseCreate):
    try:
        embedding = embed_text(f"{case.title} {case.description}")
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(500, f"Embedding failed: {e}")

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO cases (case_id, title, description, category, tags, content, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id) DO NOTHING
                """,
                (
                    case.case_id, case.title, case.description, case.category,
                    case.tags, json.dumps(case.content), json.dumps(case.metadata),
                    embedding,
                ),
            )
            # Check if actually inserted
            cur = conn.execute("SELECT 1 FROM cases WHERE case_id = %s", (case.case_id,))
            if cur.rowcount == 0:
                raise HTTPException(409, f"Case {case.case_id} already exists")
        return {"status": "created", "case_id": case.case_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DB write failed: %s", e)
        raise HTTPException(500, f"DB write failed: {e}")


@app.post("/cases/search")
async def search_cases(req: CaseSearch):
    try:
        query_embedding = embed_text(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(500, f"Embedding failed: {e}")

    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT case_id, title, description, category, tags, content, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM cases
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, query_embedding, req.min_similarity, query_embedding, req.top_k),
            ).fetchall()

        results = []
        for r in rows:
            results.append({
                "case": {
                    "case_id": r["case_id"],
                    "title": r["title"],
                    "description": r["description"],
                    "category": r["category"],
                    "tags": r["tags"],
                    "content": r["content"] if isinstance(r["content"], dict) else json.loads(r["content"]),
                },
                "similarity": float(r["similarity"]),
            })
        return {"results": results}
    except Exception as e:
        logger.error("Search failed: %s", e)
        raise HTTPException(500, f"Search failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8010)
