#!/usr/bin/env python3
"""corpus_embeddings.py -- local, dependency-light semantic index over determinex_corpus_api's
entries (topic summaries, class_patterns, verified learned_classes, dated top-level entries --
the SAME entries token-overlap search() walks). Closes the 2026-07-18 audit finding: "No
embeddings, no BM25, no reranking, deliberately" -- token-overlap alone misses synonyms and
paraphrases (a query for "missing dependency" won't find an entry about "package not found").

Deliberately does NOT depend on Postgres/pgvector (scripts/determinex_rag_index.py's approach) --
that would make the corpus query surface's basic operation depend on an external service being up.
Instead: Ollama's local embeddings endpoint (nomic-embed-text, already pulled -- see
determinex_rag_index.EMBED_MODEL for the same convention) + a flat numpy cache file. If Ollama
isn't reachable, every function here degrades to returning None/empty -- callers (corpus_api's
hybrid_search) fall back to pure token-overlap, never a hard failure.

Usage:
    python scripts/corpus/corpus_embeddings.py build      # (re)build the cache, resumable
    python scripts/corpus/corpus_embeddings.py query "how does the compile gate retry?"
    python scripts/corpus/corpus_embeddings.py stats

KNOWN GAP (not yet done): the cache carries no embed-model-version stamp, so switching
EMBED_MODEL silently mixes old and new vectors instead of triggering a full rebuild. Low risk
today (one model, one machine) but worth a schema field (meta["_model_version"]) before this
is relied on across model upgrades -- deferred rather than rushed into the hash-keyed meta dict
structure that build_index/semantic_search iterate directly.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import determinex_corpus_api as api  # noqa: E402

EMBED_MODEL = "nomic-embed-text:latest"  # matches determinex_rag_index.EMBED_MODEL
OLLAMA_URL = "http://localhost:11434"
CACHE_VEC = ROOT / "corpus" / "programbench" / "embeddings_cache.npy"
CACHE_META = ROOT / "corpus" / "programbench" / "embeddings_cache.meta.json"

# Reserved key in the meta dict, alongside real entries -- stamps which
# EMBED_MODEL the cached vectors were built with. Was the module's own
# documented KNOWN GAP: switching EMBED_MODEL used to silently mix
# old-model and new-model vectors in the same cosine-similarity space
# instead of forcing a rebuild. Fixed 2026-07-20.
_MODEL_VERSION_KEY = "_model_version"


def embed_text(text: str, timeout: int = 30) -> list[float] | None:
    """Reuses the exact call shape of determinex_rag_index.embed() -- same endpoint, same model
    -- so a cache built here and one built there are directly comparable if ever merged."""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=json.dumps({"model": EMBED_MODEL, "prompt": text[:4000]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["embedding"]
    except Exception:
        return None


def _entries(corpus: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Same universe of entries as determinex_corpus_api.search(): topic-index summaries,
    class_patterns, verified learned_classes, and every dated top-level entry's stringified
    content (truncated). One flat list of {key, text, topic}, keys GLOBALLY UNIQUE across
    categories -- a dated top-level key that's ALSO indexed in _topic_index (the common case;
    the topic index is a pointer TO the top-level entries) is merged into ONE row using the
    fuller top-level blob + the real topic name, not embedded twice under the same cache key.
    (Two same-keyed-but-different-text rows previously silently collided in the embeddings
    cache's overwrite path, permanently capping cached vectors below the true entry count --
    found + fixed 2026-07-19.) class_pattern/learned_class keys are namespaced defensively in
    case a key string ever collides with an unrelated top-level entry."""
    kn = corpus if corpus is not None else api.load_corpus()
    by_key: dict[str, dict[str, str]] = {}

    skip = {
        "_topic_index",
        "_topic_index_doc",
        "class_patterns",
        "learned_classes",
        "absorbed_sources",
    }
    for k, v in kn.items():
        if k in skip or k.startswith("_"):
            continue
        blob = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        by_key[k] = {"key": k, "topic": "entry", "text": f"{k} {blob[:2000]}"}

    ti = kn.get("_topic_index", {})
    if isinstance(ti, dict):
        for topic, items in ti.items():
            for it in items if isinstance(items, list) else []:
                if not (isinstance(it, dict) and it.get("key")):
                    continue
                key = str(it["key"])
                if key in by_key:
                    by_key[key]["topic"] = str(topic)  # richer topic label than generic "entry"
                else:
                    by_key[key] = {
                        "key": key,
                        "topic": str(topic),
                        "text": f"{key} {it.get('summary', '')}",
                    }

    out: list[dict[str, str]] = list(by_key.values())
    for k, v in api.class_patterns(kn).items():
        blob = json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v)
        out.append(
            {"key": f"class_pattern::{k}", "topic": "class_pattern", "text": f"{k} {blob[:1500]}"}
        )
    for k, v in api.learned_classes(verified_only=True, corpus=kn).items():
        det = v.get("detect") or v.get("symptom") or "" if isinstance(v, dict) else str(v)
        fix = v.get("fix", "") if isinstance(v, dict) else ""
        out.append(
            {
                "key": f"learned_class::{k}",
                "topic": "learned_class",
                "text": f"{k} {det} {fix}"[:1500],
            }
        )
    return out


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def build_index(max_new: int = 10_000, corpus: dict[str, Any] | None = None) -> dict:
    """Resumable, incremental: only embeds entries whose (key, content-hash) isn't already
    cached, so re-running after a corpus edit only pays for what changed -- same discipline as
    determinex_pb_absorb's absorbed_sources resume tracking."""
    import numpy as np

    meta: dict[str, Any] = {}
    vecs: list[list[float]] = []
    rebuilt_for_model_change = False
    if CACHE_META.exists() and CACHE_VEC.exists():
        try:
            meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
            arr = np.load(CACHE_VEC)
            vecs = [list(row) for row in arr]
        except Exception:
            meta, vecs = {}, []
        if meta.get(_MODEL_VERSION_KEY) != EMBED_MODEL:
            # Mismatched (or absent, i.e. pre-stamp) model version -- these
            # vectors live in a different embedding space, cosine similarity
            # against a blended cache would be meaningless. Force a full
            # rebuild rather than silently mixing them.
            meta, vecs = {}, []
            rebuilt_for_model_change = True

    meta[_MODEL_VERSION_KEY] = EMBED_MODEL

    entries = _entries(corpus)
    added = skipped_cached = failed = 0
    for e in entries:
        if added >= max_new:
            break
        h = _text_hash(e["text"])
        cache_key = e["key"]
        if meta.get(cache_key, {}).get("hash") == h:
            skipped_cached += 1
            continue
        emb = embed_text(e["text"])
        if emb is None:
            failed += 1
            continue
        if cache_key in meta:
            idx = meta[cache_key]["idx"]
            vecs[idx] = emb
            meta[cache_key]["hash"] = h  # MUST update, or a changed entry re-embeds every
            meta[cache_key]["topic"] = e["topic"]  # future run without ever converging (the
            meta[cache_key]["snippet"] = e["text"][:160]  # 2026-07-19 non-convergent-loop bug)
        else:
            meta[cache_key] = {
                "idx": len(vecs),
                "hash": h,
                "topic": e["topic"],
                "snippet": e["text"][:160],
            }
            vecs.append(emb)
        added += 1
        if added % 25 == 0:
            _flush(meta, vecs)
    _flush(meta, vecs)
    return {
        "added_or_updated": added,
        "skipped_cached": skipped_cached,
        "failed": failed,
        "total_cached": len(vecs),
        "ollama_reachable": failed < len(entries) or added > 0,
        "rebuilt_for_model_change": rebuilt_for_model_change,
    }


