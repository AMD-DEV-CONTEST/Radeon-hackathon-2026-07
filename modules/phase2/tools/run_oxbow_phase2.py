#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from run_oxbow_local_edit import (
    BEFORE_PROMPT,
    FULL_SIZE,
    PATCH_APPEARANCE_SIZE,
    PATCH_MODEL_SIZE,
    PATCH_STYLE_SIZE,
    SEED,
    STEPS,
    GUIDANCE,
    SAMPLER,
    MODEL,
    TEXT_ENCODER,
    VAE,
    build_workflow,
    copy_comfy_input,
    run_workflow,
)


ANCHOR_IDS = (
    "meander_developed",
    "before_cutoff",
    "after_cutoff",
    "before_isolation",
    "after_isolation",
)

LOCAL_BBOX = (256, 160, 544, 480)
LOCAL_DENOISES = (0.72, 0.86)
CUTOFF_DENOISE = 0.86
UPPER_PLUG = [
    (297, 242), (316, 225), (339, 227), (362, 239), (386, 236),
    (404, 244), (414, 260), (410, 280), (399, 291), (412, 300),
    (400, 315), (380, 312), (358, 298), (337, 291), (316, 280),
    (297, 259),
]
LOWER_PLUG = [
    (380, 382), (393, 367), (414, 353), (434, 346), (459, 331),
    (477, 337), (488, 354), (482, 374), (479, 395), (465, 409),
    (443, 413), (422, 408), (407, 416), (391, 409),
]

PROVEN_AFTER_CUTOFF_PROMPT = """Transform this scientific river diagram into a realistic top-down aerial view of the same floodplain immediately after a flood cutoff.

Image 1 defines the exact current water-land geometry and channel connectivity. Preserve it precisely. The newly opened diagonal cutoff channel crosses the lower part of the meander neck and continuously connects the upstream river to the lower downstream channel. The large abandoned meander is still connected to the active river by visible water openings at both entrances. Keep both entrances open. Do not isolate the old channel yet.

Image 2 defines only the natural environmental appearance: realistic dark river water, irregular wet sand and mud along banks, floodplain grass and shrubs, soft daylight, and fixed aerial scale.

Preserve the exact position and shape of every channel, the fixed top-down camera, the surrounding terrain, the diagonal cutoff connection, and the complete connected old meander. Render natural bank-connected sediment and shoreline texture without introducing plugs across either entrance.

The pale center lines, white dots, hard colored outlines, and tan geometric wedges are programmatic notation. Remove the lines and dots; reinterpret the tan wedges as natural bank-attached sand bars.

No text, arrows, flow lines, white particles, diagram symbols, roads, buildings, boats, people, new tributaries, geometric patches, disconnected water, restored land across the cutoff, or isolated oxbow lake."""

