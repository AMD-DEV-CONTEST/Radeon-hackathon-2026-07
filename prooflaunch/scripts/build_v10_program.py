#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_program import CortexProgram, canonical_source_text


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the exact Cortex-X V10 1500-item evidence program"
    )
    parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="ordered V9 0001-1200 and V10 1201-1500 source documents",
    )
    parser.add_argument(
        "--canonical-output",
        type=Path,
        default=ROOT / "docs" / "CORTEX_X_V10_1500_TODO.md",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=ROOT / "evidence" / "v10" / "program-manifest.json",
    )
    args = parser.parse_args()

    source_texts = [path.read_text(encoding="utf-8") for path in args.sources]
    program = CortexProgram.parse(source_texts)
    canonical = canonical_source_text(source_texts)
    args.canonical_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.canonical_output, canonical)
    program.write(args.manifest_output)
    print(
        json.dumps(
            {
                "schema": program.schema,
                "todo_count": len(program.todos),
                "summary": program.summary,
                "canonical_output": str(args.canonical_output),
                "manifest_output": str(args.manifest_output),
                "source_sha256": program.source_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
