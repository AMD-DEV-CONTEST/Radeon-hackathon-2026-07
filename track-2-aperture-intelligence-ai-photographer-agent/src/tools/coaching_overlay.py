"""Render actionable photography coaching directly on the user's image."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

PROJECT_FONT = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "fonts"
    / "NotoSansCJK-Regular.ttc"
)
FONT_CANDIDATES = (
    str(PROJECT_FONT),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _xy(box: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    return tuple(
        int(value * (width if index % 2 == 0 else height) / 1000)
        for index, value in enumerate(box)
    )  # type: ignore[return-value]


def _intersection_fraction(
    first: list[int],
    second: list[int],
) -> float:
    """Return how much of ``first`` is covered by ``second``."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    return intersection / first_area if first_area else 0.0


def _filter_avoid_regions(
    regions: list[list[int]],
    people: list[list[int]],
    *,
    max_person_overlap: float = 0.15,
) -> tuple[list[list[int]], int]:
    """Suppress distraction boxes that substantially cover a coached person."""
    kept = [
        region
        for region in regions
        if not any(
            _intersection_fraction(region, person) > max_person_overlap
            for person in people
        )
    ]
    return kept, len(regions) - len(kept)


def _safe_tag_position(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    canvas_size: tuple[int, int],
    protected: tuple[int, int, int, int],
    occupied: list[tuple[int, int, int, int]] | None = None,
) -> tuple[int, int]:
    """Keep a tag on-canvas and away from the panel and earlier tags."""
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    padding = max(5, int(getattr(font, "size", 16) * 0.32))
    canvas_width, canvas_height = canvas_size
    occupied = occupied or []

    def clamp(candidate: tuple[int, int]) -> tuple[int, int]:
        return (
            max(padding, min(candidate[0], canvas_width - text_width - padding)),
            max(padding, min(candidate[1], canvas_height - text_height - padding)),
        )

    def bounds(candidate: tuple[int, int]) -> tuple[int, int, int, int]:
        x, y = candidate
        return (
            x - padding,
            y - padding,
            x + text_width + padding,
            y + text_height + padding,
        )

    def intersects(
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
    ) -> bool:
        return not (
            first[2] < second[0]
            or first[0] > second[2]
            or first[3] < second[1]
            or first[1] > second[3]
        )

    step = text_height + padding * 3
    candidates = [
        position,
        (position[0], protected[3] + padding * 2),
        (position[0], position[1] + step),
        (position[0], position[1] - step),
        (position[0], position[1] + step * 2),
        (position[0], position[1] - step * 2),
    ]
    last = clamp(position)
    for raw_candidate in candidates:
        candidate = clamp(raw_candidate)
        last = candidate
        candidate_box = bounds(candidate)
        if intersects(candidate_box, protected):
            continue
        if any(intersects(candidate_box, existing) for existing in occupied):
            continue
        return candidate
    return last


def _tag_bounds(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = draw.textbbox(position, text, font=font)
    padding = max(5, int(getattr(font, "size", 16) * 0.32))
    return left - padding, top - padding, right + padding, bottom + padding


def _dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    width: int,
    dash: int,
) -> None:
    x1, y1, x2, y2 = box
    for start in range(x1, x2, dash * 2):
        draw.line((start, y1, min(start + dash, x2), y1), fill=fill, width=width)
        draw.line((start, y2, min(start + dash, x2), y2), fill=fill, width=width)
    for start in range(y1, y2, dash * 2):
        draw.line((x1, start, x1, min(start + dash, y2)), fill=fill, width=width)
        draw.line((x2, start, x2, min(start + dash, y2)), fill=fill, width=width)


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = width * 4
    for offset in (2.55, -2.55):
        point = (
            int(end[0] + math.cos(angle + offset) * size),
            int(end[1] + math.sin(angle + offset) * size),
        )
        draw.line((end, point), fill=fill, width=width)