PROMPTS = {
    "meander_developed": """Create a scientifically accurate, photorealistic top-down aerial image of this exact river floodplain.

Image 1 is a clean scientific structure map and is the only authority for geometry. Its broad blue ribbon is one continuous meandering river flowing from the left edge, around the large upper-right loop, and back to the right edge. Preserve the exact river centerline, widths, bend locations, narrow meander neck, inner floodplain island, and two point-bar locations. The two nearby channel limbs at the narrow neck remain separated by continuous land; no cutoff channel exists yet.

Reinterpret the green areas as a natural grassy floodplain with low shrubs and irregular tree belts. Reinterpret the tan wedges as bank-attached wet sand and silt point bars, never floating objects. Reinterpret the blue bands as natural dark river water and shallow margins. Use soft neutral daylight, a fixed vertical camera, realistic aerial scale, coherent vegetation, wet soil, sand, and subtle bank erosion.

The dark outlines, pale cyan center line, white dots, red arc, regular hatch marks, and geometric color bands are diagram styling, not physical objects. Remove them completely.

No text, arrows, flow lines, particles, labels, UI, roads, buildings, boats, people, bridges, new tributaries, islands in the channel, cutoff opening, or oxbow lake.""",
    "before_cutoff": """Transform this exact clean scientific frame into a photorealistic top-down aerial view of the same river floodplain.

Image 1 is the current-state structure authority. Preserve its one continuous flooded meandering river, fixed 16:9 vertical aerial camera, channel centerline, bend geometry, point bars, and surrounding land. The critical narrow neck at left-center is still continuous land between the approaching upstream and downstream limbs. Floodwater is eroding it, but no water passage crosses the neck. The long old meander remains the only complete river route from left to right. Do not create the diagonal cutoff channel yet.

Image 2 provides only the world appearance: the same season, grassy floodplain, shrubs and tree belts, dark natural water, wet sand and mud banks, soft daylight, camera height, and realistic aerial texture. It must not change Image 1 geometry.

Reinterpret tan wedges as natural bank-connected point-bar sediment. Remove pale center lines, white dots, rain strokes, hard outlines, geometric bands, field hatching, and every diagram symbol.

No text, arrows, particles, labels, UI, roads, buildings, boats, people, bridges, new tributaries, diagonal shortcut water, or isolated oxbow lake.""",
    "after_cutoff": """Transform this exact clean scientific frame into a photorealistic top-down aerial view of the same river floodplain immediately after a meander cutoff.

Image 1 is the current-state structure authority. Preserve the exact fixed camera, all water-land boundaries, and channel connections. The new blue diagonal water branch in the left-center is the newly opened cutoff channel: render it as a real continuous river channel connecting the upstream river directly to the lower downstream limb. At the same time, the large old meander loop around the upper-right floodplain remains water-filled and still connected at both former entrances. Two water routes temporarily coexist. Do not close either old-channel entrance and do not turn the loop into an isolated lake.

Image 2 provides only the established world appearance: grassy floodplain, shrubs and tree belts, dark water, wet sand and mud, soft neutral daylight, camera height, and aerial scale. It must not restore the pre-cutoff land neck or alter Image 1 topology.

Reinterpret tan wedges as bank-attached point-bar sediment. Remove pale center lines, white dots, hard outlines, geometric color bands, and all diagram styling.

No text, arrows, particles, labels, UI, roads, buildings, boats, people, bridges, extra tributaries, sediment dams across the old channel, or isolated oxbow lake.""",
    "before_isolation": """Transform this exact clean scientific frame into a photorealistic top-down aerial view of the same river floodplain after cutoff but before oxbow isolation.

Image 1 is the current-state structure authority. Preserve the exact fixed camera, all channel outlines, and every connection. The diagonal shortcut channel at left-center is now the active main route. The large curved old channel remains water-filled and visibly open to the active river at both its upper and lower former entrances. The flow is weaker there, but there must still be continuous water openings at both mouths. Do not isolate the old loop yet.

Image 2 provides only the established environmental appearance: identical season, grassy floodplain, shrubs and tree belts, dark natural water, irregular wet sand and mud banks, soft neutral daylight, camera height, and aerial scale. It must not alter current geometry.

Reinterpret tan wedges as natural bank-connected sediment bars and the scalloped blue shading as subtle slack-water variation. Remove pale center lines, white dots, hard outlines, regular hatching, and every diagram symbol.

No text, arrows, particles, labels, UI, roads, buildings, boats, people, bridges, new tributaries, artificial barriers, plugs across either old-channel mouth, or isolated oxbow lake.""",
    "after_isolation": """Create a scientifically accurate photorealistic top-down aerial view of this exact local river section after oxbow-lake isolation.

Image 1 is a Phase 2 topology-reinforcement map derived from the current Phase 1 after-isolation clean frame. It is the highest-priority geometry authority. Blue is water. The two irregular ochre-and-green land bridges at the upper and lower former mouths are the exact two sediment closure zones. Each bridge spans the entire former water opening, overlaps the surrounding banks, and creates a continuous land interval. The crescent old channel is therefore fully separated from the active river at both ends.

The original Phase 1 frame used two brown oval symbols merely to mark where deposition occurred. Do not copy oval objects. Replace those markers with natural bank-connected terrain at the same two locations: wet mud and sand toward the oxbow water edge, grading into floodplain soil, grasses, and sparse pioneer vegetation toward the banks. The oxbow water must stop visibly before each plug; water must not pass around, under, or through either closure.

Image 2 shows the same location before isolation and defines only the existing realistic water, vegetation, bank, soil, lighting, and aerial scale. Its two mouths are still open, so it must never override Image 1 connectivity. Image 3 supports only the shared environmental style.

Preserve the exact position and crescent shape of the oxbow, the diagonal active cutoff channel, the main river, the fixed vertical camera, and all terrain outside the two closure zones. Blend the edited terrain naturally into the existing banks.

No brown ovals, floating sediment islands, artificial barriers, white blobs, geometric patches, text, arrows, flow lines, particles, diagram symbols, roads, buildings, boats, people, new tributaries, or reconnection of the old channel.""",
}


def read_manifest(source_run: Path) -> tuple[dict, dict[str, dict]]:
    path = source_run / "bridge" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    moments = {moment["id"]: moment for moment in data["keyMoments"]}
    missing = [anchor_id for anchor_id in ANCHOR_IDS if anchor_id not in moments]
    if missing:
        raise RuntimeError(f"Missing Phase 1 moments: {missing}")
    return data, moments


def source_clean(source_run: Path, moment: dict) -> Path:
    path = source_run / "bridge" / moment["assets"]["clean"]
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generation_log(output_dir: Path) -> dict:
    path = output_dir / "generation.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "engine": "local ComfyUI FLUX.2",
        "model": MODEL,
        "text_encoder": TEXT_ENCODER,
        "vae": VAE,
        "seed": SEED,
        "steps": STEPS,
        "guidance": GUIDANCE,
        "sampler": SAMPLER,
        "full_size": list(FULL_SIZE),
        "memory_profile": {
            "dynamic_vram": True,
            "vram_headroom_gib": 10,
            "reserve_vram_gib": 6,
            "cpu_vae": True,
            "cpu_text_encoder": True,
            "tiled_vae": True,
            "pytorch_cross_attention": True,
        },
        "runs": {},
    }


def save_log(output_dir: Path, value: dict) -> None:
    write_json(output_dir / "generation.json", value)


def dilate_mask(mask: Image.Image, radius: int) -> Image.Image:
    array = np.asarray(mask.convert("L")) > 0
    yy, xx = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    structure = xx * xx + yy * yy <= radius * radius
    result = ndimage.binary_dilation(array, structure=structure)
    result = ndimage.binary_closing(result, structure=np.ones((13, 13), dtype=bool))
    return Image.fromarray((result * 255).astype(np.uint8), mode="L")


