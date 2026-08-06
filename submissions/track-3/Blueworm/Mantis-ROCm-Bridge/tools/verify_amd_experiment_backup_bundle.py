#!/usr/bin/env python3
"""Independently verify an AMD experiment backup bundle after transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    manifest = root / "BUNDLE.SHA256SUMS"
    bundle_path = root / "bundle.json"
    if not manifest.is_file() or not bundle_path.is_file():
        raise ValueError("bundle.json and BUNDLE.SHA256SUMS are required")
    expected_manifest: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or relative in expected_manifest:
            errors.append(f"invalid checksum line:{line}")
            continue
        expected_manifest[relative] = digest
        target = root / relative
        if not target.is_file():
            errors.append(f"missing:{relative}")
        elif sha256_file(target) != digest:
            errors.append(f"sha256_mismatch:{relative}")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    artifact_results: list[dict[str, Any]] = []
    for artifact in bundle.get("artifacts", []):
        archive_relative = artifact["archive"]
        files_relative = artifact["manifest"]
        archive = root / archive_relative
        files_manifest = root / files_relative
        artifact_errors: list[str] = []
        if sha256_file(archive) != artifact["archive_sha256"]:
            artifact_errors.append("archive_sha256_mismatch")
        if sha256_file(files_manifest) != artifact["manifest_sha256"]:
            artifact_errors.append("file_manifest_sha256_mismatch")
        expected_files = json.loads(files_manifest.read_text(encoding="utf-8"))
        expected_by_path = {
            entry["path"]: entry for entry in expected_files.get("files", [])
        }
        observed: set[str] = set()
        with tarfile.open(archive, mode="r:") as package:
            for member in package:
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    artifact_errors.append(f"unsafe_member:{member.name}")
                    continue
                if member.issym() or member.islnk():
                    artifact_errors.append(f"link_member:{member.name}")
                    continue
                if member.isdir():
                    continue
                if not member.isfile():
                    artifact_errors.append(f"special_member:{member.name}")
                    continue
                if not member_path.parts or member_path.parts[0] != artifact["artifact_id"]:
                    artifact_errors.append(f"wrong_archive_root:{member.name}")
                    continue
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                expected = expected_by_path.get(relative)
                if expected is None:
                    artifact_errors.append(f"unexpected_file:{relative}")
                    continue
                extracted = package.extractfile(member)
                if extracted is None:
                    artifact_errors.append(f"unreadable_file:{relative}")
                    continue
                digest = hashlib.sha256()
                size = 0
                while chunk := extracted.read(8 * 1024 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
                if size != expected["size_bytes"]:
                    artifact_errors.append(f"size_mismatch:{relative}")
                if digest.hexdigest() != expected["sha256"]:
                    artifact_errors.append(f"content_sha256_mismatch:{relative}")
                observed.add(relative)
        for missing in sorted(set(expected_by_path) - observed):
            artifact_errors.append(f"archive_missing_file:{missing}")
        artifact_results.append(
            {
                "artifact_id": artifact["artifact_id"],
                "verified_file_count": len(observed),
                "errors": artifact_errors,
                "pass": not artifact_errors,
            }
        )
        errors.extend(
            f"{artifact['artifact_id']}:{error}" for error in artifact_errors
        )
    return {
        "schema_version": 1,
        "bundle_root": root.as_posix(),
        "bundle_sha256_entry_count": len(expected_manifest),
        "artifacts": artifact_results,
        "errors": errors,
        "pass": not errors,
        "claim_boundary": bundle.get("claim_boundary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = verify_bundle(args.bundle.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.receipt is not None:
        args.receipt.write_text(rendered, encoding="utf-8")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
