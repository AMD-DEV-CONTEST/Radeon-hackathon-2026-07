#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_effect_eval import Capability, Deliverable, DeliverableRole  # noqa: E402
from prooflaunch_remix.gtm_effect_packet import EffectReviewPacketBuilder, PacketArtifact  # noqa: E402


SCENARIO_ID = "prooflaunch-b2b-ai-launch-zero-budget-v1"
CURRENT_CAMPAIGN = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/audio-candidate-receipt.json"
VIDEO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/video-challenger-receipt.json"
TEXT_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3"
VISUAL_PACKET = ROOT / "artifacts/campaign-pack-visual-blind-review-v1"
DEFAULT_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return sealed


def _verify_seal(payload: dict[str, Any], label: str) -> None:
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != hashlib.sha256(_canonical(unsigned)).hexdigest():
        raise SystemExit(f"{label} content digest is invalid")


def _deliverable(
    *,
    deliverable_id: str,
    capability: Capability,
    role: DeliverableRole,
    source: Path,
    channel: str,
    rights: str,
) -> PacketArtifact:
    return PacketArtifact(
        deliverable=Deliverable(
            deliverable_id=deliverable_id,
            scenario_id=SCENARIO_ID,
            capability=capability,
            role=role,
            content_sha256=sha256_file(source),
            blind_artifact_locator=f"local://{source.name}",
            rights_locator=rights,
            evidence_locators=("evidence://claim-owner-001",),
            claim_ids=("claim-owner-001",),
            brand_profile_id="prooflaunch-cortex-x-v1",
            channel=channel,
            accessibility_locator="contract://frozen-script-and-caption-v1",
            experiment_trace_id="run-35bf6593f7aa4a4b34100a74",
            clean_room_attested=True,
            method_reference_locators=(
                "docs/product/GTM_CONCRETE_PRODUCT_EFFECT_PK_LEDGER_V1.md",
            ),
        ),
        source_path=str(source),
        comparison_key=deliverable_id.rsplit("-", 1)[0],
    )


def _write_instructions(root: Path, *, modality: str, pair_count: int) -> None:
    axes = {
        "audio": (
            "semantic fidelity; intelligibility; naturalness; prosody; brand voice; "
            "speaker consistency; mix readiness; consent provenance"
        ),
        "video": (
            "first-three-second hook; story clarity; motion control; identity continuity; "
            "proof legibility; sound-picture timing; channel fit; mastering defects"
        ),
    }[modality]
    body = f"""# {modality.title()} same-Brief blind review

Open each LEFT/RIGHT asset named in `public/blind-pairs.jsonl`; identities and roles are hidden.
Score the pair on: {axes}.

Each of five qualified reviewers must independently fill their own file under
`public/reviewers/`. Do not consult the private role map or other reviewers.

- Pair count: {pair_count}
- Overall choice: `left`, `right`, or `abstain`
- Directly publishable and major-rework fields are mandatory
- Rationale must locate concrete evidence in the artifact
- No automated publish, send, spend, runtime switch, or 4A/Top-product claim is authorized
"""
    atomic_write_text(root / "REVIEW_INSTRUCTIONS.md", body)


