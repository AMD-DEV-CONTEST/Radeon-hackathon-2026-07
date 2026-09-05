#!/usr/bin/env python3
"""Fail closed unless a local model snapshot matches its frozen manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: pathlib.Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0":
        raise ValueError("unsupported or missing manifest schema_version")
    for key in ("model_id", "served_model_name", "expected_directory_name", "license"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"manifest {key} must be a non-empty string")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("manifest source must be an object")
    for key in ("provider", "repository", "revision"):
        if not isinstance(source.get(key), str) or not source[key]:
            raise ValueError(f"manifest source.{key} must be a non-empty string")
    if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
        raise ValueError("manifest source.revision must be a full 40-character commit")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest files must be a non-empty list")
    return manifest


def validate_entry(entry: Any) -> tuple[pathlib.PurePosixPath, int, str]:
    if not isinstance(entry, dict):
        raise ValueError("every manifest file entry must be an object")
    raw_path = entry.get("path")
    size = entry.get("size")
    digest = entry.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("file path must be a non-empty string")
    path = pathlib.PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe manifest path: {raw_path!r}")
    if not isinstance(size, int) or size < 0:
        raise ValueError(f"invalid size for {raw_path!r}")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError(f"invalid SHA-256 for {raw_path!r}")
    return path, size, digest


def verify_snapshot(
    manifest: dict[str, Any], model_dir: pathlib.Path, *, quick: bool = False
) -> list[str]:
    findings: list[str] = []
    seen: set[pathlib.PurePosixPath] = set()
    resolved_root = model_dir.resolve()
    if model_dir.name != manifest["expected_directory_name"]:
        findings.append(
            "model directory name mismatch: "
            f"expected={manifest['expected_directory_name']} actual={model_dir.name}"
        )
    for raw_entry in manifest["files"]:
        try:
            relative, expected_size, expected_digest = validate_entry(raw_entry)
        except ValueError as exc:
            findings.append(str(exc))
            continue
        if relative in seen:
            findings.append(f"duplicate manifest path: {relative}")
            continue
        seen.add(relative)
        candidate = model_dir.joinpath(*relative.parts)
        if candidate.is_symlink():
            findings.append(f"manifest file must not be a symlink: {relative}")
            continue
        try:
            candidate.resolve().relative_to(resolved_root)
        except ValueError:
            findings.append(f"file escapes model directory through a symlink: {relative}")
            continue
        if not candidate.is_file():
            findings.append(f"missing file: {relative}")
            continue
        actual_size = candidate.stat().st_size
        if actual_size != expected_size:
            findings.append(
                f"size mismatch: {relative} expected={expected_size} actual={actual_size}"
            )
            continue
        if not quick:
            actual_digest = sha256_file(candidate)
            if actual_digest != expected_digest:
                findings.append(
                    f"sha256 mismatch: {relative} expected={expected_digest} actual={actual_digest}"
                )
    actual_files: set[pathlib.PurePosixPath] = set()
    for candidate in model_dir.rglob("*"):
        relative = pathlib.PurePosixPath(candidate.relative_to(model_dir).as_posix())
        if candidate.is_symlink():
            if relative not in seen:
                findings.append(f"undeclared symlink: {relative}")
            continue
        if candidate.is_file():
            actual_files.add(relative)
    for extra in sorted(actual_files - seen, key=str):
        findings.append(f"undeclared file: {extra}")
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--model-dir", required=True, type=pathlib.Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--quick",
        action="store_true",
        help="Check manifest structure and file sizes only; never use as final evidence.",
    )
    mode.add_argument(
        "--full-sha256",
        action="store_true",
        help="Hash every declared file (the default and required final-evidence mode).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"MODEL_SNAPSHOT_INVALID: {exc}", file=sys.stderr)
        return 2

    if not args.model_dir.is_dir():
        print(
            f"MODEL_SNAPSHOT_INVALID: model directory not found: {args.model_dir}",
            file=sys.stderr,
        )
        return 2

    findings = verify_snapshot(manifest, args.model_dir, quick=args.quick)
    if findings:
        print("MODEL_SNAPSHOT_INVALID", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    mode = "SIZE_ONLY" if args.quick else "FULL_SHA256"
    print(
        "MODEL_SNAPSHOT_OK "
        f"mode={mode} model={manifest.get('model_id')} "
        f"revision={manifest.get('source', {}).get('revision')} "
        f"files={len(manifest['files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
