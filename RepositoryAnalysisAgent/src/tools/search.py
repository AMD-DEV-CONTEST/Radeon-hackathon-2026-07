"""Search tools: semantic code search with reranking, and grep-based text search."""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from .registry import ToolRegistry

if TYPE_CHECKING:
    from ..index.indexer import Indexer

logger = logging.getLogger(__name__)


def register_search_tools(
    registry: ToolRegistry,
    indexer: Indexer,
    reranker=None,
) -> None:
    """Register search_code and grep_code tools."""

    async def search_code(query: str, top_k: int = 15) -> str:
        """Semantic search across the codebase using embeddings + reranking.

        Args:
            query: Natural language or code snippet to search for.
            top_k: Number of results to return (default 15).
        """
        if indexer.is_indexing:
            return "Indexing in progress. Please wait and try again."

        chunk_count = indexer.chunk_count
        if chunk_count == 0:
            return "No code has been indexed yet. Run indexing first."

        # Step 1: embedding retrieval -> top candidates
        candidate_count = 20
        if reranker is not None:
            candidate_count = reranker.config.candidate_count

        results = indexer.search(query, top_k=candidate_count)

        if not results:
            return f"No results found for: {query}"

        # Step 2: rerank with cross-encoder (GPU)
        if reranker is not None:
            ranked = reranker.rerank(
                query,
                [r["content"][:512] for r in results],
                top_k=top_k,
            )
            # Map ranked indices back to results
            final = [results[idx] for idx, _ in ranked]
        else:
            final = results[:top_k]

        # Format results
        lines = [f"Found {len(final)} results for '{query}':\n"]
        for i, r in enumerate(final):
            score = r.get("score", 0.0)
            lines.append(
                f"--- Result {i+1} (score: {score:.3f}) ---\n"
                f"File: {r['file_path']}:{r['start_line']}-{r['end_line']}\n"
                f"Symbol: {r.get('symbol_name', 'N/A')} ({r.get('symbol_kind', 'N/A')})\n"
            )
            # Truncate content to reasonable size
            content = r["content"]
            if len(content) > 2000:
                content = content[:2000] + "\n... [truncated]"
            lines.append(f"```python\n{content}\n```\n")

        return "\n".join(lines)

    registry.register(
        name="search_code",
        description=(
            "Search the codebase semantically. Use this to find code related to "
            "a concept, feature, or keyword. Returns code chunks with file paths "
            "and line numbers. Results are reranked for relevance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for (natural language or code).",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 15).",
                    "default": 15,
                },
            },
            "required": ["query"],
        },
        handler=search_code,
    )

    async def grep_code(pattern: str, file_pattern: str = "") -> str:
        """Search for exact text or regex patterns using ripgrep.

        Args:
            pattern: Text or regex pattern to search for.
            file_pattern: Optional glob pattern to filter files (e.g. "*.py").
        """
        repo_root = str(indexer.config.repo_root)
        cmd = ["rg", "--line-number", "--no-heading", "-C", "2"]
        if file_pattern:
            cmd.extend(["--glob", file_pattern])
        cmd.extend(["--", pattern, repo_root])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                output = result.stdout
                if len(output) > 5000:
                    output = output[:5000] + "\n... [truncated]"
                return f"```\n{output}\n```" if output else "No matches found."
            elif result.returncode == 1:
                return "No matches found."
            else:
                return f"Search error: {result.stderr}"
        except FileNotFoundError:
            return "ripgrep (rg) is not installed. Using search_code instead."
        except subprocess.TimeoutExpired:
            return "Search timed out (30s limit)."

    registry.register(
        name="grep_code",
        description=(
            "Search for exact text or regex patterns using ripgrep. "
            "Faster and more precise than semantic search for exact matches, "
            "variable names, or import statements."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Text or regex pattern to search for.",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Optional glob to filter files (e.g. '*.py').",
                    "default": "",
                },
            },
            "required": ["pattern"],
        },
        handler=grep_code,
    )
