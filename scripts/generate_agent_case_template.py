"""Generate raw Agent input templates; never writes execution outcomes."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "datasets" / "templates" / "agent_eval_cases.template.jsonl"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(1, 101):
            inspection = index % 4 == 0
            case = {
                "case_id": f"agent-{index:03d}",
                "input": (
                    f"确认检查第 {index} 张本地施工图片"
                    if inspection
                    else f"记录第 {index} 项本地巡检任务"
                ),
                "expected_tools": ["inspect_image" if inspection else "echo"],
                "expected_order": ["inspect_image" if inspection else "echo"],
                "expected_arguments": [],
                "expected_confirmation": inspection,
                "expected_outcome": "completed",
                "follow_up_inputs": [],
            }
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
