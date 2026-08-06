"""Build the allowlisted Track 1 contest submission bundle."""

from __future__ import annotations

import shutil
from pathlib import Path

ALLOWED_DIRECTORIES = (
    "agent",
    "api",
    "backend",
    "command",
    "docker",
    "frontend",
    "scripts",
    "session",
    "tests",
    "video",
    "vision",
    "submission",
)
ROOT_FILES = {
    ".env.example",
    ".gitignore",
    "README.md",
    "package.json",
    "package-lock.json",
    "pytest.ini",
    "requirements.txt",
    "requirements-dev.txt",
}
EXCLUDED_COMPONENTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".venv",
    ".worktrees",
    "__pycache__",
    "cache",
    "caches",
    "checkpoints",
    "data",
    "datasets",
    "dist",
    "env",
    "envs",
    "environment",
    "environments",
    "logs",
    "models",
    "node_modules",
    "output",
    "playwright-report",
    "recordings",
    "reports",
    "secrets",
    "test-results",
    "tmp",
    "venv",
}
EXCLUDED_SUFFIXES = {
    ".avi",
    ".ckpt",
    ".h5",
    ".mov",
    ".mp4",
    ".onnx",
    ".pth",
    ".pt",
    ".webm",
}
SECRET_SUFFIXES = {".key", ".pem", ".pfx", ".p12"}
BANNED_MARKETING_PHRASES = {
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "next-generation",
    "seamless",
    "harness the power of ai",
    "unlock possibilities",
}
MAX_FILE_SIZE = 50 * 1024 * 1024


def _is_excluded(relative_path: Path) -> bool:
    """Return whether a candidate conflicts with the contest safety policy."""
    name = relative_path.name.lower()
    return (
        any(component.lower() in EXCLUDED_COMPONENTS for component in relative_path.parts)
        or name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
        or relative_path.suffix.lower() in EXCLUDED_SUFFIXES
        or relative_path.suffix.lower() in SECRET_SUFFIXES
    )


def _reject_symlink_path(path: Path, label: str) -> None:
    """Reject a path when it or any lexical ancestor is a symlink."""
    absolute_path = path if path.is_absolute() else Path.cwd() / path
    candidate = Path(absolute_path.anchor)
    for component in absolute_path.parts[1:]:
        candidate /= component
        if candidate.is_symlink():
            raise ValueError(f"Contest bundle rejects symlink in {label}: {candidate}")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _allowed_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for name in sorted(ROOT_FILES):
        candidate = source / name
        if candidate.is_symlink():
            raise ValueError(f"Contest bundle rejects symlink: {candidate}")
        if not candidate.exists():
            continue
        if (
            candidate.is_file()
            and not _is_excluded(candidate.relative_to(source))
            and candidate.stat().st_size <= MAX_FILE_SIZE
        ):
            files.append(candidate)

    directories = [*ALLOWED_DIRECTORIES, "docs/runbooks", "docs/submission"]
    for name in directories:
        directory = source / name
        if directory.is_symlink():
            raise ValueError(f"Contest bundle rejects symlink: {directory}")
        if not directory.exists():
            continue
        for candidate in sorted(directory.rglob("*")):
            if candidate.is_symlink():
                raise ValueError(f"Contest bundle rejects symlink: {candidate}")
            if not candidate.is_file():
                continue
            relative_path = candidate.relative_to(source)
            if _is_excluded(relative_path):
                continue
            if candidate.stat().st_size <= MAX_FILE_SIZE:
                files.append(candidate)
    return files


def _audit_markdown(destination: Path) -> None:
    for path in sorted(destination.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "tests" in path.relative_to(destination).parts:
            continue
        lower_text = text.lower()
        for phrase in BANNED_MARKETING_PHRASES:
            if phrase in lower_text:
                raise ValueError(f"Contest-facing Markdown uses banned phrase {phrase!r}: {path}")


def build_bundle(source: Path, destination: Path) -> list[Path]:
    """Copy only reviewed runtime and submission files into *destination*."""
    _reject_symlink_path(source, "source path")
    _reject_symlink_path(destination, "destination path")
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise ValueError(f"Contest bundle source is not a directory: {source}")
    if _is_within(source, destination):
        raise ValueError("Contest bundle destination must not overlap its source")
    if _is_within(destination, source):
        relative_destination = destination.relative_to(source)
        if not relative_destination.parts or relative_destination.parts[0] != "dist":
            raise ValueError("Contest bundle destination must not overlap its source")
    files = _allowed_files(source)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    copied: list[Path] = []
    for path in files:
        relative_path = path.relative_to(source)
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(target)

    _audit_markdown(destination)
    return copied


def main() -> None:
    source = Path(__file__).resolve().parents[1]
    destination = source / "dist/contest/submissions/track1-silent-vision"
    copied = build_bundle(source, destination)
    print(f"Built {len(copied)} files in {destination}")


if __name__ == "__main__":
    main()