def create_isolation_controls(after_clean: Image.Image, anchor_dir: Path) -> None:
    structure = after_clean.resize(FULL_SIZE, Image.Resampling.LANCZOS).convert("RGB")
    overlay = Image.new("L", FULL_SIZE, 0)
    overlay_draw = ImageDraw.Draw(overlay)

    upper = UPPER_PLUG
    lower = LOWER_PLUG
    overlay_draw.polygon(upper, fill=255)
    overlay_draw.polygon(lower, fill=255)

    draw = ImageDraw.Draw(structure)
    bank = (58, 93, 59)
    sediment = (176, 143, 76)
    wet_sediment = (139, 113, 69)
    draw.polygon(upper, fill=bank)
    draw.polygon(lower, fill=bank)
    draw.polygon(
        [(305, 245), (319, 233), (337, 234), (360, 246), (384, 243),
         (398, 249), (406, 261), (402, 276), (390, 288), (403, 299),
         (397, 307), (382, 305), (360, 291), (340, 284), (321, 274),
         (305, 257)],
        fill=sediment,
    )
    draw.polygon(
        [(389, 383), (399, 373), (417, 360), (436, 353), (460, 339),
         (472, 344), (480, 355), (474, 369), (472, 390), (461, 402),
         (443, 406), (423, 400), (407, 407), (398, 402)],
        fill=sediment,
    )
    draw.line([(310, 247), (342, 252), (374, 276), (402, 292)], fill=wet_sediment, width=6)
    draw.line([(393, 399), (417, 389), (447, 362), (475, 352)], fill=wet_sediment, width=6)

    edit_mask = dilate_mask(overlay, 22)
    structure.save(anchor_dir / "structure_reference.png")
    overlay.save(anchor_dir / "core_mask.png")
    edit_mask.save(anchor_dir / "mask.png")
    structure.crop(LOCAL_BBOX).save(anchor_dir / "focus_crop.png")


def prepare(source_run: Path, output_dir: Path) -> None:
    _, moments = read_manifest(source_run)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "anchors").mkdir()
    (output_dir / "model_inputs").mkdir()
    (output_dir / "workflows").mkdir()
    (output_dir / "attempts" / "after_isolation").mkdir(parents=True)

    for anchor_id in ANCHOR_IDS:
        anchor_dir = output_dir / "anchors" / anchor_id
        anchor_dir.mkdir()
        clean = source_clean(source_run, moments[anchor_id])
        shutil.copy2(clean, anchor_dir / "input_clean.png")
        (anchor_dir / "prompt.txt").write_text(PROMPTS[anchor_id].strip() + "\n", encoding="utf-8")
        Image.open(clean).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS).save(
            output_dir / "model_inputs" / f"{anchor_id}_clean.png"
        )

    after_clean = Image.open(output_dir / "anchors" / "after_isolation" / "input_clean.png").convert("RGB")
    create_isolation_controls(after_clean, output_dir / "anchors" / "after_isolation")
    (output_dir / "selection.md").write_text(
        """# Generation anchor selection

- `meander_developed` / 18.0 s: stable, visually rich world reference; narrow neck is fully established and still closed.
- `before_cutoff` / 26.0 s: retained pre-event topology; flood state is complete and neck remains land.
- `after_cutoff` / 34.0 s: retained post-event topology; diagonal shortcut is fully open while the old loop remains connected.
- `before_isolation` / 37.0 s: retained pre-event topology; both old-channel mouths remain open.
- `after_isolation` / 44.5 s: retained post-event topology; Phase 2 adds a derived structure reference so the two brown program markers become bank-connected land closures.

Omitted: `initial_bend` adds little world or topology control; `oxbow_stable` repeats the after-isolation geometry and mainly adds tiny vegetation dots, so it is not a separate generation anchor.
""",
        encoding="utf-8",
    )
    save_log(output_dir, generation_log(output_dir))


def generate_world(output_dir: Path) -> None:
    anchor_id = "meander_developed"
    clean_name = copy_comfy_input(
        output_dir / "model_inputs" / f"{anchor_id}_clean.png",
        "oxbow-phase2-meander-developed-clean.png",
    )
    graph, save_node = build_workflow(
        [clean_name],
        PROMPTS[anchor_id],
        "oxbow_phase2/world_reference",
        FULL_SIZE,
        1.0,
        None,
    )
    write_json(output_dir / "workflows" / "world_reference.json", graph)
    destination = output_dir / "world_reference.png"
    result = run_workflow(graph, save_node, destination, "world reference")
    image = Image.open(destination).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS)
    image.save(destination)
    image.save(output_dir / "anchors" / anchor_id / "realistic.png")
    image.resize((320, 180), Image.Resampling.LANCZOS).save(
        output_dir / "model_inputs" / "world_reference_style.png"
    )
    log = generation_log(output_dir)
    log["runs"][anchor_id] = {
        **result,
        "strategy": "full_generation_world_reference",
        "denoise": 1.0,
        "references": [f"{anchor_id}_clean.png"],
        "output": "world_reference.png",
    }
    save_log(output_dir, log)


def generate_full_anchors(output_dir: Path) -> None:
    style_path = output_dir / "model_inputs" / "world_reference_style.png"
    if not style_path.is_file():
        raise FileNotFoundError("Generate world reference first")
    style_name = copy_comfy_input(style_path, "oxbow-phase2-world-style.png")
    log = generation_log(output_dir)
    for anchor_id in ("before_cutoff", "after_cutoff", "before_isolation"):
        clean_name = copy_comfy_input(
            output_dir / "model_inputs" / f"{anchor_id}_clean.png",
            f"oxbow-phase2-{anchor_id}-clean.png",
        )
        graph, save_node = build_workflow(
            [clean_name, style_name],
            PROMPTS[anchor_id],
            f"oxbow_phase2/{anchor_id}",
            FULL_SIZE,
            1.0,
            None,
        )
        write_json(output_dir / "workflows" / f"{anchor_id}.json", graph)
        destination = output_dir / "anchors" / anchor_id / "realistic.png"
        result = run_workflow(graph, save_node, destination, anchor_id)
        Image.open(destination).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS).save(destination)
        log["runs"][anchor_id] = {
            **result,
            "strategy": "full_generation_current_clean_plus_low_resolution_world_style",
            "denoise": 1.0,
            "references": [f"{anchor_id}_clean.png", "world_reference_style.png"],
            "output": f"anchors/{anchor_id}/realistic.png",
        }
        save_log(output_dir, log)


