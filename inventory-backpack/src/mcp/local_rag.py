"""MCP Local RAG Tool - hybrid semantic + keyword search with global file indexing."""

from __future__ import annotations

import os
import re
import time
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

SUPPORTED_EXTS = {
    ".pdf", ".docx", ".doc", ".md", ".txt", ".rtf", ".odt",
    ".py", ".js", ".ts", ".java", ".cpp", ".c", ".h",
    ".html", ".css", ".json", ".xml", ".csv",
}

# Windows 中英文目录名映射
def get_search_roots() -> List[str]:
    """获取所有需要搜索的目录（支持中英文路径）"""
    home = Path.home()
    dirs = [
        home / "桌面",
        home / "Desktop",
        home / "文档",
        home / "Documents",
        home / "下载",
        home / "Downloads",
    ]
    return [str(d) for d in dirs if d.exists()]

# 保持向后兼容
_get_search_roots = get_search_roots

SEARCH_ROOTS = get_search_roots()
MAX_RESULTS = 50
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
SEARCH_TIME_BUDGET = 5.0  # seconds


@dataclass(slots=True, frozen=True)
class FileMatch:
    path: str
    name: str
    score: float
    snippet: str = ""


def _normalize(text: str) -> str:
    """Normalize text for matching: remove spaces, underscores, hyphens, dots."""
    return re.sub(r'[\s_\-\.]+', '', text.lower())


def _keyword_score(query: str, target: str) -> float:
    """Simple keyword overlap scoring with normalized matching."""
    q_tokens = set(re.findall(r"\w+", query.lower()))
    t_tokens = set(re.findall(r"\w+", target.lower()))
    if not q_tokens:
        return 0.0
    token_score = len(q_tokens & t_tokens) / len(q_tokens)
    
    # Also check normalized substring match (handles "Python教程" vs "Python 教程")
    q_norm = _normalize(query)
    t_norm = _normalize(target)
    norm_score = 1.0 if q_norm and q_norm in t_norm else 0.0
    
    return max(token_score, norm_score)


def _search_file_bar(query: str, pipeline) -> List[Dict[str, Any]]:
    """Search uploaded files in the file bar (priority)."""
    results = []
    if not pipeline or not pipeline._file_contents:
        return results

    for file_id, content in pipeline._file_contents.items():
        score = _keyword_score(query, content[:2000])
        name_match = _keyword_score(query, file_id)
        total = max(score, name_match * 0.5)

        snippet = ""
        idx = content.lower().find(query.lower()[:20])
        if idx >= 0:
            start = max(0, idx - 50)
            snippet = content[start:start + 200]

        if total > 0 or snippet:
            results.append({
                "file_id": file_id,
                "source": "file_bar",
                "score": total,
                "snippet": snippet,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


def _scan_directory(root: str, query: str, results: List[FileMatch],
                   start_time: float, max_depth: int = 6) -> None:
    """Recursively scan a directory for matching files with time budget and depth limit."""
    root_path = Path(root)
    if not root_path.exists():
        return

    q_lower = query.lower()
    q_tokens = set(re.findall(r"\w+", q_lower))

    try:
        for dirpath, dirnames, filenames in os.walk(str(root_path)):
            # Time budget check
            if time.time() - start_time > SEARCH_TIME_BUDGET:
                return

            # Depth limit
            dirpath_obj = Path(dirpath)
            try:
                rel_depth = len(dirpath_obj.relative_to(root_path).parts)
            except ValueError:
                rel_depth = 0
            if rel_depth > max_depth:
                dirnames.clear()
                continue

            # Skip system/hidden directories
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith('.') and d not in {
                    'node_modules', '__pycache__', '.git',
                    'Windows', 'System32', 'ProgramData', 'AppData',
                    '$RECYCLE.BIN'
                }
            ]

            for filename in filenames:
                if len(results) >= MAX_RESULTS:
                    return

                file_path = dirpath_obj / filename
                name = filename
                name_lower = name.lower()

                # Check file size
                try:
                    stat = file_path.stat()
                    if stat.st_size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                # Score: exact match = 1.0, normalized match = 0.9, partial = keyword overlap
                score = 0.0
                # Direct substring match
                if q_lower in name_lower:
                    score = 1.0
                # Normalized match (handles "Python教程" vs "Python 教程")
                elif _normalize(query) in _normalize(name):
                    score = 0.9
                elif q_tokens:
                    score = _keyword_score(query, name)

                if score > 0:
                    snippet = ""
                    # Try to read content snippet for non-binary files
                    ext = file_path.suffix.lower()
                    if ext in {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css"}:
                        try:
                            text = file_path.read_text(encoding="utf-8", errors="ignore")[:500]
                            idx = text.lower().find(q_lower[:20])
                            if idx >= 0:
                                snippet = text[max(0, idx - 30):idx + 170]
                        except Exception:
                            pass

                    results.append(FileMatch(
                        path=str(file_path),
                        name=name,
                        score=score,
                        snippet=snippet,
                    ))

                    if len(results) >= MAX_RESULTS:
                        return
    except (PermissionError, OSError):
        pass


def global_file_search(query: str) -> List[FileMatch]:
    """Search global filesystem for documents with time budget."""
    results: List[FileMatch] = []
    start_time = time.time()

    roots = get_search_roots()
    for root in roots:
        if len(results) >= MAX_RESULTS:
            break
        if time.time() - start_time > SEARCH_TIME_BUDGET:
            break
        _scan_directory(root, query, results, start_time)

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:MAX_RESULTS]


# 保持向后兼容
_global_file_search = global_file_search


async def local_rag_search(
    query: str,
    pipeline=None,
) -> Dict[str, Any]:
    """
    Hybrid semantic + keyword search tool.
    1. Search file bar documents first (priority)
    2. Search global filesystem for PDF/DOCX/MD/TXT/etc.
    Returns matched files with paths and snippets.
    """
    file_bar_results = _search_file_bar(query, pipeline)

    loop = asyncio.get_event_loop()
    global_results = await loop.run_in_executor(None, _global_file_search, query)

    global_dicts = [
        {
            "path": m.path,
            "name": m.name,
            "source": "global",
            "score": m.score,
            "snippet": m.snippet,
        }
        for m in global_results
    ]

    return {
        "query": query,
        "file_bar_matches": file_bar_results,
        "global_matches": global_dicts,
        "total": len(file_bar_results) + len(global_dicts),
    }
