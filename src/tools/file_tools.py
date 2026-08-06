"""File read/write tools: controlled read/write based on Workspace files_root."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def read_file(ws: Any, file_path: str) -> str:
    """Read file content from the Workspace.
    
    Args:
        ws: Agently Workspace instance
        file_path: file path (e.g., downloads/policy.txt)
        
    Returns:
        file content
    """
    content = await ws.read_file(file_path)
    logger.info("read file: %s (%d characters)", file_path, len(content) if content else 0)
    return content or ""


async def list_files(ws: Any, dir_path: str = "downloads") -> list[str]:
    """List files in a Workspace directory.
    
    Args:
        ws: Agently Workspace instance
        dir_path: directory path
        
    Returns:
        list of file names
    """
    try:
        files = await ws.list_files(dir_path)
        logger.info("listed directory %s: %d files", dir_path, len(files) if files else 0)
        return files or []
    except Exception as e:
        logger.warning("failed to list directory: %s", e)
        return []


async def search_document(ws: Any, query: str, file_path: str | None = None) -> list[dict]:
    """Search for keywords in Workspace documents.
    
    Args:
        ws: Agently Workspace instance
        query: search keyword
        file_path: specified file (optional, if not specified search all files)
        
    Returns:
        list of matched results
    """
    try:
        if file_path:
            results = await ws.grep_files(query, path=file_path)
        else:
            results = await ws.grep_files(query)
        logger.info("search '%s': %d results", query, len(results) if results else 0)
        return results or []
    except Exception as e:
        logger.warning("search failed: %s", e)
        return []