def compose_patch(output_dir: Path, patch_path: Path, destination: Path) -> None:
    base = Image.open(output_dir / "anchors" / "before_isolation" / "realistic.png").convert("RGB")
    base = base.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    patch = Image.open(patch_path).convert("RGB").resize(
        (LOCAL_BBOX[2] - LOCAL_BBOX[0], LOCAL_BBOX[3] - LOCAL_BBOX[1]),
        Image.Resampling.LANCZOS,
    )
    full_mask = Image.open(output_dir / "anchors" / "after_isolation" / "mask.png").convert("L")
    crop_mask = np.asarray(full_mask.crop(LOCAL_BBOX)) > 0
    distance = ndimage.distance_transform_edt(crop_mask)
    alpha = np.clip(distance / 12.0, 0.0, 1.0)
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
    original_crop = base.crop(LOCAL_BBOX)
    blended = Image.composite(patch, original_crop, alpha_image)
    base.paste(blended, (LOCAL_BBOX[0], LOCAL_BBOX[1]))
    base.save(destination)


def create_cutoff_mask(anchor_dir: Path) -> Image.Image:
    mask = Image.new("L", FULL_SIZE, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        [(278, 222), (330, 208), (371, 226), (433, 278), (463, 333),
         (462, 392), (425, 437), (365, 447), (313, 419), (277, 359)],
        fill=255,
    )
    mask = dilate_mask(mask, 12)
    mask.save(anchor_dir / "mask.png")
    return mask


def compose_with_mask(
    base_path: Path,
    patch_path: Path,
    mask: Image.Image,
    destination: Path,
) -> None:
    base = Image.open(base_path).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS)
    patch = Image.open(patch_path).convert("RGB").resize(
        (LOCAL_BBOX[2] - LOCAL_BBOX[0], LOCAL_BBOX[3] - LOCAL_BBOX[1]),
        Image.Resampling.LANCZOS,
    )
    crop_mask = np.asarray(mask.crop(LOCAL_BBOX)) > 0
    distance = ndimage.distance_transform_edt(crop_mask)
    alpha = np.clip(distance / 12.0, 0.0, 1.0)
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
    original_crop = base.crop(LOCAL_BBOX)
    blended = Image.composite(patch, original_crop, alpha_image)
    base.paste(blended, (LOCAL_BBOX[0], LOCAL_BBOX[1]))
    base.save(destination)


def generate_cutoff_locals(output_dir: Path) -> None:
    log = generation_log(output_dir)
    world = Image.open(output_dir / "world_reference.png").convert("RGB")
    world_crop = world.crop(LOCAL_BBOX)
    world_input_path = output_dir / "model_inputs" / "cutoff_world_style_patch.png"
    world_crop.resize(PATCH_STYLE_SIZE, Image.Resampling.LANCZOS).save(world_input_path)
    world_name = copy_comfy_input(world_input_path, "oxbow-phase2-cutoff-world-style.png")

    for anchor_id, base_id in (
        ("after_cutoff", "before_cutoff"),
        ("before_isolation", "after_cutoff"),
    ):
        anchor_dir = output_dir / "anchors" / anchor_id
        attempts_dir = output_dir / "attempts" / anchor_id
        attempts_dir.mkdir(parents=True, exist_ok=True)
        current_output = anchor_dir / "realistic.png"
        full_attempt = attempts_dir / "full_generation.png"
        if current_output.is_file() and not full_attempt.exists():
            shutil.copy2(current_output, full_attempt)

        clean = Image.open(output_dir / "model_inputs" / f"{anchor_id}_clean.png").convert("RGB")
        clean_crop = clean.crop(LOCAL_BBOX)
        clean_crop.save(anchor_dir / "focus_crop.png")
        structure_path = output_dir / "model_inputs" / f"{anchor_id}_structure_patch.png"
        clean_crop.resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS).save(structure_path)

        base_path = output_dir / "anchors" / base_id / "realistic.png"
        appearance = Image.open(base_path).convert("RGB").crop(LOCAL_BBOX)
        appearance_path = output_dir / "model_inputs" / f"{anchor_id}_appearance_patch.png"
        appearance.resize(PATCH_APPEARANCE_SIZE, Image.Resampling.LANCZOS).save(appearance_path)

        structure_name = copy_comfy_input(structure_path, f"oxbow-phase2-{anchor_id}-structure.png")
        appearance_name = copy_comfy_input(appearance_path, f"oxbow-phase2-{anchor_id}-appearance.png")
        graph, save_node = build_workflow(
            [structure_name, appearance_name, world_name],
            PROMPTS[anchor_id],
            f"oxbow_phase2/{anchor_id}_local",
            PATCH_MODEL_SIZE,
            CUTOFF_DENOISE,
            structure_name,
        )
        write_json(output_dir / "workflows" / f"{anchor_id}_local.json", graph)
        patch_path = attempts_dir / "local_patch_086.png"
        result = run_workflow(graph, save_node, patch_path, f"{anchor_id} local topology retry")
        mask = create_cutoff_mask(anchor_dir)
        compose_with_mask(base_path, patch_path, mask, current_output)

        previous = log["runs"].pop(anchor_id, None)
        if previous is not None:
            previous["accepted"] = False
            previous["failure_reason"] = "new cutoff channel was not visually established"
            previous["preserved_output"] = f"attempts/{anchor_id}/full_generation.png"
            log["runs"][f"{anchor_id}_full_failed"] = previous
        log["runs"][anchor_id] = {
            **result,
            "strategy": "local_topology_edit_from_current_clean_structure",
            "denoise": CUTOFF_DENOISE,
            "effective_transitions": round(STEPS * CUTOFF_DENOISE),
            "bbox": list(LOCAL_BBOX),
            "references": [
                f"{anchor_id}_structure_patch.png",
                f"{anchor_id}_appearance_patch.png",
                "cutoff_world_style_patch.png",
            ],
            "start_latent": f"{anchor_id}_structure_patch.png",
            "base": f"anchors/{base_id}/realistic.png",
            "patch": f"attempts/{anchor_id}/local_patch_086.png",
            "output": f"anchors/{anchor_id}/realistic.png",
            "accepted": True,
        }
        save_log(output_dir, log)


