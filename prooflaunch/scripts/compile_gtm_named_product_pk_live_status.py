#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_pk import NamedProductPKReviewService


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
ADMISSION = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v3/manifest.json"
REGISTRY = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/registry.json"
PACKET_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1"
OUTPUT = ROOT / "evidence/v10/gtm-named-product-pk-live-status-v1.json"
MARKDOWN = ROOT / "docs/product/GTM_NAMED_PRODUCT_PK_LIVE_STATUS_V1.md"
REVIEW_ROOT = ROOT / "evidence/v10/named-product-pk-reviews-v1"
ACTIVE_PACKET_ROOTS = (
    "named-product-pk-qwen-image-v2",
    "named-product-pk-openai-image-v1",
    "named-product-pk-qwen3-tts-v1",
    "named-product-pk-mem0-v2",
    "named-product-pk-letta-v1",
    "named-product-pk-memos-v2",
    "named-product-pk-postiz-v1",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def verify(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != hashlib.sha256(canonical(unsigned)).hexdigest():
        raise SystemExit(f"sealed input drifted: {path}")
    return payload


def slot_id(category_id: str, product: str) -> str:
    digest = hashlib.sha256(f"{category_id}\0{product}".encode()).hexdigest()
    return f"pk-{digest[:16]}"


def main() -> None:
    ledger = verify(LEDGER)
    admission = verify(ADMISSION)
    registry = verify(REGISTRY)
    captures = {row["capture_slot_id"]: row for row in registry["captures"]}
    packets: dict[str, dict[str, Any]] = {}
    for packet_name in ACTIVE_PACKET_ROOTS:
        receipt_path = PACKET_ROOT / packet_name / "review-packet/packet-receipt.json"
        receipt = verify(receipt_path)
        slot = receipt["capture_slot_id"]
        if slot in packets:
            raise SystemExit(f"duplicate packet for {slot}")
        packets[slot] = {**receipt, "receipt_path": str(receipt_path.relative_to(ROOT)), "receipt_sha256": sha256_file(receipt_path)}
    rows = []
    for row in ledger["product_pk_rows"]:
        slot = slot_id(row["category_id"], row["reference_product"])
        capture = captures.get(slot)
        packet = packets.get(slot)
        submitted = 0
        completed = False
        candidate_win = False
        if packet:
            packet_root = ROOT / packet["receipt_path"].rsplit("/packet-receipt.json", 1)[0]
            store_root = REVIEW_ROOT / slot
            review_status = NamedProductPKReviewService(
                packet_root=packet_root,
                store_root=store_root,
            ).status()
            submitted = review_status["submitted_review_count"]
            completed = review_status["review_complete"]
            candidate_win = review_status["candidate_won_same_brief_last_mile_pk"]
        status = "awaiting_authorized_baseline"
        if capture:
            status = "authorized_baseline_present_review_packet_pending"
        if packet:
            status = "blind_review_packet_ready_awaiting_five_humans"
        if submitted:
            status = "human_review_in_progress"
        if completed:
            status = "candidate_win" if candidate_win else "candidate_did_not_clear_pk_gate"
        rows.append({
            "capture_slot_id": slot,
            "category_id": row["category_id"],
            "reference_product": row["reference_product"],
            "authorized_baseline_present": capture is not None,
            "blind_review_packet_ready": packet is not None,
            "active_packet_receipt_path": packet["receipt_path"] if packet else None,
            "active_packet_receipt_sha256": packet["receipt_sha256"] if packet else None,
            "comparison_id": packet["comparison_id"] if packet else None,
            "submitted_human_review_count": submitted,
            "completed": completed,
            "candidate_win": candidate_win,
            "status": status,
            "next_action": (
                "collect_five_independent_source_hidden_human_reviews"
                if packet else "capture_authorized_same_brief_product_output"
            ),
        })
    core = {
        "schema": "ProofLaunchNamedProductPKLiveStatusV1",
        "source_ledger_sha256": ledger["content_sha256"],
        "challenger_admission_sha256": admission["content_sha256"],
        "baseline_registry_sha256": registry["content_sha256"],
        "row_count": len(rows),
        "category_count": 13,
        "challenger_dossier_count": admission["dossier_count"],
        "challenger_admitted_category_count": admission["admitted_category_count"],
        "authorized_baseline_count": sum(row["authorized_baseline_present"] for row in rows),
        "blind_review_packet_count": sum(row["blind_review_packet_ready"] for row in rows),
        "submitted_human_review_count": sum(row["submitted_human_review_count"] for row in rows),
        "completed_product_pk_rows": sum(row["completed"] for row in rows),
        "candidate_win_count": sum(row["candidate_win"] for row in rows),
        "effect_aligned_category_count": len({row["category_id"] for row in rows if row["candidate_win"]}),
        "rows": rows,
        "truth_boundary": "The live layer joins the frozen 130-row plan with current baseline and blind-packet state. A captured baseline or empty review packet is not a vote, completion, win, 4A result or observed market effect."
    }
    core["content_sha256"] = hashlib.sha256(canonical(core)).hexdigest()
    atomic_write_text(OUTPUT, json.dumps(core, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    ready = [row for row in rows if row["blind_review_packet_ready"]]
    lines = [
        "# Named-product PK live status V1", "",
        f"- Challenger dossiers admitted: **{core['challenger_admitted_category_count']}/13**",
        f"- Authorized named-product baselines: **{core['authorized_baseline_count']}/130**",
        f"- Five-reviewer packets ready: **{core['blind_review_packet_count']}/130**",
        f"- Submitted human reviews: **{core['submitted_human_review_count']}**",
        f"- Completed rows / candidate wins: **{core['completed_product_pk_rows']} / {core['candidate_win_count']}**", "",
        "## Executable now", "",
    ]
    lines.extend(
        f"- `{row['capture_slot_id']}` · {row['category_id']} × {row['reference_product']} · {row['next_action']}"
        for row in ready
    )
    lines += ["", "## Truth boundary", "", core["truth_boundary"], ""]
    atomic_write_text(MARKDOWN, "\n".join(lines))
    print(json.dumps({key: core[key] for key in ("row_count", "authorized_baseline_count", "blind_review_packet_count", "submitted_human_review_count", "completed_product_pk_rows", "candidate_win_count", "content_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
