#!/usr/bin/env python3
"""Stage and hash the Apache-2.0 VLM backbone used by strict-open SmolVLA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


REPO_ID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
REVISION = "7b375e1b73b11138ff12fe22c8f2822d8fe03467"
EXPECTED_LICENSE = "apache-2.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_license(readme: Path) -> str:
    for line in readme.read_text(encoding="utf-8").splitlines()[:40]:
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "license":
            return value.strip().lower()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"),
    )
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import snapshot_download

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=output,
        endpoint=args.endpoint,
    )
    readme = output / "README.md"
    observed_license = _declared_license(readme)
    if observed_license != EXPECTED_LICENSE:
        raise RuntimeError(
            f"checkpoint license must be {EXPECTED_LICENSE}, got {observed_license or 'missing'}"
        )

    files = [
        {
            "path": path.relative_to(output).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and ".cache" not in path.relative_to(output).parts
        and path.name != "OPEN_SOURCE_MANIFEST.json"
    ]
    manifest = {
        "schema_version": 1,
        "repo_id": REPO_ID,
        "revision": REVISION,
        "license": observed_license,
        "endpoint_used_for_transfer": args.endpoint,
        "files": files,
    }
    manifest_path = output / "OPEN_SOURCE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "files": len(files), "license": observed_license}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