def generate_proven_topology_retries(output_dir: Path, proven_world_reference: Path) -> None:
    if not proven_world_reference.is_file():
        raise FileNotFoundError(proven_world_reference)
    proven_style_path = output_dir / "model_inputs" / "proven_topology_world_style.png"
    Image.open(proven_world_reference).convert("RGB").resize((320, 180), Image.Resampling.LANCZOS).save(
        proven_style_path
    )
    style_name = copy_comfy_input(proven_style_path, "oxbow-phase2-proven-topology-style.png")
    log = generation_log(output_dir)
    for anchor_id, prompt in (
        ("after_cutoff", PROVEN_AFTER_CUTOFF_PROMPT),
        ("before_isolation", BEFORE_PROMPT),
    ):
        anchor_dir = output_dir / "anchors" / anchor_id
        attempts_dir = output_dir / "attempts" / anchor_id
        attempts_dir.mkdir(parents=True, exist_ok=True)
        local_failure = attempts_dir / "local_composite_failed.png"
        if (anchor_dir / "realistic.png").is_file() and not local_failure.exists():
            shutil.copy2(anchor_dir / "realistic.png", local_failure)
        clean_name = copy_comfy_input(
            output_dir / "model_inputs" / f"{anchor_id}_clean.png",
            f"oxbow-phase2-{anchor_id}-proven-retry-clean.png",
        )
        graph, save_node = build_workflow(
            [clean_name, style_name],
            prompt,
            f"oxbow_phase2/{anchor_id}_proven_retry",
            FULL_SIZE,
            1.0,
            None,
        )
        write_json(output_dir / "workflows" / f"{anchor_id}_proven_retry.json", graph)
        destination = attempts_dir / "proven_full_retry.png"
        result = run_workflow(graph, save_node, destination, f"{anchor_id} proven full retry")
        Image.open(destination).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS).save(destination)
        shutil.copy2(destination, anchor_dir / "realistic.png")
        local_run = log["runs"].pop(anchor_id, None)
        if local_run is not None:
            local_run["accepted"] = False
            local_run["failure_reason"] = "programmatic center lines and severe patch seam remained"
            local_run["preserved_output"] = f"attempts/{anchor_id}/local_composite_failed.png"
            log["runs"][f"{anchor_id}_local_failed"] = local_run
        log["runs"][anchor_id] = {
            **result,
            "strategy": "full_generation_with_previously_validated_low_resolution_style_configuration",
            "denoise": 1.0,
            "references": [f"{anchor_id}_clean.png", "proven_topology_world_style.png"],
            "supporting_style_source": str(proven_world_reference),
            "output": f"anchors/{anchor_id}/realistic.png",
            "accepted": True,
        }
        save_log(output_dir, log)


def generate_after_cutoff_polish(output_dir: Path) -> None:
    start_path = output_dir / "anchors" / "before_isolation" / "realistic.png"
    clean_path = output_dir / "model_inputs" / "after_cutoff_clean.png"
    style_path = output_dir / "model_inputs" / "world_reference_style.png"
    if not all(path.is_file() for path in (start_path, clean_path, style_path)):
        raise FileNotFoundError("after-cutoff polish inputs are incomplete")
    start_name = copy_comfy_input(start_path, "oxbow-phase2-after-cutoff-correct-topology-start.png")
    clean_name = copy_comfy_input(clean_path, "oxbow-phase2-after-cutoff-polish-clean.png")
    style_name = copy_comfy_input(style_path, "oxbow-phase2-after-cutoff-polish-style.png")
    denoise = 0.32
    graph, save_node = build_workflow(
        [clean_name, style_name],
        PROVEN_AFTER_CUTOFF_PROMPT,
        "oxbow_phase2/after_cutoff_polish",
        FULL_SIZE,
        denoise,
        start_name,
    )
    write_json(output_dir / "workflows" / "after_cutoff_polish.json", graph)
    destination = output_dir / "attempts" / "after_cutoff" / "topology_start_polish_032.png"
    result = run_workflow(graph, save_node, destination, "after_cutoff topology-start polish")
    Image.open(destination).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS).save(destination)
    log = generation_log(output_dir)
    log["runs"]["after_cutoff_polish_candidate"] = {
        **result,
        "strategy": "low_denoise_full_polish_from_correct_topology_realistic_start",
        "denoise": denoise,
        "effective_transitions": round(STEPS * denoise),
        "references": ["after_cutoff_clean.png", "world_reference_style.png"],
        "start_latent": "anchors/before_isolation/realistic.png",
        "output": "attempts/after_cutoff/topology_start_polish_032.png",
    }
    save_log(output_dir, log)


