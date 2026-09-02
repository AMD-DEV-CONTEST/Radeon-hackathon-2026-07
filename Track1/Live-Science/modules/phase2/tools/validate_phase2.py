#!/usr/bin/env python3
"""Validate the generic Phase 2 handoff contract."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    pass


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValidationError(f"missing or empty file: {path}")


def probe_image(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams or not streams[0].get("width") or not streams[0].get("height"):
        raise ValidationError(f"not a readable image: {path}")
    return streams[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    run_dir, source_run = args.run_dir.resolve(), args.source_run.resolve()
    manifest_path = run_dir / "selected_anchors.json"
    for path in (manifest_path, run_dir / "world_reference.png", run_dir / "contact_sheet.png", run_dir / "report.md"):
        require_file(path)
    source_manifest_path = source_run / "bridge/manifest.json"
    require_file(source_manifest_path)
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    route = source_manifest.get("route")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    anchors = data.get("anchors")
    minimum = 1 if route == "hybrid" else 2
    if not isinstance(anchors, list) or not minimum <= len(anchors) <= 5:
        raise ValidationError(f"selected_anchors.json must contain {minimum}-5 anchors for route={route}")
    ids: list[str] = []
    times: list[float] = []
    dimensions: list[dict[str, Any]] = []
    for item in anchors:
        anchor_id = item.get("id")
        if not isinstance(anchor_id, str) or not anchor_id or "/" in anchor_id or ".." in anchor_id:
            raise ValidationError(f"invalid anchor id: {anchor_id!r}")
        if anchor_id in ids:
            raise ValidationError(f"duplicate anchor id: {anchor_id}")
        ids.append(anchor_id)
        try:
            times.append(float(item["time"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError(f"anchor {anchor_id} has invalid time") from error
        anchor_dir = run_dir / "anchors" / anchor_id
        for name in ("input_clean.png", "prompt.txt", "realistic.png"):
            require_file(anchor_dir / name)
        dimensions.append(probe_image(anchor_dir / "realistic.png"))
    if times != sorted(times):
        raise ValidationError("anchors are not in chronological order")
    probe_image(run_dir / "world_reference.png")
    probe_image(run_dir / "contact_sheet.png")
    result = {"status": "passed", "route": route, "anchorCount": len(ids), "anchors": ids, "realisticDimensions": dimensions}
    if not args.check_only:
        (run_dir / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Phase 2 validation passed: {len(ids)} anchors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
