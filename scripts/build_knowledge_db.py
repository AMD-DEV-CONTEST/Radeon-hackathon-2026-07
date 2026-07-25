#!/usr/bin/env python3
"""Validate the four-field cards and rebuild the local Milvus Lite database."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from xianglens.config import PROJECT_ROOT, Settings
from xianglens.storage.knowledge_store import (
    MilvusKnowledgeStore,
    create_embedder,
    load_knowledge_records,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=Path, default=PROJECT_ROOT / "data/knowledge/cards.yaml")
    parser.add_argument(
        "--sources", type=Path, default=PROJECT_ROOT / "data/knowledge/sources.yaml"
    )
    parser.add_argument("--uri", type=Path, default=None)
    parser.add_argument("--provider", choices=("hash", "fastembed"), default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    uri = args.uri or settings.milvus_uri
    provider = args.provider or settings.embedding_provider
    records = load_knowledge_records(args.cards, args.sources)
    embedder = create_embedder(provider, settings.embedding_model, settings.embedding_dimension)
    count = MilvusKnowledgeStore(uri, embedder).rebuild(records)
    print(f"Built {count} cards in {uri}")
    print(f"Embedding provider: {provider} ({embedder.dimension} dimensions)")
    print(f"Pack counts: {dict(Counter(record.pack for record in records))}")


if __name__ == "__main__":
    main()
