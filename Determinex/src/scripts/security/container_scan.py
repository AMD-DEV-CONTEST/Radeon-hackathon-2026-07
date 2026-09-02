"""Container image inventory scanner.

This records local Docker images and flags unpinned tags. It does not perform a
CVE scan by itself; attach Trivy/Grype later if present.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "assurance" / "security" / "container_scan.json"


def scan() -> dict:
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except Exception as exc:
        return {
            "schema_version": "determinex-container-scan-v1",
            "scanner": "docker",
            "error": str(exc),
            "images": [],
        }

    images = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        tag = row.get("Tag") or ""
        repo = row.get("Repository") or ""
        images.append(
            {
                "repository": repo,
                "tag": tag,
                "id": row.get("ID"),
                "size": row.get("Size"),
                # CreatedAt (absolute), not CreatedSince ("6 days ago"). A relative
                # time is unresolvable once persisted -- this artifact carries no
                # generation timestamp, so "6 days ago" had no reference point at all --
                # and it rewrote the file on every run even when nothing changed, which
                # trains people to ignore diffs in a security artifact. Docker's
                # `{{json .}}` already returns both fields; this only ever picked the
                # wrong one. Fixed 2026-07-28.
                "created_at": row.get("CreatedAt"),
                "unpinned": tag in {"latest", "<none>", ""},
            }
        )
    return {
        "schema_version": "determinex-container-scan-v1",
        "scanner": "docker",
        "image_count": len(images),
        "unpinned_count": sum(1 for image in images if image["unpinned"]),
        "images": images,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = scan()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.out)
    print(
        json.dumps(
            {
                "image_count": report.get("image_count", 0),
                "unpinned_count": report.get("unpinned_count", 0),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
