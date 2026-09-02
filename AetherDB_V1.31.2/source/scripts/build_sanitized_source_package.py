"""Build a source-only AetherDB archive with fail-closed privacy checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "LICENSE",
    "NOTICE",
    "README.md",
    "README_CN.md",
    "alembic.ini",
    "check_routes_auth.py",
    "config.example.yaml",
    "logging.conf",
    "main.py",
    "pytest.ini",
    "requirements-desktop-build.txt",
    "requirements-test.txt",
    "requirements.txt",
    "start.bat",
}
SOURCE_DIRECTORIES = {
    "alembic",
    "api",
    "app",
    "deploy",
    "extractors",
    "frontend",
    "prompts",
    "resources",
    "routes",
    "scripts",
    "services",
    "static",
    "templates",
    "tests",
}
FORBIDDEN_RELATIVE_PREFIXES = {
    ("scripts", "archive"),
    ("frontend", "src-tauri", "gen", "schemas"),
}
FORBIDDEN_RELATIVE_PATHS = {
    ("scripts", "backup_project.ps1"),
}
FORBIDDEN_PARTS = {
    ".agents",
    ".codex",
    ".codex-remote-attachments",
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "app_data",
    "backup",
    "backups",
    "build",
    "chroma_db",
    "dist",
    "local_agent_runs",
    "logs",
    "models",
    "node_modules",
    "target",
    "venv",
    "备份内容",
}
FORBIDDEN_NAMES = {
    ".api_keys.json",
    ".env",
    "api_keys.json",
    "config.local.yaml",
    "config.yaml",
}
FORBIDDEN_SUFFIXES = {
    ".bin",
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".dll",
    ".dylib",
    ".exe",
    ".gguf",
    ".key",
    ".log",
    ".onnx",
    ".onnx_data",
    ".p12",
    ".pem",
    ".pfx",
    ".pt",
    ".pth",
    ".safetensors",
    ".so",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = tuple(
    re.compile(value, re.IGNORECASE)
    for value in (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"nvk_(?:admin_)?[a-f0-9]{32}",
        r"ghp_[A-Za-z0-9]{30,}",
        r"AIza[0-9A-Za-z_-]{30,}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"Bearer\s+[A-Za-z0-9._-]{24,}",
    )
)
SENSITIVE_FIELD_RE = re.compile(
    r"(?im)^[ \t]*[\"']?(?:[A-Za-z0-9]+_)*"
    r"(?:api[_-]?key|password|secret(?:_key)?|token|credential)[\"']?"
    r"[ \t]*[:=][ \t]*[\"']?([^\"'#,\s}]+)"
)
PLACEHOLDER_VALUES = {
    "",
    "none",
    "null",
    "placeholder",
    "replace-me",
    "your-api-key",
    "your_api_key",
}
MAX_SOURCE_FILE_BYTES = 25 * 1024 * 1024


class ReleasePackageError(RuntimeError):
    pass


def _is_forbidden(relative_path: Path) -> bool:
    parts = {part.lower() for part in relative_path.parts}
    name = relative_path.name.lower()
    lowered_tuple = tuple(part.lower() for part in relative_path.parts)
    if lowered_tuple in FORBIDDEN_RELATIVE_PATHS:
        return True
    if any(
        lowered_tuple[: len(prefix)] == prefix
        for prefix in FORBIDDEN_RELATIVE_PREFIXES
    ):
        return True
    if parts & {value.lower() for value in FORBIDDEN_PARTS}:
        return True
    if name in FORBIDDEN_NAMES:
        return True
    if name.startswith("api_keys.json"):
        return True
    if name.startswith(".env") and name not in {
        ".env.example",
        ".env.competition.example",
    }:
        return True
    if any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True
    if any(part.endswith(".egg-info") for part in parts):
        return True
    generated = ("frontend", "src-tauri", "backend", "generated")
    if lowered_tuple[: len(generated)] == generated and name != ".gitkeep":
        return True
    return False


def _sensitive_files(source_root: Path) -> list[Path]:
    candidates = {
        source_root / ".api_keys.json",
        source_root / "config.yaml",
        source_root / "config.local.yaml",
    }
    candidates.update(
        path for path in source_root.glob(".env*") if path.name != ".env.example"
    )
    candidates.update(source_root.glob("api_keys.json*"))
    return sorted(path for path in candidates if path.is_file())


def _collect_json_strings(value) -> set[str]:
    if isinstance(value, dict):
        result: set[str] = set()
        for nested in value.values():
            result.update(_collect_json_strings(nested))
        return result
    if isinstance(value, list):
        result = set()
        for nested in value:
            result.update(_collect_json_strings(nested))
        return result
    return {value} if isinstance(value, str) else set()


def _local_secret_values(source_root: Path) -> set[str]:
    values: set[str] = set()
    for path in _sensitive_files(source_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name.lower() in {"api_keys.json", ".api_keys.json"}:
            try:
                values.update(_collect_json_strings(json.loads(text)))
            except ValueError:
                pass
        values.update(match.group(1).strip() for match in SENSITIVE_FIELD_RE.finditer(text))
    return {
        value
        for value in values
        if len(value) >= 8
        and value.lower() not in PLACEHOLDER_VALUES
        and not value.startswith("${")
        and not re.fullmatch(
            r"[A-Z][A-Z0-9_]*(?:API_KEY|PASSWORD|SECRET|TOKEN)",
            value,
        )
    }


def _candidate_files(source_root: Path):
    for name in sorted(ROOT_FILES):
        path = source_root / name
        if path.is_file():
            yield path, Path(name)
    for directory_name in sorted(SOURCE_DIRECTORIES):
        directory = source_root / directory_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_root)
            if not _is_forbidden(relative):
                yield path, relative


def _validate_source_file(
    path: Path,
    relative: Path,
    local_secret_values: set[str],
) -> None:
    if path.is_symlink():
        raise ReleasePackageError(f"Symlinks are not allowed: {relative.as_posix()}")
    size = path.stat().st_size
    if size > MAX_SOURCE_FILE_BYTES:
        raise ReleasePackageError(f"Source file exceeds size limit: {relative.as_posix()}")
    if _is_forbidden(relative):
        raise ReleasePackageError(f"Forbidden path selected: {relative.as_posix()}")
    raw = path.read_bytes()
    for secret in local_secret_values:
        if secret.encode("utf-8") in raw:
            raise ReleasePackageError(
                f"Value from a local credential file found: {relative.as_posix()}"
            )
    text = raw.decode("utf-8", errors="replace")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise ReleasePackageError(
            f"Real-looking credential pattern found: {relative.as_posix()}"
        )


def verify_package(
    archive_path: Path,
    *,
    local_secret_values: set[str] | None = None,
) -> dict:
    local_secrets = local_secret_values or set()
    with zipfile.ZipFile(archive_path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if not files:
            raise ReleasePackageError("Source archive is empty")
        roots = {Path(item.filename).parts[0] for item in files}
        if len(roots) != 1:
            raise ReleasePackageError("Source archive must have exactly one root directory")
        package_root = roots.pop()
        manifest_name = f"{package_root}/SOURCE_PACKAGE_MANIFEST.json"
        if manifest_name not in {item.filename for item in files}:
            raise ReleasePackageError("Source package manifest is missing")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        records = {item["path"]: item for item in manifest.get("files", [])}
        archived_source_paths: set[str] = set()

        for item in files:
            parts = Path(item.filename).parts
            if (
                Path(item.filename).is_absolute()
                or ".." in parts
                or parts[0] != package_root
            ):
                raise ReleasePackageError("Unsafe path found in source archive")
            if item.filename == manifest_name:
                continue
            relative = Path(*parts[1:])
            if _is_forbidden(relative):
                raise ReleasePackageError(
                    f"Forbidden path found in archive: {relative.as_posix()}"
                )
            payload = archive.read(item)
            if len(payload) > MAX_SOURCE_FILE_BYTES:
                raise ReleasePackageError(
                    f"Archived source file exceeds size limit: {relative.as_posix()}"
                )
            text = payload.decode("utf-8", errors="replace")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                raise ReleasePackageError(
                    f"Real-looking credential pattern found in archive: "
                    f"{relative.as_posix()}"
                )
            if any(secret.encode("utf-8") in payload for secret in local_secrets):
                raise ReleasePackageError(
                    f"Local credential value found in archive: {relative.as_posix()}"
                )
            record = records.get(relative.as_posix())
            if record is None:
                raise ReleasePackageError(
                    f"Archived file is absent from manifest: {relative.as_posix()}"
                )
            if record["size"] != len(payload) or record["sha256"] != hashlib.sha256(
                payload
            ).hexdigest():
                raise ReleasePackageError(
                    f"Archived file does not match manifest: {relative.as_posix()}"
                )
            archived_source_paths.add(relative.as_posix())

        if archived_source_paths != set(records):
            raise ReleasePackageError("Source package manifest file set does not match archive")
        return {
            "verified": True,
            "package": package_root,
            "file_count": len(records),
            "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        }


def build_package(
    source_root: Path,
    output_dir: Path,
    *,
    version: str,
    timestamp: datetime | None = None,
) -> tuple[Path, dict]:
    source_root = source_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    created = timestamp or datetime.now(timezone.utc)
    stamp = created.strftime("%Y%m%dT%H%M%SZ")
    package_root_name = f"aetherdb-v{version}-source"
    archive_path = output_dir / f"{package_root_name}-{stamp}.zip"
    if archive_path.exists():
        raise ReleasePackageError(f"Output archive already exists: {archive_path.name}")

    local_secrets = _local_secret_values(source_root)
    selected = list(_candidate_files(source_root))
    if not selected:
        raise ReleasePackageError("No source files were selected")

    with tempfile.TemporaryDirectory(prefix="aetherdb-package-", dir=output_dir) as temp:
        staging_root = Path(temp) / package_root_name
        records = []
        for source, relative in selected:
            _validate_source_file(source, relative, local_secrets)
            destination = staging_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            records.append(
                {
                    "path": relative.as_posix(),
                    "size": destination.stat().st_size,
                    "sha256": digest,
                }
            )

        manifest = {
            "schema_version": 1,
            "package": package_root_name,
            "version": version,
            "created_at": created.isoformat(),
            "privacy_boundary": (
                "source-only; excludes credentials, local config, databases, "
                "logs, user content, caches, build output, and model weights"
            ),
            "file_count": len(records),
            "files": records,
        }
        manifest_path = staging_root / "SOURCE_PACKAGE_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_archive = Path(temp) / archive_path.name
        with zipfile.ZipFile(
            temporary_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(staging_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging_root.parent))
        verification = verify_package(
            temporary_archive,
            local_secret_values=local_secrets,
        )
        os.replace(temporary_archive, archive_path)

    result = {
        "archive": str(archive_path),
        "sha256": verification["archive_sha256"],
        "verified": verification["verified"],
        "file_count": len(records),
        "size_bytes": archive_path.stat().st_size,
    }
    return archive_path, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", default="1.31.2")
    args = parser.parse_args()
    _archive, result = build_package(
        args.source_root,
        args.output_dir,
        version=args.version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
