#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_creative_alpha_flightbook import compile_flightbook, verify


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/codex-creative-alpha-flightbook-v1.json"
B2B = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
B2C = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json"
KERNEL = ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/creative-alpha-flightbook-v1/creative-alpha-flightbook.json"


def main() -> None:
    inputs = [CONFIG, B2B, B2C, KERNEL]
    source_bindings = [
        {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in inputs
    ]
    payload = compile_flightbook(
        json.loads(CONFIG.read_text(encoding="utf-8")),
        b2b_receipt=json.loads(B2B.read_text(encoding="utf-8")),
        b2c_receipt=json.loads(B2C.read_text(encoding="utf-8")),
        human_kernel=json.loads(KERNEL.read_text(encoding="utf-8")),
        source_bindings=source_bindings,
    )
    verify(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "candidate_count": payload["candidate_count"],
        "surface_count_per_case": payload["surface_count_per_case"],
        "role_count": payload["team_operating_system"]["role_count"],
        "skill_count": payload["team_operating_system"]["professional_skill_card_count"],
        "edge_play_count": len(payload["unconventional_edge_play_cards"]),
        "completed_named_product_pk_count": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
