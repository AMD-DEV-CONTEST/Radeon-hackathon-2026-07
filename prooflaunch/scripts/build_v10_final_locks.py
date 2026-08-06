#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_final_lock import LOCK_PATH, build_lock_bundle, verify_lock_bundle


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = ROOT / LOCK_PATH
    bundle = build_lock_bundle(ROOT)
    atomic_write_text(output, json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    errors = verify_lock_bundle(ROOT, json.loads(output.read_text(encoding="utf-8")))
    if errors:
        raise SystemExit(f"final lock verification failed: {errors}")
    print(json.dumps({"output": str(output), "sha256": sha256_file(output), "content_sha256": bundle["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
