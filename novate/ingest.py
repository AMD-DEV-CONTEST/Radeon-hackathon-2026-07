"""
Build (or refresh) Nova's local vector database from documents in
config.DATA_DIR.

Usage:
    python ingest.py
    python ingest.py --data-dir path/to/other/docs
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import config
from src.vectorstore import VectorStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into Nova's local vector store.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=config.DATA_DIR,
        help="Directory of .txt/.md documents to index (default: data/sample_docs).",
    )
    args = parser.parse_args()

    if not args.data_dir.exists():
        raise SystemExit(f"Data directory not found: {args.data_dir}")

    store = VectorStore()
    total_chunks = 0
    total_docs = 0

    for path in sorted(args.data_dir.rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        n_chunks = store.add_document(
            doc_id=path.stem,
            text=text,
            source=str(path.relative_to(args.data_dir)),
        )
        total_docs += 1
        total_chunks += n_chunks

    logger.info(
        "Ingestion complete: %d documents, %d chunks, stored at %s",
        total_docs,
        total_chunks,
        config.VECTOR_DB_DIR,
    )


if __name__ == "__main__":
    main()
