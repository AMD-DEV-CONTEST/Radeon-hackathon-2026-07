#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_generation_quality import (  # noqa: E402
    compile_platform_generation_quality_audit,
)
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    CREATIVE_FIELDS,
    EXPECTED_SURFACE_COUNT,
    canonical_json,
    compile_platform_native_receipt,
    verify_platform_native_challenger_plan,
)


GOLD_SCHEMA = "ProofLaunchPlatformNativeGoldReferenceV1"
OVERLAY_SCHEMA = "ProofLaunchPlatformNativeCodexOverlayV1"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile an original clean-room platform reference into sealed pre-human quality evidence."
    )
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--reference", required=True, type=_inside_project)
    parser.add_argument(
        "--overlay",
        type=_inside_project,
        help="Optional digest-bound Codex clean-room capability overlay.",
    )
    parser.add_argument(
        "--capability-reference-only",
        action="store_true",
        help=(
            "Evaluate the frozen synthetic B2C benchmark as a capability reference "
            "while preserving its permanent publication block."
        ),
    )
    parser.add_argument("--receipt-output", required=True, type=_inside_project)
    parser.add_argument("--audit-output", required=True, type=_inside_project)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    reference_bytes = args.reference.read_bytes()
    reference = json.loads(reference_bytes)
    base_reference_sha256 = hashlib.sha256(reference_bytes).hexdigest()
    overlay_sha256: str | None = None
    overlay_surfaces: set[str] = set()
    verify_platform_native_challenger_plan(plan)
    if reference.get("schema") != GOLD_SCHEMA:
        raise SystemExit("gold reference schema is invalid")
    if (
        reference.get("brief_id") != plan["brief"]["brief_id"]
        or reference.get("business_model") != plan["business_model"]
    ):
        raise SystemExit("gold reference escaped the plan brief")
    for field in (
        "named_product_baseline",
        "human_review_completed",
        "production_effect_observed",
    ):
        if reference.get(field) is not False:
            raise SystemExit(f"gold reference overclaimed {field}")
    if args.capability_reference_only and (
        plan.get("business_model") != "b2c"
        or "synthetic benchmark"
        not in str(plan.get("brief", {}).get("product_truth", "")).casefold()
    ):
        raise SystemExit(
            "--capability-reference-only requires the frozen synthetic B2C benchmark"
        )
    candidates = reference.get("candidates")
    expected_surfaces = [row["surface_id"] for row in plan["requests"]]
    if (
        not isinstance(candidates, list)
        or len(candidates) != EXPECTED_SURFACE_COUNT
        or [row.get("surface_id") for row in candidates] != expected_surfaces
    ):
        raise SystemExit("gold reference platform coverage is invalid")
    if args.overlay:
        overlay_bytes = args.overlay.read_bytes()
        overlay = json.loads(overlay_bytes)
        overlay_sha256 = hashlib.sha256(overlay_bytes).hexdigest()
        if overlay.get("schema") != OVERLAY_SCHEMA:
            raise SystemExit("gold reference overlay schema is invalid")
        if overlay.get("base_reference_sha256") != base_reference_sha256:
            raise SystemExit("gold reference overlay base digest is invalid")
        if (
            overlay.get("brief_id") != plan["brief"]["brief_id"]
            or overlay.get("business_model") != plan["business_model"]
        ):
            raise SystemExit("gold reference overlay escaped the plan brief")
        for field in (
            "named_product_baseline",
            "human_review_completed",
            "production_effect_observed",
        ):
            if overlay.get(field) is not False:
                raise SystemExit(f"gold reference overlay overclaimed {field}")
        overrides = overlay.get("overrides")
        if not isinstance(overrides, list) or not overrides:
            raise SystemExit("gold reference overlay is empty")
        override_by_surface = {
            str(row.get("surface_id")): row for row in overrides if isinstance(row, dict)
        }
        if len(override_by_surface) != len(overrides) or not set(override_by_surface).issubset(
            expected_surfaces
        ):
            raise SystemExit("gold reference overlay surface coverage is invalid")
        for surface_id, row in override_by_surface.items():
            if any(field not in row for field in CREATIVE_FIELDS):
                raise SystemExit(
                    f"gold reference overlay candidate is incomplete: {surface_id}"
                )
        overlay_surfaces = set(override_by_surface)
        candidates = [
            override_by_surface.get(str(row["surface_id"]), row) for row in candidates
        ]
        reference = dict(reference)
        reference["candidates"] = candidates
    reference_bundle_sha256 = hashlib.sha256(
        canonical_json(reference).encode("utf-8")
    ).hexdigest()
    attempts = {
        row["surface_id"]: [
            {
                "raw_output": json.dumps(
                    {field: row[field] for field in CREATIVE_FIELDS},
                    ensure_ascii=False,
                ),
                "source": (
                    "codex_clean_room_capability_overlay"
                    if row["surface_id"] in overlay_surfaces
                    else "original_clean_room_workspace_reference"
                ),
                "elapsed_seconds": 0,
                "generated_token_count": 0,
            }
        ]
        for row in candidates
    }
    receipt = compile_platform_native_receipt(
        plan=plan,
        model={
            "provider": "codex_workspace_clean_room_reference_authoring",
            "model_id": "current_codex_session_unspecified",
            "device_family": "not_attested_for_reference_authoring",
            "base_reference_sha256": base_reference_sha256,
            "overlay_sha256": overlay_sha256,
            "source_reference_sha256": reference_bundle_sha256,
            "overlay_surface_count": len(overlay_surfaces),
            "network_download_performed": False,
            "cloud_api_call_count": "not_measured_by_worktree",
            "local_inference_claimed": False,
            "training_observed": False,
            "reference_only": True,
            "competition_core_eligible": False,
            "capability_reference_only": args.capability_reference_only,
        },
        attempts_by_surface=attempts,
    )
    audit = compile_platform_generation_quality_audit(
        plan=plan,
        receipt=receipt,
        capability_reference_only=args.capability_reference_only,
    )
    args.receipt_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.receipt_output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(
        args.audit_output,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "receipt_output": str(args.receipt_output.relative_to(ROOT)),
                "audit_output": str(args.audit_output.relative_to(ROOT)),
                "accepted_surface_count": receipt["accepted_surface_count"],
                "pre_human_quality_pass_count": audit[
                    "pre_human_quality_pass_count"
                ],
                "cross_surface_duplicate_pair_count": len(
                    audit["cross_surface_duplicate_pairs"]
                ),
                "overlay_surface_count": len(overlay_surfaces),
                "overlay_sha256": overlay_sha256,
                "capability_reference_only": args.capability_reference_only,
                "mechanically_publication_ready_count": audit.get(
                    "mechanically_publication_ready_count"
                ),
                "human_craft_review_completed_count": 0,
                "production_effect_observed": False,
                "four_a_claim_eligible": False,
                "top1_claim_eligible": False,
                "receipt_sha256": receipt["content_sha256"],
                "audit_sha256": audit["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if audit["pre_human_quality_pass_count"] == EXPECTED_SURFACE_COUNT else 2


if __name__ == "__main__":
    raise SystemExit(main())
