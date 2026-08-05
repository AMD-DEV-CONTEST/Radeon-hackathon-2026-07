"""
THEMIS Triage Agent
Parses the PR diff, detects file types, computes risk score, and chunks large diffs.
This is the entry point of the tribunal — it shapes what all downstream agents see.
"""

import re
from typing import Any

from backend.config import get_settings

settings = get_settings()

# File type → risk weight mapping
_FILE_RISK_WEIGHTS = {
    ".py": 0.9,    # Python — high attack surface
    ".js": 0.9,    # JavaScript
    ".ts": 0.85,   # TypeScript
    ".jsx": 0.85,
    ".tsx": 0.85,
    ".php": 1.0,   # PHP — historically high vulnerability rate
    ".java": 0.8,
    ".go": 0.7,
    ".rb": 0.8,    # Ruby
    ".sh": 0.95,   # Shell scripts — RCE risk
    ".sql": 0.95,  # SQL — injection risk
    ".env": 1.0,   # Environment files — secrets exposure
    ".yml": 0.7,
    ".yaml": 0.7,
    ".json": 0.5,
    ".md": 0.1,
    ".txt": 0.1,
    ".css": 0.2,
}

# High-risk patterns in filenames
_HIGH_RISK_FILENAME_PATTERNS = [
    r"auth", r"login", r"password", r"token", r"secret", r"key",
    r"admin", r"sudo", r"crypt", r"hash", r"payment", r"billing",
    r"config", r"setting", r"database", r"db", r"sql",
]

# Max diff size per chunk for LLM context window (32K tokens ≈ ~24K chars)
MAX_CHUNK_CHARS = 20_000


def _extract_files_from_diff(diff: str) -> list[dict]:
    """Parse diff into file-level segments."""
    files = []
    current_file = None
    current_lines = []

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            if current_file:
                current_file["content"] = "\n".join(current_lines)
                files.append(current_file)
            # Extract filename
            match = re.search(r"b/(.+)$", line)
            filename = match.group(1) if match else "unknown"
            ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
            current_file = {"filename": filename, "ext": ext.lower(), "content": ""}
            current_lines = [line]
        elif current_file is not None:
            current_lines.append(line)

    if current_file:
        current_file["content"] = "\n".join(current_lines)
        files.append(current_file)

    return files


def _compute_risk_score(files: list[dict]) -> float:
    """
    Compute a 0–1 risk score for the PR based on file types and names.
    Higher = more likely to contain security-relevant changes.
    """
    if not files:
        return 0.0

    scores = []
    for f in files:
        base_score = _FILE_RISK_WEIGHTS.get(f["ext"], 0.5)
        # Boost for high-risk filenames
        filename_lower = f["filename"].lower()
        for pattern in _HIGH_RISK_FILENAME_PATTERNS:
            if re.search(pattern, filename_lower):
                base_score = min(1.0, base_score + 0.15)
                break
        scores.append(base_score)

    return round(sum(scores) / len(scores), 3)


def _chunk_diff(diff: str, files: list[dict]) -> list[str]:
    """
    Split a large diff into chunks that fit within the LLM context window.
    Each chunk preserves complete file diffs (never splits mid-file).
    """
    chunks = []
    current_chunk = ""

    for f in files:
        file_content = f["content"]
        if len(current_chunk) + len(file_content) > MAX_CHUNK_CHARS:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = file_content
        else:
            current_chunk += "\n" + file_content

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [diff]


async def triage_agent(state: dict) -> dict:
    """
    Triage agent implementation.

    Input state keys: sanitized_diff, pr_metadata
    Output state updates: file_types, risk_score, chunked_diffs
    """
    sanitized_diff = state.get("sanitized_diff", "")
    raw_diff = state.get("diff", sanitized_diff)

    # Parse files from diff
    files = _extract_files_from_diff(raw_diff)

    # Extract unique file types
    file_types = list({f["ext"] for f in files if f["ext"]})

    # Compute risk score
    risk_score = _compute_risk_score(files)

    # Chunk the diff for downstream agents
    chunked_diffs = _chunk_diff(raw_diff, files)

    # Sort files by risk (highest risk first) for downstream agents
    files_sorted = sorted(
        files,
        key=lambda f: _FILE_RISK_WEIGHTS.get(f["ext"], 0.5),
        reverse=True,
    )

    triage_summary = {
        "file_count": len(files),
        "file_types": file_types,
        "risk_score": risk_score,
        "chunk_count": len(chunked_diffs),
        "high_risk_files": [
            f["filename"] for f in files_sorted
            if _FILE_RISK_WEIGHTS.get(f["ext"], 0) >= 0.8
        ][:10],  # Top 10 high-risk files
    }

    return {
        "file_types": file_types,
        "risk_score": risk_score,
        "chunked_diffs": chunked_diffs,
        "triage_summary": triage_summary,
    }
