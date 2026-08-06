#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.gtm_local_judge_queue import seal_local_judge_queue
from prooflaunch_remix.inference_gateway import OllamaLocalClient, OllamaLocalSpec


def _inside_project(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a real localhost-model, empty-human-label governance Judge queue."
    )
    parser.add_argument(
        "--lifecycle-matrix",
        type=_inside_project,
        default=ROOT / "evidence/v10/gtm-lifecycle-closure-matrix-v1.json",
    )
    parser.add_argument(
        "--model-receipt",
        type=_inside_project,
        default=ROOT / "artifacts/local-gtm-generative-baseline-v1/receipt.json",
    )
    parser.add_argument(
        "--private-source-root",
        type=_inside_project,
        default=ROOT / ".prooflaunch-runtime/judge-calibration-source",
    )
    parser.add_argument(
        "--bundle-root",
        type=_inside_project,
        default=ROOT / ".prooflaunch-runtime/judge-calibration",
    )
    parser.add_argument(
        "--status-output",
        type=_inside_project,
        default=ROOT / "evidence/v10/local-judge-calibration-queue-status.json",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 300:
        raise SystemExit("--timeout-seconds must be in [1, 300]")
    seed = os.environ.get("PROOFLAUNCH_JUDGE_CALIBRATION_SEED", "").strip()
    seed_source = "environment"
    if not seed:
        # The frozen bundle persists the assignments and only the seed digest. A
        # cryptographically strong ephemeral seed therefore avoids exposing an
        # assignment secret in shell history without weakening the review packet.
        seed = secrets.token_urlsafe(48)
        seed_source = "ephemeral_generated_not_persisted"
    if len(seed) < 16:
        raise SystemExit(
            "PROOFLAUNCH_JUDGE_CALIBRATION_SEED must contain at least 16 characters"
        )
    receipt = json.loads(args.model_receipt.read_text(encoding="utf-8"))
    model = receipt.get("model")
    if not isinstance(model, dict):
        raise SystemExit("model receipt is invalid")
    name = str(model.get("name", ""))
    digest = str(model.get("digest", ""))
    client = OllamaLocalClient(OllamaLocalSpec(name, digest))
    status = seal_local_judge_queue(
        lifecycle_matrix_path=args.lifecycle_matrix,
        model_name=name,
        model_digest=digest,
        client=client,
        private_source_root=args.private_source_root,
        bundle_root=args.bundle_root,
        status_path=args.status_output,
        assignment_seed=seed,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "status_output": str(args.status_output),
                "content_sha256": status["content_sha256"],
                "observed_model_call_count": status["observed_model_call_count"],
                "expected_human_label_count": status["expected_human_label_count"],
                "real_human_label_count": status["real_human_label_count"],
                "judge_calibrated": status["judge_calibrated"],
                "assignment_seed_source": seed_source,
                "raw_assignment_seed_persisted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
