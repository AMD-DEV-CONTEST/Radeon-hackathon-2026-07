"""Controlled source-directory scanning for Phase A document imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.security.paths import ensure_project_path, validate_project_id


SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".md": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
}


@dataclass(frozen=True, slots=True)
class ScannedSourceEntry:
    full_path: Path
    relative_path: str
    format: str
    error_message: str | None = None


def is_path_safe(project_dir: Path, candidate: Path) -> bool:
    """Return whether a resolved candidate remains within a resolved project."""
    try:
        candidate.resolve().relative_to(project_dir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _detect_format(file_path: Path) -> str:
    return SUPPORTED_EXTENSIONS.get(file_path.suffix.lower(), "unsupported")


def _project_root(*, base_dir: Path | None, project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root
    return (base_dir or Path.cwd()) / "data" / "projects"


def scan_source_entries(
    project_id: str,
    *,
    base_dir: Path | None = None,
    project_root: Path | None = None,
) -> list[ScannedSourceEntry]:
    """Scan all source files and retain unsafe/unsupported outcomes for audit."""
    project_id = validate_project_id(project_id)
    root = _project_root(base_dir=base_dir, project_root=project_root)
    project_dir = ensure_project_path(root, project_id)
    source_dir = ensure_project_path(root, project_id, "source")

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {source_dir}")

    results: list[ScannedSourceEntry] = []
    for entry in source_dir.rglob("*"):
        if entry.is_dir():
            continue
        try:
            relative_path = str(entry.relative_to(project_dir)).replace("\\", "/")
        except ValueError:
            continue

        fmt = _detect_format(entry)
        if entry.is_symlink() and not is_path_safe(project_dir, entry):
            results.append(
                ScannedSourceEntry(entry, relative_path, fmt, "symlink escape detected")
            )
        elif entry.is_file():
            results.append(ScannedSourceEntry(entry, relative_path, fmt))
        elif entry.is_symlink():
            results.append(ScannedSourceEntry(entry, relative_path, fmt, "broken symlink detected"))
    return results


def scan_source_dir(
    project_id: str,
    *,
    base_dir: Path | None = None,
    project_root: Path | None = None,
) -> list[tuple[Path, str, str]]:
    """Return only safe, supported files for compatibility with existing callers."""
    return [
        (entry.full_path, entry.relative_path, entry.format)
        for entry in scan_source_entries(project_id, base_dir=base_dir, project_root=project_root)
        if entry.error_message is None and entry.format != "unsupported"
    ]
