#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.files import atomic_write_bytes
from prooflaunch_remix.ledger import canonical_json
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.v10_submission_runtime import (
    AgencyRunWorker,
    ProductionAgencyService,
)
from prooflaunch_remix.v10_submission_store import SubmissionStore


def _read_regular(path: str | Path, *, maximum_bytes: int) -> tuple[Path, bytes]:
    candidate = Path(path).expanduser().resolve(strict=True)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"input must be a regular file: {candidate}")
    payload = candidate.read_bytes()
    if not 1 <= len(payload) <= maximum_bytes:
        raise ValueError(f"input file size is outside [1, {maximum_bytes}]: {candidate}")
    return candidate, payload


def _put(store: SubmissionStore, payload: bytes, media_type: str) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    store.artifacts.put(
        io.BytesIO(payload),
        expected_sha256=digest,
        media_type=media_type,
    )
    return digest


def run_pilot(
    *,
    output_dir: str | Path,
    product_image: str | Path,
    signal_snapshot: str | Path,
    collection_receipt: str | Path,
) -> dict[str, object]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    product_path, product_bytes = _read_regular(product_image, maximum_bytes=25_000_000)
    snapshot_path, snapshot_bytes = _read_regular(signal_snapshot, maximum_bytes=1_000_000)
    receipt_path, receipt_bytes = _read_regular(collection_receipt, maximum_bytes=1_000_000)
    if not product_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("product image must be a PNG byte stream")

    store = SubmissionStore(output / "state")
    worker = AgencyRunWorker(
        store,
        worker_id="public-signal-pilot-worker",
        supervisor_factory=lambda event_sink: build_supervisor(
            audience=LexicalAudiencePulse(),
            seed=20260803,
            event_sink=event_sink,
        ),
    )
    service = ProductionAgencyService(store, worker=worker)
    product_sha256 = _put(store, product_bytes, "image/png")
    snapshot_sha256 = _put(store, snapshot_bytes, "application/json")
    receipt_artifact_sha256 = _put(store, receipt_bytes, "application/json")
    request_id = f"public-signal-pilot-{snapshot_sha256[:16]}"
    payload = {
        "request_id": request_id,
        "campaign_id": f"campaign-{request_id}",
        "campaign": {
            "product_name": "ProofLaunch",
            "specification_text": (
                "ProofLaunch converts owner-supplied evidence and bounded public channel "
                "measurements into a human-reviewable GTM campaign system."
            ),
            "market": "United States",
            "platform": "YouTube",
            "goal": "Prepare a zero-media-spend, source-bound launch system for human review.",
            "target_emotion": "joy",
        },
        "strategy": {
            "org_id": "org-prooflaunch-pilot",
            "project_id": "project-public-signal-pilot",
            "owner": "ProofLaunch operator",
            "industry": "GTM operations software",
            "business_model": "b2b",
            "lifecycle": "launch",
            "budget": "zero",
            "industry_risk": "standard",
            "audience_name": "GTM campaign owner",
            "audience_problem": "Needs channel evidence without copying source creative.",
            "audience_outcome": "Select a testable format hypothesis and reviewable campaign pack.",
            "buying_context": "Evaluating a governed local-first GTM employee.",
            "brand_purpose": "Make campaign production inspectable and governable.",
            "customer_promise": "Every strategy hypothesis remains source-bound and human-gated.",
            "brand_voice": "clear, evidence-bound, specific",
            "offer": "A local approval-gated campaign system",
            "landing_url": "https://example.invalid/prooflaunch-pilot",
            "schedule_timezone": "America/New_York",
        },
        "input_artifacts": {
            "product_image": product_sha256,
            "creative_signal_snapshot": snapshot_sha256,
            "creative_signal_collection_receipt": receipt_artifact_sha256,
        },
        "rights": {
            "confirmed": True,
            "basis": "Owner-created ProofLaunch product image and public-measurement-only channel signals.",
        },
        "maximum_actions": 12,
        "maximum_cost_usd": 0,
        "human_release_required": True,
        "data_class": "internal",
        "creative_signal_data_class": "public",
    }
    created = service.create_run(payload)
    processed = worker.process_one()
    if processed.status != "awaiting_release":
        raise RuntimeError(f"pilot did not stop at the human gate: {processed.status}")
    run_id = str(created["run_id"])
    state, _ = worker._find_prepared_state(run_id)
    strategy = json.loads((state.output_path / "gtm-strategy.json").read_text(encoding="utf-8"))
    intelligence = json.loads(
        (state.output_path / "creative-signal-intelligence.json").read_text(
            encoding="utf-8"
        )
    )
    experiment = json.loads((state.output_path / "experiment.json").read_text(encoding="utf-8"))
    calendar = json.loads((state.output_path / "content-calendar.json").read_text(encoding="utf-8"))
    signal_guidance = strategy["signal_guidance"]
    receipt: dict[str, object] = {
        "schema": "ProofLaunchPublicSignalGTMPilotV1",
        "status": "awaiting_human_release",
        "run_id": run_id,
        "input_paths": {
            "product_image": product_path.name,
            "signal_snapshot": snapshot_path.name,
            "collection_receipt": receipt_path.name,
        },
        "input_artifact_sha256": {
            "product_image": product_sha256,
            "signal_snapshot": snapshot_sha256,
            "collection_receipt": receipt_artifact_sha256,
        },
        "run_data_class": "internal",
        "creative_signal_data_class": intelligence["field_data_class"],
        "signal_count": intelligence["signal_count"],
        "platform_counts": intelligence["platform_counts"],
        "hypothesis_count": len(signal_guidance["hypothesis_queue"]),
        "hypothesis_ids": [
            item["hypothesis_id"] for item in signal_guidance["hypothesis_queue"]
        ],
        "collection_receipt_sha256": signal_guidance["collection_receipt_sha256"],
        "collection_plan_sha256": signal_guidance["collection_plan_sha256"],
        "experiment_id": experiment["run_id"],
        "content_calendar_sha256": calendar["content_sha256"],
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "external_release_executed": False,
        "human_release_required": True,
        "truth_boundary": (
            "This receipt proves a real bounded public-metadata collection entered the "
            "local GTM strategy path and stopped at the human release gate. It does not "
            "prove human preference, publication, lift, revenue, 4A quality or Radeon execution."
        ),
    }
    receipt["content_sha256"] = hashlib.sha256(
        canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    atomic_write_bytes(
        output / "pilot-receipt.json",
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real public-signal GTM pilot to the human release gate."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--product-image", required=True)
    parser.add_argument("--signal-snapshot", required=True)
    parser.add_argument("--collection-receipt", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_pilot(
                output_dir=args.output_dir,
                product_image=args.product_image,
                signal_snapshot=args.signal_snapshot,
                collection_receipt=args.collection_receipt,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
