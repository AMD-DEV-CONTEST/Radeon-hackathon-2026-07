#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_named_product_pk import (  # noqa: E402
    PREPARATION_ATTESTATIONS,
    NamedProductPKError,
    create_preparation,
)


DEFAULT_MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v2/manifest.json"
DEFAULT_LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
DEFAULT_CHALLENGER_ADMISSION = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v3/manifest.json"
DEFAULT_BASELINE_STORE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one named, human-attested anonymization/fidelity receipt before blind pairing."
    )
    parser.add_argument("--capture-slot-id", required=True)
    parser.add_argument("--baseline-review-artifact", required=True, type=_inside_project)
    parser.add_argument("--candidate-review-artifact", required=True, type=_inside_project)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--output", required=True, type=_inside_project)
    parser.add_argument("--capture-manifest", default=str(DEFAULT_MANIFEST), type=_inside_project)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER), type=_inside_project)
    parser.add_argument("--challenger-admission", default=str(DEFAULT_CHALLENGER_ADMISSION), type=_inside_project)
    parser.add_argument("--baseline-store", default=str(DEFAULT_BASELINE_STORE), type=_inside_project)
    for key in PREPARATION_ATTESTATIONS:
        parser.add_argument(f"--attest-{key.replace('_', '-')}", action="store_true", required=True)
    args = parser.parse_args()
    attestations = {
        key: bool(getattr(args, f"attest_{key}"))
        for key in PREPARATION_ATTESTATIONS
    }
    try:
        prep = create_preparation(
            project_root=ROOT,
            capture_manifest_path=args.capture_manifest,
            ledger_path=args.ledger,
            challenger_admission_path=args.challenger_admission,
            baseline_store_root=args.baseline_store,
            capture_slot_id=args.capture_slot_id,
            baseline_review_path=args.baseline_review_artifact,
            candidate_review_path=args.candidate_review_artifact,
            operator_id=args.operator_id,
            prepared_at=datetime.now(timezone.utc).isoformat(),
            attestations=attestations,
        )
    except NamedProductPKError as error:
        parser.error(str(error))
    atomic_write_text(args.output, json.dumps(prep, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    args.output.chmod(0o600)
    print(json.dumps({"output": str(args.output), "content_sha256": prep["content_sha256"], "automatic_pairing_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
