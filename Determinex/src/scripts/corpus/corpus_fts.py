#!/usr/bin/env python3
"""corpus_fts.py -- BM25 ranking over the corpus via SQLite FTS5.

Third leg of the retrieval triangle, alongside the two that already exist:
  * corpus_embeddings.py  -- semantic / paraphrase (cosine over Ollama nomic vectors)
  * corpus_tree_index.py  -- structural (markdown heading-tree navigation)
  * this module           -- lexical, but properly ranked

determinex_corpus_api.search() ranks by `len(query_tokens & entry_tokens)` -- a count of
distinct matching terms. That has no term frequency, no inverse document frequency and no
length normalisation, so a term appearing once in a 40-word summary scores exactly like a
term appearing nine times in the entry that is actually about it, and a common word like
"build" contributes as much as a rare one like "provenance".

It also tokenises with `[a-z0-9_]+`, which KEEPS underscores. Corpus keys are snake_case,
so `_provenance_restore_2026_06_22` is a SINGLE token that the query "provenance restore"
can never intersect -- the key contributes exactly zero to its own entry's score. Measured
on the live corpus: that query scored the entry 1, in a five-way tie that included two
unrelated smolvlm2 PR entries, so the exactly-named answer ranked second on tie-break.
BM25 over FTS5's unicode61 tokeniser (which splits on underscore) ranks it 1.000, next
result 0.537.

Same effect on the playbook: "collection cap not_run" ranked `class_pattern::collection_cap`
FIFTH under token overlap, behind three entries tied at the same score. BM25 puts it second
at 0.974, under `not_run_taxonomy_2026_06_23`.

Zero new dependency: FTS5 ships inside the stdlib `sqlite3`. Availability is still probed at
runtime (`fts5_available()`) rather than assumed, because it is a compile-time option and a
different Python build may lack it. Every entry point degrades to [] rather than raising, so
callers keep the same best-effort contract corpus_embeddings.semantic_search() already has.

Document universe is corpus_embeddings._entries() -- deliberately reused, not re-derived, so
the key space is identical to the embeddings cache and the two can blend in hybrid_search().
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Package-qualified so this resolves under pyrightconfig.json's extraPaths=["scripts"];
# a bare `import corpus_embeddings` only works via runtime sys.path and reads as unresolved.
from corpus import corpus_embeddings as ce  # noqa: E402

INDEX_PATH = ROOT / "corpus" / "programbench" / "fts_index.sqlite3"

# FTS5 query syntax treats -, ", *, :, ^, ( and ) as operators. User text is never
# interpolated raw; only these token characters survive into a MATCH expression.
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_MIN_TOKEN_LEN = 2


def fts5_available() -> bool:
    """FTS5 is a compile-time SQLite option. Probe it rather than assume it."""
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _corpus_fingerprint(entries: list[dict[str, str]]) -> str:
    """Content hash of the indexed universe, so a stale index rebuilds itself.

    corpus_embeddings uses a per-entry hash for RESUMABLE embedding (each vector costs an
    Ollama round trip). An FTS rebuild is pure local CPU over ~430KB, so a whole-corpus
    fingerprint plus full rebuild is simpler and has no incremental-staleness failure mode.
    """
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x["key"]):
        h.update(e["key"].encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(e["text"].encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _safe_match_query(query: str) -> str:
    """Build an injection-safe FTS5 MATCH expression: quoted tokens OR'd together.

    OR rather than AND because the callers treat retrieval as ranked recall -- an entry
    matching two of three query terms should still surface, ranked below one matching all
    three. BM25 already handles that ordering; AND would just drop it.
    """
    toks = [t.lower() for t in _QUERY_TOKEN_RE.findall(query)]
    toks = [t for t in toks if len(t) >= _MIN_TOKEN_LEN]
    if not toks:
        return ""
    seen: list[str] = []
    for t in toks:
        if t not in seen:
            seen.append(t)
    return " OR ".join(f'"{t}"' for t in seen)


def build_index(corpus: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    """(Re)build the FTS5 index. Full rebuild -- fast enough that incremental buys nothing."""
    if not fts5_available():
        return {"ok": False, "reason": "fts5_unavailable", "indexed": 0}

    entries = ce._entries(corpus)
    fingerprint = _corpus_fingerprint(entries)

    if not force and INDEX_PATH.exists():
        try:
            con = sqlite3.connect(INDEX_PATH)
            try:
                row = con.execute("SELECT value FROM meta WHERE name = 'fingerprint'").fetchone()
                if row and row[0] == fingerprint:
                    n = con.execute("SELECT count(*) FROM docs").fetchone()[0]
                    return {"ok": True, "indexed": n, "rebuilt": False, "fingerprint": fingerprint}
            finally:
                con.close()
        except sqlite3.Error:
            pass  # unreadable/older index -- fall through and rebuild

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".sqlite3.tmp")
    tmp.unlink(missing_ok=True)

    con = sqlite3.connect(tmp)
    try:
        # `key` IS indexed (not UNINDEXED): the snake_case key carries real signal, and
        # making its words matchable is the specific gap this module closes.
        con.execute("CREATE VIRTUAL TABLE docs USING fts5(key, topic UNINDEXED, text)")
        con.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT)")
        con.executemany(
            "INSERT INTO docs (key, topic, text) VALUES (?, ?, ?)",
            [(e["key"], e.get("topic", ""), e["text"]) for e in entries],
        )
        con.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.execute("INSERT INTO meta VALUES ('count', ?)", (str(len(entries)),))
        con.commit()
    finally:
        con.close()

    INDEX_PATH.unlink(missing_ok=True)
    tmp.replace(INDEX_PATH)
    return {"ok": True, "indexed": len(entries), "rebuilt": True, "fingerprint": fingerprint}


def bm25_search(query: str, k: int = 10, auto_build: bool = True) -> list[dict[str, Any]]:
    """BM25-ranked hits as [{key, score, snippet, topic}] -- same shape as
    corpus_embeddings.semantic_search(), so hybrid_search can blend them identically.

    `score` is normalised to (0, 1] with 1.0 = best hit in THIS result set. Raw FTS5 bm25()
    is an unbounded negative number (more negative = better) and is not comparable across
    queries, so it is unusable as a blend weight without normalisation.

    Returns [] on any failure -- no FTS5, no index, malformed query. Never raises.
    """
    if not fts5_available():
        return []
    match = _safe_match_query(query)
    if not match:
        return []

    if auto_build and not INDEX_PATH.exists():
        build_index()
    if not INDEX_PATH.exists():
        return []

    try:
        con = sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT key, topic, substr(text, 1, 220), bm25(docs) AS rank "
            "FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?",
            (match, k),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    if not rows:
        return []
    # bm25() is negative, best = most negative. Flip, then scale by the best magnitude.
    best = max(abs(r[3]) for r in rows) or 1.0
    return [{"key": r[0], "topic": r[1], "snippet": r[2], "score": abs(r[3]) / best} for r in rows]


def stats() -> dict[str, Any]:
    if not fts5_available():
        return {"available": False, "reason": "fts5_unavailable"}
    if not INDEX_PATH.exists():
        return {"available": True, "built": False, "path": str(INDEX_PATH)}
    try:
        con = sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True)
        try:
            n = con.execute("SELECT count(*) FROM docs").fetchone()[0]
            fp = con.execute("SELECT value FROM meta WHERE name='fingerprint'").fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"available": True, "built": False, "error": str(exc)}

    current = _corpus_fingerprint(ce._entries())
    return {
        "available": True,
        "built": True,
        "indexed": n,
        "fingerprint": fp[0] if fp else None,
        "stale": bool(fp) and fp[0] != current,
        "size_bytes": INDEX_PATH.stat().st_size,
        "path": str(INDEX_PATH),
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="BM25 (SQLite FTS5) search over the corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build or refresh the FTS index")
    b.add_argument("--force", action="store_true", help="rebuild even if the fingerprint matches")
    s = sub.add_parser("search", help="BM25 search")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=10)
    sub.add_parser("stats", help="index status")
    args = ap.parse_args()

    if args.cmd == "build":
        print(json.dumps(build_index(force=args.force), indent=2))
    elif args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    else:
        hits = bm25_search(args.query, k=args.k)
        if not hits:
            print("(no hits)")
            return 0
        for h in hits:
            print(f"  {h['score']:.3f}  {h['topic']:<20s} {h['key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
