from __future__ import annotations

import json
import re
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1"
SOURCE_PATHS = (
    OUTPUT / "index.html",
    OUTPUT / "operator.css",
    OUTPUT / "frontier.css",
    OUTPUT / "qa.css",
    OUTPUT / "operator.js",
    OUTPUT / "case-system-v2.json",
    OUTPUT / "media-v2/b2b-refusal-wall-frontier-v1.png",
    OUTPUT / "media-v2/b2c-keep-unpostable-frontier-v1.png",
)
BOUND_PATHS = (
    ROOT / "scripts/compile_gtm_breakout_operator_cases_v2.py",
    ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json",
    ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json",
    ROOT / "scripts/build_radeon_gate_v5.py",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen-image-v2/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-openai-image-v1/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-letta-v1/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-memos-v2/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-postiz-v1/review-packet/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/registry.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-blind-jury-console-v1/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-copy-ab-v1/packet-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-carousel-v1/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-audio-v1/audio-candidate-receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-video-v1/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-release-jury-v1/receipt.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-execution-room-v1/receipt.json",
)


def main() -> None:
    for path in (*SOURCE_PATHS, *BOUND_PATHS):
        if not path.is_file():
            raise SystemExit(f"missing breakout-operator dependency: {path}")

    html = (OUTPUT / "index.html").read_text(encoding="utf-8")
    script = (OUTPUT / "operator.js").read_text(encoding="utf-8")
    case_system = json.loads((OUTPUT / "case-system-v2.json").read_text(encoding="utf-8"))
    activation_routes = [
        route
        for case in case_system["cases"].values()
        for route in case["activation_wave"]
    ]
    required_markers = (
        "MAKE<br>THE <em>BET.</em>",
        "01B / FRONTIER CREATIVE",
        "Beautiful<br>drafts are <em>cheap.</em>",
        "Your day<br>doesn’t need<br>an <em>audience</em>",
        "Not more content.",
        "One idea.<br>Thirteen native jobs.",
        "03 / ACTIVATION WAVE",
        "The post is only<br>the opening move.",
        "No victory lap",
        "Seven real fights.",
        "OPEN BLIND JURY CONSOLE",
        "OPEN LEGACY POSTIZ ROOM",
        "OPEN B2C EXECUTION ROOM",
        "OPEN LAST-MILE COPY REVIEW",
        "No publish, preference, organic breakout, conversion, revenue or named-product win is claimed.",
    )
    missing = [marker for marker in required_markers if marker not in html]
    if missing:
        raise SystemExit(f"breakout operator contract drifted: {missing}")
    for phrase in (
        "THE 40-ASSET INTERVIEW",
        "KEEP THE UNPOSTABLE",
        "Don’t ask an AI GTM employee to make 40 launch assets. Ask it which 39 it would refuse to ship.",
        "Your day does not need a documentary to be worth remembering.",
    ):
        if phrase not in script:
            raise SystemExit(f"missing last-mile copy: {phrase}")
    if re.search(r'\bscore\s*:\s*["\']\d+\s*/\s*\d+["\']', script):
        raise SystemExit("numeric author-side craft score is forbidden")
    if script.count('"gate": "PENDING"') != 26:
        raise SystemExit("every concrete GTM asset must remain pending independent human craft review")
    if script.count('"disclosure": "') != 2:
        raise SystemExit("both concrete GTM fixtures must carry an explicit disclosure")
    if "SYNTHETIC PRODUCT FIXTURE · NO APP, USER RESULT OR MARKET EFFECT EXISTS" not in script:
        raise SystemExit("synthetic B2C fixture disclosure is missing")
    if '"winner_selected": true' in script or '"external_publish_executed": true' in script:
        raise SystemExit("operator source overstates a winner or external execution")

    receipt = seal(
        {
            "schema": "ProofLaunchGTMBreakoutOperatorReceiptV1",
            "artifact_id": "gtm-breakout-operator-v1",
            "case_count": 2,
            "cases": [
                {
                    "id": "b2b",
                    "business_model": "b2b",
                    "campaign_platform": "The 40-Asset Interview",
                    "platform_native_draft_count": 13,
                    "produced_media_count": 2,
                    "fixture_status": "owned_product_capability_fixture",
                },
                {
                    "id": "b2c",
                    "business_model": "b2c",
                    "campaign_platform": "Keep the Unpostable",
                    "platform_native_draft_count": 13,
                    "produced_media_count": 1,
                    "fixture_status": "synthetic_product_launch_fixture",
                },
            ],
            "platform_native_draft_count": 26,
            "surface_count_per_case": 13,
            "activated_handoff_role_count": 12,
            "craft_context_count": 144,
            "territory_handoff_count": 432,
            "surface_specialist_lens_assignment_count": 15552,
            "unconventional_edge_play_binding_count": 3888,
            "maximum_simultaneous_primary_channels_per_case": 1,
            "maximum_simultaneous_secondary_channels_per_case": 1,
            "remaining_surfaces_held_until_human_approved_signal": True,
            "interactive_case_switch_present": True,
            "interactive_channel_switch_present": True,
            "frontier_cloud_key_visual_count": 2,
            "draft_copy_action_present": True,
            "frozen_brief_disclosure_present": True,
            "graph_loop_harness_visible": True,
            "named_product_target_count": 130,
            "authorized_named_product_baseline_count": 7,
            "source_hidden_five_human_packet_count": 7,
            "expected_human_review_count": 35,
            "submitted_human_review_count": 0,
            "last_mile_copy_ab_expected_human_review_count": 5,
            "last_mile_copy_ab_submitted_human_review_count": 0,
            "activation_route_count": len(activation_routes),
            "primary_activation_route_count": sum(route["role"] == "PRIMARY" for route in activation_routes),
            "secondary_activation_route_count": sum(route["role"] == "SECONDARY" for route in activation_routes),
            "activation_conversation_reply_count": sum(len(route["conversation_tree"]) for route in activation_routes),
            "activation_conversion_step_count": sum(len(route["conversion_path"]) for route in activation_routes),
            "activation_production_instruction_count": sum(len(route.get("production_contract", [])) for route in activation_routes),
            "activation_finished_asset_count": sum(len(route.get("production_assets", [])) for route in activation_routes),
            "activation_finished_image_count": sum(
                asset.get("kind") == "image" for route in activation_routes for asset in route.get("production_assets", [])
            ),
            "activation_finished_video_count": sum(
                asset.get("kind") == "video" for route in activation_routes for asset in route.get("production_assets", [])
            ),
            "activation_audio_candidate_count": sum(
                asset.get("kind") == "audio" for route in activation_routes for asset in route.get("production_assets", [])
            ),
            "activation_release_review_packet_count": sum("release_review" in route for route in activation_routes),
            "activation_release_review_expected_human_count": sum(
                route.get("release_review", {}).get("expected_human_review_count", 0) for route in activation_routes
            ),
            "activation_release_review_submitted_human_count": sum(
                route.get("release_review", {}).get("submitted_human_review_count", 0) for route in activation_routes
            ),
            "activation_execution_room_count": sum("execution_room" in route for route in activation_routes),
            "activation_execution_route_count": sum(
                route.get("execution_room", {}).get("route_count", 0) for route in activation_routes
            ),
            "activation_execution_external_request_count": sum(
                route.get("execution_room", {}).get("external_request_count", 0) for route in activation_routes
            ),
            "activation_external_execution_count": sum(bool(route["external_execution"]) for route in activation_routes),
            "activation_human_release_required_count": sum(bool(route["human_release_required"]) for route in activation_routes),
            "completed_named_product_pk_count": 0,
            "candidate_win_count": 0,
            "human_review_completed": False,
            "winner_selected": False,
            "visible_craft_contract_checks_per_asset": 4,
            "numeric_quality_score_present": False,
            "external_publish_executed": False,
            "human_preference_observed": False,
            "organic_breakout_observed": False,
            "conversion_observed": False,
            "revenue_observed": False,
            "named_product_superiority_observed": False,
            "artifact_files": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
                for path in SOURCE_PATHS
            ],
            "source_bindings": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": sha256_file(path),
                }
                for path in BOUND_PATHS
            ],
            "truth_boundary": (
                "This local interactive demonstrates two concrete strategy-to-execution fixtures, twenty-six platform-native "
                "drafts, a one-primary/one-secondary activation policy, four ready-for-human-review activation packs and one previously produced 4K challenger. "
                "None of the activation packs has been externally executed. The B2C product scenario is synthetic. Internal craft "
                "checks are author-side completeness checks, not human preference, craft scores or virality predictions. No external publication, "
                "market effect, conversion, revenue or named-product win is asserted. Seven authorized same-task baselines "
                "and empty five-human review packets are exposed; 123 named-product baselines remain missing."
            ),
        }
    )
    atomic_write_text(
        OUTPUT / "receipt.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps({"output": str(OUTPUT), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