def _flush(meta: dict, vecs: list) -> None:
    import numpy as np

    if not vecs:
        return
    CACHE_VEC.parent.mkdir(parents=True, exist_ok=True)
    np.save(CACHE_VEC, np.array(vecs, dtype=np.float32))
    CACHE_META.write_text(json.dumps(meta, indent=1), encoding="utf-8")


def semantic_search(query: str, k: int = 10) -> list[dict[str, Any]]:
    """Cosine-similarity search over the cache. Returns [] (never raises) if the cache doesn't
    exist yet or Ollama is unreachable -- callers must treat this as a best-effort enhancement,
    not a dependency."""
    import numpy as np

    if not (CACHE_VEC.exists() and CACHE_META.exists()):
        return []
    qemb = embed_text(query)
    if qemb is None:
        return []
    try:
        meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
        vecs = np.load(CACHE_VEC)
    except Exception:
        return []
    q = np.array(qemb, dtype=np.float32)
    qn = q / (np.linalg.norm(q) + 1e-9)
    vn = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    sims = vn @ qn
    idx_to_key = {
        v["idx"]: k for k, v in meta.items() if k != _MODEL_VERSION_KEY and v["idx"] < len(sims)
    }
    ranked = sorted(((float(sims[i]), i) for i in range(len(sims))), reverse=True)[:k]
    return [
        {
            "key": idx_to_key.get(i, "?"),
            "score": round(s, 4),
            "topic": meta.get(idx_to_key.get(i, ""), {}).get("topic", ""),
            "snippet": meta.get(idx_to_key.get(i, ""), {}).get("snippet", ""),
        }
        for s, i in ranked
        if i in idx_to_key
    ]


def stats() -> dict:
    if not (CACHE_VEC.exists() and CACHE_META.exists()):
        return {"exists": False}
    try:
        import numpy as np

        meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
        vecs = np.load(CACHE_VEC)
        cached_entries = sum(1 for k in meta if k != _MODEL_VERSION_KEY)
        return {
            "exists": True,
            "cached_entries": cached_entries,
            "vector_dim": vecs.shape[1] if len(vecs) else 0,
            "cache_bytes": CACHE_VEC.stat().st_size + CACHE_META.stat().st_size,
            "embed_model": meta.get(_MODEL_VERSION_KEY),
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: corpus_embeddings.py <build|query QUERY|stats>")
        return 1
    cmd = sys.argv[1]
    if cmd == "build":
        t0 = time.time()
        res = build_index()
        res["elapsed_s"] = round(time.time() - t0, 1)
        print(json.dumps(res, indent=1))
    elif cmd == "query" and len(sys.argv) > 2:
        print(json.dumps(semantic_search(" ".join(sys.argv[2:])), indent=1))
    elif cmd == "stats":
        print(json.dumps(stats(), indent=1))
    else:
        print("usage: corpus_embeddings.py <build|query QUERY|stats>")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
