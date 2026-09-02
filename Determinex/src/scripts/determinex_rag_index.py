#!/usr/bin/env python3
"""determinex_rag_index.py — index Determinex corpora into pgvector for semantic RAG.

Replaces the file-based markdown ingestion in scripts/seed_knowledge_base.py.
Uses ollama for embeddings (default model: nomic-embed-text:latest).

Schema lives in docker/monitoring/postgres-init.sql (rag_chunks table).

Usage:
    determinex_rag_index.py index --corpus programbench --root corpus/programbench/
    determinex_rag_index.py query "How does the Compile Oracle work?" --corpus determinex-docs
    determinex_rag_index.py stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

EMBED_MODEL = os.environ.get("DETERMINEX_EMBED_MODEL", "nomic-embed-text:latest")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
PG_DSN = os.environ.get("PG_DSN", "postgresql://determinex:determinex@localhost:5432/determinex")
CHUNK_SIZE = 600  # tokens approx; we count characters/4


def embed(text: str) -> list[float] | None:
    """Get embedding from ollama."""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["embedding"]
    except Exception as e:
        sys.stderr.write(f"embed failed: {e}\n")
        return None


def _pg():
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        print("Install: pip install 'psycopg[binary]'")
        sys.exit(1)
    return psycopg.connect(PG_DSN, autocommit=True)


def chunk_text(text: str, target_chars: int = CHUNK_SIZE * 4) -> list[str]:
    """Split text into ~600-token chunks at paragraph boundaries."""
    paras = text.split("\n\n")
    chunks, cur, cur_len = [], [], 0
    for p in paras:
        if cur_len + len(p) > target_chars and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [p], len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def cmd_index(args):
    c = _pg()
    cur = c.cursor()
    root = Path(args.root)
    if not root.is_dir():
        print(f"no such dir: {root}")
        sys.exit(1)

    n_files = 0
    n_chunks = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".md", ".txt", ".py", ".sh", ".rs", ".go", ".rst"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        for i, chunk in enumerate(chunk_text(text)):
            emb = embed(chunk)
            if emb is None:
                continue
            cur.execute(
                """
                INSERT INTO rag_chunks(corpus, source_path, chunk_idx, text, embedding, meta)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    args.corpus,
                    rel,
                    i,
                    chunk,
                    emb,
                    json.dumps({"ext": path.suffix, "size": len(text)}),
                ),
            )
            n_chunks += 1
        n_files += 1
        if n_files % 10 == 0:
            print(f"  indexed {n_files} files / {n_chunks} chunks")
    c.close()
    print(f"OK: {n_files} files, {n_chunks} chunks into corpus='{args.corpus}'")


def cmd_query(args):
    qemb = embed(args.query)
    if qemb is None:
        print("query embed failed")
        sys.exit(1)
    c = _pg()
    cur = c.cursor()
    cur.execute(
        """
        SELECT corpus, source_path, chunk_idx, text,
               1 - (embedding <=> %s::vector) AS similarity
        FROM rag_chunks
        WHERE corpus = %s OR %s = 'all'
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """,
        (qemb, args.corpus, args.corpus, qemb, args.k),
    )
    for corpus, path, idx, text, sim in cur.fetchall():
        print(f"--- {corpus}:{path}#{idx}  sim={sim:.3f} ---")
        print(text[:500])
        print()
    c.close()


def cmd_stats(args):
    c = _pg()
    cur = c.cursor()
    cur.execute("""
        SELECT corpus, COUNT(*), MIN(created_at), MAX(created_at)
        FROM rag_chunks
        GROUP BY corpus
        ORDER BY corpus
    """)
    for corpus, n, first, last in cur.fetchall():
        print(f"  {corpus}: {n} chunks  first={first}  last={last}")
    c.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("index")
    sp.add_argument("--corpus", required=True)
    sp.add_argument("--root", required=True)

    sp = sub.add_parser("query")
    sp.add_argument("query")
    sp.add_argument("--corpus", default="all")
    sp.add_argument("--k", type=int, default=5)

    sub.add_parser("stats")
    args = ap.parse_args()
    {"index": cmd_index, "query": cmd_query, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    main()
