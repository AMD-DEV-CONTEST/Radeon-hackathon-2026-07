#!/usr/bin/env python3
"""Verify a private local LoRA archive against its frozen cross-platform tree hash."""

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
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    files = (value for value in path.rglob("*") if value.is_file())
    for item in sorted(files, key=lambda value: value.relative_to(path).as_posix().encode("utf-8")):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def verify(release: Path) -> dict[str, object]:
    manifest_path = release / "adapter-freeze-manifest.json"
    adapter = release / "adapter"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = tree_hash(adapter)
    expected = manifest.get("adapterTreeSha256")
    files = [path for path in adapter.rglob("*") if path.is_file()]
    return {
        "schemaVersion": "yijian-local-adapter-archive-verification-v1",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "passed": actual == expected,
        "adapterTreeSha256": actual,
        "freezeManifestSha256": sha256_file(manifest_path),
        "adapterModelSha256": sha256_file(adapter / "adapter_model.safetensors"),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "locationPolicy": "private local archive; path intentionally omitted from public evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.release.resolve())
    if not value["passed"]:
        raise SystemExit("local adapter archive does not match the frozen tree hash")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
