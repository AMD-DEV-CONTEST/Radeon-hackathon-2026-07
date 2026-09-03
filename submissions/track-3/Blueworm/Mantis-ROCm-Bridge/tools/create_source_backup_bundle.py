#!/usr/bin/env python3
"""Create a deterministic, allowlisted, no-overwrite project source backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


BASE_ALLOWLIST = [
    "src",
    "tools",
    "configs",
    "tests",
    "docs",
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "third_party",
]
ALLOWLIST = [
    *BASE_ALLOWLIST,
    "receipts/urdf-act-compiler-terminal-20260729-v1",
]
DEFAULT_WORK_PACKAGE_ID = "WP-URDF-ACT-COMPILER-MVP-004"
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: str) -> PurePosixPath:
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"unsafe allowlist path: {path}")
    return relative


def _excluded(relative: Path) -> bool:
    return (
        any(part in EXCLUDED_PARTS for part in relative.parts)
        or relative.name == ".DS_Store"
        or relative.suffix in EXCLUDED_SUFFIXES
    )


def inventory(project_root: Path, allowlist: Iterable[str]) -> list[dict[str, Any]]:
    """Inventory regular allowlisted files without following symlinks."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in allowlist:
        relative = _safe_relative(raw)
        source = project_root.joinpath(*relative.parts)
        if not source.exists():
            raise FileNotFoundError(f"required allowlist entry missing: {relative}")
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for candidate in candidates:
            item_relative = candidate.relative_to(project_root)
            if _excluded(item_relative):
                continue
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"symlink forbidden: {item_relative.as_posix()}")
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"special file forbidden: {item_relative.as_posix()}")
            name = item_relative.as_posix()
            if name in seen:
                continue
            seen.add(name)
            records.append(
                {
                    "path": name,
                    "size_bytes": candidate.stat().st_size,
                    "mode": stat.S_IMODE(mode),
                    "sha256": sha256_file(candidate),
                }
            )
    records.sort(key=lambda item: item["path"])
    return records


def _normalized_tar_info(source: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    info.size = source.stat().st_size
    info.mode = stat.S_IMODE(source.stat().st_mode)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    return info


def _write_json_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def create_bundle(
    project_root: Path,
    output: Path,
    *,
    allowlist: Iterable[str] = ALLOWLIST,
    work_package_id: str = DEFAULT_WORK_PACKAGE_ID,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = inventory(project_root, allowlist)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=output.parent)
    )
    try:
        manifest = {
            "schema_version": 1,
            "work_package_id": work_package_id,
            "archive_root": "mantis-rocm-bridge",
            "allowlist": list(allowlist),
            "excluded": {
                "parts": sorted(EXCLUDED_PARTS),
                "suffixes": sorted(EXCLUDED_SUFFIXES),
                "names": [".DS_Store"],
                "external_robot_assets": True,
                "datasets": True,
                "checkpoints": True,
                "unrelated_receipts": True,
            },
            "file_count": len(records),
            "total_file_bytes": sum(item["size_bytes"] for item in records),
            "files": records,
        }
        manifest_path = staging / "SOURCE_FILES.json"
        _write_json_exclusive(manifest_path, manifest)
        sums_path = staging / "SOURCE_FILES.SHA256SUMS"
        with sums_path.open("x", encoding="utf-8") as stream:
            for item in records:
                stream.write(f"{item['sha256']}  {item['path']}\n")

        archive_path = staging / "mantis-rocm-bridge-source.tar"
        with tarfile.open(archive_path, mode="x") as archive:
            for item in records:
                source = project_root / item["path"]
                arcname = f"mantis-rocm-bridge/{item['path']}"
                with source.open("rb") as stream:
                    archive.addfile(_normalized_tar_info(source, arcname), stream)
        archive_record = {
            "path": archive_path.name,
            "sha256": sha256_file(archive_path),
            "size_bytes": archive_path.stat().st_size,
        }
        bundle = {
            "schema_version": 1,
            "work_package_id": work_package_id,
            "archive": archive_record,
            "source_manifest": {
                "path": manifest_path.name,
                "sha256": sha256_file(manifest_path),
            },
            "source_sums": {
                "path": sums_path.name,
                "sha256": sha256_file(sums_path),
            },
            "file_count": len(records),
            "claim_boundary": (
                "Allowlisted source backup only. External robot assets, datasets, "
                "checkpoints, credentials, and unrelated receipts are excluded."
            ),
        }
        bundle_path = staging / "bundle.json"
        _write_json_exclusive(bundle_path, bundle)
        checksum_targets = sorted(
            path for path in staging.iterdir() if path.name != "BUNDLE.SHA256SUMS"
        )
        with (staging / "BUNDLE.SHA256SUMS").open("x", encoding="utf-8") as stream:
            for target in checksum_targets:
                stream.write(f"{sha256_file(target)}  {target.name}\n")
        os.rename(staging, output)
        return bundle
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--work-package-id",
        default=DEFAULT_WORK_PACKAGE_ID,
        help="work package recorded in the bundle and source manifests",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        help=(
            "relative file or directory to include; repeat for every entry. "
            "Omitting it preserves the historical WP-004 allowlist."
        ),
    )
    args = parser.parse_args()
    result = create_bundle(
        args.project_root,
        args.output,
        allowlist=args.allowlist or ALLOWLIST,
        work_package_id=args.work_package_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
