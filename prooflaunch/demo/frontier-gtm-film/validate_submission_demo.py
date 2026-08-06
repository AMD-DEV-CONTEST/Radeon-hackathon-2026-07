from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_FFPROBE = Path("ffprobe")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path, ffprobe: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight",
        type=Path,
        default=ROOT.parents[1] / "evidence/v10/radeon-live-preflight.json",
    )
    parser.add_argument(
        "--execution-receipt",
        type=Path,
        default=ROOT / "radeon/radeon-demo-execution-receipt.json",
    )
    parser.add_argument(
        "--subtitles",
        type=Path,
        default=ROOT / "subtitles/frontier-gtm-demo-en.srt",
    )
    parser.add_argument("--final", type=Path, default=ROOT / "dist/frontier-gtm-demo-en.mp4")
    parser.add_argument("--ffprobe", type=Path, default=DEFAULT_FFPROBE)
    args = parser.parse_args()

    checks: dict[str, Any] = {}
    preflight = read_json(args.preflight) if args.preflight.exists() else {}
    checks["radeon_preflight_exists"] = args.preflight.is_file()
    checks["radeon_runtime_observed"] = preflight.get("radeon_runtime_observed") is True
    checks["bf16_matmul_observed"] = preflight.get("bf16_matmul_observed") is True
    checks["backward_observed"] = preflight.get("backward_observed") is True
    checks["sdpa_observed"] = preflight.get("sdpa_observed") is True
    checks["preflight_passed"] = preflight.get("preflight_passed") is True

    execution = read_json(args.execution_receipt) if args.execution_receipt.exists() else {}
    checks["execution_receipt_exists"] = args.execution_receipt.is_file()
    checks["project_execution_observed"] = execution.get("execution_observed") is True
    required_execution_fields = (
        "observed_at",
        "exact_command",
        "exit_code",
        "gpu_name",
        "rocm_version",
        "hip_version",
        "torch_version",
        "total_vram_bytes",
        "peak_vram_bytes",
        "latency_ms",
        "model_or_workload_id",
        "model_revision",
        "output_path",
        "output_bytes",
        "output_sha256",
        "continuous_capture_path",
        "continuous_capture_sha256",
    )
    checks["execution_fields_complete"] = all(execution.get(key) is not None for key in required_execution_fields)

    if execution.get("output_path"):
        output = Path(execution["output_path"])
        checks["execution_output_exists"] = output.is_file()
        checks["execution_output_hash_matches"] = output.is_file() and sha256_file(output) == execution.get(
            "output_sha256"
        )
    else:
        checks["execution_output_exists"] = False
        checks["execution_output_hash_matches"] = False

    if execution.get("continuous_capture_path"):
        capture = Path(execution["continuous_capture_path"])
        checks["continuous_capture_exists"] = capture.is_file()
        checks["continuous_capture_hash_matches"] = capture.is_file() and sha256_file(capture) == execution.get(
            "continuous_capture_sha256"
        )
    else:
        checks["continuous_capture_exists"] = False
        checks["continuous_capture_hash_matches"] = False

    subtitle_text = args.subtitles.read_text(encoding="utf-8") if args.subtitles.exists() else ""
    checks["english_subtitles_exist"] = bool(subtitle_text.strip())
    checks["no_radeon_placeholder"] = "RADEON CAPTURE REQUIRED" not in subtitle_text
    checks["no_unobserved_claim_in_subtitles"] = "execution observed: false" not in subtitle_text.lower()

    checks["final_exists"] = args.final.is_file()
    final_probe: dict[str, Any] = {}
    if args.final.is_file() and args.ffprobe.is_file():
        final_probe = probe(args.final, args.ffprobe)
        duration = float(final_probe.get("format", {}).get("duration", 0))
        streams = final_probe.get("streams", [])
        checks["final_duration_3_to_5_minutes"] = 180 <= duration <= 300
        checks["final_has_h264_video"] = any(
            stream.get("codec_type") == "video" and stream.get("codec_name") == "h264" for stream in streams
        )
        checks["final_has_aac_audio"] = any(
            stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac" for stream in streams
        )
        checks["final_is_at_least_1080p"] = any(
            stream.get("codec_type") == "video"
            and int(stream.get("width", 0)) >= 1920
            and int(stream.get("height", 0)) >= 1080
            for stream in streams
        )
    else:
        checks["final_duration_3_to_5_minutes"] = False
        checks["final_has_h264_video"] = False
        checks["final_has_aac_audio"] = False
        checks["final_is_at_least_1080p"] = False

    passed = all(checks.values())
    report = {
        "schema": "FrontierGTMSubmissionDemoGateV1",
        "passed": passed,
        "checks": checks,
        "final_probe": final_probe,
        "truth_boundary": (
            "A pass requires genuine Radeon runtime and project execution receipts, matching output and capture "
            "hashes, completed English subtitles, and a playable 3–5 minute H.264/AAC final master."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
