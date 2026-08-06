#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_one_hour_final_plan import (  # noqa: E402
    compile_one_hour_final_plan,
    load_one_hour_snapshot,
    render_one_hour_html,
    render_one_hour_markdown,
)


EVIDENCE = ROOT / "evidence/v10/gtm-one-hour-final-execution-contract-v1.json"
DOCUMENT = ROOT / "docs/product/GTM_ONE_HOUR_FINAL_EXECUTION_PLAN_2026-08-06.md"
WAR_ROOM = ROOT / "artifacts/gtm-one-hour-final-war-room-v1/index.html"


def main() -> int:
    plan = compile_one_hour_final_plan(load_one_hour_snapshot(ROOT))
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    DOCUMENT.parent.mkdir(parents=True, exist_ok=True)
    WAR_ROOM.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(EVIDENCE, json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(DOCUMENT, render_one_hour_markdown(plan))
    atomic_write_text(WAR_ROOM, render_one_hour_html(plan))
    print(
        json.dumps(
            {
                "schema": plan["schema"],
                "content_sha256": plan["content_sha256"],
                "launch_label": plan["decision"]["launch_label"],
                "document": str(DOCUMENT),
                "war_room": str(WAR_ROOM),
                "evidence": str(EVIDENCE),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