def select_after_cutoff_polish(output_dir: Path) -> None:
    source = output_dir / "attempts" / "after_cutoff" / "topology_start_polish_032.png"
    destination = output_dir / "anchors" / "after_cutoff" / "realistic.png"
    if not source.is_file():
        raise FileNotFoundError(source)
    old = output_dir / "attempts" / "after_cutoff" / "proven_full_retry_failed.png"
    if destination.is_file() and not old.exists():
        shutil.copy2(destination, old)
    shutil.copy2(source, destination)
    log = generation_log(output_dir)
    previous = log["runs"].pop("after_cutoff", None)
    if previous is not None:
        previous["accepted"] = False
        previous["failure_reason"] = "cutoff connection appeared as an implausibly narrow pale line"
        previous["preserved_output"] = "attempts/after_cutoff/proven_full_retry_failed.png"
        log["runs"]["after_cutoff_proven_full_failed"] = previous
    candidate = log["runs"].pop("after_cutoff_polish_candidate")
    candidate["accepted"] = True
    candidate["output"] = "anchors/after_cutoff/realistic.png"
    log["runs"]["after_cutoff"] = candidate
    save_log(output_dir, log)


def generate_isolation(output_dir: Path) -> None:
    anchor_dir = output_dir / "anchors" / "after_isolation"
    structure = Image.open(anchor_dir / "structure_reference.png").convert("RGB")
    structure_crop = structure.crop(LOCAL_BBOX)
    structure_crop.resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS).save(
        output_dir / "model_inputs" / "after_isolation_structure_patch.png"
    )
    before = Image.open(output_dir / "anchors" / "before_isolation" / "realistic.png").convert("RGB")
    before_crop = before.crop(LOCAL_BBOX)
    before_crop.resize(PATCH_APPEARANCE_SIZE, Image.Resampling.LANCZOS).save(
        output_dir / "model_inputs" / "before_isolation_appearance_patch.png"
    )
    world = Image.open(output_dir / "world_reference.png").convert("RGB")
    world_crop = world.crop(LOCAL_BBOX)
    world_crop.resize(PATCH_STYLE_SIZE, Image.Resampling.LANCZOS).save(
        output_dir / "model_inputs" / "world_style_patch.png"
    )

    structure_name = copy_comfy_input(
        output_dir / "model_inputs" / "after_isolation_structure_patch.png",
        "oxbow-phase2-after-isolation-structure.png",
    )
    appearance_name = copy_comfy_input(
        output_dir / "model_inputs" / "before_isolation_appearance_patch.png",
        "oxbow-phase2-before-isolation-appearance.png",
    )
    world_name = copy_comfy_input(
        output_dir / "model_inputs" / "world_style_patch.png",
        "oxbow-phase2-world-patch.png",
    )
    log = generation_log(output_dir)
    for denoise in LOCAL_DENOISES:
        suffix = f"{int(round(denoise * 100)):03d}"
        graph, save_node = build_workflow(
            [structure_name, appearance_name, world_name],
            PROMPTS["after_isolation"],
            f"oxbow_phase2/after_isolation_{suffix}",
            PATCH_MODEL_SIZE,
            denoise,
            structure_name,
        )
        write_json(output_dir / "workflows" / f"after_isolation_{suffix}.json", graph)
        patch_path = output_dir / "attempts" / "after_isolation" / f"patch_{suffix}.png"
        result = run_workflow(graph, save_node, patch_path, f"after_isolation local {denoise:.2f}")
        composite_path = output_dir / "attempts" / "after_isolation" / f"composite_{suffix}.png"
        compose_patch(output_dir, patch_path, composite_path)
        log["runs"][f"after_isolation_{suffix}"] = {
            **result,
            "strategy": "local_edit_from_derived_topology_structure",
            "denoise": denoise,
            "effective_transitions": round(STEPS * denoise),
            "bbox": list(LOCAL_BBOX),
            "references": [
                "after_isolation_structure_patch.png",
                "before_isolation_appearance_patch.png",
                "world_style_patch.png",
            ],
            "start_latent": "after_isolation_structure_patch.png",
            "patch": f"attempts/after_isolation/patch_{suffix}.png",
            "composite": f"attempts/after_isolation/composite_{suffix}.png",
        }
        save_log(output_dir, log)


def generate_isolation_realistic_start(output_dir: Path) -> None:
    anchor_dir = output_dir / "anchors" / "after_isolation"
    structure_path = output_dir / "model_inputs" / "after_isolation_structure_patch.png"
    appearance_path = output_dir / "model_inputs" / "before_isolation_appearance_patch.png"
    world_path = output_dir / "model_inputs" / "world_style_patch.png"
    before = Image.open(output_dir / "anchors" / "before_isolation" / "realistic.png").convert("RGB")
    start_path = output_dir / "model_inputs" / "before_isolation_realistic_start_patch.png"
    before.crop(LOCAL_BBOX).resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS).save(start_path)
    structure_name = copy_comfy_input(structure_path, "oxbow-phase2-isolation-realistic-start-structure.png")
    appearance_name = copy_comfy_input(appearance_path, "oxbow-phase2-isolation-realistic-start-appearance.png")
    world_name = copy_comfy_input(world_path, "oxbow-phase2-isolation-realistic-start-world.png")
    start_name = copy_comfy_input(start_path, "oxbow-phase2-isolation-realistic-start.png")
    denoise = 0.86
    graph, save_node = build_workflow(
        [structure_name, appearance_name, world_name],
        PROMPTS["after_isolation"],
        "oxbow_phase2/after_isolation_realistic_start_086",
        PATCH_MODEL_SIZE,
        denoise,
        start_name,
    )
    write_json(output_dir / "workflows" / "after_isolation_realistic_start_086.json", graph)
    patch_path = output_dir / "attempts" / "after_isolation" / "patch_086_realistic_start.png"
    result = run_workflow(graph, save_node, patch_path, "after_isolation realistic-start 0.86")
    composite_path = output_dir / "attempts" / "after_isolation" / "composite_086_realistic_start.png"
    compose_patch(output_dir, patch_path, composite_path)
    log = generation_log(output_dir)
    log["runs"]["after_isolation_086_realistic_start"] = {
        **result,
        "strategy": "local_edit_with_structure_reference_and_realistic_start_latent",
        "denoise": denoise,
        "effective_transitions": round(STEPS * denoise),
        "bbox": list(LOCAL_BBOX),
        "references": [
            "after_isolation_structure_patch.png",
            "before_isolation_appearance_patch.png",
            "world_style_patch.png",
        ],
        "start_latent": "before_isolation_realistic_start_patch.png",
        "patch": "attempts/after_isolation/patch_086_realistic_start.png",
        "composite": "attempts/after_isolation/composite_086_realistic_start.png",
    }
    save_log(output_dir, log)


