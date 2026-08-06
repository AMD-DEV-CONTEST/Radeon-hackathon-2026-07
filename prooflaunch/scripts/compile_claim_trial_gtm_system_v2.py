#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-gtm-system-v2"
FILES = ("index.html", "system.css", "mobile-fixes.css", "platform-copy.json", "comment-loop.json", "video-15s.json", "measurement.json")
BINDINGS = (
    ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen-image-v2/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/40-asset-campaign-board-v1/board-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v2/receipt.json",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main() -> None:
    paths = [OUTPUT / name for name in FILES]
    for path in (*paths, *BINDINGS):
        if not path.is_file():
            raise SystemExit(f"missing GTM system dependency: {path}")
    copy = json.loads((OUTPUT / "platform-copy.json").read_text(encoding="utf-8"))
    loop = json.loads((OUTPUT / "comment-loop.json").read_text(encoding="utf-8"))
    video = json.loads((OUTPUT / "video-15s.json").read_text(encoding="utf-8"))
    measurement = json.loads((OUTPUT / "measurement.json").read_text(encoding="utf-8"))
    if len(loop["verdicts"]) != 5 or len(video["scenes"]) != 6 or len(measurement["decision_chain"]) != 5:
        raise SystemExit("last-mile campaign system coverage drifted")
    if video["render_status"] != "rendered_local_4k_master":
        raise SystemExit("GTM system does not bind the rendered 4K master")
    if copy["launch_post"]["publish_status"] != "human_approval_required":
        raise SystemExit("launch post escaped human approval")
    if any((copy["external_publish_executed"], loop["external_reply_executed"], video["external_publish_executed"])):
        raise SystemExit("campaign system falsely records an external action")
    receipt = {
        "schema": "ProofLaunchClaimTrialGTMSystemReceiptV2",
        "artifact_id": "claim-trial-gtm-system-v2",
        "campaign_nucleus_count": 1,
        "last_mile_job_count": 6,
        "last_mile_jobs": ["organic_post", "key_visual", "vertical_video", "comment_diagnosis", "conversion_handoff", "measurement_loop"],
        "verified_platform_candidate_count": 26,
        "comment_verdict_count": len(loop["verdicts"]),
        "video_scene_count": len(video["scenes"]),
        "video_render_status": video["render_status"],
        "measurement_stage_count": len(measurement["decision_chain"]),
        "human_approval_required": True,
        "external_action_count": 0,
        "human_review_count": 0,
        "named_product_win_count": 0,
        "files": [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in paths],
        "source_bindings": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)} for path in BINDINGS],
        "truth_boundary": "This receipt binds one integrated GTM campaign system and its current image PK packet. It proves no publication, human preference, organic breakout, conversion, revenue, 4A quality or named-product superiority.",
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
