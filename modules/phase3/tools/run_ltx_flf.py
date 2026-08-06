#!/usr/bin/env python3
"""Run one conservative local LTX-2.3 first/last-frame segment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


COMFY_ROOT = Path("/persistent/ComfyUI")
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_OUTPUT = COMFY_ROOT / "output"
CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"
TEXT_ENCODER = "gemma_3_12B_it_fp4_mixed.safetensors"
DISTILLED_LORA = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"
SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"


def node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI HTTP {error.code}: {body}") from error


def find_video(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        filename = value.get("filename")
        if isinstance(filename, str) and filename.lower().endswith(".mp4"):
            return value
        for child in value.values():
            found = find_video(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_video(child)
            if found:
                return found
    return None


def parse_prompt(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    marker = "\nNEGATIVE\n"
    if not text.startswith("POSITIVE\n") or marker not in text:
        raise ValueError("prompt.txt must contain POSITIVE and NEGATIVE sections")
    positive, negative = text[len("POSITIVE\n"):].split(marker, 1)
    return positive.strip(), negative.strip()


def build_workflow(segment: dict[str, Any], first_name: str, last_name: str, positive: str, negative: str) -> dict[str, Any]:
    settings = segment["settings"]
    width, height = int(settings["width"]), int(settings["height"])
    fps, frame_count = float(settings["fps"]), int(settings["frameCount"])
    if frame_count % 8 != 1:
        raise ValueError("LTX frameCount must equal 8n+1")
    return {
        "1": node("CheckpointLoaderSimple", ckpt_name=CHECKPOINT),
        "2": node("LTXAVTextEncoderLoader", text_encoder=TEXT_ENCODER, ckpt_name=CHECKPOINT, device="default"),
        "3": node("CLIPTextEncode", text=positive, clip=["2", 0]),
        "4": node("CLIPTextEncode", text=negative, clip=["2", 0]),
        "5": node("LTXVConditioning", positive=["3", 0], negative=["4", 0], frame_rate=fps),
        "6": node("LoraLoaderModelOnly", model=["1", 0], lora_name=DISTILLED_LORA, strength_model=float(settings["loraStrength"])),
        "7": node("LTXVAudioVAELoader", ckpt_name=CHECKPOINT),
        "8": node("LoadImage", image=first_name),
        "9": node("LoadImage", image=last_name),
        "10": node("ImageScale", image=["8", 0], upscale_method="bicubic", width=width, height=height, crop="center"),
        "11": node("ImageScale", image=["9", 0], upscale_method="bicubic", width=width, height=height, crop="center"),
        "12": node("LTXVPreprocess", image=["10", 0], img_compression=int(settings["imageCompression"])),
        "13": node("LTXVPreprocess", image=["11", 0], img_compression=int(settings["imageCompression"])),
        "14": node("EmptyLTXVLatentVideo", width=width, height=height, length=frame_count, batch_size=1),
        "15": node("LTXVEmptyLatentAudio", frames_number=frame_count, frame_rate=fps, batch_size=1, audio_vae=["7", 0]),
        "16": node("LTXVAddGuide", positive=["5", 0], negative=["5", 1], vae=["1", 2], latent=["14", 0], image=["12", 0], frame_idx=0, strength=float(settings["guideStrength"])),
        "17": node("LTXVAddGuide", positive=["16", 0], negative=["16", 1], vae=["1", 2], latent=["16", 2], image=["13", 0], frame_idx=-1, strength=float(settings["guideStrength"])),
        "18": node("LTXVConcatAVLatent", video_latent=["17", 2], audio_latent=["15", 0]),
        "19": node("RandomNoise", noise_seed=int(settings["seed"])),
        "20": node("CFGGuider", model=["6", 0], positive=["17", 0], negative=["17", 1], cfg=1.0),
        "21": node("SamplerEulerAncestral", eta=0.0, s_noise=1.0),
        "22": node("ManualSigmas", sigmas=SIGMAS),
        "23": node("SamplerCustomAdvanced", noise=["19", 0], guider=["20", 0], sampler=["21", 0], sigmas=["22", 0], latent_image=["18", 0]),
        "24": node("LTXVSeparateAVLatent", av_latent=["23", 1]),
        "25": node("LTXVCropGuides", positive=["17", 0], negative=["17", 1], latent=["24", 0]),
        "26": node("VAEDecodeTiled", samples=["25", 2], vae=["1", 2], tile_size=768, overlap=64, temporal_size=64, temporal_overlap=4),
        "27": node("LTXVAudioVAEDecode", samples=["24", 1], audio_vae=["7", 0]),
        "28": node("CreateVideo", images=["26", 0], audio=["27", 0], fps=fps, bit_depth=8),
        "29": node("SaveVideo", video=["28", 0], filename_prefix=segment["outputPrefix"], format="mp4", codec="h264"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--segment-id")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    if args.segment_id:
        matches = [item for item in timeline["segments"] if item["id"] == args.segment_id]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one segment {args.segment_id!r}, found {len(matches)}")
        segment = matches[0]
    else:
        segment = timeline["segments"][0]
    segment_dir = run_dir / "segments" / segment["id"]
    start, end = segment_dir / "start.png", segment_dir / "end.png"
    positive, negative = parse_prompt(segment_dir / "prompt.txt")
    for path in (start, end, COMFY_ROOT / "models/checkpoints" / CHECKPOINT, COMFY_ROOT / "models/text_encoders" / TEXT_ENCODER, COMFY_ROOT / "models/loras" / DISTILLED_LORA):
        if not path.is_file():
            raise FileNotFoundError(path)
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    safe_run = "".join(ch if ch.isalnum() else "_" for ch in run_dir.name)
    safe_segment = "".join(ch if ch.isalnum() else "_" for ch in segment["id"])
    first_input = COMFY_INPUT / f"phase3_{safe_run}_{safe_segment}_start.png"
    last_input = COMFY_INPUT / f"phase3_{safe_run}_{safe_segment}_end.png"
    shutil.copy2(start, first_input)
    shutil.copy2(end, last_input)
    workflow = build_workflow(segment, first_input.name, last_input.name, positive, negative)
    workflow_path = segment_dir / "workflow_api.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prepared = {
        "status": "prepared" if args.prepare_only else "queued",
        "engine": "local ComfyUI LTX-2.3 first/last-frame",
        "model": CHECKPOINT,
        "textEncoder": TEXT_ENCODER,
        "distilledLora": DISTILLED_LORA,
        "settings": segment["settings"],
        "source": {"start": str(start), "startSha256": sha256(start), "end": str(end), "endSha256": sha256(end)},
        "workflow": str(workflow_path),
    }
    (segment_dir / "generation.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.prepare_only:
        print(workflow_path)
        return 0
    request_json(f"{args.server}/system_stats")
    queue = request_json(f"{args.server}/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not empty; refusing to add a GPU-heavy job")
    queued = request_json(f"{args.server}/prompt", {"prompt": workflow})
    prompt_id = queued["prompt_id"]
    print(f"Queued LTX-2.3 prompt: {prompt_id}", flush=True)
    started = time.monotonic()
    next_update = 0.0
    while True:
        elapsed = time.monotonic() - started
        if elapsed > args.timeout:
            raise TimeoutError(f"generation exceeded {args.timeout} seconds")
        history = request_json(f"{args.server}/history/{prompt_id}")
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI generation failed: " + json.dumps(status, ensure_ascii=False))
            video_record = find_video(record.get("outputs", {}))
            if video_record:
                break
        if elapsed >= next_update:
            stats = request_json(f"{args.server}/system_stats")
            device = stats.get("devices", [{}])[0]
            free_gib = float(device.get("vram_free", 0)) / (1024 ** 3)
            print(f"LTX-2.3 generating: {elapsed / 60:.1f} min; reported free VRAM {free_gib:.1f} GiB", flush=True)
            next_update = elapsed + 20
        time.sleep(5)
    source_video = COMFY_OUTPUT / video_record.get("subfolder", "") / video_record["filename"]
    if not source_video.is_file():
        raise FileNotFoundError(source_video)
    segment_video = segment_dir / "video.mp4"
    shutil.copy2(source_video, segment_video)
    prepared.update({
        "status": "complete",
        "promptId": prompt_id,
        "generationSeconds": round(time.monotonic() - started, 3),
        "comfyOutput": str(source_video),
        "video": str(segment_video),
        "videoSha256": sha256(segment_video),
    })
    (segment_dir / "generation.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(segment_video)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
