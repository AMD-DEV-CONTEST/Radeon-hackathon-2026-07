"""Document ingestion: write Record + File to the Workspace."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ingest_document(
    ws: Any,
    file_path: str,
    content: str,
) -> dict:
    """Ingest a document: write File + Record, return the ref.
    
    Note: embedding and FAISS indexing are handled in src/rag/indexer.py.
    
    Args:
        ws: Agently Workspace instance
        file_path: file name (stored under downloads/)
        content: file content
    
    Returns:
        ref dict (containing collection, kind, id, etc.)
    """
    # File path: tools can continue to process it
    await ws.write_file(f"downloads/{file_path}", content)
    logger.info("File written: downloads/%s", file_path)
    
    # Record: the system knows what this is
    ref = await ws.put(
        content[:200],  # Record stores only a summary; the full text is in the File
        collection="inputs",
        kind="uploaded_doc",
        meta={"filename": file_path, "summary": content[:100]},
    )
    logger.info("Record written: %s", ref)
    return ref
