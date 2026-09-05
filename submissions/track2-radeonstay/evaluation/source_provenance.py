"""Stable provenance hashing for the immutable RadeonStay C2 inputs."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

_FROZEN_DIRECTORIES = ("src", "data", "scripts", "tests", "evaluation")
_FROZEN_ROOT_FILES = frozenset(
    {
        ".env.example",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "requirements.lock",
    }
)
_EXCLUDED_PREFIXES = ("evaluation/results/",)
_HASH_DOMAIN = b"radeonstay-c2-frozen-inputs-v1\0"


@dataclass(frozen=True, slots=True)
class _TrackedInput:
    mode: str
    object_id: str
    path: str


def _is_frozen_input(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in _FROZEN_ROOT_FILES:
        return True
    if any(normalized.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
        return False
    return any(
        normalized.startswith(f"{directory}/")
        for directory in _FROZEN_DIRECTORIES
    )


def _git_tracked_inputs(project_root: Path) -> tuple[_TrackedInput, ...]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "ls-tree",
            "-r",
            "-z",
            "HEAD",
            "--",
            *_FROZEN_DIRECTORIES,
            *sorted(_FROZEN_ROOT_FILES),
        ],
        check=True,
        capture_output=True,
    )
    entries: list[_TrackedInput] = []
    for raw_entry in completed.stdout.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative_path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("Git returned an invalid C2 tree entry") from exc
        if not _is_frozen_input(relative_path):
            continue
        if object_type != "blob":
            raise RuntimeError(
                f"Tracked C2 input is not a Git blob: {relative_path} ({object_type})"
            )
        entries.append(
            _TrackedInput(
                mode=mode,
                object_id=object_id,
                path=relative_path,
            )
        )
    return tuple(sorted(entries, key=lambda item: item.path))


def _head_blob(project_root: Path, object_id: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), "cat-file", "blob", object_id],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _validated_worktree_file(project_root: Path, entry: _TrackedInput) -> Path:
    if entry.mode not in {"100644", "100755"}:
        raise RuntimeError(
            f"Tracked C2 input is not a regular file: {entry.path} ({entry.mode})"
        )
    path = project_root / entry.path
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            f"Tracked C2 input is missing or is not a regular file: {entry.path}"
        )
    cursor = path.parent
    while cursor != project_root:
        if cursor.is_symlink():
            raise RuntimeError(
                f"Tracked C2 input has a symbolic-link parent: {entry.path}"
            )
        if project_root not in cursor.parents:
            raise RuntimeError(f"Tracked C2 input escapes the project root: {entry.path}")
        cursor = cursor.parent
    resolved = path.resolve(strict=True)
    if project_root not in resolved.parents:
        raise RuntimeError(f"Tracked C2 input escapes the project root: {entry.path}")
    return path


def source_tree_sha256(project_root: Path) -> str:
    """Hash only Git-tracked C2 inputs, independent of docs and run outputs."""

    root = project_root.resolve(strict=True)
    tracked_inputs = _git_tracked_inputs(root)
    if not tracked_inputs:
        raise RuntimeError("No Git-tracked RadeonStay C2 inputs were found")
    tracked_paths = {entry.path for entry in tracked_inputs}
    missing_root_files = sorted(_FROZEN_ROOT_FILES - tracked_paths)
    if missing_root_files:
        raise RuntimeError(
            f"Required C2 root inputs are not tracked: {missing_root_files}"
        )
    missing_directories = sorted(
        directory
        for directory in _FROZEN_DIRECTORIES
        if not any(path.startswith(f"{directory}/") for path in tracked_paths)
    )
    if missing_directories:
        raise RuntimeError(
            f"Required C2 input directories are empty or untracked: {missing_directories}"
        )

    digest = hashlib.sha256(_HASH_DOMAIN)
    for entry in tracked_inputs:
        path = _validated_worktree_file(root, entry)
        content = _head_blob(root, entry.object_id)
        if path.read_bytes() != content:
            raise RuntimeError(
                f"Tracked C2 input differs byte-for-byte from HEAD: {entry.path}"
            )
        label = f"{entry.mode} {entry.path}".encode()
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