def generate_isolation_full_semantic(output_dir: Path) -> None:
    structure_path = output_dir / "anchors" / "after_isolation" / "structure_reference.png"
    style_path = output_dir / "model_inputs" / "world_reference_style.png"
    structure_name = copy_comfy_input(
        structure_path,
        "oxbow-phase2-after-isolation-full-structure.png",
    )
    style_name = copy_comfy_input(
        style_path,
        "oxbow-phase2-after-isolation-full-world-style.png",
    )
    graph, save_node = build_workflow(
        [structure_name, style_name],
        PROMPTS["after_isolation"],
        "oxbow_phase2/after_isolation_full_semantic",
        FULL_SIZE,
        1.0,
        None,
    )
    write_json(output_dir / "workflows" / "after_isolation_full_semantic.json", graph)
    destination = output_dir / "attempts" / "after_isolation" / "full_semantic_generation.png"
    result = run_workflow(graph, save_node, destination, "after_isolation full semantic")
    Image.open(destination).convert("RGB").resize(FULL_SIZE, Image.Resampling.LANCZOS).save(destination)
    log = generation_log(output_dir)
    log["runs"]["after_isolation_full_semantic"] = {
        **result,
        "strategy": "full_generation_from_corrected_topology_structure",
        "denoise": 1.0,
        "references": [
            "anchors/after_isolation/structure_reference.png",
            "world_reference_style.png",
        ],
        "output": "attempts/after_isolation/full_semantic_generation.png",
    }
    save_log(output_dir, log)


def select_isolation(output_dir: Path, suffix: str) -> None:
    source = output_dir / "attempts" / "after_isolation" / f"composite_{suffix}.png"
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, output_dir / "anchors" / "after_isolation" / "realistic.png")
    data = generation_log(output_dir)
    data["selected_after_isolation_attempt"] = suffix
    save_log(output_dir, data)


def recompose_isolation_tight(output_dir: Path, suffix: str) -> None:
    patch_path = output_dir / "attempts" / "after_isolation" / f"patch_{suffix}.png"
    base = Image.open(output_dir / "anchors" / "before_isolation" / "realistic.png").convert("RGB")
    base = base.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    patch = Image.open(patch_path).convert("RGB").resize(
        (LOCAL_BBOX[2] - LOCAL_BBOX[0], LOCAL_BBOX[3] - LOCAL_BBOX[1]),
        Image.Resampling.LANCZOS,
    )
    core = Image.open(output_dir / "anchors" / "after_isolation" / "core_mask.png").convert("L")
    crop_mask = np.asarray(core.crop(LOCAL_BBOX)) > 0
    distance = ndimage.distance_transform_edt(crop_mask)
    alpha = np.clip(distance / 5.0, 0.0, 1.0)
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
    original_crop = base.crop(LOCAL_BBOX)
    blended = Image.composite(patch, original_crop, alpha_image)
    base.paste(blended, (LOCAL_BBOX[0], LOCAL_BBOX[1]))
    destination = output_dir / "attempts" / "after_isolation" / f"composite_{suffix}_tight.png"
    base.save(destination)


def create_isolation_hybrid(output_dir: Path) -> None:
    semantic_patch = Image.open(
        output_dir / "attempts" / "after_isolation" / "patch_086.png"
    ).convert("RGB").resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS)
    realistic_patch = Image.open(
        output_dir / "attempts" / "after_isolation" / "patch_086_realistic_start.png"
    ).convert("RGB").resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS)
    core = Image.open(output_dir / "anchors" / "after_isolation" / "core_mask.png").convert("L")
    core_patch = core.crop(LOCAL_BBOX).resize(PATCH_MODEL_SIZE, Image.Resampling.NEAREST)
    core_array = np.asarray(core_patch) > 0
    distance = ndimage.distance_transform_edt(core_array)
    alpha = np.clip(distance / 10.0, 0.0, 1.0)
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
    hybrid = Image.composite(semantic_patch, realistic_patch, alpha_image)
    hybrid_path = output_dir / "attempts" / "after_isolation" / "patch_086_hybrid.png"
    hybrid.save(hybrid_path)
    composite_path = output_dir / "attempts" / "after_isolation" / "composite_086_hybrid.png"
    compose_patch(output_dir, hybrid_path, composite_path)

    structure = Image.open(
        output_dir / "model_inputs" / "after_isolation_structure_patch.png"
    ).convert("RGB").resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS)
    semantic_array = np.asarray(semantic_patch, dtype=np.int16)
    structure_array = np.asarray(structure, dtype=np.int16)
    changed_from_program = np.mean(np.abs(semantic_array - structure_array), axis=2) > 34
    filtered_core = core_array & changed_from_program
    filtered_core = ndimage.binary_closing(filtered_core, structure=np.ones((9, 9), dtype=bool))
    filtered_core = ndimage.binary_opening(filtered_core, structure=np.ones((3, 3), dtype=bool))
    filtered_distance = ndimage.distance_transform_edt(filtered_core)
    filtered_alpha = np.clip(filtered_distance / 8.0, 0.0, 1.0)
    filtered_alpha_image = Image.fromarray(
        np.round(filtered_alpha * 255).astype(np.uint8), mode="L"
    )
    filtered_alpha_image.save(
        output_dir / "attempts" / "after_isolation" / "hybrid_natural_content_mask.png"
    )
    filtered_hybrid = Image.composite(semantic_patch, realistic_patch, filtered_alpha_image)
    filtered_hybrid_path = output_dir / "attempts" / "after_isolation" / "patch_086_hybrid_filtered.png"
    filtered_hybrid.save(filtered_hybrid_path)
    filtered_composite_path = (
        output_dir / "attempts" / "after_isolation" / "composite_086_hybrid_filtered.png"
    )
    compose_patch(output_dir, filtered_hybrid_path, filtered_composite_path)


