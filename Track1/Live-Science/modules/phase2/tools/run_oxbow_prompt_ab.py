#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage


HERE = Path(__file__).resolve().parent
BASE_SCRIPT = HERE / "run_oxbow_local_edit.py"
SPEC = importlib.util.spec_from_file_location("oxbow_local_edit", BASE_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {BASE_SCRIPT}")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


A_PROMPT = base.PATCH_PROMPT

B_PROMPT = """This is a precise two-region edit, not a global redraw.

Image 1 is a program-generated structure diagram. It contains exactly two
brown oval marker shapes: one upper marker and one lower marker. These two
brown ovals identify the only two former-channel entrances that must change.
They are temporary diagram markers, not physical objects, not desired
sediment silhouettes, and not geometry to preserve.

At the UPPER brown marker, remove the complete brown oval, the blue water
directly beneath and immediately around it, and every white diagram line or
white particle crossing the marked area. Replace that short marked
side-channel mouth with one broad, low, irregular deposit of natural mud,
sand and floodplain soil. The deposit must span the full width of that former
entrance. Both ends of the deposit must physically merge into the two existing
banks. No blue water may pass around either end.

At the LOWER brown marker, perform the same transformation. Remove the entire
brown oval, the underlying blue water, and all white linework inside the
marked area. Fill the complete width of that former entrance with one
irregular bank-connected sediment plug. Both ends must merge into the existing
banks. Leave no water-filled center, side gap, ring, island, or narrow channel
around the deposit.

Close only the two abandoned-meander side entrances identified by the brown
markers. Keep the adjacent active main river as one uninterrupted water
channel through the crop. Do not extend sediment across or block the active
main river.

On the abandoned-channel side of each new plug, the remaining water must end
at a natural irregular shoreline. Water on opposite sides of a plug must not
touch. Each former mouth must contain a clearly visible continuous land
interval from bank to bank.

Make each filled mouth broad along the former channel direction and irregular
at its edges, like gradual natural channel infill rather than a thin straight
dam. Use wet mud and sand at the remaining water edge, transitioning into
drier floodplain soil and sparse low vegetation. The new terrain must look
fused with the surrounding banks, never placed on top of the water.

Image 2 supplies only the local material appearance of this same place:
river-water color, mud, sand, soil, vegetation, lighting and aerial scale.
Do not copy its open-water connectivity or its former channel openings.

Image 3 supplies only supporting environmental texture and color. Do not copy
its river geometry or connectivity.

Preserve the geometry and appearance of every area outside the two narrow
marked entrance regions. Keep all other banks, water channels, vegetation,
lighting, top-down camera and terrain unchanged.

No brown ellipses, blue halos, water-filled rings, floating sediment,
vegetated islands, isolated objects, white lines, white particles, arrows,
symbols, text, new channels, blocked active river, roads, buildings, boats or
people."""


CONDITIONS = {
    "A_original": A_PROMPT,
    "B_marker_explicit": B_PROMPT,
}
DENOISES = (0.55, 0.70, 0.85)


def suffix(denoise: float) -> str:
    return f"{int(round(denoise * 100)):03d}"


def copy_inputs(source_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("inputs", "prompts", "workflows", "patches", "composites"):
        (output_dir / directory).mkdir(exist_ok=True)
    for condition in CONDITIONS:
        (output_dir / "workflows" / condition).mkdir(exist_ok=True)
        (output_dir / "patches" / condition).mkdir(exist_ok=True)
        (output_dir / "composites" / condition).mkdir(exist_ok=True)

    copies = {
        source_dir / "model_inputs" / "after_clean_patch.png": output_dir / "inputs" / "after_clean_patch.png",
        source_dir / "model_inputs" / "before_realistic_reference.png": output_dir / "inputs" / "before_realistic_reference.png",
        source_dir / "model_inputs" / "world_reference_patch.png": output_dir / "inputs" / "world_reference_patch.png",
        source_dir / "before_isolation_realistic.png": output_dir / "inputs" / "before_isolation_realistic.png",
        source_dir / "change_mask.png": output_dir / "inputs" / "change_mask.png",
        source_dir / "change_bbox.png": output_dir / "inputs" / "change_bbox.png",
        source_dir / "selection.json": output_dir / "inputs" / "selection.json",
    }
    for source, destination in copies.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)

    (output_dir / "prompts" / "A_original.txt").write_text(A_PROMPT + "\n", encoding="utf-8")
    (output_dir / "prompts" / "B_marker_explicit.txt").write_text(B_PROMPT + "\n", encoding="utf-8")


def comfy_inputs(output_dir: Path) -> tuple[str, str, str, str]:
    after_reference = base.copy_comfy_input(
        output_dir / "inputs" / "after_clean_patch.png",
        "oxbow-prompt-ab-after-clean-reference.png",
    )
    before_reference = base.copy_comfy_input(
        output_dir / "inputs" / "before_realistic_reference.png",
        "oxbow-prompt-ab-before-realistic-reference.png",
    )
    world_reference = base.copy_comfy_input(
        output_dir / "inputs" / "world_reference_patch.png",
        "oxbow-prompt-ab-world-reference.png",
    )
    after_start = base.copy_comfy_input(
        output_dir / "inputs" / "after_clean_patch.png",
        "oxbow-prompt-ab-after-clean-start.png",
    )
    return after_reference, before_reference, world_reference, after_start


def load_generation(output_dir: Path) -> dict:
    path = output_dir / "generation.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "experiment": "oxbow local edit prompt A/B",
        "controlled_variable": "prompt text only",
        "engine": "local ComfyUI",
        "server": base.SERVER,
        "model": base.MODEL,
        "text_encoder": base.TEXT_ENCODER,
        "vae": base.VAE,
        "seed": base.SEED,
        "steps": base.STEPS,
        "guidance": base.GUIDANCE,
        "sampler": base.SAMPLER,
        "output_size": list(base.PATCH_MODEL_SIZE),
        "start_latent": "inputs/after_clean_patch.png",
        "references": [
            "inputs/after_clean_patch.png",
            "inputs/before_realistic_reference.png",
            "inputs/world_reference_patch.png",
        ],
        "runs": {},
    }


