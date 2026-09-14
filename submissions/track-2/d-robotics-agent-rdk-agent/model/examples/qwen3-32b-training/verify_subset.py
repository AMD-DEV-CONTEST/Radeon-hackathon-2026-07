#!/usr/bin/env python3
"""Verify the compact judge-facing training snapshot with the standard library."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    listed = {"source-manifest.json"}
    kinds: dict[str, int] = {}

    for entry in manifest["files"]:
        rel = entry["file"]
        path = ROOT / rel
        listed.add(rel)
        kind = entry["kind"]
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind not in {"frozen", "authored"}:
            errors.append(f"unknown file kind {kind!r}: {rel}")
        elif not path.is_file():
            errors.append(f"missing file: {rel}")
        elif sha256(path) != entry["sha256"]:
            errors.append(f"SHA-256 mismatch: {rel}")

    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(ROOT))
            if rel not in listed and not rel.endswith(".DS_Store"):
                errors.append(f"unlisted stray file: {rel}")

    release = manifest["data_release"]
    release_root = (ROOT / release["path"]).resolve()
    for entry in release["files"]:
        path = release_root / entry["file"]
        if not path.is_file():
            errors.append(f"missing release file: {entry['file']}")
            continue
        if sha256(path) != entry["sha256"]:
            errors.append(f"release SHA-256 mismatch: {entry['file']}")
        rows = sum(1 for line in path.open("rb") if line.strip())
        if rows != entry["rows"]:
            errors.append(f"release row-count mismatch: {entry['file']} ({rows} != {entry['rows']})")

    report = {
        "schema_version": "qwen3_training_subset_verification.v2",
        "valid": not errors,
        "files_checked": len(manifest["files"]),
        "kinds": kinds,
        "release_files_checked": len(release["files"]),
        "archive_tag": manifest["full_evidence_archive"]["git_tag"],
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