def compile_packets(output: Path, *, audio_key: str, video_key: str) -> dict[str, Any]:
    try:
        output.resolve().relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("output must remain inside the project") from error
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    output.mkdir(parents=True, mode=0o700)

    receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    _verify_seal(receipt, "audio candidate receipt")
    if receipt.get("mechanical_gate_passed") is not True:
        raise SystemExit("audio candidates did not pass their mechanical gate")
    if receipt.get("frozen_script_sha256") != hashlib.sha256(
        receipt["frozen_script"].encode("utf-8")
    ).hexdigest():
        raise SystemExit("audio frozen script digest is invalid")

    current_audio = CURRENT_CAMPAIGN / "prooflaunch-audio-master-48k-stereo-24bit.wav"
    audio_entries: list[PacketArtifact] = []
    for index, row in enumerate(receipt["candidates"], start=1):
        challenger = ROOT / row["master"]["project_relative_path"]
        if sha256_file(challenger) != row["master"]["sha256"]:
            raise SystemExit("audio challenger digest mismatch")
        key = f"audio-direction-{index:02d}"
        audio_entries.extend(
            (
                _deliverable(
                    deliverable_id=f"{key}-candidate",
                    capability=Capability.AUDIO,
                    role=DeliverableRole.CANDIDATE,
                    source=challenger,
                    channel="audio",
                    rights="rights://apache-2.0-voice-design-no-reference-audio",
                ),
                _deliverable(
                    deliverable_id=f"{key}-baseline",
                    capability=Capability.AUDIO,
                    role=DeliverableRole.BASELINE,
                    source=current_audio,
                    channel="audio",
                    rights="rights://prooflaunch-owner-generated-clean-room",
                ),
            )
        )
    audio_root = output / "audio"
    audio_packet = EffectReviewPacketBuilder().build(
        audio_entries,
        audio_root,
        randomization_key=audio_key,
        reviewer_count=5,
    )
    _write_instructions(audio_root, modality="audio", pair_count=audio_packet.pair_count)
    audio_scope = _seal(
        {
            "schema": "ProofLaunchGTMAudioBlindReviewScopeV1",
            "packet_sha256": audio_packet.packet_sha256,
            "same_script": True,
            "pair_count": audio_packet.pair_count,
            "reviewer_count": audio_packet.reviewer_count,
            "expected_human_review_count": audio_packet.pair_count * audio_packet.reviewer_count,
            "submitted_human_review_count": 0,
            "top_product_baseline": False,
            "human_preference_observed": False,
            "promotion_requires_named_human_review": True,
            "truth_boundary": (
                "This packet compares three local same-script voice directions with the current "
                "master. It is an internal challenger tournament, not a leading-product baseline "
                "or evidence of 4A quality, semantic fidelity, publication effect or revenue."
            ),
        }
    )
    atomic_write_text(audio_root / "scope.json", json.dumps(audio_scope, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    video_receipt = json.loads(VIDEO_RECEIPT.read_text(encoding="utf-8"))
    _verify_seal(video_receipt, "video challenger receipt")
    if video_receipt.get("mechanical_three_beat_gate_passed") is not True:
        raise SystemExit("video challenger did not pass its mechanical three-beat gate")
    challenger_video = ROOT / video_receipt["video"]["path"]
    if sha256_file(challenger_video) != video_receipt["video"]["sha256"]:
        raise SystemExit("video challenger digest mismatch")
    if (video_receipt["video"]["width"], video_receipt["video"]["height"]) != (3840, 2160):
        raise SystemExit("video challenger is not 4K")
    current_video = CURRENT_CAMPAIGN / "prooflaunch-campaign-film-4k.mp4"
    video_entries = (
        _deliverable(
            deliverable_id="video-film-candidate",
            capability=Capability.VIDEO,
            role=DeliverableRole.CANDIDATE,
            source=challenger_video,
            channel="video",
            rights="rights://prooflaunch-owner-generated-clean-room",
        ),
        _deliverable(
            deliverable_id="video-film-baseline",
            capability=Capability.VIDEO,
            role=DeliverableRole.BASELINE,
            source=current_video,
            channel="video",
            rights="rights://prooflaunch-owner-generated-clean-room",
        ),
    )
    video_root = output / "video"
    video_packet = EffectReviewPacketBuilder().build(
        video_entries,
        video_root,
        randomization_key=video_key,
        reviewer_count=5,
    )
    _write_instructions(video_root, modality="video", pair_count=video_packet.pair_count)
    video_scope = _seal(
        {
            "schema": "ProofLaunchGTMVideoBlindReviewScopeV1",
            "packet_sha256": video_packet.packet_sha256,
            "same_campaign_lineage": True,
            "same_brief": True,
            "challenger_receipt_sha256": sha256_file(VIDEO_RECEIPT),
            "mechanical_three_beat_gate_passed": True,
            "pair_count": video_packet.pair_count,
            "reviewer_count": video_packet.reviewer_count,
            "expected_human_review_count": video_packet.pair_count * video_packet.reviewer_count,
            "submitted_human_review_count": 0,
            "top_product_baseline": False,
            "human_preference_observed": False,
            "promotion_requires_named_human_review": True,
            "truth_boundary": (
                "This packet compares a content-addressed 4K three-beat internal challenger with "
                "the current 4K campaign master. It is not a leading video-product baseline or evidence of 4A quality, "
                "production lift, publication effect or revenue."
            ),
        }
    )
    atomic_write_text(video_root / "scope.json", json.dumps(video_scope, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    text_manifest = json.loads((TEXT_PACKET / "manifest.json").read_text(encoding="utf-8"))
    text_scope = json.loads((TEXT_PACKET / "scope.json").read_text(encoding="utf-8"))
    visual_public = json.loads(
        (VISUAL_PACKET / "campaign-pack-blind-review-public.json").read_text(encoding="utf-8")
    )
    review_streams = (
        {
            "stream_id": "text-decision",
            "lane_count": 11,
            "pair_count": text_manifest["pair_count"],
            "reviewer_count": text_manifest["reviewer_count"],
            "expected_review_count": text_scope["expected_human_review_count"],
            "submitted_review_count": text_scope["submitted_human_review_count"],
            "packet_locator": str(TEXT_PACKET.relative_to(ROOT)),
            "comparison_class": text_scope["comparison_class"],
        },
        {
            "stream_id": "visual-system",
            "lane_count": 1,
            "pair_count": 1,
            "reviewer_count": visual_public["reviewer_slot_count"],
            "expected_review_count": visual_public["expected_review_count"],
            "submitted_review_count": 0,
            "packet_locator": str(VISUAL_PACKET.relative_to(ROOT)),
            "comparison_class": "current_campaign_visual_system_vs_previous_internal_revision",
        },
        {
            "stream_id": "video",
            "lane_count": 1,
            "pair_count": video_packet.pair_count,
            "reviewer_count": video_packet.reviewer_count,
            "expected_review_count": video_packet.pair_count * video_packet.reviewer_count,
            "submitted_review_count": 0,
            "packet_locator": str(video_root.relative_to(ROOT)),
            "comparison_class": "three_beat_4k_challenger_vs_current_internal_master",
        },
        {
            "stream_id": "audio",
            "lane_count": 1,
            "pair_count": audio_packet.pair_count,
            "reviewer_count": audio_packet.reviewer_count,
            "expected_review_count": audio_packet.pair_count * audio_packet.reviewer_count,
            "submitted_review_count": 0,
            "packet_locator": str(audio_root.relative_to(ROOT)),
            "comparison_class": "three_local_voice_design_challengers_vs_current_master",
        },
    )
    lane_count = sum(row["lane_count"] for row in review_streams)
    pair_count = sum(row["pair_count"] for row in review_streams)
    expected = sum(row["expected_review_count"] for row in review_streams)
    if (lane_count, pair_count, expected) != (14, 16, 80):
        raise SystemExit("unified review inventory gate failed")
    unified = _seal(
        {
            "schema": "ProofLaunchGTMUnifiedLastMileReviewV1",
            "scenario_id": SCENARIO_ID,
            "lane_count": lane_count,
            "comparison_pair_count": pair_count,
            "reviewer_slots_per_pair": 5,
            "expected_human_review_count": expected,
            "submitted_human_review_count": 0,
            "review_streams": review_streams,
            "quality_authority": "named_qualified_independent_humans",
            "model_judge_can_diagnose_only": True,
            "automatic_promotion_enabled": False,
            "automatic_publish_enabled": False,
            "product_pk_rows_total": 130,
            "product_pk_rows_completed": 0,
            "top_product_baselines_present": False,
            "four_a_quality_proven": False,
            "effect_alignment_achieved": False,
            "predeclared_gate": {
                "minimum_reviewers_per_pair": 5,
                "minimum_candidate_preference_rate": 0.75,
                "minimum_wilson_lower_95_exclusive": 0.50,
                "minimum_candidate_publishable_rate": 0.95,
                "maximum_candidate_major_rework_rate": 0.05,
                "blocking_defects_allowed": 0,
                "failed_lane_action": "repair_and_rerun_same_brief",
            },
            "truth_boundary": (
                "This manifest makes all fourteen last-mile lanes reviewable and binds eighty "
                "empty human-review tasks. Empty templates are not observations. The current "
                "opponents are internal challengers, not the named leading products in the 130-row "
                "ledger; therefore no Top-product, 4A, causal lift, publication or revenue claim is earned."
            ),
        }
    )
    unified_path = output / "unified-last-mile-review.json"
    atomic_write_text(unified_path, json.dumps(unified, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return unified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_ROOT))
    parser.add_argument("--audio-key", default=None)
    parser.add_argument("--video-key", default=None)
    args = parser.parse_args()
    result = compile_packets(
        Path(args.output_dir).expanduser().resolve(),
        audio_key=args.audio_key or secrets.token_urlsafe(32),
        video_key=args.video_key or secrets.token_urlsafe(32),
    )
    print(
        json.dumps(
            {
                "lane_count": result["lane_count"],
                "comparison_pair_count": result["comparison_pair_count"],
                "expected_human_review_count": result["expected_human_review_count"],
                "submitted_human_review_count": result["submitted_human_review_count"],
                "content_sha256": result["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
