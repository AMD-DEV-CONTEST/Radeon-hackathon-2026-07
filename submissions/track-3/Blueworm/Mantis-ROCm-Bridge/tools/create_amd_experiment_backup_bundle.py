#!/usr/bin/env python3
"""Create a no-clobber, hash-verifiable bundle of AMD experiment roots.

Run this on the official AMD worker after all selected jobs are terminal. The
tool writes one uncompressed tar archive per source root so interrupted
transfers can resume at archive granularity. It never includes virtual
environments, caches, symlinks, sockets, device nodes, or other special files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("backup contract schema_version must be 1")
    bundle = data.get("bundle", {})
    required_true = (
        "one_archive_per_source_root",
        "exclusive_output",
        "atomic_destination_publish",
        "source_file_sha256_required",
        "archive_sha256_required",
        "destination_independent_verification_required",
        "forbid_symlinks",
        "forbid_special_files",
    )
    if bundle.get("archive_format") != "tar":
        raise ValueError("backup archive_format must be tar")
    execution = data.get("execution")
    if isinstance(execution, dict) and execution.get("authorized") is not True:
        raise ValueError(
            "backup contract is frozen but not execution-authorized; "
            "record a fresh instance identity and version a ready contract first"
        )
    for key in required_true:
        if bundle.get(key) is not True:
            raise ValueError(f"backup bundle.{key} must be true")
    roots = data.get("source_roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("backup source_roots must be a non-empty list")
    artifact_ids = [entry.get("artifact_id") for entry in roots]
    if not all(isinstance(value, str) and value for value in artifact_ids):
        raise ValueError("every source root needs an artifact_id")
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("backup artifact_id values must be unique")
    return data


def inventory_root(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        relative = candidate.relative_to(root)
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"symlink forbidden in backup source: {candidate}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"special file forbidden in backup source: {candidate}")
        records.append(
            {
                "path": relative.as_posix(),
                "size_bytes": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
        )
    return records


def add_tree(archive: tarfile.TarFile, root: Path, artifact_id: str) -> None:
    directories = [root]
    directories.extend(
        path
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix())
        if path.is_dir() and not path.is_symlink()
    )
    for directory in directories:
        relative = directory.relative_to(root)
        arcname = Path(artifact_id) / relative
        info = archive.gettarinfo(str(directory), arcname=arcname.as_posix())
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        archive.addfile(info)
    for source in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(root)
        arcname = Path(artifact_id) / relative
        info = archive.gettarinfo(str(source), arcname=arcname.as_posix())
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with source.open("rb") as stream:
            archive.addfile(info, stream)


def write_json_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def create_bundle(contract_path: Path, output: Path) -> dict[str, Any]:
    contract = load_contract(contract_path)
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=output.parent)
    )
    artifacts_dir = staging / "artifacts"
    manifests_dir = staging / "manifests"
    artifacts_dir.mkdir()
    manifests_dir.mkdir()
    bundle_records: list[dict[str, Any]] = []
    missing_optional: list[str] = []
    try:
        for entry in contract["source_roots"]:
            artifact_id = entry["artifact_id"]
            source = Path(entry["path"])
            if not source.exists():
                if entry.get("required") is True:
                    raise FileNotFoundError(f"required source root missing: {source}")
                missing_optional.append(source.as_posix())
                continue
            if not source.is_dir() or source.is_symlink():
                raise ValueError(f"source root must be a real directory: {source}")
            records = inventory_root(source)
            manifest_path = manifests_dir / f"{artifact_id}.files.json"
            write_json_exclusive(
                manifest_path,
                {
                    "artifact_id": artifact_id,
                    "source_path": source.as_posix(),
                    "file_count": len(records),
                    "total_file_bytes": sum(item["size_bytes"] for item in records),
                    "files": records,
                },
            )
            archive_path = artifacts_dir / f"{artifact_id}.tar"
            with tarfile.open(archive_path, mode="x") as archive:
                add_tree(archive, source, artifact_id)
            bundle_records.append(
                {
                    "artifact_id": artifact_id,
                    "source_path": source.as_posix(),
                    "class": entry["class"],
                    "file_count": len(records),
                    "total_file_bytes": sum(item["size_bytes"] for item in records),
                    "manifest": manifest_path.relative_to(staging).as_posix(),
                    "manifest_sha256": sha256_file(manifest_path),
                    "archive": archive_path.relative_to(staging).as_posix(),
                    "archive_size_bytes": archive_path.stat().st_size,
                    "archive_sha256": sha256_file(archive_path),
                }
            )
        bundle = {
            "schema_version": 1,
            "backup_id": contract["backup_id"],
            "source_instance_id": contract["source"]["instance_id"],
            "created_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "contract_sha256": sha256_file(contract_path),
            "artifacts": bundle_records,
            "missing_optional_roots": missing_optional,
            "claim_boundary": contract["claim_boundary"],
        }
        write_json_exclusive(staging / "bundle.json", bundle)
        checksum_targets = sorted(
            path
            for path in staging.rglob("*")
            if path.is_file() and path.name != "BUNDLE.SHA256SUMS"
        )
        with (staging / "BUNDLE.SHA256SUMS").open("x", encoding="utf-8") as stream:
            for target in checksum_targets:
                stream.write(
                    f"{sha256_file(target)}  {target.relative_to(staging).as_posix()}\n"
                )
        os.replace(staging, output)
        return bundle
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/amd-experiment-backup-219-v2.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = create_bundle(args.contract.resolve(), args.output.resolve())
    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
