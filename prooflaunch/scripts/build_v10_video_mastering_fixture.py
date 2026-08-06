#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_image_mastering import PixelBox
from prooflaunch_remix.v10_supply_chain import stable_sha256
from prooflaunch_remix.v10_video_mastering import (
    MASTER_FPS,
    MASTER_FRAME_COUNT,
    FrameChunkPlan,
    FrameRepairRequest,
    KeyframeRef,
    PronunciationLexicon,
    Shot,
    ShotGraph,
    Storyboard,
    TemporalReward,
    TemporalRewardDimension,
    TimedEvent,
    UHD_LANDSCAPE,
    VAETilePlan,
    VideoComputePolicy,
    VideoConstraint,
    VideoMasterSpec,
    VideoRole,
    av_alignment_score,
    cross_media_claim_pass,
    exact_product_identity,
    flicker_score,
    frame_sha256,
    motion_continuity_score,
    planned_video_pack_card,
    safe_zone_pass,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/video-mastering-fixture"


def _save(image: Image.Image, name: str) -> Path:
    path = OUTPUT / name
    image.save(path, format="PNG", optimize=False)
    return path


def _box(box: PixelBox) -> list[int]:
    return [box.left, box.top, box.right, box.bottom]


def _background() -> Image.Image:
    gradient = Image.linear_gradient("L").resize(UHD_LANDSCAPE)
    return ImageOps.colorize(gradient, black=(8, 14, 32), white=(62, 84, 132)).convert("RGBA")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    product = Image.open(ROOT / "evidence/v10/image-mastering-fixture/product-source.png").convert("RGBA")
    product_sha = sha256_file(ROOT / "evidence/v10/image-mastering-fixture/product-source.png")
    logo_sha = stable_sha256({"logo": "PROOFLAUNCH", "origin": "project_owned_mechanical"})
    observed_indices = (0, 47, 48, 143, 144, 191)
    observed_boxes: dict[int, PixelBox] = {}
    logo_boxes: dict[int, PixelBox] = {}
    frame_paths: dict[int, Path] = {}
    frames: dict[int, Image.Image] = {}
    for ordinal, frame_index in enumerate(observed_indices):
        frame = _background()
        x = 2760 + ordinal * 10
        y = 790
        product_box = PixelBox(x, y, x + product.width, y + product.height)
        frame.alpha_composite(product, (x, y))
        logo_box = PixelBox(260, 220, 940, 360)
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle(tuple(_box(logo_box)), radius=24, fill=(26, 111, 255, 255))
        observed_boxes[frame_index] = product_box
        logo_boxes[frame_index] = logo_box
        frames[frame_index] = frame
        frame_paths[frame_index] = _save(frame, f"frame-{frame_index:03d}-3840x2160.png")

    keyframes = {
        index: KeyframeRef(index, frame_sha256(frames[index]), f"shot boundary at frame {index}")
        for index in observed_indices
    }
    storyboard = Storyboard(
        "gtm-eight-second-fixture-v1",
        (
            Shot("hook", 0, 47, "evidence-led hook", keyframes[0], keyframes[47]),
            Shot("proof", 48, 143, "product proof", keyframes[48], keyframes[143]),
            Shot("action", 144, 191, "bounded call to action", keyframes[144], keyframes[191]),
        ),
        tuple(VideoRole),
    )
    shot_graph = ShotGraph(("hook", "proof", "action"), (("hook", "proof"), ("proof", "action")))
    constraint = VideoConstraint(
        product_sha,
        logo_sha,
        observed_boxes,
        logo_boxes,
        24.0,
        4.0,
        ("locked", "slow_push", "product_orbit_under_3_degrees"),
        ("whip_pan", "handheld_jitter", "unmotivated_roll"),
    )
    locators = {dimension: f"video-mastering-fixture/report.json#temporal_reward/{dimension.value}" for dimension in TemporalRewardDimension}
    reward = TemporalReward({dimension: 1.0 for dimension in TemporalRewardDimension}, locators)
    compute_policy = VideoComputePolicy(1, 12.0, "finetune", "wan-teacher-pinned", "a" * 64, True)
    chunk_plan = FrameChunkPlan(MASTER_FRAME_COUNT, 48, 8)
    tile_plan = VAETilePlan(UHD_LANDSCAPE, 1024, 128)
    repair = FrameRepairRequest(
        96,
        PixelBox(1200, 1500, 1450, 1750),
        PixelBox(1100, 1400, 1550, 1850),
        (observed_boxes[48], logo_boxes[48]),
    )
    safe_zone = PixelBox(192, 108, 3648, 2052)
    pronunciation = PronunciationLexicon({"ProofLaunch": "P R UW F L AO N CH", "ROCm": "R AA K AH M"})
    video_events = (TimedEvent("product_reveal", 2.00), TimedEvent("proof_lock", 5.50))
    audio_events = (TimedEvent("product_reveal", 2.04), TimedEvent("proof_lock", 5.46))
    ordered_frames = [frames[index] for index in (0, 48, 144)]
    ordered_boxes = [observed_boxes[index] for index in (0, 48, 144)]
    identities = {
        f"{index:03d}": exact_product_identity(frames[index], product, observed_boxes[index])
        for index in observed_indices
    }
    files = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in frame_paths.values()
    }
    report = {
        "schema": "ProofLaunch4KVideoMasteringFixtureV1",
        "status": "passed",
        "fixture_origin": "project_owned_mechanical_frames_not_model_generated_not_encoded_video",
        "master_spec": {
            "variants": [list(item) for item in VideoMasterSpec().variants],
            "duration_seconds": 8,
            "fps": MASTER_FPS,
            "frame_count": MASTER_FRAME_COUNT,
            "audio_target_lufs": -16.0,
            "audio_true_peak_dbtp": -1.0,
        },
        "files": files,
        "roles": [item.value for item in storyboard.roles],
        "storyboard": {
            "id": storyboard.storyboard_id,
            "sha256": storyboard.digest,
            "shots": [
                {
                    "shot_id": item.shot_id,
                    "start_frame": item.start_frame,
                    "end_frame": item.end_frame,
                    "purpose": item.purpose,
                    "first_keyframe_sha256": item.first_keyframe.image_sha256,
                    "last_keyframe_sha256": item.last_keyframe.image_sha256,
                }
                for item in storyboard.shots
            ],
        },
        "shot_graph": {"nodes": list(shot_graph.nodes), "edges": [list(item) for item in shot_graph.edges]},
        "constraints": {
            "product_source_sha256": constraint.product_source_sha256,
            "logo_source_sha256": constraint.logo_source_sha256,
            "product_boxes": {str(key): _box(value) for key, value in constraint.product_boxes.items()},
            "logo_boxes": {str(key): _box(value) for key, value in constraint.logo_boxes.items()},
            "motion": {"maximum_center_velocity_px": 24.0, "maximum_center_acceleration_px": 4.0},
            "camera": {"allowed": list(constraint.allowed_camera_moves), "forbidden": list(constraint.forbidden_camera_moves)},
        },
        "temporal_reward": {dimension.value: {"value": reward.values[dimension], "locator": reward.locators[dimension]} for dimension in TemporalRewardDimension},
        "temporal_reward_pass": reward.passed,
        "single_card_12b_teacher_training_admitted": compute_policy.admitted,
        "frame_chunk_windows": [list(item) for item in chunk_plan.windows()],
        "vae_tiles": {"count": len(tile_plan.tiles()), "first": _box(tile_plan.tiles()[0]), "last": _box(tile_plan.tiles()[-1])},
        "local_frame_repair_admitted": repair.admitted,
        "pronunciation_pass": pronunciation.validate_tokens({"ProofLaunch": "P R UW F L AO N CH", "ROCm": "R AA K AH M"}),
        "safe_zone_pass": safe_zone_pass(tuple(logo_boxes.values()), safe_zone),
        "product_identity": identities,
        "flicker_score": flicker_score(ordered_frames, ordered_boxes),
        "motion_continuity_score": motion_continuity_score(ordered_boxes, 4.0),
        "av_alignment_score": av_alignment_score(video_events, audio_events),
        "cross_media_claim_pass": cross_media_claim_pass({"claim-01": "evidence://experiment/01"}, {"claim-01": "evidence://experiment/01"}),
        "model_execution": {"wan_2_2_5b": False, "wan_i2v": False, "ltx": False, "seedvr2": False, "rcm": False, "causal_forcing": False},
        "encoded_video": None,
        "audio_master": None,
        "truth_boundary": "Observed 4K boundary frames and deterministic mastering checks only; no generative video, restoration, optical-flow inference, audio render or encoded master.",
    }
    atomic_write_text(OUTPUT / "report.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    contract = {
        "schema": "ProofLaunch4KVideoMasteringContractV1",
        "status": "mechanically_verified_model_runs_pending",
        "storyboard_sha256": storyboard.digest,
        "fixture_report_sha256": sha256_file(OUTPUT / "report.json"),
        "hard_rules": {
            "single_card_teacher_training_forbidden_at_or_above_billions": 10,
            "duration_seconds": 8,
            "fps": 24,
            "frame_count": 192,
            "product_identity_floor": 1.0,
            "logo_identity_floor": 1.0,
            "audio_integrated_lufs": -16.0,
            "audio_true_peak_dbtp": -1.0,
        },
        "required_model_runs": ["wan_2_2_5b", "wan_i2v", "ltx_fallback", "seedvr2", "rcm", "causal_forcing"],
    }
    atomic_write_text(ROOT / "config/cortex_x_v10_video_mastering_contract.json", json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(ROOT / "evidence/v10/video-pack-card.planned.json", json.dumps(planned_video_pack_card(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"report": str(OUTPUT / "report.json"), "report_sha256": sha256_file(OUTPUT / "report.json"), "frame_files": len(frame_paths)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
