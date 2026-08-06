from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
OUTPUT = ROOT / "evidence/v10/delete-one-line-three-lane-named-pk-portfolio-v1.json"
LANES: dict[str, dict[str, Any]] = {
    "text_content_generation": {
        "candidate": ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v2.json",
        "support": [
            ROOT / "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v2/source-hidden-review-dossier.html",
            ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1/receipt.json",
            ROOT / "artifacts/gtm-last-mile-pk-v1/text-campaign-ab-v2/packet-receipt.json",
        ],
        "stress_path": ("candidate", "opponent_stress_tests"),
    },
    "content_scheduling_operations": {
        "candidate": ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v2/content-calendar.json",
        "support": [
            ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-response-loop-v1/response-learning-contract.json",
            ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-receipt.json",
            ROOT / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1/receipt.json",
        ],
        "stress_path": ("opponent_stress_tests",),
    },
    "gtm_lifecycle_orchestration": {
        "candidate": ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-lifecycle-super-challenger-v2/gtm-lifecycle-execution-dossier.json",
        "support": [
            ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v2/content-calendar.json",
            ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-response-loop-v1/response-learning-contract.json",
        ],
        "stress_path": ("opponent_stress_tests",),
    },
}


def nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        value = value[key]
    return value


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
    lanes, rows = [], []
    for category_id, spec in LANES.items():
        candidate_path = spec["candidate"]
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        stress = nested(candidate, spec["stress_path"])
        ledger_rows = [row for row in ledger["product_pk_rows"] if row["category_id"] == category_id]
        if len(ledger_rows) != 10 or set(stress) != {row["reference_product"] for row in ledger_rows}:
            raise SystemExit(f"named-product coverage drifted for {category_id}")
        source_bindings = [binding(candidate_path), *(binding(path) for path in spec["support"])]
        lanes.append({
            "category_id": category_id,
            "candidate_binding": source_bindings[0],
            "support_bindings": source_bindings[1:],
            "named_product_target_count": 10,
            "authorized_named_product_baseline_count": 0,
            "completed_named_product_pk_count": 0,
            "candidate_win_count": 0,
            "qualified_human_review_count": 0,
            "release_eligible": False,
        })
        for row in ledger_rows:
            rows.append({
                "row_id": row_id(category_id, row["reference_product"]),
                "category_id": category_id,
                "reference_product": row["reference_product"],
                "reference_product_url": row["reference_product_url"],
                "reference_capability": row["reference_capability"],
                "same_brief_task": row["same_brief_task"],
                "effect_pk_question": row["effect_pk_question"],
                "quality_axes": row["quality_axes"],
                "opponent_specific_stress_test": stress[row["reference_product"]],
                "candidate_sha256": source_bindings[0]["sha256"],
                "authorized_named_product_baseline_present": False,
                "source_hidden_five_human_packet_present": False,
                "qualified_human_review_count": 0,
                "comparison_status": "awaiting_authorized_same_brief_baseline",
                "candidate_won": False,
                "effect_alignment_achieved": False,
            })
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineThreeLaneNamedPKPortfolioV1",
        "source_ledger_sha256": ledger["content_sha256"],
        "campaign_id": "delete-one-line",
        "lane_count": 3,
        "named_product_row_count": 30,
        "lanes": lanes,
        "rows": rows,
        "authorized_named_product_baseline_count": 0,
        "source_hidden_five_human_packet_count": 0,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "effect_aligned_lane_count": 0,
        "automatic_product_execution_enabled": False,
        "automatic_promotion_enabled": False,
        "production_effect_observed": False,
        "truth_boundary": "This portfolio binds the Delete One Line V2 challenger to thirty existing named-product rows in text, scheduling and GTM lifecycle. No authorized same-brief product baseline or five-human named-product review exists, so all thirty comparisons and wins remain zero."
    })
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "lane_count": 3, "named_product_row_count": 30, "completed_named_product_pk_count": 0, "candidate_win_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
