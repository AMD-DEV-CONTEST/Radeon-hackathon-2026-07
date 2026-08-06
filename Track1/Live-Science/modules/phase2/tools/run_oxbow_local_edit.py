#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage


SERVER = "http://127.0.0.1:8188"
COMFY_INPUT = Path("/workspace/persistent/ComfyUI/input")
MODEL = "flux2_dev_fp8mixed.safetensors"
TEXT_ENCODER = "mistral_3_small_flux2_fp4_mixed.safetensors"
VAE = "flux2-vae.safetensors"
SEED = 271828
STEPS = 20
GUIDANCE = 4.0
SAMPLER = "euler"
FULL_SIZE = (1024, 576)
PATCH_MODEL_SIZE = (704, 768)
BEFORE_STYLE_SIZE = (320, 180)
PATCH_APPEARANCE_SIZE = (352, 384)
PATCH_STYLE_SIZE = (256, 288)
DIFF_THRESHOLD = 32
MASK_DILATION_SOURCE_PX = 40
BBOX_BUFFER_FRACTION = 0.20
VAE_TILE_SIZE = 512
VAE_TILE_OVERLAP = 64

BEFORE_PROMPT = """Transform this scientific river diagram into a realistic top-down aerial view of the same floodplain.

Image 1 defines the exact water-land geometry and channel connectivity. Preserve it precisely. The active cutoff channel crosses the lower part of the meander neck, while the abandoned meander is still connected to the active river by visible water openings at both entrances. Keep both entrances open. Do not isolate the old channel yet.

Image 2 defines only the natural environmental appearance: realistic dark river water, irregular wet sand and mud along banks, floodplain grass and shrubs, soft daylight, and fixed aerial scale.

Preserve the exact position and shape of every channel, the fixed top-down camera, the surrounding terrain, and the complete connected old meander. Render natural bank-connected sediment and shoreline texture without introducing plugs across either entrance.

No text, arrows, flow lines, white particles, diagram symbols, roads, buildings, boats, people, new tributaries, geometric patches, or disconnected water."""

PATCH_PROMPT = """Transform this local river section into a scientifically accurate realistic
top-down aerial view of the same floodplain.

Image 1 defines the exact final water-land geometry and channel connectivity.
Preserve it precisely. The abandoned meander must be fully separated from
the active river by continuous land at both former channel entrances.

Image 2 defines the appearance of the same location before isolation:
vegetation, river water, soil, bank texture, lighting and aerial scale.

Image 3 provides only supporting environmental style.

The former channel entrances have been gradually plugged by natural sediment
deposition. Render the plugs as irregular bank-connected sediment terrain:
wet mud and sand near the former water edge, gradually transitioning into
floodplain soil and sparse vegetation.

The sediment must grow continuously from the surrounding banks. It must not
look like floating brown ovals, isolated objects, artificial barriers,
white blobs or geometric patches.

The blue water of the old channel must visibly end before each plug.
There must be a clear continuous land interval between the oxbow lake and
the active river.

Preserve the exact position and crescent shape of the oxbow lake, the active
main river, the fixed top-down camera and the surrounding terrain.

No text, arrows, flow lines, white particles, diagram symbols, roads,
buildings, boats, people, new tributaries or reconnection of the old channel."""


