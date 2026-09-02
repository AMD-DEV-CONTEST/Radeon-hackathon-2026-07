#!/usr/bin/env python3
"""Export public intelligence metadata without protected model bodies."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "signalforge/mission-control-evidence/v1"
FORBIDDEN_KEYS = {
    "question",
    "messages",
    "raw_output",
    "prompt",
    "response",
    "authorization",
    "api_key",
    "password",
    "secret",
}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_public(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"protected field {path}.{key} cannot enter public evidence")
            validate_public(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_public(child, f"{path}[{index}]")


def collect(audit_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    files: list[dict[str, str]] = []
    if not audit_dir.exists():
        return records, files
    for path in sorted(audit_dir.glob("*.metadata.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        validate_public(value)
        payload = canonical_json(value)
        records.append(value)
        files.append({"name": path.name, "sha256": hashlib.sha256(payload).hexdigest()})
    return records, files


def add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(payload))


def export(audit_dir: Path, output: Path) -> dict[str, Any]:
    records, files = collect(audit_dir)
    manifest = {
        "schema_version": SCHEMA,
        "record_count": len(records),
        "files": files,
        "privacy": {
            "protected_bodies_included": False,
            "source": "public intelligence metadata only",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", compresslevel=9) as archive:
        add_bytes(archive, "manifest.json", canonical_json(manifest))
        for record in records:
            name = f"records/{record['run_id']}.metadata.json"
            add_bytes(archive, name, canonical_json(record))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=ROOT / ".signalforge" / "intelligence-audit",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export(args.audit_dir, args.output)
    print(f"exported {manifest['record_count']} public intelligence records to {args.output}")


if __name__ == "__main__":
    main()
