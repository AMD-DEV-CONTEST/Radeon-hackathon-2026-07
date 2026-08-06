from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.v10_breakthrough_matrix import (  # noqa: E402
    write_breakthrough_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="evidence/v10/breakthrough-matrix.json",
    )
    args = parser.parse_args()
    payload = write_breakthrough_matrix(ROOT, args.output)
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "content_sha256": payload["content_sha256"],
                "summary": payload["summary"],
                "output": args.output,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
