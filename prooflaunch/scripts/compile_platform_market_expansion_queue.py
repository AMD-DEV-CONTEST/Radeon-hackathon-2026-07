#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.ledger import canonical_json


PRIORITY_PLATFORMS = (
    "linkedin", "tiktok", "instagram", "reddit", "x", "facebook",
    "pinterest", "bluesky", "mastodon",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--execution-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    source_registry = (
        json.loads(args.source_registry.read_text(encoding="utf-8"))
        if args.source_registry is not None
        else None
    )
    observed = {
        row["lane_id"]: row
        for row in coverage.get("observed_platform_market_lanes", [])
    }
    contracts = {
        row["platform"]: row for row in standard["platform_contracts"]
    }
    discovered_by_lane = {}
    execution_by_source_sha = {}
    execution_receipts = sorted(
        receipt_path
        for execution_root in args.execution_root
        if execution_root.exists()
        for receipt_path in execution_root.glob("*/collection-receipt.json")
    )
    if execution_receipts:
        for receipt_path in execution_receipts:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            for run in receipt.get("runs", []):
                if not isinstance(run, dict) or not run.get("source_url_sha256"):
                    continue
                freshness = run.get("public_freshness", {})
                freshness = freshness if isinstance(freshness, dict) else {}
                recent_180 = int(freshness.get("recent_item_count_180d", 0) or 0)
                if run.get("status") in {"completed", "completed_with_item_handoffs"}:
                    status = (
                        "executed_recent_public_metadata"
                        if recent_180 > 0
                        else "executed_stale_or_undated_public_metadata"
                    )
                else:
                    status = "executed_human_handoff_required"
                execution_by_source_sha[str(run["source_url_sha256"])] = {
                    "status": status,
                    "execution_receipt": str(receipt_path),
                    "connector_id": run.get("connector_id"),
                    "recent_item_count_180d": recent_180,
                    "normalized_signal_count": int(run.get("normalized_signal_count", 0) or 0),
                    "error": str(run.get("error") or run.get("stderr_excerpt") or "")[:500] or None,
                }
    if source_registry is not None:
        if source_registry.get("schema") != "ProofLaunchPlatformSourceDiscoveryRegistryV1":
            raise SystemExit("unsupported source discovery registry")
        for organization in source_registry.get("organizations", []):
            if not isinstance(organization, dict):
                continue
            business_model = organization.get("business_model")
            market = organization.get("market")
            discovered = organization.get("discovered_sources", {})
            if not isinstance(discovered, dict):
                continue
            for platform, urls in discovered.items():
                if platform not in PRIORITY_PLATFORMS or not isinstance(urls, list):
                    continue
                lane_id = f"{business_model}:{market}:{platform}"
                lane_candidates = discovered_by_lane.setdefault(lane_id, [])
                for url in urls:
                    if not isinstance(url, str) or not url.startswith("https://"):
                        continue
                    candidate = {
                        "organization_id": organization.get("organization_id"),
                        "organization_name": organization.get("name"),
                        "source_url": url,
                        "source_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                        "vertical": organization.get("vertical"),
                        "company_scale": organization.get("company_scale"),
                        "lifecycle": organization.get("lifecycle"),
                        "identity_basis": "organization_homepage_public_link",
                        "status": "discovered_collection_not_yet_executed",
                    }
                    candidate.update(execution_by_source_sha.get(candidate["source_url_sha256"], {}))
                    lane_candidates.append(candidate)
    lanes = []
    for target in standard["platform_market_lanes"]:
        platform = target["platform"]
        if platform not in PRIORITY_PLATFORMS:
            continue
        current = observed.get(target["lane_id"], {})
        source_count = int(current.get("distinct_source_count", 0))
        recent_count = int(current.get("recent_item_count", 0))
        contract = contracts[platform]
        needed_sources = max(0, target["minimum_distinct_sources"] - source_count)
        candidates = []
        seen_organizations = set()
        for candidate in discovered_by_lane.get(target["lane_id"], []):
            organization_id = candidate.get("organization_id")
            if organization_id in seen_organizations:
                continue
            seen_organizations.add(organization_id)
            candidates.append(candidate)
            if len(candidates) >= needed_sources:
                break
        source_slots = []
        for index in range(source_count + 1, target["minimum_distinct_sources"] + 1):
            candidate_index = index - source_count - 1
            if candidate_index < len(candidates):
                candidate = candidates[candidate_index]
                source_slots.append({
                    "slot_id": f"{target['lane_id']}:source:{index}",
                    **candidate,
                })
            else:
                source_slots.append({
                    "slot_id": f"{target['lane_id']}:source:{index}",
                    "source_url": None,
                    "status": "candidate_discovery_required",
                })
        lanes.append({
            "lane_id": target["lane_id"],
            "priority_rank": PRIORITY_PLATFORMS.index(platform) + 1,
            "platform": platform,
            "business_model": target["business_model"],
            "market": target["market"],
            "observed_distinct_source_count": source_count,
            "observed_recent_item_count": recent_count,
            "remaining_distinct_sources": max(
                0, target["minimum_distinct_sources"] - source_count
            ),
            "remaining_recent_items": max(
                0, target["minimum_recent_items"] - recent_count
            ),
            "discovered_candidate_count": len(candidates),
            "oss_routes": contract["oss_routes"],
            "access_contract": contract["access"],
            "candidate_requirements": [
                "public_or_operator_authorized_source",
                "market_and_business_model_basis_verified_before_collection",
                "recent_90_to_180_day_publication_dates",
                "public_counter_or_feed_metadata_when_exposed",
                "distinct_source_sha256_not_already_counted_in_lane",
            ],
            "source_slots": source_slots,
            "forbidden": [
                "authentication_bypass", "captcha_bypass", "paywall_bypass",
                "rate_limit_evasion", "automatic_raw_content_training",
            ],
        })
    lanes.sort(key=lambda row: (
        row["priority_rank"], row["observed_distinct_source_count"],
        row["market"], row["business_model"],
    ))
    payload = {
        "schema": "ProofLaunchPlatformMarketExpansionQueueV1",
        "sampling_standard_sha256": standard["content_sha256"],
        "coverage_receipt_sha256": coverage["content_sha256"],
        "source_registry_sha256": (
            source_registry.get("content_sha256") if source_registry is not None else None
        ),
        "execution_receipt_count": len(execution_receipts),
        "priority_platforms": list(PRIORITY_PLATFORMS),
        "target_lane_count": len(lanes),
        "candidate_source_slot_count": sum(
            len(row["source_slots"]) for row in lanes
        ),
        "discovered_candidate_slot_count": sum(
            sum(slot.get("source_url") is not None for slot in row["source_slots"])
            for row in lanes
        ),
        "filled_lane_count": sum(
            row["observed_distinct_source_count"] + row["discovered_candidate_count"] >= 3
            for row in lanes
        ),
        "partially_filled_lane_count": sum(
            0 < row["observed_distinct_source_count"] + row["discovered_candidate_count"] < 3
            for row in lanes
        ),
        "executed_candidate_slot_count": sum(
            sum(str(slot.get("status", "")).startswith("executed_") for slot in row["source_slots"])
            for row in lanes
        ),
        "recent_candidate_slot_count": sum(
            sum(slot.get("status") == "executed_recent_public_metadata" for slot in row["source_slots"])
            for row in lanes
        ),
        "stale_or_undated_candidate_slot_count": sum(
            sum(slot.get("status") == "executed_stale_or_undated_public_metadata" for slot in row["source_slots"])
            for row in lanes
        ),
        "handoff_candidate_slot_count": sum(
            sum(slot.get("status") == "executed_human_handoff_required" for slot in row["source_slots"])
            for row in lanes
        ),
        "lanes": lanes,
        "automatic_external_publish_count": 0,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": (
            "This is an execution queue, not observed coverage. Empty source slots must be "
            "filled with verified public or operator-authorized sources before collection."
        ),
    }
    payload["content_sha256"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps({
        "output": str(args.output),
        "target_lane_count": payload["target_lane_count"],
        "candidate_source_slot_count": payload["candidate_source_slot_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
