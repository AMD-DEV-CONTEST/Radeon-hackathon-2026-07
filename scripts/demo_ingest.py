"""Seed and index the demo's confidential sample documents.

Copies ``demo/sample_documents/*`` into ``data/documents/`` and runs the
incremental ``BatchIngestor`` over that directory so the RAG path has real
content to retrieve during a demo recording.

Usage:
    python scripts/demo_ingest.py [--documents DIR] [--output-dir DIR]

Without arguments it seeds ``demo/sample_documents`` into ``data/documents``
(the app's default documents folder) and indexes them into the ChromaDB store
at ``data/vector_db``. The script is idempotent: unchanged files are skipped
via the ingestion manifest.
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy  # noqa: E402  (import fully first to avoid the dspy lazy-import / numpy._typing circular import)

from src.config import get_config
from src.rag.batch_ingest import BatchIngestor
from src.rag.document_loader import DocumentLoader
from src.rag.embeddings import ROCEmbeddings
from src.rag.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("demo_ingest")

SEED_EXTENSIONS = {".txt", ".md", ".json", ".pdf", ".docx"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--documents",
        default=str(PROJECT_ROOT / "demo" / "sample_documents"),
        help="Folder of sample documents to seed and index.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "documents"),
        help="App documents folder to seed into (default: data/documents).",
    )
    args = parser.parse_args()

    src_dir = Path(args.documents)
    dst_dir = Path(args.output_dir)
    if not src_dir.is_dir():
        logger.error("Sample documents folder not found: %s", src_dir)
        return 1
    dst_dir.mkdir(parents=True, exist_ok=True)

    seeded = 0
    for p in sorted(src_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in SEED_EXTENSIONS:
            shutil.copy2(p, dst_dir / p.name)
            seeded += 1
    logger.info("Seeded %d sample documents into %s", seeded, dst_dir)

    config = get_config()
    try:
        embeddings = ROCEmbeddings(model_name=config.rag.embedding_model)
    except Exception as exc:  # graceful degradation: index with no embeddings
        logger.warning("Embeddings unavailable (%s); indexing without them.", exc)
        embeddings = None

    vector_store = VectorStore(embeddings=embeddings, persist_dir=config.rag.vector_db_path)
    loader = DocumentLoader(
        chunk_size=config.rag.chunk_size,
        chunk_overlap=config.rag.chunk_overlap,
    )
    ingestor = BatchIngestor(
        document_loader=loader,
        vector_store=vector_store,
        manifest_path=str(PROJECT_ROOT / "data" / "ingestion_manifest.json"),
    )

    stats = ingestor.ingest_directory(str(dst_dir))
    logger.info("Ingest summary: %s", stats)

    print(f"Seeded {seeded} docs; ingest -> {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
