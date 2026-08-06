#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_genome_learning_memory import compile_genome_learning_memory


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-genome-learning-memory-v1.json"


def main() -> None:
    # Production starts empty. Test fixtures exercise learning behavior, but
    # synthetic outcomes must never be promoted into production memory.
    payload = compile_genome_learning_memory([])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "record_count": payload["record_count"],
        "human_approval_required": payload["human_approval_required"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
