#!/usr/bin/env python3
"""Generate one generic Phase 2 image with local ComfyUI FLUX.2."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_COMFY_ROOT = Path("/persistent/ComfyUI")
DEFAULT_MODEL = "flux2_dev_fp8mixed.safetensors"
DEFAULT_TEXT_ENCODER = "mistral_3_small_flux2_fp4_mixed.safetensors"
DEFAULT_VAE = "flux2-vae.safetensors"


def node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(server: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        server.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI HTTP {error.code}: {body}") from error


def download_image(server: str, image: dict[str, Any], destination: Path) -> None:
    query = urllib.parse.urlencode(
        {
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    with urllib.request.urlopen(server.rstrip("/") + "/view?" + query, timeout=120) as response:
        destination.write_bytes(response.read())


def add_reference(
    graph: dict[str, Any], node_number: int, image_name: str, conditioning: list[Any]
) -> tuple[list[Any], int]:
    load_id, encode_id, reference_id = (str(node_number + offset) for offset in range(3))
    graph[load_id] = node("LoadImage", image=image_name)
    graph[encode_id] = node(
        "VAEEncodeTiled",
        pixels=[load_id, 0],
        vae=["3", 0],
        tile_size=512,
        overlap=64,
        temporal_size=64,
        temporal_overlap=8,
    )
    graph[reference_id] = node("ReferenceLatent", conditioning=conditioning, latent=[encode_id, 0])
    return [reference_id, 0], node_number + 3


def build_workflow(args: argparse.Namespace, references: list[str], start_image: str | None) -> tuple[dict[str, Any], str]:
    graph: dict[str, Any] = {
        "1": node("UNETLoader", unet_name=args.model, weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=args.text_encoder, type="flux2", device=args.text_encoder_device),
        "3": node("VAELoader", vae_name=args.vae),
        "4": node("CLIPTextEncode", text=args.prompt_text, clip=["2", 0]),
        "5": node("FluxGuidance", conditioning=["4", 0], guidance=args.guidance),
    }
    conditioning: list[Any] = ["5", 0]
    next_id = 6
    for reference in references:
        conditioning, next_id = add_reference(graph, next_id, reference, conditioning)

    guider_id, noise_id, scheduler_id, sampler_select_id = (
        str(next_id + offset) for offset in range(4)
    )
    graph[guider_id] = node("BasicGuider", model=["1", 0], conditioning=conditioning)
    graph[noise_id] = node("RandomNoise", noise_seed=args.seed)
    graph[scheduler_id] = node("Flux2Scheduler", steps=args.steps, width=args.width, height=args.height)
    graph[sampler_select_id] = node("KSamplerSelect", sampler_name=args.sampler)
    next_id += 4
    sigmas: list[Any] = [scheduler_id, 0]
    if args.denoise < 1:
        split_id = str(next_id)
        graph[split_id] = node("SplitSigmasDenoise", sigmas=sigmas, denoise=args.denoise)
        sigmas = [split_id, 1]
        next_id += 1

    if start_image:
        load_id, encode_id = str(next_id), str(next_id + 1)
        graph[load_id] = node("LoadImage", image=start_image)
        graph[encode_id] = node(
            "VAEEncodeTiled", pixels=[load_id, 0], vae=["3", 0], tile_size=512,
            overlap=64, temporal_size=64, temporal_overlap=8,
        )
        latent: list[Any] = [encode_id, 0]
        next_id += 2
    else:
        latent_id = str(next_id)
        graph[latent_id] = node("EmptyFlux2LatentImage", width=args.width, height=args.height, batch_size=1)
        latent = [latent_id, 0]
        next_id += 1

    sampler_id, decode_id, save_id = str(next_id), str(next_id + 1), str(next_id + 2)
    graph[sampler_id] = node(
        "SamplerCustomAdvanced",
        noise=[noise_id, 0], guider=[guider_id, 0], sampler=[sampler_select_id, 0],
        sigmas=sigmas, latent_image=latent,
    )
    graph[decode_id] = node(
        "VAEDecodeTiled", samples=[sampler_id, 0], vae=["3", 0], tile_size=512,
        overlap=64, temporal_size=64, temporal_overlap=8,
    )
    graph[save_id] = node("SaveImage", images=[decode_id, 0], filename_prefix=args.output_prefix)
    return graph, save_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, action="append", required=True, help="repeat in semantic priority order")
    parser.add_argument("--start-image", type=Path)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--text-encoder", default=DEFAULT_TEXT_ENCODER)
    parser.add_argument("--vae", default=DEFAULT_VAE)
    parser.add_argument("--text-encoder-device", choices=("default", "cpu"), default="cpu")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=4.0)
    parser.add_argument("--sampler", default="euler")
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument("--denoise", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.width % 32 or args.height % 32:
        parser.error("width and height must be multiples of 32")
    if not 0 < args.denoise <= 1:
        parser.error("denoise must be in (0, 1]")
    return args


def main() -> int:
    args = parse_args()
    references = [path.resolve() for path in args.reference]
    start = args.start_image.resolve() if args.start_image else None
    for path in [*references, args.prompt.resolve(), *([start] if start else [])]:
        if not path.is_file():
            raise FileNotFoundError(path)
    args.prompt_text = args.prompt.read_text(encoding="utf-8").strip()
    if not args.prompt_text:
        raise ValueError("prompt is empty")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workflow_path = (args.workflow or output.parent / "workflow_api.json").resolve()
    metadata_path = (args.metadata or output.parent / "generation.json").resolve()
    comfy_input = args.comfy_root.resolve() / "input"
    comfy_input.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256((str(output) + str(args.seed)).encode()).hexdigest()[:12]
    copied_references: list[str] = []
    for index, source in enumerate(references, start=1):
        destination = comfy_input / f"phase2_{token}_ref{index}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        copied_references.append(destination.name)
    copied_start = None
    if start:
        destination = comfy_input / f"phase2_{token}_start{start.suffix.lower()}"
        shutil.copy2(start, destination)
        copied_start = destination.name
    args.output_prefix = f"live_science_phase2/{token}"
    workflow, save_node = build_workflow(args, copied_references, copied_start)
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata: dict[str, Any] = {
        "status": "prepared" if args.prepare_only else "queued",
        "engine": "local ComfyUI FLUX.2",
        "model": args.model,
        "textEncoder": args.text_encoder,
        "vae": args.vae,
        "settings": {"width": args.width, "height": args.height, "steps": args.steps, "guidance": args.guidance, "sampler": args.sampler, "seed": args.seed, "denoise": args.denoise},
        "sources": [{"path": str(path), "sha256": sha256(path)} for path in references],
        "workflow": str(workflow_path),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.prepare_only:
        print(workflow_path)
        return 0

    request_json(args.server, "/system_stats")
    queue = request_json(args.server, "/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not empty; refusing to add a GPU-heavy job")
    queued = request_json(args.server, "/prompt", {"prompt": workflow, "client_id": "live-science-phase2"})
    prompt_id = queued["prompt_id"]
    print(f"Queued FLUX.2 prompt: {prompt_id}", flush=True)
    started = time.monotonic()
    next_update = 0.0
    minimum_free = None
    image_record: dict[str, Any] | None = None
    while time.monotonic() - started <= args.timeout:
        elapsed = time.monotonic() - started
        history = request_json(args.server, f"/history/{prompt_id}")
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI generation failed: " + json.dumps(status, ensure_ascii=False))
            images = record.get("outputs", {}).get(save_node, {}).get("images", [])
            if images:
                image_record = images[0]
                break
        if elapsed >= next_update:
            stats = request_json(args.server, "/system_stats")
            device = stats.get("devices", [{}])[0]
            free = float(device.get("vram_free", 0)) / (1024 ** 3)
            minimum_free = free if minimum_free is None else min(minimum_free, free)
            print(f"FLUX.2 generating: {elapsed / 60:.1f} min; reported free VRAM {free:.1f} GiB", flush=True)
            next_update = elapsed + 20
        time.sleep(5)
    if image_record is None:
        raise TimeoutError(f"generation exceeded {args.timeout} seconds")
    download_image(args.server, image_record, output)
    metadata.update({
        "status": "complete", "promptId": prompt_id,
        "generationSeconds": round(time.monotonic() - started, 3),
        "minimumReportedFreeVramGiB": None if minimum_free is None else round(minimum_free, 3),
        "output": str(output), "outputSha256": sha256(output),
    })
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
