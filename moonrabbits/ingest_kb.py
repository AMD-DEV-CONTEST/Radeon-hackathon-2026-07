#!/usr/bin/env python3
"""MoonRabbits KB ingestion v3: jsonl -> bge-m3 embeddings -> ChromaDB.

Bulletproof: batch auto-splits to singles on failure, poison entries skipped,
resume support (already-ingested ids are skipped on re-run).

Usage:
  python ingest_kb.py --input kb/ceramic_all.jsonl          # ingest (resumable)
  python ingest_kb.py --test "德化白瓷的猪油白是什么"        # recall test
"""
import argparse, json, sys, time, urllib.request
from pathlib import Path

BASE = Path("/workspace/persistent/moonrabbits")
CHROMA_DIR = BASE / "chroma"
OLLAMA = "http://localhost:11434"
EMBED_MODEL = "bge-m3"
BATCH = 16  # smaller batches are gentler on the server

KEEP_TAG_DIMS = ["carrier", "color", "era", "glaze", "kiln", "form", "pattern", "topic"]


def _post(endpoint, payload, timeout=300):
    req = urllib.request.Request(
        OLLAMA + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed_single(text, retries=3):
    for attempt in range(retries):
        try:
            return _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text}, timeout=120)["embedding"]
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def embed_batch(texts):
    """Try batch endpoint; on any failure fall back to singles with retry."""
    try:
        return _post("/api/embed", {"model": EMBED_MODEL, "input": texts})
    except Exception:
        pass
    out, poisoned = [], []
    for i, t in enumerate(texts):
        try:
            out.append(embed_single(t))
        except Exception:
            poisoned.append(i)
            out.append(None)
    return out, poisoned


def get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name="cultural_kb", metadata={"hnsw:space": "cosine"}
    )


def existing_ids(coll):
    """All ids already in the collection (for resume)."""
    if coll.count() == 0:
        return set()
    return set(coll.get(include=[])["ids"])


def normalize(e: dict):
    eid = e.get("id")
    content = e.get("content") or e.get("text") or ""
    if not eid or not content.strip():
        return None
    if "parse_error" in content and len(content) < 200:
        return None
    if e.get("source_type") == "测试":
        return None
    source = e.get("source") or e.get("source_file") or ""
    meta = {"kb_id": eid, "source": str(source)[:200]}
    if e.get("source_type"):
        meta["source_type"] = str(e["source_type"])
    conf = e.get("tag_confidence")
    try:
        meta["tag_confidence"] = float(conf)
    except (TypeError, ValueError):
        pass
    for k, v in (e.get("tags") or {}).items():
        if k in KEEP_TAG_DIMS and str(v).strip():
            meta[k] = str(v)[:200]
    if len(content) > 4000:
        content = content[:4000]
    return eid, content, meta


def ingest(path: Path, max_entries: int = 0):
    entries, skipped = [], 0
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                skipped += 1
                continue
            n = normalize(e)
            if n is None:
                skipped += 1
                continue
            entries.append(n)
            if max_entries and len(entries) >= max_entries:
                break
    if not entries:
        print("no valid entries in", path)
        sys.exit(1)
    print(f"loaded {len(entries)} entries (skipped {skipped} junk)", flush=True)

    coll = get_collection()
    done_ids = existing_ids(coll)
    if done_ids:
        before = len(entries)
        entries = [e for e in entries if e[0] not in done_ids]
        print(f"resume: {before - len(entries)} already ingested, {len(entries)} to go", flush=True)
    if not entries:
        print(f"nothing to do. collection count = {coll.count()}")
        return

    t0 = time.time()
    total = len(entries)
    poison_total = 0
    for start in range(0, total, BATCH):
        batch = entries[start:start + BATCH]
        ids = [b[0] for b in batch]
        docs = [b[1] for b in batch]
        metas = [b[2] for b in batch]
        result = embed_batch(docs)
        if isinstance(result, tuple):
            embs, poisoned = result
        else:  # batch endpoint succeeded — dict with 'embeddings'
            embs, poisoned = result["embeddings"], []
        if poisoned:
            poison_total += len(poisoned)
            keep = [(i, d, m, e2) for i, (d, m, e2) in enumerate(zip(docs, metas, embs)) if e2 is not None]
            if not keep:
                continue
            ids = [batch[i][0] for i, _, _, _ in keep]
            docs = [d for _, d, _, _ in keep]
            metas = [m for _, _, m, _ in keep]
            embs = [e2 for _, _, _, e2 in keep]
        coll.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
        done = min(start + BATCH, total)
        if done % (BATCH * 20) == 0 or done == total:
            rate = done / max(time.time() - t0, 0.1)
            eta = (total - done) / max(rate, 0.01) / 60
            print(f"  {done}/{total}  ({rate:.1f}/s, ETA {eta:.0f} min, poison {poison_total})", flush=True)

    print(f"ingested: {total - poison_total} entries (poison {poison_total}), collection count = {coll.count()}")


def test_query(query: str, n: int = 3):
    coll = get_collection()
    if coll.count() == 0:
        print("collection is empty - run ingestion first")
        sys.exit(1)
    res = coll.query(query_embeddings=[embed_single(query)], n_results=min(n, coll.count()))
    print(f"\nquery: {query}\n" + "=" * 60)
    for rank, (doc, meta, dist) in enumerate(
        zip(res["documents"][0], res["metadatas"][0], res["distances"][0]), 1
    ):
        print(f"[{rank}] similarity={1 - dist:.3f}  conf={meta.get('tag_confidence', '?')}  src={meta.get('source', '?')[:50]}")
        print(f"    {doc[:180]}")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="path to jsonl")
    ap.add_argument("--test", help="run a test query instead of ingestion")
    ap.add_argument("--max", type=int, default=0, help="ingest at most N entries (dry run)")
    ap.add_argument("-n", type=int, default=3)
    args = ap.parse_args()
    if args.test:
        test_query(args.test, args.n)
    elif args.input:
        ingest(Path(args.input), args.max)
    else:
        ap.print_help()
