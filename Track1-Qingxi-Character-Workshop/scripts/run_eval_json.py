from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm_role import generate_character
from src.world import load_world


def main() -> int:
    world = load_world()
    path = ROOT / "data" / "eval" / "cases.jsonl"
    ok = fail = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        try:
            card = generate_character(
                case["user_text"],
                affinity_pref=case.get("expect_affinity"),
                mock=True,
            )
            assert card.primary_affinity in world.affinity_names()
            assert card.image_prompt
            ok += 1
            print("OK", case["id"], card.name, card.primary_affinity)
        except Exception as e:
            fail += 1
            print("FAIL", case["id"], e)
    print(f"summary ok={ok} fail={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