def request_json(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def download_image(image: dict, destination: Path) -> None:
    query = urllib.parse.urlencode(
        {
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    with urllib.request.urlopen(f"{SERVER}/view?{query}", timeout=120) as response:
        destination.write_bytes(response.read())


def disk(radius: int) -> np.ndarray:
    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return x * x + y * y <= radius * radius


def find_moments(manifest_path: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    moments = {moment["id"]: moment for moment in manifest["keyMoments"]}
    candidates = [
        event
        for event in manifest["events"]
        if event.get("type") == "topology_change"
        and ({"old-channel", "oxbow-lake"} & set(event.get("objects", [])))
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one oxbow isolation event, found {len(candidates)}")
    event = candidates[0]
    before = moments[event["preMomentId"]]
    after = moments[event["postMomentId"]]
    if "not sealed" not in before.get("description", ""):
        raise RuntimeError(f"Pre-event description does not describe open entrances: {before}")
    if "sealed" not in after.get("description", "") and "separated" not in after.get("description", ""):
        raise RuntimeError(f"Post-event description does not describe isolation: {after}")
    return manifest, before, after


def clean_path(manifest_path: Path, moment: dict) -> Path:
    bridge_dir = manifest_path.parent
    path = bridge_dir / moment["assets"]["clean"]
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def round_bbox_to_grid(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
    grid: int = 32,
) -> tuple[int, int, int, int]:
    width, height = image_size
    x0 = max(0, int(math.floor(bbox[0] / grid) * grid))
    y0 = max(0, int(math.floor(bbox[1] / grid) * grid))
    x1 = min(width, int(math.ceil(bbox[2] / grid) * grid))
    y1 = min(height, int(math.ceil(bbox[3] / grid) * grid))
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError(f"Invalid rounded bbox {(x0, y0, x1, y1)}")
    return x0, y0, x1, y1


def prepare(manifest_path: Path, world_reference: Path, output_dir: Path) -> dict:
    manifest, before, after = find_moments(manifest_path)
    before_path = clean_path(manifest_path, before)
    after_path = clean_path(manifest_path, after)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "crops").mkdir(exist_ok=True)
    (output_dir / "patches").mkdir(exist_ok=True)
    (output_dir / "composites").mkdir(exist_ok=True)
    (output_dir / "model_inputs").mkdir(exist_ok=True)
    (output_dir / "workflows").mkdir(exist_ok=True)

    before_source = Image.open(before_path).convert("RGB")
    after_source = Image.open(after_path).convert("RGB")
    if before_source.size != after_source.size:
        raise RuntimeError("Before and after clean frames have different sizes")
    a = np.asarray(before_source, dtype=np.int16)
    b = np.asarray(after_source, dtype=np.int16)
    absolute_difference = np.max(np.abs(a - b), axis=2)

    thresholded = absolute_difference > DIFF_THRESHOLD
    thresholded = ndimage.binary_closing(thresholded, structure=disk(4))
    thresholded = ndimage.binary_opening(thresholded, structure=disk(2))
    labels, count = ndimage.label(thresholded)
    components = []
    for label_id, component_slice in enumerate(ndimage.find_objects(labels), start=1):
        if component_slice is None:
            continue
        area = int(np.count_nonzero(labels[component_slice] == label_id))
        if area < 1000:
            continue
        y_slice, x_slice = component_slice
        components.append(
            {
                "label": label_id,
                "area": area,
                "bbox": [x_slice.start, y_slice.start, x_slice.stop, y_slice.stop],
            }
        )
    components.sort(key=lambda component: component["area"], reverse=True)
    selected = components[:2]
    if len(selected) != 2:
        raise RuntimeError(f"Expected two major entrance components, found {components}")

    selected_mask = np.isin(labels, [component["label"] for component in selected])
    edit_mask_source = ndimage.binary_dilation(
        selected_mask,
        structure=disk(MASK_DILATION_SOURCE_PX),
    )
    edit_mask_source = ndimage.binary_closing(edit_mask_source, structure=disk(10))
    ys, xs = np.nonzero(edit_mask_source)
    mask_bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    mask_width = mask_bbox[2] - mask_bbox[0]
    mask_height = mask_bbox[3] - mask_bbox[1]
    buffered_source_bbox = (
        mask_bbox[0] - mask_width * BBOX_BUFFER_FRACTION,
        mask_bbox[1] - mask_height * BBOX_BUFFER_FRACTION,
        mask_bbox[2] + mask_width * BBOX_BUFFER_FRACTION,
        mask_bbox[3] + mask_height * BBOX_BUFFER_FRACTION,
    )

    source_width, source_height = before_source.size
    target_width, target_height = FULL_SIZE
    scaled_bbox = (
        buffered_source_bbox[0] * target_width / source_width,
        buffered_source_bbox[1] * target_height / source_height,
        buffered_source_bbox[2] * target_width / source_width,
        buffered_source_bbox[3] * target_height / source_height,
    )
    bbox = round_bbox_to_grid(scaled_bbox, FULL_SIZE)

    before_full = before_source.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    after_full = after_source.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    mask_source_image = Image.fromarray((edit_mask_source * 255).astype(np.uint8), mode="L")
    mask_full = mask_source_image.resize(FULL_SIZE, Image.Resampling.NEAREST)
    mask_full.save(output_dir / "change_mask.png")

    preview = after_full.convert("RGBA")
    overlay = Image.new("RGBA", FULL_SIZE, (0, 0, 0, 0))
    overlay_array = np.zeros((target_height, target_width, 4), dtype=np.uint8)
    overlay_array[np.asarray(mask_full) > 0] = (255, 52, 52, 72)
    overlay = Image.fromarray(overlay_array, mode="RGBA")
    preview = Image.alpha_composite(preview, overlay)
    draw = ImageDraw.Draw(preview)
    draw.rectangle((bbox[0], bbox[1], bbox[2] - 1, bbox[3] - 1), outline=(255, 32, 32, 255), width=4)
    preview.convert("RGB").save(output_dir / "change_bbox.png")

    crop_paths = {
        "before_clean": output_dir / "crops" / "before_clean.png",
        "after_clean": output_dir / "crops" / "after_clean.png",
        "world_reference": output_dir / "crops" / "world_reference.png",
    }
    before_crop = before_full.crop(bbox)
    after_crop = after_full.crop(bbox)
    world_full = Image.open(world_reference).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS)
    world_crop = world_full.crop(bbox)
    before_crop.save(crop_paths["before_clean"])
    after_crop.save(crop_paths["after_clean"])
    world_crop.save(crop_paths["world_reference"])

    model_inputs = output_dir / "model_inputs"
    before_full.resize(FULL_SIZE, Image.Resampling.LANCZOS).save(model_inputs / "before_clean_full.png")
    Image.open(world_reference).convert("RGB").resize(BEFORE_STYLE_SIZE, Image.Resampling.LANCZOS).save(
        model_inputs / "world_reference_full_style.png"
    )
    after_crop.resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS).save(model_inputs / "after_clean_patch.png")
    world_crop.resize(PATCH_STYLE_SIZE, Image.Resampling.LANCZOS).save(model_inputs / "world_reference_patch.png")

    metadata = {
        "manifest": str(manifest_path),
        "event_id": before["eventId"],
        "before_moment_id": before["id"],
        "after_moment_id": after["id"],
        "before_description": before["description"],
        "after_description": after["description"],
        "source_size": list(before_source.size),
        "experiment_size": list(FULL_SIZE),
        "diff_threshold": DIFF_THRESHOLD,
        "connected_components_over_1000px": components,
        "selected_components": selected,
        "mask_dilation_source_px": MASK_DILATION_SOURCE_PX,
        "bbox_buffer_fraction": BBOX_BUFFER_FRACTION,
        "bbox_experiment_pixels": list(bbox),
        "manual_adjustment": False,
        "split_edit_regions": False,
        "world_reference": str(world_reference),
    }
    (output_dir / "selection.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def copy_comfy_input(source: Path, name: str) -> str:
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    destination = COMFY_INPUT / name
    shutil.copy2(source, destination)
    return name


def add_reference(
    graph: dict,
    node_number: int,
    image_name: str,
    conditioning: list,
) -> tuple[list, int]:
    load_id = str(node_number)
    encode_id = str(node_number + 1)
    reference_id = str(node_number + 2)
    graph[load_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    graph[encode_id] = {
        "class_type": "VAEEncodeTiled",
        "inputs": {
            "pixels": [load_id, 0],
            "vae": ["3", 0],
            "tile_size": VAE_TILE_SIZE,
            "overlap": VAE_TILE_OVERLAP,
            "temporal_size": 64,
            "temporal_overlap": 8,
        },
    }
    graph[reference_id] = {
        "class_type": "ReferenceLatent",
        "inputs": {"conditioning": conditioning, "latent": [encode_id, 0]},
    }
    return [reference_id, 0], node_number + 3


def build_workflow(
    references: list[str],
    prompt: str,
    prefix: str,
    output_size: tuple[int, int],
    denoise: float,
    start_image: str | None,
) -> tuple[dict, str]:
    width, height = output_size
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "flux2", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": GUIDANCE}},
    }
    conditioning = ["5", 0]
    next_id = 6
    for image_name in references:
        conditioning, next_id = add_reference(graph, next_id, image_name, conditioning)

    guider_id = str(next_id)
    noise_id = str(next_id + 1)
    scheduler_id = str(next_id + 2)
    sampler_select_id = str(next_id + 3)
    graph[guider_id] = {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": conditioning}}
    graph[noise_id] = {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}}
    graph[scheduler_id] = {"class_type": "Flux2Scheduler", "inputs": {"steps": STEPS, "width": width, "height": height}}
    graph[sampler_select_id] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": SAMPLER}}
    next_id += 4

    sigmas = [scheduler_id, 0]
    if denoise < 1.0:
        split_id = str(next_id)
        graph[split_id] = {
            "class_type": "SplitSigmasDenoise",
            "inputs": {"sigmas": sigmas, "denoise": denoise},
        }
        sigmas = [split_id, 1]
        next_id += 1

    if start_image is None:
        latent_id = str(next_id)
        graph[latent_id] = {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        }
        latent = [latent_id, 0]
        next_id += 1
    else:
        load_start_id = str(next_id)
        encode_start_id = str(next_id + 1)
        graph[load_start_id] = {"class_type": "LoadImage", "inputs": {"image": start_image}}
        graph[encode_start_id] = {
            "class_type": "VAEEncodeTiled",
            "inputs": {
                "pixels": [load_start_id, 0],
                "vae": ["3", 0],
                "tile_size": VAE_TILE_SIZE,
                "overlap": VAE_TILE_OVERLAP,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        }
        latent = [encode_start_id, 0]
        next_id += 2

    sampler_id = str(next_id)
    decode_id = str(next_id + 1)
    save_id = str(next_id + 2)
    graph[sampler_id] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": [noise_id, 0],
            "guider": [guider_id, 0],
            "sampler": [sampler_select_id, 0],
            "sigmas": sigmas,
            "latent_image": latent,
        },
    }
    graph[decode_id] = {
        "class_type": "VAEDecodeTiled",
        "inputs": {
            "samples": [sampler_id, 0],
            "vae": ["3", 0],
            "tile_size": VAE_TILE_SIZE,
            "overlap": VAE_TILE_OVERLAP,
            "temporal_size": 64,
            "temporal_overlap": 8,
        },
    }
    graph[save_id] = {
        "class_type": "SaveImage",
        "inputs": {"images": [decode_id, 0], "filename_prefix": prefix},
    }
    return graph, save_id


def run_workflow(graph: dict, save_node: str, destination: Path, label: str) -> dict:
    queued = request_json("/prompt", {"prompt": graph, "client_id": "oxbow-local-edit-test"})
    prompt_id = queued["prompt_id"]
    print(f"{label}: queued {prompt_id}", flush=True)
    started = time.monotonic()
    while True:
        history = request_json(f"/history/{prompt_id}")
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False, indent=2))
            images = record.get("outputs", {}).get(save_node, {}).get("images", [])
            if images:
                download_image(images[0], destination)
                elapsed = round(time.monotonic() - started, 2)
                print(f"{label}: saved {destination} in {elapsed}s", flush=True)
                return {"prompt_id": prompt_id, "elapsed_seconds": elapsed}
        if time.monotonic() - started > 3600:
            raise TimeoutError(f"Timed out waiting for {label}")
        time.sleep(5)


