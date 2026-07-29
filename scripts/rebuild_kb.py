"""Clear vector store and re-ingest sample_docs (including faq_10k)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.rag.store import VectorStore


def main() -> None:
    settings = load_settings()
    persist = settings.resolve(settings.rag.persist_dir)
    if persist.exists():
        shutil.rmtree(persist)
        print(f"cleared: {persist}")
    persist.mkdir(parents=True, exist_ok=True)

    store = VectorStore(settings)
    docs = settings.resolve(settings.paths.sample_docs)
    n = store.add_directory(docs)
    print(f"ingested chunks: {n} from {docs}")
    print(f"collection count: {store.count()}")


if __name__ == "__main__":
    main()
