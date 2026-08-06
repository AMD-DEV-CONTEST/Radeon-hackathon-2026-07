from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
V1 = ROOT / "evidence/v10/delete-one-line-three-lane-named-pk-portfolio-v1.json"
CAROUSEL = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2/receipt.json"
IMAGE_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-qwen-image-ab-v1/packet-receipt.json"
QWEN_CAPTURE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen-image/capture.json"
OUTPUT = ROOT / "evidence/v10/delete-one-line-four-lane-named-pk-portfolio-v2.json"


IMAGE_STRESS = {
    "Midjourney": "Match high-taste visual stopping power while keeping every required verdict word readable and the evidence gap, not atmosphere, as the focal idea.",
    "Adobe Firefly": "Preserve commercial provenance and exact-copy editability while making the deletion feel authored rather than assembled from safe stock treatments.",
    "OpenAI Image": "Follow the exact visible-copy and one-glance hierarchy contract without hallucinated microcopy, duplicate lines or softened self-indictment.",
    "Google Imagen": "Resist photoreal spectacle that obscures the product mechanism; the conflict, verdict and missing witness must resolve before visual decoration.",
    "FLUX": "Reach deployable local-generation craft while preserving exact spelling, 4:5 geometry, brand consistency and a distinctive evidence mark.",
    "Ideogram": "Beat typography-first generation on hierarchy, exact text, spacing and legibility without collapsing into a generic quote card.",
    "Recraft": "Turn the concept into a reusable editorial design system with crisp geometry and brand-ownable structure, not a one-off illustration.",
    "Leonardo.Ai": "Maintain production repeatability and clean export quality across the five-beat system without style drift or inconsistent copy.",
    "Qwen-Image": "Beat the captured local raw output on exact copy, dimensional compliance and direct publishability while retaining the same frozen task and no hidden repair.",
    "Canva Magic Media": "Preserve template-speed usability while avoiding familiar template grammar, filler decoration and interchangeable campaign styling.",
}


def binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def row_id(category_id: str, product: str) -> str:
    digest = hashlib.sha256(f"{category_id}\0{product}".encode()).hexdigest()[:12]
    return f"dol-pk-{category_id}-{digest}"


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    previous = json.loads(V1.read_text(encoding="utf-8"))
    carousel = json.loads(CAROUSEL.read_text(encoding="utf-8"))
    packet = json.loads(IMAGE_PACKET.read_text(encoding="utf-8"))
    capture = json.loads(QWEN_CAPTURE.read_text(encoding="utf-8"))
    if previous["lane_count"] != 3 or previous["named_product_row_count"] != 30:
        raise SystemExit("three-lane portfolio drifted")
    if carousel["slide_count"] != 5 or carousel["production_effect_observed"] is not False:
        raise SystemExit("carousel receipt drifted or overclaims effect")
    if packet["reviewer_kit_count"] != 5 or packet["submitted_review_count"] != 0:
        raise SystemExit("Qwen image packet review state drifted")
    if packet["capture_slot_id"] != capture["capture_slot_id"]:
        raise SystemExit("Qwen capture and packet are not bound")
    image_rows = [
        row for row in ledger["product_pk_rows"]
        if row["category_id"] == "image_generation_editing"
    ]
    if len(image_rows) != 10 or set(IMAGE_STRESS) != {row["reference_product"] for row in image_rows}:
        raise SystemExit("image named-product coverage drifted")
    candidate = binding(CAROUSEL)
    supports = [
        binding(ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2" / f"slide-{index:02d}-1080x1350.png")
        for index in range(1, 6)
    ]
    supports += [binding(IMAGE_PACKET), binding(QWEN_CAPTURE)]
    lane = {
        "category_id": "image_generation_editing",
        "candidate_binding": candidate,
        "support_bindings": supports,
        "named_product_target_count": 10,
        "authorized_named_product_baseline_count": 1,
        "source_hidden_five_human_packet_count": 1,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "qualified_human_review_count": 0,
        "release_eligible": False,
    }
    compiled_rows = []
    for row in image_rows:
        qwen = row["reference_product"] == "Qwen-Image"
        compiled_rows.append({
            "row_id": row_id(row["category_id"], row["reference_product"]),
            "category_id": row["category_id"],
            "reference_product": row["reference_product"],
            "reference_product_url": row["reference_product_url"],
            "reference_capability": row["reference_capability"],
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": row["quality_axes"],
            "opponent_specific_stress_test": IMAGE_STRESS[row["reference_product"]],
            "candidate_sha256": candidate["sha256"],
            "authorized_named_product_baseline_present": qwen,
            "source_hidden_five_human_packet_present": qwen,
            "qualified_human_review_count": 0,
            "comparison_status": (
                "source_hidden_packet_ready_awaiting_five_humans"
                if qwen else "awaiting_authorized_same_brief_baseline"
            ),
            "candidate_won": False,
            "effect_alignment_achieved": False,
        })
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineFourLaneNamedPKPortfolioV2",
        "source_ledger_sha256": ledger["content_sha256"],
        "source_three_lane_portfolio_sha256": previous["content_sha256"],
        "campaign_id": "delete-one-line",
        "lane_count": 4,
        "named_product_row_count": 40,
        "lanes": [*previous["lanes"], lane],
        "rows": [*previous["rows"], *compiled_rows],
        "authorized_named_product_baseline_count": 1,
        "source_hidden_five_human_packet_count": 1,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "effect_aligned_lane_count": 0,
        "automatic_product_execution_enabled": False,
        "automatic_promotion_enabled": False,
        "production_effect_observed": False,
        "truth_boundary": "This portfolio binds Delete One Line challengers to forty named-product rows across text, scheduling, GTM lifecycle and image generation. Only Qwen-Image has an authorized same-task baseline and current-candidate five-human packet; it has zero submitted reviews. All forty wins and all market-effect claims remain zero.",
    })
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "lane_count": 4, "named_product_row_count": 40, "authorized_named_product_baseline_count": 1, "source_hidden_five_human_packet_count": 1, "candidate_win_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
