#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_content_scheduling_named_pk import compile_schedule, verify_schedule


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a content-scheduling named-product challenger.")
    parser.add_argument("--config", type=Path, default=ROOT / "config/codex-content-scheduling-named-pk-super-challenger-v1.json")
    parser.add_argument("--text-portfolio", type=Path, default=ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json")
    args = parser.parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    text = json.loads(args.text_portfolio.resolve().read_text(encoding="utf-8"))
    source_paths = {str(row["source_asset"]).split("#", 1)[0] for row in config["slots"]}
    source_artifact_sha256_by_path = {}
    for source_path in source_paths:
        target = ROOT / source_path
        if not target.is_file():
            raise SystemExit(f"content schedule source is missing: {source_path}")
        source_artifact_sha256_by_path[source_path] = sha256_file(target)
    payload = compile_schedule(
        config,
        source_candidate_sha256=text["candidate"]["content_sha256"],
        source_artifact_sha256_by_path=source_artifact_sha256_by_path,
    )
    verify_schedule(payload)
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "slot_count": 7, "named_product_target_count": 10, "completed_named_product_pk_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