def create_isolation_texture_composite(output_dir: Path) -> None:
    base = Image.open(output_dir / "anchors" / "before_isolation" / "realistic.png").convert("RGB")
    base = base.resize(FULL_SIZE, Image.Resampling.LANCZOS)
    generated = Image.open(
        output_dir / "attempts" / "after_isolation" / "patch_086.png"
    ).convert("RGB").resize(PATCH_MODEL_SIZE, Image.Resampling.LANCZOS)

    texture_sources = (
        generated.crop((140, 210, 325, 325)),
        generated.crop((335, 465, 565, 590)),
    )
    for polygon, texture in zip((UPPER_PLUG, LOWER_PLUG), texture_sources):
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        texture = texture.resize((bbox[2] - bbox[0], bbox[3] - bbox[1]), Image.Resampling.LANCZOS)
        texture_layer = base.copy()
        texture_layer.paste(texture, (bbox[0], bbox[1]))
        mask = Image.new("L", FULL_SIZE, 0)
        ImageDraw.Draw(mask).polygon(polygon, fill=255)
        mask_array = np.asarray(mask) > 0
        distance = ndimage.distance_transform_edt(mask_array)
        alpha = np.clip(distance / 5.0, 0.0, 1.0)
        alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
        base = Image.composite(texture_layer, base, alpha_image)

    destination = output_dir / "attempts" / "after_isolation" / "topology_texture_composite.png"
    base.save(destination)


def fit_cell(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, (20, 27, 38))
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def contact_sheet(output_dir: Path) -> None:
    cell = (512, 288)
    title = 42
    columns = 2
    rows = len(ANCHOR_IDS)
    sheet = Image.new("RGB", (columns * cell[0], rows * (cell[1] + title)), (14, 20, 30))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    for row, anchor_id in enumerate(ANCHOR_IDS):
        for column, (kind, name) in enumerate((("clean", "input_clean.png"), ("realistic", "realistic.png"))):
            path = output_dir / "anchors" / anchor_id / name
            if not path.is_file():
                raise FileNotFoundError(path)
            x = column * cell[0]
            y = row * (cell[1] + title)
            draw.text((x + 10, y + 8), f"{anchor_id} · {kind}", fill=(241, 245, 249), font=font)
            sheet.paste(fit_cell(Image.open(path), cell), (x, y + title))
    sheet.save(output_dir / "contact_sheet.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("prepare", "refresh-controls", "world", "full", "cutoff-locals", "topology-retries", "after-cutoff-polish", "select-after-cutoff-polish", "isolation", "isolation-realistic-start", "isolation-full-semantic", "recompose-isolation-tight", "isolation-hybrid", "isolation-texture-composite", "select-isolation", "contact-sheet"),
    )
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempt", choices=("072", "086"))
    parser.add_argument("--proven-world-reference", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.action == "prepare":
        if args.source_run is None:
            parser.error("prepare requires --source-run")
        prepare(args.source_run.resolve(), output_dir)
    elif args.action == "refresh-controls":
        after_clean = Image.open(output_dir / "anchors" / "after_isolation" / "input_clean.png").convert("RGB")
        create_isolation_controls(after_clean, output_dir / "anchors" / "after_isolation")
    elif args.action == "world":
        generate_world(output_dir)
    elif args.action == "full":
        generate_full_anchors(output_dir)
    elif args.action == "cutoff-locals":
        generate_cutoff_locals(output_dir)
    elif args.action == "topology-retries":
        if args.proven_world_reference is None:
            parser.error("topology-retries requires --proven-world-reference")
        generate_proven_topology_retries(output_dir, args.proven_world_reference.resolve())
    elif args.action == "after-cutoff-polish":
        generate_after_cutoff_polish(output_dir)
    elif args.action == "select-after-cutoff-polish":
        select_after_cutoff_polish(output_dir)
    elif args.action == "isolation":
        generate_isolation(output_dir)
    elif args.action == "isolation-realistic-start":
        generate_isolation_realistic_start(output_dir)
    elif args.action == "isolation-full-semantic":
        generate_isolation_full_semantic(output_dir)
    elif args.action == "recompose-isolation-tight":
        if args.attempt is None:
            parser.error("recompose-isolation-tight requires --attempt")
        recompose_isolation_tight(output_dir, args.attempt)
    elif args.action == "isolation-hybrid":
        create_isolation_hybrid(output_dir)
    elif args.action == "isolation-texture-composite":
        create_isolation_texture_composite(output_dir)
    elif args.action == "select-isolation":
        if args.attempt is None:
            parser.error("select-isolation requires --attempt")
        select_isolation(output_dir, args.attempt)
    elif args.action == "contact-sheet":
        contact_sheet(output_dir)


if __name__ == "__main__":
    main()