def save_generation(output_dir: Path, data: dict) -> None:
    (output_dir / "generation.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def graph_signature(graph: dict) -> str:
    normalized = json.loads(json.dumps(graph))
    for node in normalized.values():
        if node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = "<PROMPT>"
        if node.get("class_type") == "SaveImage":
            node["inputs"]["filename_prefix"] = "<PREFIX>"
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate(output_dir: Path) -> None:
    after_reference, before_reference, world_reference, after_start = comfy_inputs(output_dir)
    generation = load_generation(output_dir)
    signatures: dict[str, dict[str, str]] = {}
    for condition, prompt in CONDITIONS.items():
        signatures[condition] = {}
        for denoise in DENOISES:
            name = suffix(denoise)
            graph, save_node = base.build_workflow(
                [after_reference, before_reference, world_reference],
                prompt,
                f"oxbow_prompt_ab/{condition}/denoise_{name}",
                base.PATCH_MODEL_SIZE,
                denoise,
                after_start,
            )
            workflow_path = output_dir / "workflows" / condition / f"denoise_{name}.json"
            workflow_path.write_text(
                json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            signatures[condition][name] = graph_signature(graph)
            destination = output_dir / "patches" / condition / f"denoise_{name}.png"
            result = base.run_workflow(
                graph,
                save_node,
                destination,
                f"{condition} denoise {denoise:.2f}",
            )
            generation["runs"][f"{condition}/denoise_{name}"] = {
                **result,
                "prompt": f"prompts/{condition}.txt",
                "denoise": denoise,
                "effective_transitions": round(base.STEPS * denoise),
                "workflow": f"workflows/{condition}/denoise_{name}.json",
                "output": f"patches/{condition}/denoise_{name}.png",
                "graph_signature_without_prompt_or_prefix": signatures[condition][name],
            }
            save_generation(output_dir, generation)

    for name in (suffix(value) for value in DENOISES):
        if signatures["A_original"][name] != signatures["B_marker_explicit"][name]:
            raise RuntimeError(f"A/B workflow differs beyond prompt/prefix at denoise {name}")
    generation["ab_graph_equivalence_verified"] = True
    save_generation(output_dir, generation)


def compose(output_dir: Path) -> None:
    selection = json.loads((output_dir / "inputs" / "selection.json").read_text(encoding="utf-8"))
    bbox = tuple(selection["bbox_experiment_pixels"])
    base_image = Image.open(output_dir / "inputs" / "before_isolation_realistic.png").convert("RGB")
    hard_mask = np.asarray(Image.open(output_dir / "inputs" / "change_mask.png").convert("L")) > 0
    crop_mask = hard_mask[bbox[1] : bbox[3], bbox[0] : bbox[2]]
    distance_inside = ndimage.distance_transform_edt(crop_mask)
    alpha = np.clip(distance_inside / 12.0, 0.0, 1.0)
    alpha[crop_mask & (distance_inside >= 12)] = 1.0
    alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L")
    crop_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])

    for condition in CONDITIONS:
        for denoise in DENOISES:
            name = suffix(denoise)
            patch = Image.open(output_dir / "patches" / condition / f"denoise_{name}.png").convert("RGB")
            patch = patch.resize(crop_size, Image.Resampling.LANCZOS)
            composite = base_image.copy()
            original_crop = base_image.crop(bbox)
            blended = Image.composite(patch, original_crop, alpha_image)
            composite.paste(blended, (bbox[0], bbox[1]))
            composite.save(output_dir / "composites" / condition / f"denoise_{name}.png")