def _tag(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = draw.textbbox(position, text, font=font)
    padding = max(5, int(getattr(font, "size", 16) * 0.32))
    draw.rounded_rectangle(
        (
            left - padding,
            top - padding,
            right + padding,
            bottom + padding,
        ),
        radius=padding,
        fill=(12, 15, 14, 205),
        outline=fill,
        width=max(1, padding // 3),
    )
    draw.text(position, text, font=font, fill="white")


def render_coaching_overlay(
    image_path: str | Path,
    analysis: dict[str, Any],
    plan: dict[str, Any],
    output_path: str | Path,
    *,
    segmenter: Any | None = None,
) -> dict[str, Any]:
    """Create a standalone contour coaching card without source-image pixels."""
    started = time.perf_counter()
    source = Path(image_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    scale = min(1.0, 1600 / max(image.size))
    image = image.resize(
        (int(image.width * scale), int(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", image.size, (24, 29, 33, 255))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    pose_mask = Image.new("L", canvas.size, 0)
    width, height = canvas.size
    stroke = max(3, int(max(width, height) / 350))

    people = analysis.get("people_boxes") or [[300, 180, 700, 900]]
    requested_avoid = list(analysis.get("avoid_regions") or [])
    avoid, suppressed_avoid = _filter_avoid_regions(requested_avoid, list(people))
    camera_move = str(analysis.get("camera_move", "stay"))
    subject_move = str(analysis.get("subject_move", "stay"))

    shifts = {
        "left": (-int(width * 0.08), 0),
        "right": (int(width * 0.08), 0),
        "forward": (0, int(height * 0.04)),
        "back": (0, -int(height * 0.04)),
        "stay": (0, 0),
    }
    dx, dy = shifts.get(subject_move, (0, 0))
    targets: list[tuple[int, int, int, int]] = []
    for raw_box in people:
        current = _xy(raw_box, width, height)
        targets.append(current)
        if dx or dy:
            center = ((current[0] + current[2]) // 2, (current[1] + current[3]) // 2)
            _arrow(draw, center, (center[0] + dx, center[1] + dy), (255, 193, 61, 240), stroke)

    model_direction = plan.get("model_direction", {})
    human_context = " ".join(
        (
            str(analysis.get("subject", "")),
            str(analysis.get("relationship", "")),
            str(model_direction.get("position", "")),
            str(model_direction.get("action", "")),
        )
    ).lower()
    family = any(
        word in human_context
        for word in ("child", "parent", "family", "mother", "father")
    )
    pose_color = (255, 193, 61, 215)
    action_tags: list[tuple[tuple[int, int], str]] = []
    used_action_anchors: set[str] = set()
    for label in analysis.get("action_labels") or []:
        if not isinstance(label, dict):
            continue
        indices = [
            index
            for index in label.get("person_indices", [])
            if isinstance(index, int) and 0 <= index < len(targets)
        ]
        text = str(label.get("text", "")).strip()
        if not indices or not text:
            continue
        boxes = [targets[index] for index in indices]
        anchor = str(label.get("anchor", "body"))
        if anchor == "between" and len(boxes) >= 2:
            centers = [
                ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
                for box in boxes
            ]
            position = (
                sum(center[0] for center in centers) // len(centers),
                sum(center[1] for center in centers) // len(centers),
            )
        else:
            box = boxes[0]
            box_width = box[2] - box[0]
            box_height = box[3] - box[1]
            fractions = {
                "head": (0.58, 0.12),
                "body": (0.02, 0.40),
                "hands": (0.02, 0.68),
                "feet": (0.02, 0.88),
                "between": (0.02, 0.55),
            }
            x_fraction, y_fraction = fractions.get(anchor, fractions["body"])
            position = (
                int(box[0] + box_width * x_fraction),
                int(box[1] + box_height * y_fraction),
            )
        action_tags.append((position, text))
        used_action_anchors.add(anchor)

    action_tag_source = "vlm" if action_tags else "fallback"
    visible_props = " ".join(analysis.get("visible_props") or []).lower()
    if (
        action_tags
        and targets
        and "hands" not in used_action_anchors
        and any(word in visible_props for word in ("phone", "smartphone", "mobile"))
    ):
        subject_box = targets[0]
        subject_height = subject_box[3] - subject_box[1]
        action_tags.append(
            (
                (
                    subject_box[0],
                    int(subject_box[1] + subject_height * 0.68),
                ),
                "Phone: lower it slightly",
            )
        )
        action_tag_source = "vlm+validated_fallback"
    if not action_tags and family and len(targets) >= 2:
        ranked = sorted(
            targets,
            key=lambda item: (item[3] - item[1], item[2] - item[0]),
            reverse=True,
        )
        adult_box, child_box = ranked[0], ranked[-1]
        adult_center = (adult_box[0] + adult_box[2]) // 2
        child_center = (child_box[0] + child_box[2]) // 2
        adult_height = adult_box[3] - adult_box[1]
        child_height = child_box[3] - child_box[1]
        action_tags.extend(
            [
                (
                    (adult_box[0], max(8, adult_box[1] - stroke * 8)),
                    "Adult: turn toward the child",
                ),
                (
                    (child_box[0], max(8, child_box[1] - stroke * 8)),
                    "Child: look up in response",
                ),
                (
                    (
                        (adult_center + child_center) // 2,
                        int(
                            max(adult_box[1], child_box[1])
                            + min(adult_height, child_height) * 0.36
                        ),
                    ),
                    "Hold hands naturally",
                ),
            ]
        )
    elif not action_tags and targets:
        subject_box = targets[0]
        subject_width = subject_box[2] - subject_box[0]
        subject_height = subject_box[3] - subject_box[1]
        hand_text = (
            "Hands: hold the phone naturally"
            if any(word in human_context for word in ("phone", "smartphone", "mobile"))
            else "Hands: use one simple action"
        )
        action_tags.extend(
            [
                (
                    (subject_box[0], max(8, subject_box[1] - stroke * 8)),
                    "Body: turn slightly to the side",
                ),
                (
                    (
                        subject_box[0],
                        int(subject_box[1] + subject_height * 0.72),
                    ),
                    hand_text,
                ),
                (
                    (
                        int(subject_box[0] + subject_width * 0.58),
                        int(subject_box[1] + subject_height * 0.18),
                    ),
                    "Gaze: look to camera, then away",
                ),
            ]
        )

    outline_details: dict[str, Any]
    try:
        if segmenter is None:
            from src.tools.person_segmenter import get_shared_person_segmenter

            segmenter = get_shared_person_segmenter()
        segmentation = segmenter.segment(image, list(people))
        for person_mask in segmentation.pop("masks", []):
            if person_mask.size != canvas.size:
                person_mask = person_mask.resize(
                    canvas.size,
                    Image.Resampling.BILINEAR,
                )
            pose_mask = ImageChops.lighter(pose_mask, person_mask)
        outline_details = segmentation
    except Exception as exc:
        outline_details = {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "people_matched": 0,
        }

    smooth_mask = pose_mask.filter(
        ImageFilter.GaussianBlur(radius=max(1.5, stroke * 0.75))
    ).point(lambda value: 255 if value >= 92 else 0)
    edge_size = 3
    outer = smooth_mask.filter(ImageFilter.MaxFilter(edge_size))
    inner = smooth_mask.filter(ImageFilter.MinFilter(edge_size))
    pose_edge = ImageChops.subtract(outer, inner)
    silhouette_layer = Image.new("RGBA", canvas.size, (238, 241, 238, 0))
    silhouette_layer.putalpha(
        smooth_mask.point(lambda value: int(value * 0.10))
    )
    layer = Image.alpha_composite(layer, silhouette_layer)
    pose_layer = Image.new("RGBA", canvas.size, pose_color)
    pose_layer.putalpha(pose_edge.point(lambda value: int(value * 0.78)))
    layer = Image.alpha_composite(layer, pose_layer)
    draw = ImageDraw.Draw(layer)

    camera_text = {
        "left": "Move the camera left to clear the background",
        "right": "Move the camera right to clear the background",
        "closer": "Move closer to emphasize subject interaction",
        "lower": "Lower the camera slightly to strengthen the sense of place",
        "higher": "Raise the camera slightly to simplify subject-background overlap",
        "stay": "Keep this angle, then take one side-step to clear bystanders",
    }.get(camera_move, "Keep this angle, then take one side-step to clear bystanders")
    model_text = {
        "left": "Move the subject left to the yellow target",
        "right": "Move the subject right to the yellow target",
        "forward": "Take one step forward, then begin the interaction",
        "back": "Take one step back to leave room for the setting",
        "stay": (
            "Adult turns toward child; child looks up; walk three to five steps holding hands"
            if family
            else "Keep the same spot, turn slightly, and take one small step"
        ),
    }.get(
        subject_move,
        "Adult turns toward child; child looks up; walk three to five steps holding hands"
        if family
        else "Keep the same spot, turn slightly, and take one small step",
    )
    simple_model_steps = list(
        plan.get("plain_language_guide", {}).get("model", [])
    )
    instructions = [
        camera_text,
        model_text,
    ]
    if family:
        instructions.append(
            "Adult turns toward child; child looks up; walk three to five steps holding hands"
        )
    if simple_model_steps:
        instructions.append(str(simple_model_steps[-1]))
    instructions = list(dict.fromkeys(instructions))

    font = _font(max(18, int(max(width, height) / 55)))
    small = _font(max(14, int(max(width, height) / 70)))
    tag_font = _font(max(14, int(max(width, height) / 82)))
    outline_ready = int(outline_details.get("people_matched", 0)) > 0
    legend = [
        ("1", camera_text, (50, 190, 255, 255)),
        (
            "2",
            (
                "Yellow contour: " + model_text
                if outline_ready
                else "Action labels: " + model_text
            ),
            (255, 193, 61, 255),
        ),
    ]
    line_height = max(30, int(max(width, height) / 36))
    panel_width = min(width - 24, int(width * 0.66))
    panel_height = 20 + line_height * len(legend)
    panel_box = (12, 12, 12 + panel_width, 12 + panel_height)
    draw.rounded_rectangle(
        panel_box,
        radius=12,
        fill=(8, 12, 12, 190),
    )
    for index, (number, text, color) in enumerate(legend):
        y = 22 + index * line_height
        draw.ellipse((22, y, 22 + line_height - 8, y + line_height - 8), fill=color)
        draw.text(
            (31, y - 2),
            number,
            font=small,
            fill=(10, 10, 10, 255),
            anchor="ma",
        )
        draw.text((22 + line_height, y - 2), text, font=font, fill="white")
    occupied_tag_boxes: list[tuple[int, int, int, int]] = []
    for position, text in action_tags:
        safe_position = _safe_tag_position(
            draw,
            position,
            text,
            tag_font,
            canvas.size,
            panel_box,
            occupied_tag_boxes,
        )
        _tag(draw, safe_position, text, tag_font, pose_color)
        occupied_tag_boxes.append(
            _tag_bounds(draw, safe_position, text, tag_font)
        )

    result = Image.alpha_composite(canvas, layer).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result.save(destination, "PNG")
    return {
        "status": "generated",
        "render_mode": "isolated_contour",
        "path": str(destination),
        "width": result.width,
        "height": result.height,
        "seconds": round(time.perf_counter() - started, 3),
        "instructions": instructions,
        "action_tags": [text for _, text in action_tags],
        "action_tag_source": action_tag_source,
        "person_outline": outline_details,
        "avoid_regions": {
            "requested": len(requested_avoid),
            "rendered": 0,
            "suppressed_person_overlap": suppressed_avoid,
            "omitted_by_isolated_mode": len(avoid),
        },
        "legend": {
            "yellow": (
                "Real person-segmentation contour"
                if outline_ready
                else "Contour unavailable; action labels only"
            ),
            "background": "Isolated dark guidance canvas",
        },
        "source_preserved": True,
        "source_pixels_in_output": False,
    }
