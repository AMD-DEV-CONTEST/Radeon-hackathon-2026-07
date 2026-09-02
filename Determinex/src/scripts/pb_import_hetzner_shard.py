#!/usr/bin/env python3
"""Import returned Hetzner ProgramBench eval artifacts into local staging."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESERVATIONS = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_RESERVATIONS.json"


def _load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("shard_dir", help="local path to returned shard directory")
    ap.add_argument("--copy-logs", action="store_true")
    args = ap.parse_args()

    shard = Path(args.shard_dir).resolve()
    manifest = json.loads((shard / "manifest.json").read_text(encoding="utf-8"))
    imported = 0
    missing = []

    for item in manifest["items"]:
        slug = item["slug"]
        local_run = Path(item["run_root"])
        if not local_run.is_absolute():
            local_run = ROOT / local_run
        target = local_run / slug / f"{slug}.eval.json"
        source = shard / "results" / f"{slug}.eval.json"
        if not source.is_file():
            # Fallback: whole returned run tree may contain the eval in place.
            source = shard / item["remote_run_root"] / slug / f"{slug}.eval.json"
        if not source.is_file():
            missing.append(slug)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        imported += 1

    reservations = _load_json(RESERVATIONS, {})
    removed = 0
    for item in manifest["items"]:
        for key in (item.get("slug"), item.get("base_slug")):
            if key and key in reservations:
                reservations.pop(key, None)
                removed += 1
    _write_json(RESERVATIONS, reservations)

    if args.copy_logs and (shard / "logs").is_dir():
        log_dest = ROOT / "logs" / "programbench_factory" / f"hetzner_{shard.name}"
        if log_dest.exists():
            shutil.rmtree(log_dest)
        shutil.copytree(shard / "logs", log_dest)
        print(f"copied logs: {log_dest}")

    print(f"imported={imported}")
    print(f"reservations_removed={removed}")
    if missing:
        print("missing_eval:")
        for slug in missing:
            print(f"  {slug}")
    return 0 if imported else 1


if __name__ == "__main__":
    raise SystemExit(main())
