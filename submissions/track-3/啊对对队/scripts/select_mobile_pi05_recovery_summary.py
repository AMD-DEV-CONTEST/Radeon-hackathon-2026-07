#!/usr/bin/env python3
"""Select verified recovery results for an episode-subset dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episode-id", action="append", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not already exist")

    source = json.loads(args.source.read_text(encoding="utf-8"))
    requested = list(dict.fromkeys(map(str, args.episode_id)))
    if len(requested) != len(args.episode_id):
        parser.error("episode ids must be unique")
    by_id = {
        str(item.get("episode_id")): item for item in source.get("results", ())
    }
    missing = [episode_id for episode_id in requested if episode_id not in by_id]
    if missing:
        parser.error(f"episode ids are absent from the collector summary: {missing}")
    selected = [by_id[episode_id] for episode_id in requested]
    invalid = [
        str(item.get("episode_id"))
        for item in selected
        if not bool(item.get("success"))
        or not bool((item.get("recovery_label") or {}).get("verified_success"))
    ]
    if invalid:
        parser.error(f"subset contains unverified recovery results: {invalid}")

    payload = {
        **source,
        "source_collection_summary": str(args.source.resolve()),
        "source_collection_summary_sha256": _sha256(args.source),
        "requested_episodes": len(selected),
        "completed_episodes": len(selected),
        "successful_episodes": len(selected),
        "results": selected,
        "successful_episode_order": requested,
        "subset_selection": {
            "episode_ids": requested,
            "policy": "predeclared mode-balanced training subset; verified successes only",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "episodes": len(selected),
                "successful_episode_order": requested,
                "source_sha256": payload["source_collection_summary_sha256"],
            },
            indent=2,
        )
    )
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
