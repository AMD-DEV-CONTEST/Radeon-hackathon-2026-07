#!/usr/bin/env python3
"""Ingest sample docs into the local Chroma knowledge base."""

from __future__ import annotations

from src.config import load_settings
from src.rag.store import VectorStore


def main() -> None:
    settings = load_settings()
    store = VectorStore(settings)
    sample_dir = settings.resolve(settings.paths.sample_docs)
    n = store.add_directory(sample_dir)
    print(f"Ingested chunks: {n}")
    print(f"Total chunks: {store.count()}")


if __name__ == "__main__":
    main()
