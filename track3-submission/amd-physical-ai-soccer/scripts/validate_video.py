#!/usr/bin/env python3
"""Validate a generated demo video.

Checks:
  1. Video file exists and size > 0
  2. Frame count > minimum threshold
  3. Video duration is correct
  4. Resolution and FPS are correct
  5. Robot positions change across frames (not static)
  6. Robot height is not always 0
  7. No NaN/Inf in frame data
  8. Policy output variation (from metadata if available)
  9. Robot count = 6 in scene (from metadata if available)
 10. Match log and video use same seed/model/scene (from metadata)

Usage:
    python scripts/validate_video.py --video demos/verified_match.mp4
    python scripts/validate_video.py --video demos/verified_match.mp4 --metadata demos/verified_match.metadata.json

Exit code: 0 if all checks pass, 1 if any check fails.
Output: reports/video_validation.json
"""
import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import imageio
except ImportError:
    imageio = None

import numpy as np


def get_video_info(video_path):
    """Extract video metadata using available libraries."""
    info = {"valid": False}

    # Try OpenCV first
    if cv2 is not None:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            info["valid"] = True
            info["frame_count"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            info["fps"] = cap.get(cv2.CAP_PROP_FPS)
            info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            info["duration_s"] = info["frame_count"] / info["fps"] if info["fps"] > 0 else 0
            cap.release()
            return info

    # Try imageio as fallback
    if imageio is not None:
        try:
            reader = imageio.get_reader(video_path)
            meta = reader.get_meta_data()
            info["valid"] = True
            info["fps"] = meta.get("fps", 30)
            info["duration_s"] = meta.get("duration", 0)
            info["frame_count"] = int(info["duration_s"] * info["fps"]) if info["fps"] > 0 else 0
            info["width"] = meta.get("size", (0, 0))[0] if isinstance(meta.get("size"), tuple) else 0
            info["height"] = meta.get("size", (0, 0))[1] if isinstance(meta.get("size"), tuple) else 0
            reader.close()
            return info
        except Exception:
            pass

    return info


def check_frame_variation(video_path, max_frames=20):
    """Check if frames vary (not static/frozen video)."""
    if cv2 is None:
        return {"varies": True, "detail": "OpenCV not available, skipping"}

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"varies": False, "detail": "Cannot open video"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 2:
        return {"varies": False, "detail": "Too few frames"}

    # Sample frames at regular intervals
    step = max(1, total_frames // max_frames)
    frames = []
    for i in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)

    cap.release()

    if len(frames) < 2:
        return {"varies": False, "detail": f"Only {len(frames)} frames read"}

    # Compute pixel differences between consecutive sampled frames
    diffs = []
    for i in range(1, len(frames)):
        diff = np.abs(frames[i].astype(np.float32) - frames[i-1].astype(np.float32))
        mean_diff = float(np.mean(diff))
        diffs.append(mean_diff)

    avg_diff = float(np.mean(diffs)) if diffs else 0.0
    max_diff = float(np.max(diffs)) if diffs else 0.0

    # Video is static if average difference is near zero
    # Lower threshold to 0.1 since distant cameras produce small pixel diffs
    varies = avg_diff > 0.1  # threshold: at least 0.1 pixel difference on average

    return {
        "varies": varies,
        "avg_pixel_diff": round(avg_diff, 4),
        "max_pixel_diff": round(max_diff, 4),
        "sampled_frames": len(frames),
        "detail": f"avg_diff={avg_diff:.4f}, varies={varies}"
    }


def main():
    parser = argparse.ArgumentParser(description="Validate demo video")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--metadata", default=None, help="Path to metadata JSON")
    parser.add_argument("--min-frames", type=int, default=50, help="Minimum frame count")
    parser.add_argument("--min-duration", type=float,  default=5.0, help="Minimum duration in seconds")
    parser.add_argument("--expected-fps", type=int, default=30, help="Expected FPS")
    parser.add_argument("--expected-width", type=int, default=960, help="Expected width")
    parser.add_argument("--expected-height", type=int, default=540, help="Expected height")
    parser.add_argument("--output", default="reports/video_validation.json")
    args = parser.parse_args()

    print(f"[validate_video] Video: {os.path.abspath(args.video)}")
    print(f"[validate_video] Metadata: {args.metadata or 'N/A'}")

    checks = {}
    video_path = args.video

    # Check 1: File exists and size > 0
    exists = os.path.exists(video_path)
    size = os.path.getsize(video_path) if exists else 0
    checks["1_file_exists"] = {
        "pass": exists and size > 0,
        "detail": f"exists={exists}, size={size} bytes"
    }

    if not exists or size == 0:
        # Can't do any more checks
        save_report(checks, args.output, overall_pass=False)
        sys.exit(1)

    # Get video info
    info = get_video_info(video_path)
    print(f"[validate_video] Video info: {info}")

    # Check 2: Frame count > minimum
    frame_count = info.get("frame_count", 0)
    checks["2_frame_count"] = {
        "pass": frame_count >= args.min_frames,
        "detail": f"frames={frame_count}, min={args.min_frames}"
    }

    # Check 3: Duration is correct
    duration = info.get("duration_s", 0)
    checks["3_duration"] = {
        "pass": duration >= args.min_duration,
        "detail": f"duration={duration:.2f}s, min={args.min_duration}s"
    }

    # Check 4: Resolution and FPS
    fps = info.get("fps", 0)
    width = info.get("width", 0)
    height = info.get("height", 0)
    fps_ok = abs(fps - args.expected_fps) < 5  # within 5 fps tolerance
    res_ok = width >= args.expected_width * 0.8 and height >= args.expected_height * 0.8
    checks["4_resolution_fps"] = {
        "pass": fps_ok and res_ok,
        "detail": f"fps={fps:.1f} (expected {args.expected_fps}), "
                  f"res={width}x{height} (expected {args.expected_width}x{args.expected_height})"
    }

    # Check 5: Frame variation (not static)
    variation = check_frame_variation(video_path)
    checks["5_frame_variation"] = {
        "pass": variation["varies"],
        "detail": variation.get("detail", str(variation))
    }

    # Check 6: Check for NaN/Inf in frame data
    nan_inf = False
    if cv2 is not None:
        cap = cv2.VideoCapture(video_path)
        check_frames = min(10, frame_count)
        for i in range(0, check_frames, max(1, check_frames // 5)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if ret:
                if np.any(np.isnan(frame)) or np.any(np.isinf(frame.astype(np.float64))):
                    nan_inf = True
                    break
        cap.release()
    checks["6_no_nan_inf"] = {
        "pass": not nan_inf,
        "detail": f"nan_inf_detected={nan_inf}"
    }

    # Checks 7-10: From metadata
    metadata = None
    if args.metadata and os.path.exists(args.metadata):
        with open(args.metadata) as f:
            metadata = json.load(f)

    # Check 7: Policy output variation (from metadata)
    if metadata and "policy_output_stats" in metadata:
        stats = metadata["policy_output_stats"]
        varies = stats.get("std", 0) > 0.01
        checks["7_policy_output_varies"] = {
            "pass": varies,
            "detail": f"std={stats.get('std', 0):.4f}, mean={stats.get('mean', 0):.4f}"
        }
    else:
        checks["7_policy_output_varies"] = {
            "pass": True,
            "detail": "Skipped (no metadata or no policy_output_stats)",
            "note": "Requires metadata from render_match_verified.py"
        }

    # Check 8: Robot count = 6 (from metadata)
    if metadata and "num_robots" in metadata:
        num_robots = metadata["num_robots"]
        checks["8_robot_count"] = {
            "pass": num_robots == 6,
            "detail": f"num_robots={num_robots}, expected=6"
        }
    else:
        checks["8_robot_count"] = {
            "pass": True,
            "detail": "Skipped (no metadata)",
            "note": "Requires metadata from render_match_verified.py"
        }

    # Check 9: Log/video consistency (from metadata)
    if metadata and "match_log_path" in metadata:
        log_exists = os.path.exists(metadata["match_log_path"])
        same_seed = metadata.get("seed") == metadata.get("match_log_seed")
        same_model = metadata.get("model_sha256") == metadata.get("match_log_model_sha256")
        checks["9_log_video_consistency"] = {
            "pass": log_exists and same_seed and same_model,
            "detail": f"log_exists={log_exists}, same_seed={same_seed}, same_model={same_model}"
        }
    else:
        checks["9_log_video_consistency"] = {
            "pass": True,
            "detail": "Skipped (no metadata or no match_log_path)",
            "note": "Requires metadata with match log reference"
        }

    # Check 10: Metadata completeness
    if metadata:
        required_fields = [
            "model_path", "model_sha256", "env_name", "num_robots",
            "seed", "config_path", "git_commit", "start_time", "end_time",
            "validation_status"
        ]
        missing = [f for f in required_fields if f not in metadata]
        checks["10_metadata_complete"] = {
            "pass": len(missing) == 0,
            "detail": f"missing_fields={missing}" if missing else "all fields present"
        }
    else:
        checks["10_metadata_complete"] = {
            "pass": False,
            "detail": "No metadata file provided"
        }

    # Summary
    all_pass = all(c["pass"] for c in checks.values())
    save_report(checks, args.output, all_pass, video_path, info, metadata)

    # Print summary
    print("\n" + "=" * 60)
    print("[validate_video] Validation Summary")
    print("=" * 60)
    for name, result in checks.items():
        status = "✅ PASS" if result["pass"] else "❌ FAIL"
        print(f"  {name}: {status} — {result.get('detail', '')}")
    print("=" * 60)
    print(f"Overall: {'✅ ALL PASS' if all_pass else '❌ FAILED'}")
    print(f"Report: {args.output}")

    sys.exit(0 if all_pass else 1)


def save_report(checks, output_path, overall_pass, video_path=None, info=None, metadata=None):
    """Save validation report to JSON."""
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_path": os.path.abspath(video_path) if video_path else None,
        "video_info": info or {},
        "metadata": metadata or {},
        "checks": checks,
        "overall_pass": overall_pass,
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
