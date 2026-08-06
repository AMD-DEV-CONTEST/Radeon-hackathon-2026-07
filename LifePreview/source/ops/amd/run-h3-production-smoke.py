#!/usr/bin/env python3
"""Run one production-shape MiniMax H3 Ref2VA smoke against local ComfyUI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4


HARD_MEMORY_MAX_BYTES = 59_055_800_320
ADMISSION_REJECT_BYTES = 47_244_640_256
DEFAULT_RUN_TIMEOUT_SECONDS = 25_200
EXPECTED_TEMPLATE_SHA256 = (
    "f85fc557edcb22f2ca191867e96bc4551ba32755b133271e295a5ff471018789"
)
EXPECTED_H3_FILES = {
    "H3_DIFFUSION": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "H3_TEXT_ENCODER": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "H3_VIDEO_VAE": "minimax_h3_video_vae_fp16.safetensors",
    "H3_AUDIO_VAE": "minimax_h3_audio_vae_fp32.safetensors",
}
REQUIRED_NODES = {
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "MiniMaxH3SigmaShift",
    "MiniMaxH3ReferenceToVideo",
    "RandomNoise",
    "KSamplerSelect",
    "BasicScheduler",
    "BasicGuider",
    "SamplerCustomAdvanced",
    "VAEDecode",
    "VAEDecodeAudio",
    "CreateVideo",
    "SaveVideo",
    "LoadImage",
}
PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
PROMPT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,199}$")


class SmokeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_resume_queue(
    path: Path,
    *,
    expected_workflow_sha256: str,
) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError("resume queue evidence is unreadable") from exc
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "promptId",
        "submissionNonce",
        "workflowSha256",
        "templateSha256",
        "startedAt",
        "beforeSubmission",
    }:
        raise SmokeError("resume queue evidence fields are not frozen")
    if value.get("schemaVersion") != "amd.h3-production-smoke-queue.v1":
        raise SmokeError("resume queue evidence schema is not frozen")
    prompt_id = value.get("promptId")
    if not isinstance(prompt_id, str) or PROMPT_ID_PATTERN.fullmatch(prompt_id) is None:
        raise SmokeError("resume prompt id is unsafe")
    nonce = value.get("submissionNonce")
    if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
        raise SmokeError("resume submission nonce is unsafe")
    workflow_sha256 = value.get("workflowSha256")
    if (
        not isinstance(workflow_sha256, str)
        or SHA256_PATTERN.fullmatch(workflow_sha256) is None
        or workflow_sha256 != expected_workflow_sha256
    ):
        raise SmokeError("resume workflow digest does not match the frozen graph")
    if value.get("templateSha256") != EXPECTED_TEMPLATE_SHA256:
        raise SmokeError("resume template digest does not match the frozen template")
    started_at = value.get("startedAt")
    try:
        parsed_started_at = datetime.fromisoformat(str(started_at))
    except ValueError as exc:
        raise SmokeError("resume start time is invalid") from exc
    if parsed_started_at.tzinfo is None or parsed_started_at.utcoffset() is None:
        raise SmokeError("resume start time must be timezone-aware")
    if not isinstance(value.get("beforeSubmission"), dict):
        raise SmokeError("resume admission snapshot is invalid")
    return value


def _read_int(path: str) -> int:
    raw = Path(path).read_text(encoding="ascii").strip()
    if raw == "max":
        raise SmokeError(f"{path} must not be unlimited")
    return int(raw)


def _memory_events() -> dict[str, int]:
    path = Path("/sys/fs/cgroup/memory.events.local")
    if not path.exists():
        path = Path("/sys/fs/cgroup/memory.events")
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, raw = line.split()
        values[key] = int(raw)
    required = {"low", "high", "max", "oom", "oom_kill", "oom_group_kill"}
    if not required.issubset(values):
        raise SmokeError("cgroup memory.events is incomplete")
    return values


def _memory_stat() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/sys/fs/cgroup/memory.stat").read_text(
        encoding="ascii"
    ).splitlines():
        key, raw = line.split()
        if key in {"anon", "file", "kernel"}:
            values[key] = int(raw)
    if set(values) != {"anon", "file", "kernel"}:
        raise SmokeError("cgroup memory.stat is incomplete")
    return values


def _vram() -> dict[str, int | str]:
    completed = subprocess.run(
        [
            "rocm-smi",
            "--showuse",
            "--showmemuse",
            "--showmeminfo",
            "vram",
            "--csv",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    row = next((line for line in reversed(rows) if line.startswith("card")), None)
    if row is None:
        raise SmokeError("rocm-smi returned no GPU row")
    cells = [cell.strip() for cell in row.split(",")]
    if len(cells) < 3:
        raise SmokeError("rocm-smi GPU row is incomplete")
    return {
        "device": cells[0],
        "totalBytes": int(cells[-2]),
        "usedBytes": int(cells[-1]),
    }


def _snapshot() -> dict[str, object]:
    return {
        "capturedAt": _utc_now(),
        "memoryCurrentBytes": _read_int("/sys/fs/cgroup/memory.current"),
        "memoryPeakBytes": _read_int("/sys/fs/cgroup/memory.peak"),
        "memoryMaxBytes": _read_int("/sys/fs/cgroup/memory.max"),
        "memorySwapCurrentBytes": _read_int(
            "/sys/fs/cgroup/memory.swap.current"
        ),
        "memorySwapMaxBytes": _read_int("/sys/fs/cgroup/memory.swap.max"),
        "memoryEvents": _memory_events(),
        "memoryStat": _memory_stat(),
        "vram": _vram(),
    }


def _request_json(
    method: str,
    url: str,
    payload: object | None = None,
    *,
    timeout: float = 30,
) -> Any:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SmokeError(f"ComfyUI request failed: {method} {url}") from exc
    if not body:
        return None
    return json.loads(body)


def _wait_ready(base_url: str, timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = _request_json("GET", f"{base_url}/object_info", timeout=10)
            if isinstance(value, dict):
                missing = sorted(REQUIRED_NODES - set(value))
                if missing:
                    raise SmokeError(
                        "ComfyUI is missing H3 nodes: " + ", ".join(missing)
                    )
                return value
        except Exception as exc:  # readiness retry boundary
            last_error = exc
        time.sleep(2)
    raise SmokeError("ComfyUI did not become H3-ready") from last_error


def _substitute(value: object, replacements: dict[str, object]) -> object:
    if isinstance(value, dict):
        return {key: _substitute(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, replacements) for item in value]
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        key = value[2:-2]
        if key not in replacements:
            raise SmokeError(f"unresolved H3 workflow placeholder: {key}")
        return replacements[key]
    return value


def _compile_workflow(template_path: Path, reference_names: list[str]) -> dict[str, Any]:
    template_sha256 = _sha256(template_path)
    if template_sha256 != EXPECTED_TEMPLATE_SHA256:
        raise SmokeError("H3 workflow template SHA-256 is not frozen")
    graph = json.loads(template_path.read_text(encoding="utf-8"))
    for node_id in ("19", "20", "21", "22", "23", "24"):
        graph.pop(node_id)
    conditioning = graph["6"]["inputs"]
    for index in range(3, 9):
        conditioning.pop(f"ref_images.ref_image_{index}")
    replacements: dict[str, object] = {
        **EXPECTED_H3_FILES,
        "SHIFT_VIDEO": 12.0,
        "SHIFT_AUDIO": 3.0,
        "PROMPT": (
            "A dignified young Chinese historical scholar in pale blue Hanfu "
            "stands in a quiet palace corridor, turns toward the camera, "
            "speaks one short Mandarin greeting with natural lip movement, "
            "then walks two measured steps. Stable identity, realistic fabric, "
            "cinematic soft daylight, fixed camera, no subtitles, no text."
        ),
        "WIDTH": 1344,
        "HEIGHT": 768,
        "FRAME_COUNT": 192,
        "SEED": 2026080604,
        "SAMPLER": "res_multistep",
        "SCHEDULER": "simple",
        "STEPS": 20,
        "DENOISE": 1.0,
        "FPS": 24.0,
        "FILENAME_PREFIX": "h3-production-smoke/h3-ref2va-8s",
    }
    for index, name in enumerate(reference_names, start=1):
        replacements[f"REF_IMAGE_{index}"] = name
    concrete = _substitute(graph, replacements)
    serialized = json.dumps(concrete, ensure_ascii=False, allow_nan=False)
    if PLACEHOLDER_PATTERN.search(serialized):
        raise SmokeError("compiled H3 workflow still has placeholders")
    return concrete


def _reference_names(sources: list[Path]) -> list[str]:
    if len(sources) != 3:
        raise SmokeError("formal H3 smoke requires exactly three references")
    names: list[str] = []
    for ordinal, source in enumerate(sources, start=1):
        if not source.is_file() or source.suffix.lower() != ".png":
            raise SmokeError(f"reference {ordinal} is not a PNG file")
        name = f"h3-smoke-reference-{ordinal}-{_sha256(source)[:12]}.png"
        names.append(name)
    return names


def _stage_references(sources: list[Path], input_root: Path) -> list[str]:
    names = _reference_names(sources)
    input_root.mkdir(parents=True, exist_ok=True)
    for ordinal, (source, name) in enumerate(zip(sources, names, strict=True), start=1):
        destination = input_root / name
        shutil.copyfile(source, destination)
        if _sha256(destination) != _sha256(source):
            raise SmokeError(f"reference {ordinal} staging digest mismatch")
    return names


def _find_video(history: dict[str, object], output_root: Path) -> Path:
    outputs = history.get("outputs")
    if not isinstance(outputs, dict):
        raise SmokeError("ComfyUI history has no outputs")
    node_output = outputs.get("15")
    if not isinstance(node_output, dict):
        raise SmokeError("ComfyUI history has no SaveVideo output")
    candidates: list[dict[str, object]] = []
    for value in node_output.values():
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    for item in candidates:
        filename = item.get("filename")
        subfolder = item.get("subfolder", "")
        output_type = item.get("type")
        if (
            isinstance(filename, str)
            and filename.endswith(".mp4")
            and PurePosixPath(filename).name == filename
            and isinstance(subfolder, str)
            and ".." not in PurePosixPath(subfolder).parts
            and output_type == "output"
        ):
            path = output_root.joinpath(*PurePosixPath(subfolder).parts, filename)
            resolved = path.resolve(strict=True)
            resolved.relative_to(output_root.resolve(strict=True))
            return resolved
    raise SmokeError("ComfyUI SaveVideo did not return an MP4")


def _probe(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    probe = json.loads(completed.stdout)
    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise SmokeError("ffprobe returned no streams")
    video = next(
        (item for item in streams if item.get("codec_type") == "video"), None
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"), None
    )
    if video is None or audio is None:
        raise SmokeError("H3 MP4 must contain native video and audio streams")
    if video.get("avg_frame_rate") not in {"24/1", "48/2"}:
        raise SmokeError("H3 MP4 frame rate is not 24 fps")
    duration = float(probe.get("format", {}).get("duration", 0))
    if not 7.5 <= duration <= 8.5:
        raise SmokeError(f"H3 MP4 duration is unexpected: {duration}")
    return probe


def _validate_admission(snapshot: dict[str, object]) -> None:
    if snapshot["memoryMaxBytes"] != HARD_MEMORY_MAX_BYTES:
        raise SmokeError("memory.max does not match the frozen 55 GiB contract")
    if snapshot["memorySwapCurrentBytes"] != 0 or snapshot["memorySwapMaxBytes"] != 0:
        raise SmokeError("swap must be disabled")
    if int(snapshot["memoryCurrentBytes"]) >= ADMISSION_REJECT_BYTES:
        raise SmokeError("memory is at or above the 80% admission wall")
    events = snapshot["memoryEvents"]
    if not isinstance(events, dict) or any(
        int(events[key]) != 0 for key in ("oom", "oom_kill", "oom_group_kill")
    ):
        raise SmokeError("OOM counters require recovery before H3 admission")


def _queue_is_empty(base_url: str) -> bool:
    queue = _request_json("GET", f"{base_url}/queue", timeout=10)
    if not isinstance(queue, dict):
        return False
    running = queue.get("queue_running", [])
    pending = queue.get("queue_pending", [])
    return isinstance(running, list) and isinstance(pending, list) and not running and not pending


def run(args: argparse.Namespace) -> dict[str, object]:
    runtime_root = args.runtime_root.resolve()
    input_root = runtime_root / "input"
    output_root = runtime_root / "output"
    evidence_root = args.evidence_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)

    _wait_ready(args.comfy_url, args.ready_timeout_seconds)
    names = (
        _reference_names(args.reference)
        if args.resume_queued is not None
        else _stage_references(args.reference, input_root)
    )
    workflow = _compile_workflow(args.template, names)
    workflow_sha256 = _canonical_sha256(workflow)
    resume_snapshot: dict[str, object] | None = None
    if args.resume_queued is not None:
        queued = _load_resume_queue(
            args.resume_queued.resolve(),
            expected_workflow_sha256=workflow_sha256,
        )
        prompt_id = str(queued["promptId"])
        submission_nonce = str(queued["submissionNonce"])
        started_at = str(queued["startedAt"])
        before = dict(queued["beforeSubmission"])
        resume_snapshot = _snapshot()
    else:
        if not _queue_is_empty(args.comfy_url):
            raise SmokeError("ComfyUI already has a running or pending prompt")
        before = _snapshot()
        _validate_admission(before)
        client_id = f"h3-production-smoke-{uuid4().hex}"
        submission_nonce = uuid4().hex
        started_at = _utc_now()
        response = _request_json(
            "POST",
            f"{args.comfy_url}/prompt",
            {
                "prompt": workflow,
                "client_id": client_id,
                "extra_data": {
                    "provider": "local-minimax-h3-comfy.smoke",
                    "submission_nonce": submission_nonce,
                    "workflow_digest": workflow_sha256,
                },
            },
            timeout=60,
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("prompt_id"), str
        ):
            raise SmokeError(f"ComfyUI rejected H3 prompt: {response!r}")
        if response.get("node_errors") not in ({}, None):
            raise SmokeError(
                f"ComfyUI reported H3 node errors: {response['node_errors']!r}"
            )
        prompt_id = response["prompt_id"]
        _atomic_json(
            evidence_root / "queued.json",
            {
                "schemaVersion": "amd.h3-production-smoke-queue.v1",
                "promptId": prompt_id,
                "submissionNonce": submission_nonce,
                "workflowSha256": workflow_sha256,
                "templateSha256": EXPECTED_TEMPLATE_SHA256,
                "startedAt": started_at,
                "beforeSubmission": before,
            },
        )

    deadline = time.monotonic() + args.run_timeout_seconds
    initial_observation = resume_snapshot or before
    peak_vram = int(initial_observation["vram"]["usedBytes"])
    max_current = max(
        int(before["memoryCurrentBytes"]),
        int(initial_observation["memoryCurrentBytes"]),
    )
    latest_history: dict[str, object] | None = None
    while time.monotonic() < deadline:
        sample = _snapshot()
        peak_vram = max(peak_vram, int(sample["vram"]["usedBytes"]))
        max_current = max(max_current, int(sample["memoryCurrentBytes"]))
        history_root = _request_json(
            "GET", f"{args.comfy_url}/history/{prompt_id}", timeout=20
        )
        if isinstance(history_root, dict) and isinstance(
            history_root.get(prompt_id), dict
        ):
            latest_history = history_root[prompt_id]
            status = latest_history.get("status")
            completed = isinstance(status, dict) and status.get("completed") is True
            if completed:
                break
        time.sleep(args.poll_seconds)
    if latest_history is None:
        raise SmokeError("H3 prompt did not reach history before timeout")
    status = latest_history.get("status")
    if not isinstance(status, dict) or status.get("status_str") != "success":
        raise SmokeError(f"H3 prompt failed: {status!r}")

    source = _find_video(latest_history, output_root)
    destination = evidence_root / "h3-ref2va-8s.mp4"
    temporary = destination.with_suffix(".mp4.partial")
    shutil.copyfile(source, temporary)
    source_sha256 = _sha256(source)
    output_sha256 = _sha256(temporary)
    if output_sha256 != source_sha256:
        raise SmokeError("H3 MP4 digest changed during evidence copy")
    probe = _probe(temporary)
    os.replace(temporary, destination)

    completed_at = _utc_now()
    after_completion = _snapshot()
    _request_json(
        "POST",
        f"{args.comfy_url}/free",
        {"unload_models": True, "free_memory": True},
        timeout=30,
    )
    time.sleep(5)
    after_free = _snapshot()
    result = {
        "schemaVersion": "amd.h3-production-smoke-result.v1",
        "status": "succeeded",
        "modelFamily": "minimax-h3",
        "modelRevision": "h3-amd-local-v1",
        "mode": "ref2va",
        "width": 1344,
        "height": 768,
        "fps": 24,
        "frameCount": 192,
        "steps": 20,
        "nativeAudio": True,
        "subtitles": False,
        "promptId": prompt_id,
        "submissionNonce": submission_nonce,
        "templateSha256": EXPECTED_TEMPLATE_SHA256,
        "compiledWorkflowSha256": workflow_sha256,
        "startedAt": started_at,
        "completedAt": completed_at,
        "elapsedSeconds": round(
            (
                datetime.fromisoformat(completed_at)
                - datetime.fromisoformat(started_at)
            ).total_seconds(),
            3,
        ),
        "peakUsedVramMiB": peak_vram // (1024 * 1024),
        "maxObservedMemoryCurrentBytes": max_current,
        "outputPath": str(destination),
        "outputBytes": destination.stat().st_size,
        "outputSha256": output_sha256,
        "referenceSha256": [_sha256(path) for path in args.reference],
        "resourceSnapshots": {
            "beforeSubmission": before,
            **(
                {"resumeAttachment": resume_snapshot}
                if resume_snapshot is not None
                else {}
            ),
            "afterCompletion": after_completion,
            "afterFree": after_free,
        },
        "ffprobe": probe,
    }
    _atomic_json(evidence_root / "result.json", result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", required=True)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:18188")
    parser.add_argument("--ready-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--run-timeout-seconds",
        type=int,
        default=DEFAULT_RUN_TIMEOUT_SECONDS,
    )
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--resume-queued", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = run(args)
    except Exception as exc:
        error = {
            "schemaVersion": "amd.h3-production-smoke-error.v1",
            "status": "failed",
            "recordedAt": _utc_now(),
            "errorType": type(exc).__name__,
            "error": str(exc),
        }
        _atomic_json(args.evidence_root / "error.json", error)
        print(json.dumps(error, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
