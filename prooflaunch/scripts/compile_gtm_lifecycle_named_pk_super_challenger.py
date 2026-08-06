#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_lifecycle_named_pk import compile_lifecycle, verify_lifecycle


ROOT = Path(__file__).resolve().parents[1]


def _binding(role: str, relative: str) -> dict[str, object]:
    path = ROOT / relative
    return {"role": role, "path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a GTM-lifecycle named-product challenger.")
    parser.add_argument("--config", type=Path, default=ROOT / "config/codex-gtm-lifecycle-named-pk-super-challenger-v1.json")
    parser.add_argument("--strategy", default="artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/creative-brief.json")
    parser.add_argument("--text-assets", default="artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/source-hidden-review-dossier.html")
    parser.add_argument("--content-schedule", default="artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json")
    parser.add_argument("--response-loop", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-lifecycle-super-challenger-v1/gtm-lifecycle-execution-dossier.json")
    args = parser.parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    bindings = [
        _binding("strategy_and_creative", args.strategy),
        _binding("text_assets", args.text_assets),
        _binding("content_schedule", args.content_schedule),
    ]
    if args.response_loop:
        bindings.append(_binding("response_learning_contract", args.response_loop))
    payload = compile_lifecycle(config, bindings=bindings)
    verify_lifecycle(payload)
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "node_count": 10, "team_cell_count": len(payload["team_cells"]), "named_product_target_count": 10, "completed_named_product_pk_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
