from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from privateops.submission_evidence import build_submission_evidence, render_submission_csv


def main() -> None:
    payload = build_submission_evidence(ROOT)
    submission = ROOT / "submission"
    (submission / "benchmark-evidence.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (submission / "benchmark-evidence.csv").write_text(
        render_submission_csv(payload),
        encoding="utf-8",
    )
    print(f"Synchronized {len(payload['runs'])} verified Radeon run.")


if __name__ == "__main__":
    main()
