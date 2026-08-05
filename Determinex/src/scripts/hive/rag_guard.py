"""
scripts/hive/rag_guard.py — RAG Ingestion Safety Layer
=======================================================
Centralises the three Red Team mitigations that protect the vector ingestion
pipeline from catastrophic failures and credential leaks.

#14 OOM-Bomb Artifact Guard
    fastembed (ONNX CPU) attempting to embed a 300MB Rust target/ binary or
    a 50MB app.log causes the host RAM to fill instantly, triggering the OS
    OOM killer which vaporises the Rust orchestrator silently.
    Mitigation: hard file-size cap + magic byte binary rejection before any
    file content reaches the embedding model.

#24 Ghost Vector Sync
    Deleting a file and rolling back to a snapshot (Step N rollback) does NOT
    automatically remove the stale embeddings from sqlite-vec/ChromaDB. Over
    hours the vector index fills with "ghost embeddings" pointing at deleted
    or superseded code. Sentinel retrieves broken code from the past and the
    DAG resurrects already-proven-bad logic in an infinite loop.
    Mitigation: checksum diff between live filesystem and vector index;
    DELETE any embedding whose source file hash no longer matches disk.

#27 Secret Key Absolute Denylist
    See workspace.py for the primary denylist. This module exposes the same
    guard for callers that operate outside the workspace hash path (e.g. a
    standalone RAG ingestor CLI).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("hive.rag_guard")

# ── #14 File ingestion limits ─────────────────────────────────────────────────
MAX_INGEST_BYTES = 1_048_576  # 1 MB — above this the file is silently skipped

# Magic byte signatures for binary formats that must never be embedded.
# fastembed treats binary blobs as text and tokenises them into massive garbage
# tensors that exhaust RAM instantly.
_BINARY_MAGIC: list[bytes] = [
    b"\x7fELF",  # Linux ELF binary
    b"MZ",  # Windows PE binary (EXE/DLL)
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit (macOS)
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit
    b"\xca\xfe\xba\xbe",  # Mach-O fat binary
    b"PK\x03\x04",  # ZIP (JAR, APKG, WASM container)
    b"\x1f\x8b",  # gzip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # XZ
    b"\x89PNG",  # PNG image
    b"\xff\xd8\xff",  # JPEG image
    b"GIF8",  # GIF image
    b"RIFF",  # WAV / AVI
    b"ftyp",  # MP4 (offset 4)
    b"\x00\x00\x00\x00",  # null-padded binary (compiled .rmeta, .o, .a)
]


def is_binary_file(path: Path) -> bool:
    """#14: Return True if the file is a binary that must not be embedded.

    Uses magic byte detection on the first 16 bytes rather than relying on
    file extensions, which can be spoofed or absent for compiler artifacts.

    G33: Single read_bytes() call — previously called twice ([:16] then [:512]),
    causing an extra syscall and a TOCTOU window if the file changed between reads.
    """
    try:
        header = path.read_bytes()[:512]  # covers both magic check and null heuristic
        for magic in _BINARY_MAGIC:
            if header.startswith(magic):
                return True
        if b"\x00" in header:
            return True
        return False
    except OSError:
        return True  # unreadable = treat as binary for safety


def is_oversized_file(path: Path, max_bytes: int = MAX_INGEST_BYTES) -> bool:
    """#14: Return True if the file is too large to safely embed."""
    try:
        size = path.stat().st_size
        if size > max_bytes:
            log.warning(
                "RAG guard: skipping oversized file '%s' (%d bytes > %d byte limit)",
                path,
                size,
                max_bytes,
            )
            return True
        return False
    except OSError:
        return True


def is_safe_to_ingest(path: Path) -> bool:
    """#14 + #27: Return True if the file is safe to embed into the vector DB.

    Applies both the binary/size guard (#14) and the secret denylist (#27).
    This is the single gate that must be called before any file content is
    passed to fastembed or any other embedding model.
    """
    # Import the denylist from workspace to avoid duplication
    try:
        from hive.workspace import _is_sensitive_file

        if _is_sensitive_file(path):
            return False
    except ImportError:
        pass

    if is_oversized_file(path):
        return False

    if is_binary_file(path):
        log.warning("RAG guard: blocking binary file '%s' from embedding", path)
        return False

    return True


def iter_safe_workspace_files(
    workspace: Path,
    extensions: list[str] | None = None,
) -> Iterator[Path]:
    """Yield files that are safe to ingest into the vector DB.

    Applies all guards: exclusion dirs (#11), binary detection (#14),
    secret denylist (#27).
    """
    from hive.workspace import _is_excluded_path

    if extensions is None:
        extensions = [".rs", ".go", ".py", ".ts", ".js", ".md", ".toml", ".yaml", ".yml"]

    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        if _is_excluded_path(path, workspace):
            continue
        if not is_safe_to_ingest(path):
            continue
        yield path


# ── #24 Ghost Vector Sync ─────────────────────────────────────────────────────


def hash_file(path: Path) -> str:
    """Return a short SHA256 hex digest of the file contents."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    except OSError:
        return ""


def sync_vector_index(
    workspace: Path,
    index: dict[str, str],
    extensions: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """#24: Diff live filesystem against the vector index; return stale/new keys.

    Args:
        workspace:  The project workspace directory.
        index:      A dict mapping {relative_path -> file_hash} representing
                    what is currently stored in the vector DB.
        extensions: File extensions to consider (default: common source types).

    Returns:
        (stale_keys, new_paths):
            stale_keys — relative paths whose hash no longer matches the live file.
                         The caller MUST issue DELETE commands for these before
                         running any RAG query.
            new_paths  — relative paths that exist on disk but are absent from
                         the index (need to be embedded).

    The caller is responsible for the actual sqlite-vec / ChromaDB DELETE and
    INSERT operations — this function only computes the diff.
    """
    if extensions is None:
        extensions = [".rs", ".go", ".py", ".ts", ".js", ".md", ".toml", ".yaml", ".yml"]

    # Build live filesystem snapshot
    live: dict[str, str] = {}
    for path in iter_safe_workspace_files(workspace, extensions):
        rel = str(path.relative_to(workspace)).replace("\\", "/")
        live[rel] = hash_file(path)

    stale: list[str] = []
    new: list[str] = []

    # Find stale: in index but file deleted or hash changed
    for rel, stored_hash in index.items():
        if rel not in live:
            log.debug("Ghost vector: '%s' no longer exists on disk — marking stale", rel)
            stale.append(rel)
        elif live[rel] != stored_hash:
            log.debug(
                "Ghost vector: '%s' hash changed (%s \u2192 %s) — marking stale",
                rel,
                stored_hash,
                live[rel],
            )
            stale.append(rel)

    # Find new: on disk but not in index
    for rel in live:
        if rel not in index:
            new.append(rel)

    if stale:
        log.info(
            "#24 Vector sync: %d stale embedding(s) detected \u2014 caller must DELETE before query: %s",
            len(stale),
            stale[:5],
        )
    if new:
        log.info("#24 Vector sync: %d new file(s) to embed: %s", len(new), new[:5])

    return stale, new
