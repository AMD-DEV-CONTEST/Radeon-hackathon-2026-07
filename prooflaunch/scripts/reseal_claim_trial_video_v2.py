#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from scripts.render_gtm_three_beat_video_challenger import _seal


OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v2"
RECEIPT = OUTPUT / "receipt.json"
PLAN = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-gtm-system-v2/video-15s.json"
CAPTIONS = OUTPUT / "prooflaunch-performance-review.vtt"


def main() -> None:
    for path in (RECEIPT, PLAN, CAPTIONS):
        if not path.is_file():
            raise SystemExit(f"missing video reseal dependency: {path}")
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    payload.pop("content_sha256", None)
    payload["video_plan_sha256"] = sha256_file(PLAN)
    payload["captions"] = {
        "path": CAPTIONS.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(CAPTIONS),
        "language": "en",
    }
    sealed = _seal(payload)
    atomic_write_text(RECEIPT, json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(RECEIPT), "content_sha256": sealed["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