def load_generation_log(output_dir: Path) -> dict:
    path = output_dir / "generation.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "engine": "local ComfyUI",
        "server": SERVER,
        "model": MODEL,
        "text_encoder": TEXT_ENCODER,
        "vae": VAE,
        "seed": SEED,
        "steps": STEPS,
        "guidance": GUIDANCE,
        "sampler": SAMPLER,
        "memory_profile": {
            "mode": "LOW_VRAM / DynamicVRAM",
            "text_encoder_device": "cpu",
            "vae_device": "cpu",
            "vae_tiled": True,
            "vram_headroom_gib": 10,
            "reserve_vram_gib": 6,
        },
        "runs": {},
    }


def save_generation_log(output_dir: Path, data: dict) -> None:
    (output_dir / "generation.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate_before(output_dir: Path) -> None:
    model_inputs = output_dir / "model_inputs"
    before_name = copy_comfy_input(model_inputs / "before_clean_full.png", "oxbow-local-before-clean.png")
    style_name = copy_comfy_input(model_inputs / "world_reference_full_style.png", "oxbow-local-world-style.png")
    graph, save_node = build_workflow(
        [before_name, style_name],
        BEFORE_PROMPT,
        "oxbow_local_edit/before_isolation_realistic",
        FULL_SIZE,
        1.0,
        None,
    )
    workflow_path = output_dir / "workflows" / "before_isolation.json"
    workflow_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    destination = output_dir / "before_isolation_realistic.png"
    result = run_workflow(graph, save_node, destination, "before_isolation")

    selection = json.loads((output_dir / "selection.json").read_text(encoding="utf-8"))
    bbox = tuple(selection["bbox_experiment_pixels"])
    before_realistic = Image.open(destination).convert("RGB")
    if before_realistic.size != FULL_SIZE:
        before_realistic = before_realistic.resize(FULL_SIZE, Image.Resampling.LANCZOS)
        before_realistic.save(destination)
    crop = before_realistic.crop(bbox)
    crop.save(output_dir / "crops" / "before_realistic.png")
    crop.resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS).save(model_inputs / "before_realistic_start.png")
    crop.resize(PATCH_APPEARANCE_SIZE, Image.Resampling.LANCZOS).save(model_inputs / "before_realistic_reference.png")

    generation = load_generation_log(output_dir)
    generation["runs"]["before_isolation"] = {
        **result,
        "denoise": 1.0,
        "output_size": list(FULL_SIZE),
        "references": ["before_clean_full.png", "world_reference_full_style.png"],
        "output": "before_isolation_realistic.png",
    }
    save_generation_log(output_dir, generation)


