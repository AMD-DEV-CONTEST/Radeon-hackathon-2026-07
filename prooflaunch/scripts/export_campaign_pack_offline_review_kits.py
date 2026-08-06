#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.campaign_pack_blind_review import (
    CampaignPackBlindReviewService,
)
from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle-root",
        default=str(ROOT / "artifacts/campaign-pack-visual-blind-review-v1"),
    )
    parser.add_argument(
        "--reviewer-token-file",
        default=str(ROOT / ".prooflaunch-secrets/blind-review-invitations.json"),
    )
    parser.add_argument(
        "--output-root",
        default=str(ROOT / ".prooflaunch-secrets/campaign-pack-offline-kits"),
    )
    args = parser.parse_args()
    token_file = Path(args.reviewer_token_file).expanduser().resolve(strict=True)
    if token_file.is_symlink() or token_file.stat().st_mode & 0o077:
        raise SystemExit("reviewer token file must be a regular owner-only file")
    raw = json.loads(token_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("reviewer token file must contain a JSON object")
    tokens = {int(slot): str(token) for slot, token in raw.items()}
    if set(tokens) != set(range(1, 6)) or any(
        len(token) < 24 for token in tokens.values()
    ):
        raise SystemExit("exactly five strong reviewer invitation tokens are required")
    output = Path(args.output_root).expanduser().resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.is_symlink():
        raise SystemExit("offline-kit output root cannot be a symlink")
    output.chmod(0o700)
    service = CampaignPackBlindReviewService(
        Path(args.bundle_root).expanduser().resolve(strict=True),
        project_root=ROOT,
        reviewer_tokens=tokens,
    )
    records = []
    for slot in range(1, 6):
        body, digest, filename = service.offline_kit_for_slot(
            slot,
            reviewer_token=tokens[slot],
        )
        path = output / filename
        atomic_write_bytes(path, body)
        path.chmod(0o600)
        records.append(
            {
                "reviewer_slot": slot,
                "filename": filename,
                "bytes": len(body),
                "sha256": digest,
            }
        )
    manifest = {
        "schema": "ProofLaunchCampaignPackOfflineReviewKitExportV1",
        "kit_count": len(records),
        "kits": records,
        "invitation_tokens_persisted_in_kits": False,
        "candidate_identity_exposed": False,
        "automatic_submission_enabled": False,
        "automatic_publish_enabled": False,
        "truth_boundary": (
            "These five token-free kits support independent offline review. "
            "No review has occurred until a qualifying human returns and the "
            "server accepts a digest-bound JSON record."
        ),
    }
    manifest_path = output / "manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest_path.chmod(0o600)
    print(
        json.dumps(
            {
                "output_root": str(output),
                "kit_count": len(records),
                "tokens_persisted_in_kits": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
