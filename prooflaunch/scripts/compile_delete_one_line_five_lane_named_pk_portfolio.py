from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
V2 = ROOT / "evidence/v10/delete-one-line-four-lane-named-pk-portfolio-v2.json"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"
AUDIO_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet/packet-receipt.json"
AUDIO_PUBLIC_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet/public/packet.json"
QWEN_CAPTURE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen3-tts/capture.json"
OUTPUT = ROOT / "evidence/v10/delete-one-line-five-lane-named-pk-portfolio-v3.json"


AUDIO_STRESS = {
    "ElevenLabs": "Match natural prosody and emotional control without identity imitation, hidden reference audio or sacrificing exact script fidelity.",
    "Suno": "Hold the spoken verdict above musical spectacle; any score must sharpen the deletion beat rather than turn a product confession into an anthem.",
    "Udio": "Preserve intelligibility and semantic pacing in a music-capable production route without repeating, stretching or rewriting the frozen script.",
    "Google Lyria": "Use music as narrative structure while keeping voice, rights provenance and the evidence boundary independently inspectable.",
    "Adobe Firefly Audio": "Reach edit-ready commercial polish with explicit source rights, reversible mastering and no ambience that implies an unobserved audience or courtroom event.",
    "Stable Audio": "Deliver a locally reproducible sonic bed whose timing supports the 15-second cut without masking consonants or manufacturing dramatic proof.",
    "MiniMax Audio": "Match expressive multilingual voice control while avoiding sales cadence, cloned identity and uncontrolled words beyond the frozen script.",
    "Qwen3-TTS": "Beat the captured raw same-script VoiceDesign output on human cadence, verdict emphasis and mix readiness without semantic drift or hidden repair.",
    "ACE-Step 1.5": "Use open music generation for a distinctive campaign mnemonic while keeping the spoken proof object dominant, consent-safe and separately reviewable.",
    "Descript": "Match editor-speed repairability, transcript alignment and production cleanup while preserving the original performance and every declared edit.",
}


def binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def row_id(category_id: str, product: str) -> str:
    return f"dol-pk-{category_id}-{hashlib.sha256(f'{category_id}\0{product}'.encode()).hexdigest()[:12]}"


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    previous = json.loads(V2.read_text(encoding="utf-8"))
    candidate = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    packet = json.loads(AUDIO_PACKET.read_text(encoding="utf-8"))
    public_packet = json.loads(AUDIO_PUBLIC_PACKET.read_text(encoding="utf-8"))
    capture = json.loads(QWEN_CAPTURE.read_text(encoding="utf-8"))
    if previous["lane_count"] != 4 or previous["named_product_row_count"] != 40:
        raise SystemExit("four-lane portfolio drifted")
    if candidate["frozen_script_sha256"] != "354412e95437212514cae01fe769d0420446e098b29ab9716218779c08762e18":
        raise SystemExit("audio candidate script drifted")
    if packet["capture_slot_id"] != capture["capture_slot_id"] or packet["submitted_review_count"] != 0:
        raise SystemExit("Qwen3-TTS packet state drifted")
    if public_packet["expected_review_count"] != 5 or public_packet["source_roles_exposed"]:
        raise SystemExit("Qwen3-TTS packet is not source-hidden five-reviewer work")
    rows = [row for row in ledger["product_pk_rows"] if row["category_id"] == "audio_voice_music"]
    if len(rows) != 10 or set(AUDIO_STRESS) != {row["reference_product"] for row in rows}:
        raise SystemExit("audio named-product coverage drifted")
    candidate_binding = binding(AUDIO_RECEIPT)
    supports = [binding(ROOT / item["master"]["project_relative_path"]) for item in candidate["candidates"]]
    supports += [binding(AUDIO_PACKET), binding(AUDIO_PUBLIC_PACKET), binding(QWEN_CAPTURE)]
    lane = {
        "category_id": "audio_voice_music",
        "candidate_binding": candidate_binding,
        "support_bindings": supports,
        "named_product_target_count": 10,
        "authorized_named_product_baseline_count": 1,
        "source_hidden_five_human_packet_count": 1,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "qualified_human_review_count": 0,
        "release_eligible": False,
    }
    compiled = []
    for row in rows:
        qwen = row["reference_product"] == "Qwen3-TTS"
        compiled.append({
            "row_id": row_id(row["category_id"], row["reference_product"]),
            "category_id": row["category_id"],
            "reference_product": row["reference_product"],
            "reference_product_url": row["reference_product_url"],
            "reference_capability": row["reference_capability"],
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": row["quality_axes"],
            "opponent_specific_stress_test": AUDIO_STRESS[row["reference_product"]],
            "candidate_sha256": candidate_binding["sha256"],
            "authorized_named_product_baseline_present": qwen,
            "source_hidden_five_human_packet_present": qwen,
            "qualified_human_review_count": 0,
            "comparison_status": "source_hidden_packet_ready_awaiting_five_humans" if qwen else "awaiting_authorized_same_brief_baseline",
            "candidate_won": False,
            "effect_alignment_achieved": False,
        })
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineFiveLaneNamedPKPortfolioV3",
        "source_ledger_sha256": ledger["content_sha256"],
        "source_four_lane_portfolio_sha256": previous["content_sha256"],
        "campaign_id": "delete-one-line",
        "lane_count": 5,
        "named_product_row_count": 50,
        "lanes": [*previous["lanes"], lane],
        "rows": [*previous["rows"], *compiled],
        "authorized_named_product_baseline_count": 2,
        "source_hidden_five_human_packet_count": 2,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "effect_aligned_lane_count": 0,
        "automatic_product_execution_enabled": False,
        "automatic_promotion_enabled": False,
        "production_effect_observed": False,
        "truth_boundary": "This portfolio binds Delete One Line challengers to fifty named-product rows across text, scheduling, GTM lifecycle, image and audio. Qwen-Image and Qwen3-TTS each have one authorized same-task baseline and an empty five-human packet. All fifty wins and all market-effect claims remain zero.",
    })
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "lane_count": 5, "named_product_row_count": 50, "authorized_named_product_baseline_count": 2, "source_hidden_five_human_packet_count": 2, "candidate_win_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