def generate_patches(output_dir: Path) -> None:
    model_inputs = output_dir / "model_inputs"
    after_name = copy_comfy_input(model_inputs / "after_clean_patch.png", "oxbow-local-after-clean-patch.png")
    before_reference_name = copy_comfy_input(
        model_inputs / "before_realistic_reference.png",
        "oxbow-local-before-realistic-reference.png",
    )
    world_name = copy_comfy_input(model_inputs / "world_reference_patch.png", "oxbow-local-world-reference-patch.png")
    start_name = copy_comfy_input(model_inputs / "after_clean_patch.png", "oxbow-local-after-clean-start.png")
    generation = load_generation_log(output_dir)
    for denoise in (0.55, 0.70, 0.85):
        suffix = f"{int(round(denoise * 100)):03d}"
        graph, save_node = build_workflow(
            [after_name, before_reference_name, world_name],
            PATCH_PROMPT,
            f"oxbow_local_edit/patch_{suffix}",
            PATCH_MODEL_SIZE,
            denoise,
            start_name,
        )
        workflow_path = output_dir / "workflows" / f"denoise_{suffix}.json"
        workflow_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destination = output_dir / "patches" / f"denoise_{suffix}.png"
        result = run_workflow(graph, save_node, destination, f"patch denoise {denoise:.2f}")
        generation["runs"][f"denoise_{suffix}"] = {
            **result,
            "denoise": denoise,
            "effective_transitions": round(STEPS * denoise),
            "output_size": list(PATCH_MODEL_SIZE),
            "references": [
                "after_clean_patch.png",
                "before_realistic_reference.png",
                "world_reference_patch.png",
            ],
            "start_latent": "after_clean_patch.png",
            "output": f"patches/denoise_{suffix}.png",
        }
        save_generation_log(output_dir, generation)


