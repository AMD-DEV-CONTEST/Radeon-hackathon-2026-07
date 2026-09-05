"""Day3: local RAG pipeline test — ingest demo workspace, search, cite.

Run on remote from /persistent/screwshell/app:
  source /opt/venv/bin/activate && HF_HOME=/persistent/hf-home python scripts/day3_rag_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screwshell.rag.pipeline import LocalEmbedder, RagIndex

WS = os.environ.get("SCREWSHELL_WS",
                    "/persistent/screwshell/app/demo_workspace")

emb = LocalEmbedder()
idx = RagIndex(WS, embedder=emb)
stats = idx.ingest()
print("INGEST:", stats, flush=True)

failures = 0
for query, expect_src in [
    ("main risks of the ROCm migration", "docs/migration_plan.md"),
    ("adapter hot swap latency measurements", "docs/rocm_notes.md"),
    ("why is the benchmark harness slow", "repo/bench_harness.py"),
]:
    hits = idx.search(query, top_k=3)
    top = [h["source"].replace("\\", "/") for h in hits]
    ok = any(expect_src in s for s in top)
    failures += 0 if ok else 1
    print(json.dumps({
        "query": query, "expect": expect_src, "ok": ok,
        "top": [f"{h['source']}#L{h['start_line']}-L{h['end_line']}"
                f" ({h['score']:.3f})" for h in hits],
    }, ensure_ascii=False), flush=True)

print("RESULT:", "ALL PASS" if failures == 0 else f"{failures} FAIL")
sys.exit(1 if failures else 0)
