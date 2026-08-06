from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.v10_todo_evidence import (  # noqa: E402
    apply_verified_todo_closures,
)


def main() -> int:
    report = apply_verified_todo_closures(ROOT)
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "closed_count": report["closed_count"],
                "status_counts": report["status_counts"],
                "program_manifest_sha256": report[
                    "program_manifest_sha256"
                ],
                "content_sha256": report["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
