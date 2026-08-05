"""Build the versioned SQLite corpus and persistent local Qdrant index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.index import LegalVectorIndex
from app.rag.service import build_embedding


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/laws/source_manifest.json")
    )
    parser.add_argument(
        "--corpus-db", type=Path, default=Path("data/laws/legal_corpus.sqlite3")
    )
    parser.add_argument(
        "--qdrant-path", type=Path, default=Path("data/qdrant/legal")
    )
    parser.add_argument(
        "--verification-report",
        type=Path,
        default=Path("data/laws/source_verification.json"),
    )
    parser.add_argument(
        "--quote-audit-report",
        type=Path,
        default=Path("data/laws/quote_audit.json"),
    )
    parser.add_argument("--minimum-verified", type=int, default=10)
    parser.add_argument(
        "--embedding-provider", choices=("bge", "hash"), default=None
    )
    args = parser.parse_args()
    verification = json.loads(
        args.verification_report.read_text(encoding="utf-8")
    )
    verified_ids = {
        item["document_id"]
        for item in verification.get("results", [])
        if item.get("verified")
    }
    if len(verified_ids) < args.minimum_verified:
        raise RuntimeError(
            "Official-source verification gate failed: "
            f"{len(verified_ids)} < {args.minimum_verified}. "
            "Run scripts/fetch_laws.py before ingestion."
        )
    documents, chunks = load_manifest(args.manifest)
    if not args.quote_audit_report.exists():
        raise RuntimeError(
            "Legal quote audit is missing. Run scripts/audit_legal_quotes.py "
            "before ingestion."
        )
    quote_audit = json.loads(
        args.quote_audit_report.read_text(encoding="utf-8")
    )
    if (
        quote_audit.get("failed") != 0
        or quote_audit.get("passed") != len(chunks)
        or quote_audit.get("quotes") != len(chunks)
    ):
        raise RuntimeError(
            "Legal quote audit gate failed: "
            f"{quote_audit.get('passed')}/{quote_audit.get('quotes')} "
            f"passed for {len(chunks)} chunks."
        )
    manifest_ids = {item.document_id for item in documents}
    if not verified_ids <= manifest_ids:
        raise RuntimeError("Verification report contains unknown document IDs.")
    corpus = LegalCorpusStore(args.corpus_db)
    counts = corpus.replace(documents, chunks)
    embedding = build_embedding(args.embedding_provider)
    vector_index = LegalVectorIndex(args.qdrant_path, embedding)
    try:
        indexed = vector_index.rebuild(chunks)
        qdrant_count = vector_index.count()
    finally:
        vector_index.close()
    result = {
        **counts,
        "indexed": indexed,
        "qdrant_count": qdrant_count,
        "embedding_provider": embedding.name,
        "embedding_dimension": embedding.dimension,
        "corpus_db": str(args.corpus_db),
        "qdrant_path": str(args.qdrant_path),
        "verified_sources": len(verified_ids),
        "verified_quotes": quote_audit["passed"],
    }
    if result["documents"] < 10 or indexed != len(chunks):
        raise RuntimeError(f"Legal ingestion acceptance failed: {result}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
