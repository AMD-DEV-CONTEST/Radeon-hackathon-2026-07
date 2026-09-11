from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from parcel_sorter.failure_analysis import analyze_expert_summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attribute expert failures from a completed trace-rich summary"
    )
    parser.add_argument("--summary", required=True, help="path to expert/summary.json")
    parser.add_argument("--output", required=True, help="path for aggregated analysis JSON")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source = Path(args.summary)
    output = Path(args.output)
    if not source.is_file():
        parser.error(f"summary does not exist: {source}")
    if output.exists() and not args.overwrite:
        parser.error(f"output already exists: {output}; pass --overwrite to replace it")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        analysis = analyze_expert_summary(payload)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    analysis["source"] = {
        "path": str(source),
        "sha256": _sha256(source),
        "size_bytes": source.stat().st_size,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "global": analysis["global"],
                "diagnostic_priority": analysis["diagnostic_priority"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