def contain(image: Image.Image, size: tuple[int, int], background=(244, 242, 234)) -> Image.Image:
    canvas = Image.new("RGB", size, background)
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def comparison(output_dir: Path) -> None:
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        title_font = label_font = ImageFont.load_default()

    columns = [
        ("A patch · original prompt", "patches", "A_original"),
        ("B patch · explicit markers", "patches", "B_marker_explicit"),
        ("A composite", "composites", "A_original"),
        ("B composite", "composites", "B_marker_explicit"),
    ]
    cell_size = (360, 300)
    header_height = 48
    row_label_width = 105
    sheet = Image.new(
        "RGB",
        (row_label_width + len(columns) * cell_size[0], header_height + len(DENOISES) * cell_size[1]),
        (24, 31, 42),
    )
    draw = ImageDraw.Draw(sheet)
    for index, (label, _, _) in enumerate(columns):
        draw.text((row_label_width + index * cell_size[0] + 10, 10), label, fill=(245, 247, 249), font=label_font)
    for row, denoise in enumerate(DENOISES):
        name = suffix(denoise)
        y = header_height + row * cell_size[1]
        draw.text((14, y + 122), f"{denoise:.2f}", fill=(245, 247, 249), font=title_font)
        for column, (_, directory, condition) in enumerate(columns):
            image_path = output_dir / directory / condition / f"denoise_{name}.png"
            tile = contain(Image.open(image_path), cell_size)
            sheet.paste(tile, (row_label_width + column * cell_size[0], y))
    sheet.save(output_dir / "comparison.png")

    input_paths = [
        ("Image 1 / start: after clean", output_dir / "inputs" / "after_clean_patch.png"),
        ("Image 2: before realistic", output_dir / "inputs" / "before_realistic_reference.png"),
        ("Image 3: world style", output_dir / "inputs" / "world_reference_patch.png"),
    ]
    input_cell = (420, 420)
    inputs_sheet = Image.new("RGB", (3 * input_cell[0], input_cell[1] + 48), (24, 31, 42))
    inputs_draw = ImageDraw.Draw(inputs_sheet)
    for index, (label, path) in enumerate(input_paths):
        inputs_draw.text((index * input_cell[0] + 10, 10), label, fill=(245, 247, 249), font=label_font)
        inputs_sheet.paste(contain(Image.open(path), input_cell), (index * input_cell[0], 48))
    inputs_sheet.save(output_dir / "inputs.png")

    selection = json.loads((output_dir / "inputs" / "selection.json").read_text(encoding="utf-8"))
    bbox = tuple(selection["bbox_experiment_pixels"])
    closeup_cell = (430, 430)
    closeup_sheet = Image.new(
        "RGB",
        (row_label_width + 2 * closeup_cell[0], header_height + len(DENOISES) * closeup_cell[1]),
        (24, 31, 42),
    )
    closeup_draw = ImageDraw.Draw(closeup_sheet)
    closeup_draw.text((row_label_width + 10, 10), "A composite close-up", fill=(245, 247, 249), font=label_font)
    closeup_draw.text((row_label_width + closeup_cell[0] + 10, 10), "B composite close-up", fill=(245, 247, 249), font=label_font)
    for row, denoise in enumerate(DENOISES):
        name = suffix(denoise)
        y = header_height + row * closeup_cell[1]
        closeup_draw.text((14, y + 185), f"{denoise:.2f}", fill=(245, 247, 249), font=title_font)
        for column, condition in enumerate(("A_original", "B_marker_explicit")):
            composite_path = output_dir / "composites" / condition / f"denoise_{name}.png"
            crop = Image.open(composite_path).convert("RGB").crop(bbox)
            tile = contain(crop, closeup_cell)
            closeup_sheet.paste(tile, (row_label_width + column * closeup_cell[0], y))
    closeup_sheet.save(output_dir / "comparison_closeups.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "generate", "compose", "comparison"])
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.action == "prepare":
        if args.source_dir is None:
            parser.error("prepare requires --source-dir")
        copy_inputs(args.source_dir.resolve(), output_dir)
    elif args.action == "generate":
        generate(output_dir)
    elif args.action == "compose":
        compose(output_dir)
    elif args.action == "comparison":
        comparison(output_dir)


if __name__ == "__main__":
    main()