def compose(output_dir: Path) -> None:
    selection = json.loads((output_dir / "selection.json").read_text(encoding="utf-8"))
    bbox = tuple(selection["bbox_experiment_pixels"])
    base = Image.open(output_dir / "before_isolation_realistic.png").convert("RGB")
    if base.size != FULL_SIZE:
        base = base.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    hard_mask = np.asarray(Image.open(output_dir / "change_mask.png").convert("L")) > 0
    crop_mask = hard_mask[bbox[1] : bbox[3], bbox[0] : bbox[2]]
    distance_inside = ndimage.distance_transform_edt(crop_mask)
    alpha = np.clip(distance_inside / 12.0, 0.0, 1.0)
    alpha[crop_mask & (distance_inside >= 12)] = 1.0
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")

    for denoise in (0.55, 0.70, 0.85):
        suffix = f"{int(round(denoise * 100)):03d}"
        patch = Image.open(output_dir / "patches" / f"denoise_{suffix}.png").convert("RGB")
        patch = patch.resize((bbox[2] - bbox[0], bbox[3] - bbox[1]), Image.Resampling.LANCZOS)
        composite = base.copy()
        original_crop = base.crop(bbox)
        blended = Image.composite(patch, original_crop, alpha_image)
        composite.paste(blended, (bbox[0], bbox[1]))
        composite.save(output_dir / "composites" / f"denoise_{suffix}.png")


def contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, (245, 245, 240))
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    x = (size[0] - copy.width) // 2
    y = (size[1] - copy.height) // 2
    canvas.paste(copy, (x, y))
    return canvas


def comparison(output_dir: Path, best_suffix: str) -> None:
    shutil.copy2(output_dir / "composites" / f"denoise_{best_suffix}.png", output_dir / "best.png")
    cells = [
        ("before clean crop", output_dir / "crops" / "before_clean.png"),
        ("after clean crop", output_dir / "crops" / "after_clean.png"),
        ("before realistic", output_dir / "before_isolation_realistic.png"),
        ("patch 0.55", output_dir / "patches" / "denoise_055.png"),
        ("patch 0.70", output_dir / "patches" / "denoise_070.png"),
        ("patch 0.85", output_dir / "patches" / "denoise_085.png"),
        ("composite 0.55", output_dir / "composites" / "denoise_055.png"),
        ("composite 0.70", output_dir / "composites" / "denoise_070.png"),
        ("composite 0.85", output_dir / "composites" / "denoise_085.png"),
        (f"best 0.{best_suffix[-2:]}", output_dir / "best.png"),
    ]
    cell_size = (384, 240)
    title_height = 34
    columns = 2
    rows = math.ceil(len(cells) / columns)
    sheet = Image.new("RGB", (columns * cell_size[0], rows * (cell_size[1] + title_height)), (24, 31, 42))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    for index, (label, path) in enumerate(cells):
        column = index % columns
        row = index // columns
        x = column * cell_size[0]
        y = row * (cell_size[1] + title_height)
        draw.text((x + 10, y + 6), label, fill=(244, 247, 250), font=font)
        image = contain(Image.open(path), cell_size)
        sheet.paste(image, (x, y + title_height))
    sheet.save(output_dir / "comparison.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "before", "patches", "compose", "comparison"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--world-reference", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--best", choices=["055", "070", "085"])
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.action == "prepare":
        if args.manifest is None or args.world_reference is None:
            parser.error("prepare requires --manifest and --world-reference")
        metadata = prepare(args.manifest.resolve(), args.world_reference.resolve(), output_dir)
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    elif args.action == "before":
        generate_before(output_dir)
    elif args.action == "patches":
        generate_patches(output_dir)
    elif args.action == "compose":
        compose(output_dir)
    elif args.action == "comparison":
        if args.best is None:
            parser.error("comparison requires --best")
        comparison(output_dir, args.best)


if __name__ == "__main__":
    main()
