#!/usr/bin/env python3
"""Remove per-frame traces while preserving an auditable expert summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_payload(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    episodes = []
    for episode in payload.get("episodes", []):
        episodes.append(
            {
                "episode_index": episode.get("episode_index"),
                "result": episode.get("result"),
                "terminal_stage": episode.get("terminal_stage"),
                "sample": episode.get("sample"),
                "safety_summary": episode.get("safety_summary", {}),
            }
        )
    return {
        "runtime": payload.get("runtime"),
        "evaluation_range": payload.get("evaluation_range"),
        "config": payload.get("config"),
        "summary": payload.get("summary"),
        "profile_summaries": payload.get("profile_summaries"),
        "episodes": episodes,
        "source_summary": {
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
            "trace_omitted": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not args.summary.is_file():
        parser.error(f"summary does not exist: {args.summary}")
    if args.output.exists() and not args.overwrite:
        parser.error(f"output already exists: {args.output}; pass --overwrite")
    try:
        payload = json.loads(args.summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not isinstance(payload, dict) or not isinstance(payload.get("episodes"), list):
        parser.error("summary must be an object containing an episodes list")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(compact_payload(payload, args.summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output": str(args.output), "episodes": len(payload["episodes"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
