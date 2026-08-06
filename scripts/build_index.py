"""Document ingestion + chunking + embedding + FAISS index + BM25 index building.

Improvements:
- Multi-format document parsing: PDF / Word / HTML / TXT / MD + tables + images
- Sliding window chunking: window=512, overlap=100 (20%)
- Source data storage: each chunk carries source, title, section_title, section_type
- BM25 index: build a sparse retrieval index to support hybrid retrieval
- Workspace Record: chunk metadata persistence
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    load_config,
    configure_agently,
    make_embedding_agent,
    get_index_dir,
    get_workspace_root,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

DOCS_DATA_DIR = PROJECT_ROOT / "docs_data"


async def write_chunks_to_workspace(
    chunks: list,
    workspace_root: Path,
) -> dict[str, str]:
    """Write chunk metadata into the Workspace Record, establishing the evidence grounding chain.

    Each chunk is written as one Record:
    - collection: "inputs"
    - kind: "doc_chunk"
    - content: chunk_text (used by retriever.py's get_data to read)
    - meta: {chunk_id, doc_ref, chunk_summary, start_char, end_char, source, title, section_title, section_type, page}

    Returns:
        chunk_id -> record_ref mapping (for the FAISS indexer to use)
    """
    chunk_id_to_ref: dict[str, str] = {}
    records_dir = workspace_root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    for chunk in chunks:
        record_path = records_dir / f"{chunk.chunk_id}.json"
        record_data = {
            "chunk_id": chunk.chunk_id,
            "doc_ref": chunk.doc_ref,
            "content": chunk.chunk_text,
            "chunk_summary": chunk.chunk_summary,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "meta": chunk.meta,
        }
        record_path.write_text(
            json.dumps(record_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chunk_id_to_ref[chunk.chunk_id] = str(record_path)

    logger.info("Workspace Records written: %d entries -> %s", len(chunks), records_dir)
    return chunk_id_to_ref


async def check_embedding_service(embedding_agent) -> None:
    """Pre-check embedding service availability to avoid discovering a connection
    failure only after chunking is complete.

    DirectEmbeddingAgent.input().async_start() returns list[list[float]],
    so test_result[0] is one vector, and len() returns the real dimension (bge-m3 = 1024).
    """
    try:
        test_result = await embedding_agent.input(["test"]).async_start()
        if test_result and len(test_result) > 0:
            dim = len(test_result[0])
            if dim < 100:
                raise RuntimeError(
                    f"Embedding vector dimension abnormal: {dim} (expected 1024 for bge-m3)"
                )
            logger.info("Embedding service pre-check passed (test vector dim=%d)", dim)
        else:
            raise RuntimeError("Embedding service returned an empty result")
    except Exception as e:
        logger.error(
            "Embedding service connection failed: %s\n"
            "Please make sure the embedding service is running:\n"
            "  text-embeddings-router --model ./models/bge-m3 --port 8001\n"
            "or check the [embedding] section's base_url config in configs/models.toml",
            e,
        )
        raise


async def main():
    t0 = time.time()

    # Load config
    agent_cfg, models_cfg = load_config()
    configure_agently(models_cfg)
    embedding_agent = make_embedding_agent(models_cfg)

    # Pre-check the embedding service (fail fast, before parsing documents)
    await check_embedding_service(embedding_agent)

    # Load RAG config
    rag_cfg = agent_cfg.get("rag", {})
    chunk_size = rag_cfg.get("chunk_size", 512)
    chunk_overlap = rag_cfg.get("chunk_overlap", 100)  # 20% of 512

    # Collect documents — use the new multi-format parser
    docs_data = DOCS_DATA_DIR
    if not docs_data.exists():
        docs_data.mkdir(parents=True, exist_ok=True)

    from src.rag.parser import collect_all_documents
    from src.rag.chunker import chunk_parsed_document, chunk_document, Chunk
    from src.rag.indexer import FaissIndexer

    # Parse all supported document formats
    parsed_docs = collect_all_documents(docs_data)

    if not parsed_docs:
        logger.error(
            "No usable documents in docs_data/. Supported formats: .pdf .docx .html .htm .txt .md"
            " You can copy from archive/CASE-multi-file-QA-Agent/docs/."
        )
        return

    # Chunking
    all_chunks: list[Chunk] = []
    for doc in parsed_docs:
        chunks = chunk_parsed_document(doc, chunk_size, chunk_overlap)
        all_chunks.extend(chunks)
        logger.info(
            "Document %s: %d chunks (format=%s, title='%s')",
            doc.source, len(chunks), doc.format, doc.title,
        )

    logger.info(
        "Total: %d documents, %d chunks (window=%d, overlap=%d, 20%%=%d)",
        len(parsed_docs), len(all_chunks), chunk_size, chunk_overlap, int(chunk_size * 0.2),
    )

    # Evidence Grounding Chain: chunk -> Workspace Record
    workspace_root = get_workspace_root(agent_cfg)
    workspace_root.mkdir(parents=True, exist_ok=True)
    chunk_id_to_ref = await write_chunks_to_workspace(all_chunks, workspace_root)

    # Generate embeddings
    logger.info("Generating embeddings...")
    texts = [c.chunk_text for c in all_chunks]

    # DirectEmbeddingAgent.input(texts).async_start() returns list[list[float]]
    # It batches internally (batch_size=32) and parses everything into pure float vectors
    all_embeddings = await embedding_agent.input(texts).async_start()

    logger.info("Embedding generation complete: %d vectors", len(all_embeddings))

    embeddings = np.array(all_embeddings, dtype=np.float32)
    logger.info("Embedding matrix: %s", embeddings.shape)

    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    # Build the FAISS index
    dimension = embeddings.shape[1]
    indexer = FaissIndexer(dimension=dimension)
    indexer.build_from_chunks(all_chunks, embeddings)

    # Persist the FAISS index
    index_dir = get_index_dir(agent_cfg)
    indexer.save(index_dir)

    # Build the BM25 index (hybrid retrieval)
    bm25_built = False
    try:
        from src.rag.bm25_indexer import BM25Indexer
        bm25_indexer = BM25Indexer()
        bm25_indexer.build_from_chunks(all_chunks)
        bm25_indexer.save(index_dir)
        bm25_built = True
        logger.info("BM25 index build complete")
    except ImportError:
        logger.warning("rank-bm25 not installed, skipping BM25 index build. pip install rank-bm25")
    except Exception as e:
        logger.warning("BM25 index build failed: %s", e)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"Index build complete!")
    print(f"  Documents:   {len(parsed_docs)}")
    print(f"  Chunks:      {len(all_chunks)}")
    print(f"  Vector dim:  {dimension}")
    print(f"  Chunk params: window={chunk_size}, overlap={chunk_overlap} (20%)")
    print(f"  Workspace Records: {len(chunk_id_to_ref)} entries")
    print(f"  FAISS index: {index_dir}")
    print(f"  BM25 index:  {'built' if bm25_built else 'not built (rank-bm25 missing)'}")
    print(f"  Total time:  {elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
