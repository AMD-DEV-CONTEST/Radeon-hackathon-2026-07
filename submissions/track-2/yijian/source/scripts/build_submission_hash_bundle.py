#!/usr/bin/env python3
"""Create the immutable SHA-256 index for public YIJIAN submission evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build(root: Path, output: Path) -> dict[str, object]:
    root = root.resolve()
    output = output.resolve()
    evidence = root / "evidence"
    status = root / "submission-status.json"
    if not evidence.is_dir() or not status.is_file():
        raise ValueError("submission root must contain evidence/ and submission-status.json")
    files = [status, *sorted(path for path in evidence.rglob("*") if path.is_file() and path.resolve() != output)]
    records = {
        path.relative_to(root).as_posix(): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in files
    }
    core: dict[str, object] = {
        "schemaVersion": "yijian-submission-hash-bundle-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "root": "submissions/track-2/yijian",
        "files": records,
    }
    return {**core, "bundleSha256": canonical_hash(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.root, args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"files": len(value["files"]), "bundleSha256": value["bundleSha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
