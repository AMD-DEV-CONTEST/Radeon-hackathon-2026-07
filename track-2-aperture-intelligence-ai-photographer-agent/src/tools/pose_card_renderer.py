"""Deterministically render a field-ready AI photography execution card."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

CARD_SIZE = (1600, 1100)
# Dark Morandi palette: low saturation, warm gray foundation, restrained accents.
BG = (36, 39, 38, 255)             # charcoal gray
PANEL = (49, 53, 51, 255)          # muted slate
PANEL_ALT = (54, 56, 53, 255)      # warm graphite
LINE = (88, 94, 89, 255)           # soft sage gray
WHITE = (232, 228, 218, 255)       # parchment
MUTED = (177, 174, 165, 255)       # mushroom gray
BLUE = (125, 147, 157, 255)        # dusty blue
GOLD = (180, 160, 124, 255)        # muted ochre
PURPLE = (151, 139, 157, 255)      # dusty mauve
SAGE = (132, 148, 132, 255)        # desaturated sage
SILHOUETTE = (75, 79, 75, 255)     # warm shadow
OUTLINE_SHADOW = (28, 31, 30, 235) # dark contrast keyline
DETAIL = (202, 197, 185, 255)       # warm light detail

# Editorial Morandi poster palette.  The product card is meant to be read in
# daylight on a phone or laptop, so the poster uses a warm paper surface while
# the pose stage keeps enough depth for the real-mask contour to remain clear.
POSTER_BG = (231, 226, 216, 255)       # warm limestone paper
POSTER_SURFACE = (242, 238, 229, 255)  # uncoated ivory
POSTER_INK = (51, 54, 50, 255)         # softened charcoal
POSTER_MUTED = (103, 103, 96, 255)     # warm gray
POSTER_LINE = (189, 181, 167, 255)     # putty rule
POSTER_BLUE = (104, 126, 134, 255)     # dusty blue
POSTER_GOLD = (164, 137, 96, 255)      # aged brass
POSTER_SAGE = (126, 139, 126, 255)     # dried sage
POSTER_CLAY = (166, 132, 113, 255)     # muted terracotta
POSTER_STAGE = (58, 62, 58, 255)       # deep olive charcoal

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
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int] = PANEL,
    radius: int = 22,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=LINE, width=2)


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int = 3,
) -> list[str]:
    clean = " ".join(str(text or "").split()) or "Not available"
    lines: list[str] = []
    current = ""
    tokens = clean.split(" ")
    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = token
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    rendered = " ".join(lines)
    if len(rendered) < len(clean) and lines:
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_width:
            lines[-1] = lines[-1][:-1].rstrip()
        lines[-1] += "…"
    return lines


def _multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    max_width: int,
    *,
    max_lines: int = 3,
    spacing: int = 8,
) -> int:
    lines = _wrap(draw, text, font, max_width, max_lines=max_lines)
    draw.multiline_text(xy, "\n".join(lines), font=font, fill=fill, spacing=spacing)
    line_height = int(getattr(font, "size", 20) * 1.28) + spacing
    return line_height * len(lines)


def _heading(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    icon: str,
    title: str,
    color: tuple[int, int, int, int],
) -> None:
    x, y = xy
    draw.rounded_rectangle((x, y + 2, x + 32, y + 34), radius=8, outline=color, width=3)
    draw.text((x + 46, y - 3), title, font=_font(28), fill=color)


def _rounded_thumbnail(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    fitted = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=18, fill=255)
    output = Image.new("RGBA", size, (0, 0, 0, 0))
    output.paste(fitted.convert("RGBA"), (0, 0), mask)
    return output


def _draw_why_good(
    card: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    pose_json: dict[str, Any],
) -> None:
    box = (40, 120, 730, 570)
    _panel(draw, box)
    _heading(draw, (68, 146), "image", "Why This Photo Works", BLUE)
    thumbnail = _rounded_thumbnail(source, (300, 330))
    card.alpha_composite(thumbnail, (68, 205))
    why = pose_json["why_beautiful"]
    entries = (
        ("Atmosphere", why["atmosphere"]),
        ("Subject + Setting", why["relationship"]),
        ("Composition", why["composition"]),
        ("Prop", why["prop_role"]),
    )
    y = 205
    for title, text in entries:
        draw.ellipse((392, y + 7, 406, y + 21), fill=GOLD)
        draw.text((420, y), title, font=_font(19), fill=WHITE)
        y += 28
        y += _multiline(draw, (420, y), text, _font(15), MUTED, 270, max_lines=2, spacing=4)
        y += 5


def _parse_angle(value: str) -> float:
    digits = "".join(character for character in value if character.isdigit())
    if digits:
        return max(10.0, min(80.0, float(digits[:2])))
    lowered = value.lower()
    if "front" in lowered:
        return 0.0
    return 35.0


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: tuple[int, int, int, int],
    *,
    width: int = 3,
    dash: int = 10,
) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, math.hypot(dx, dy))
    for offset in range(0, int(length), dash * 2):
        first = offset / length
        second = min(offset + dash, length) / length
        draw.line(
            (
                int(start[0] + dx * first),
                int(start[1] + dy * first),
                int(start[0] + dx * second),
                int(start[1] + dy * second),
            ),
            fill=fill,
            width=width,
        )


def _draw_camera_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int]) -> None:
    x, y = center
    draw.rounded_rectangle((x - 28, y - 17, x + 24, y + 17), radius=6, fill=BLUE)
    draw.polygon(((x + 24, y - 11), (x + 42, y - 23), (x + 42, y + 23), (x + 24, y + 11)), fill=BLUE)
    draw.ellipse((x - 10, y - 9, x + 8, y + 9), outline=(8, 20, 33, 255), width=4)


def _draw_person_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int]) -> None:
    x, y = center
    draw.ellipse((x - 12, y - 42, x + 12, y - 18), fill=GOLD)
    draw.rounded_rectangle((x - 13, y - 14, x + 13, y + 27), radius=7, fill=GOLD)
    draw.line((x - 7, y + 25, x - 7, y + 50), fill=GOLD, width=8)
    draw.line((x + 7, y + 25, x + 7, y + 50), fill=GOLD, width=8)


def _draw_photographer(
    draw: ImageDraw.ImageDraw,
    pose_json: dict[str, Any],
) -> None:
    box = (40, 590, 730, 1060)
    _panel(draw, box, fill=PANEL_ALT)
    _heading(draw, (68, 616), "camera", "How the Photographer Shoots", BLUE)
    photographer = pose_json["photographer"]
    entries = (
        ("Distance", photographer["distance"]),
        ("Angle", photographer["angle"]),
        ("Height", photographer["height"]),
        ("Background", photographer["background"]),
        ("Purpose", photographer["purpose"]),
    )
    y = 677
    for title, value in entries:
        draw.text((70, y), title, font=_font(18), fill=BLUE)
        _multiline(draw, (128, y), value, _font(17), WHITE, 270, max_lines=2, spacing=4)
        y += 48
    draw.text((512, 880), photographer["distance"], font=_font(18), fill=WHITE, anchor="ma")
    draw.arc((camera[0] - 15, camera[1] - 85, camera[0] + 155, camera[1] + 85), 190, 245, fill=GOLD, width=4)
    draw.text((545, 735), photographer["angle"], font=_font(18), fill=GOLD, anchor="ma")
    draw.text((565, 975), "Top-view camera diagram", font=_font(16), fill=MUTED, anchor="ma")


def _composite_masks(
    source: Image.Image,
    people: list[list[int]],
    segmenter: Any | None,
) -> tuple[Image.Image, dict[str, Any]]:
    if segmenter is None:
        from src.tools.segmentation import get_shared_person_segmenter

        segmenter = get_shared_person_segmenter()
    segmentation = segmenter.segment(source, people)
    masks = segmentation.pop("masks", [])
    combined = Image.new("L", source.size, 0)
    for mask in masks:
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.Resampling.BILINEAR)
        combined = ImageChops.lighter(combined, mask)
    return combined, segmentation


def _place_silhouette(mask: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    target = Image.new("L", CARD_SIZE, 0)
    bbox = mask.getbbox()
    if not bbox:
        return target, (980, 280, 1370, 940)
    cropped = mask.crop(bbox)
    # Leave breathing room around the cutout so labels read as coaching notes
    # around a subject, not as overlays fighting a full-bleed technical mask.
    max_width, max_height = 470, 540
    scale = min(max_width / cropped.width, max_height / cropped.height)
    resized = cropped.resize(
        (max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = 1150 - resized.width // 2
    top = 310 + (540 - resized.height) // 2
    target.paste(resized, (left, top))
    return target, (left, top, left + resized.width, top + resized.height)


def _refined_outline_layers(mask: Image.Image) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Clean a real mask and return soft fill, binary core, and restrained halo."""
    closed = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    opened = closed.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    soft = opened.filter(ImageFilter.GaussianBlur(radius=1.15))
    core = soft.point(lambda value: 255 if value >= 112 else 0)
    halo = ImageChops.subtract(
        core.filter(ImageFilter.MaxFilter(7)),
        core.filter(ImageFilter.MinFilter(7)),
    ).filter(ImageFilter.GaussianBlur(radius=1.1))
    return soft, core, halo


def _marching_contours(mask: Image.Image) -> list[list[tuple[float, float]]]:
    """Trace deterministic half-pixel contours with a marching-squares table."""
    import numpy as np

    bbox = mask.getbbox()
    if not bbox:
        return []
    pad = 2
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(mask.width, bbox[2] + pad)
    bottom = min(mask.height, bbox[3] + pad)
    binary = np.asarray(mask.crop((left, top, right, bottom)), dtype=np.uint8) >= 128
    table = {
        1: (("bottom", "left"),), 2: (("right", "bottom"),),
        3: (("right", "left"),), 4: (("top", "right"),),
        5: (("top", "left"), ("right", "bottom")),
        6: (("top", "bottom"),), 7: (("top", "left"),),
        8: (("left", "top"),), 9: (("bottom", "top"),),
        10: (("left", "bottom"), ("top", "right")),
        11: (("top", "right"),), 12: (("left", "right"),),
        13: (("right", "bottom"),), 14: (("bottom", "left"),),
    }
    graph: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y in range(binary.shape[0] - 1):
        for x in range(binary.shape[1] - 1):
            case = (
                (8 if binary[y, x] else 0)
                | (4 if binary[y, x + 1] else 0)
                | (2 if binary[y + 1, x + 1] else 0)
                | (1 if binary[y + 1, x] else 0)
            )
            points = {
                "top": (2 * x + 1, 2 * y),
                "right": (2 * x + 2, 2 * y + 1),
                "bottom": (2 * x + 1, 2 * y + 2),
                "left": (2 * x, 2 * y + 1),
            }
            for first, second in table.get(case, ()):
                a, b = points[first], points[second]
                graph.setdefault(a, []).append(b)
                graph.setdefault(b, []).append(a)
    paths: list[list[tuple[float, float]]] = []
    visited: set[frozenset[tuple[int, int]]] = set()
    for seed in graph:
        for neighbor in graph[seed]:
            edge = frozenset((seed, neighbor))
            if edge in visited:
                continue
            path = [seed]
            previous, current = seed, neighbor
            visited.add(edge)
            while True:
                path.append(current)
                candidates = [node for node in graph.get(current, []) if node != previous]
                next_node = next(
                    (node for node in candidates if frozenset((current, node)) not in visited),
                    None,
                )
                if next_node is None:
                    break
                visited.add(frozenset((current, next_node)))
                previous, current = current, next_node
                if current == seed:
                    path.append(current)
                    break
            if len(path) >= 18:
                paths.append([((x / 2) + left, (y / 2) + top) for x, y in path])
    return paths


def _chaikin(path: list[tuple[float, float]], iterations: int = 2) -> list[tuple[float, float]]:
    """Round a closed contour without inventing a different body pose."""
    points = path[:-1] if len(path) > 2 and path[0] == path[-1] else path[:]
    if len(points) < 4:
        return points
    for _ in range(iterations):
        rounded: list[tuple[float, float]] = []
        for index, point in enumerate(points):
            nxt = points[(index + 1) % len(points)]
            rounded.append((point[0] * .75 + nxt[0] * .25, point[1] * .75 + nxt[1] * .25))
            rounded.append((point[0] * .25 + nxt[0] * .75, point[1] * .25 + nxt[1] * .75))
        points = rounded
    return points


def _vector_outline(mask: Image.Image, *, clip_bottom_y: int | None = None) -> Image.Image:
    """Render smooth contour paths at 3x; omit an artificial source-edge floor."""
    scale = 3
    layer = Image.new("RGBA", (CARD_SIZE[0] * scale, CARD_SIZE[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for contour in _marching_contours(mask):
        rounded = _chaikin(contour)
        if len(rounded) < 4:
            continue
        points = [(round(x * scale), round(y * scale)) for x, y in rounded]
        points.append(points[0])
        draw.line(points, fill=OUTLINE_SHADOW, width=11, joint="curve")
        draw.line(points, fill=GOLD, width=5, joint="curve")
    rendered = layer.resize(CARD_SIZE, Image.Resampling.LANCZOS)
    if clip_bottom_y is not None:
        alpha = rendered.getchannel("A")
        ImageDraw.Draw(alpha).rectangle((0, clip_bottom_y - 3, CARD_SIZE[0], clip_bottom_y + 5), fill=0)
        rendered.putalpha(alpha)
    return rendered


def _subject_detail_edges(
    source: Image.Image,
    source_mask: Image.Image,
    placed_mask: Image.Image,
    silhouette_box: tuple[int, int, int, int],
) -> Image.Image:
    """Extract graded photographic detail lines inside the real person mask."""
    layer = Image.new("L", CARD_SIZE, 0)
    source_box = source_mask.getbbox()
    if not source_box:
        return layer
    left, top, right, bottom = silhouette_box
    size = (max(1, right - left), max(1, bottom - top))
    subject = ImageOps.grayscale(source.crop(source_box)).resize(size, Image.Resampling.LANCZOS)
    fine_raw = subject.filter(ImageFilter.GaussianBlur(radius=0.65)).filter(ImageFilter.FIND_EDGES)
    coarse_raw = subject.filter(ImageFilter.GaussianBlur(radius=2.2)).filter(ImageFilter.FIND_EDGES)
    fine_raw = ImageOps.autocontrast(fine_raw, cutoff=2)
    coarse_raw = ImageOps.autocontrast(coarse_raw, cutoff=2)
    fine = fine_raw.point(lambda value: 0 if value < 118 else min(215, int((value - 118) * 1.4)))
    coarse = coarse_raw.point(lambda value: 0 if value < 82 else min(220, int((value - 82) * 1.4)))
    strong = fine_raw.point(lambda value: 0 if value < 175 else min(240, int((value - 175) * 2.3)))

    zone = Image.new("L", size, 0)
    zone_draw = ImageDraw.Draw(zone)
    height = size[1]
    zone_draw.rectangle((0, 0, size[0], int(height * .34)), fill=125)
    zone_draw.rectangle((0, int(height * .34), size[0], int(height * .56)), fill=45)
    zone_draw.rectangle((0, int(height * .56), size[0], int(height * .80)), fill=105)
    zone_draw.rectangle((0, int(height * .80), size[0], height), fill=40)
    fine_graded = ImageChops.multiply(fine, zone)
    structure = coarse.point(lambda value: int(value * .48))
    accents = strong.point(lambda value: int(value * .62))
    graded = ImageChops.lighter(ImageChops.lighter(fine_graded, structure), accents)
    interior = placed_mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(radius=0.7))
    details = ImageChops.multiply(graded, interior.crop(silhouette_box)).filter(ImageFilter.GaussianBlur(radius=0.35))
    layer.paste(details, (left, top))
    return layer


def _composite_refined_outline(
    card: Image.Image,
    placed: Image.Image,
    detail_edges: Image.Image,
    *,
    clip_bottom_y: int | None = None,
) -> Image.Image:
    soft, core, halo = _refined_outline_layers(placed)

    fill_layer = Image.new("RGBA", CARD_SIZE, SILHOUETTE)
    fill_layer.putalpha(soft.point(lambda value: int(value * 0.34)))
    card.alpha_composite(fill_layer)

    detail_layer = Image.new("RGBA", CARD_SIZE, DETAIL)
    # Keep only structural face, hair, hand, and clothing cues.  The previous
    # stronger blend read as photographic noise rather than an action guide.
    detail_layer.putalpha(detail_edges.point(lambda value: int(value * 0.42)))
    card.alpha_composite(detail_layer)

    halo_layer = Image.new("RGBA", CARD_SIZE, SAGE)
    halo_layer.putalpha(halo.point(lambda value: int(value * 0.12)))
    card.alpha_composite(halo_layer)
    card.alpha_composite(_vector_outline(core, clip_bottom_y=clip_bottom_y))
    return core


def _label_start(box: tuple[int, int, int, int], side: str) -> tuple[int, int]:
    return (box[2], (box[1] + box[3]) // 2) if side == "left" else (box[0], (box[1] + box[3]) // 2)


def _snap_anchor_to_mask(
    mask: Image.Image,
    box: tuple[int, int, int, int],
    nominal: tuple[int, int],
    side: str,
) -> tuple[int, int]:
    """Move a semantic anchor to the first real-mask intersection from its label."""
    start = _label_start(box, side)
    for step in range(1, 241):
        ratio = step / 240
        x = round(start[0] + (nominal[0] - start[0]) * ratio)
        y = round(start[1] + (nominal[1] - start[1]) * ratio)
        if 0 <= x < mask.width and 0 <= y < mask.height and mask.getpixel((x, y)) >= 128:
            return x, y
    return nominal

def _label_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    value: str,
    anchor: tuple[int, int],
    *,
    side: str,
) -> None:
    draw.rounded_rectangle(box, radius=12, fill=(45, 48, 46, 245), outline=GOLD, width=2)
    draw.text((box[0] + 14, box[1] + 9), title, font=_font(17), fill=GOLD)
    _multiline(draw, (box[0] + 14, box[1] + 35), value, _font(16), WHITE, box[2] - box[0] - 28, max_lines=2, spacing=3)
    start = _label_start(box, side)
    _dashed_line(draw, start, anchor, GOLD, width=2, dash=7)
    draw.ellipse((anchor[0] - 5, anchor[1] - 5, anchor[0] + 5, anchor[1] + 5), fill=GOLD)


def _draw_pose(
    card: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    people: list[list[int]],
    pose_json: dict[str, Any],
    segmenter: Any | None,
) -> dict[str, Any]:
    box = (750, 120, 1560, 1060)
    _panel(draw, box, fill=PANEL_ALT)
    _heading(draw, (780, 146), "person", "How the Subject Stands and Moves", GOLD)
    try:
        mask, details = _composite_masks(source, people, segmenter)
    except Exception as exc:
        mask = Image.new("L", source.size, 0)
        details = {"status": "unavailable", "people_matched": 0, "reason": f"{type(exc).__name__}: {exc}"}
    placed, silhouette_box = _place_silhouette(mask)
    detail_edges = _subject_detail_edges(source, mask, placed, silhouette_box)
    source_box = mask.getbbox()
    clip_bottom_y = silhouette_box[3] if source_box and source_box[3] >= mask.height - 2 else None
    anchor_mask = _composite_refined_outline(
        card, placed, detail_edges, clip_bottom_y=clip_bottom_y
    )
    draw = ImageDraw.Draw(card)

    left, top, right, bottom = silhouette_box
    width, height = max(1, right - left), max(1, bottom - top)
    body = pose_json["body_pose"]
    hands = pose_json["hands"]
    gaze = pose_json["gaze"]
    labels = (
        ((790, 245, 1025, 330), "Gaze", gaze["direction"], (int(left + width * .54), int(top + height * .12)), "left"),
        ((1285, 245, 1520, 330), "Head", body["head_direction"], (int(left + width * .58), int(top + height * .15)), "right"),
        ((1285, 440, 1520, 525), "Shoulders", body["shoulder"], (int(left + width * .72), int(top + height * .35)), "right"),
        ((790, 535, 1025, 620), "Body", body["body_rotation"], (int(left + width * .30), int(top + height * .50)), "left"),
        ((790, 770, 1025, 855), "Hands / Prop", hands["position"], (int(left + width * .35), int(top + height * .70)), "left"),
    )
    for label_box, title, value, nominal_anchor, side in labels:
        anchor = _snap_anchor_to_mask(anchor_mask, label_box, nominal_anchor, side)
        _label_box(draw, label_box, title, value, anchor, side=side)

    tip_box = (790, 930, 1520, 1020)
    draw.rounded_rectangle(tip_box, radius=14, fill=(50, 51, 47, 255), outline=GOLD, width=2)
    draw.text((820, 952), "On-set cue", font=_font(19), fill=GOLD)
    tip = f"{gaze['expression']}；{hands['position']}"
    _multiline(draw, (925, 948), tip, _font(17), WHITE, 560, max_lines=2, spacing=4)
    return details


def _poster_section_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    number: str,
    title: str,
    color: tuple[int, int, int, int],
) -> None:
    x, y = xy
    draw.text((x, y), title, font=_font(28), fill=color)
    draw.line((x, y + 48, x + 74, y + 48), fill=color, width=3)


def _guidance_copy(
    pose_json: dict[str, Any],
    *,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate model facts into plain, field-ready photography direction.

    The VLM JSON remains untouched.  This is deliberately a presentation-layer
    transformation so the card can speak like a photographer without changing
    inference, planning, or segmentation behavior.
    """
    analysis = analysis or {}
    why = pose_json["why_beautiful"]
    body = pose_json["body_pose"]
    hands = pose_json["hands"]
    gaze = pose_json["gaze"]
    photographer = pose_json["photographer"]
    evidence = " ".join(
        str(value)
        for value in (
            why.get("atmosphere"),
            why.get("relationship"),
            why.get("composition"),
            why.get("prop_role"),
            hands.get("object"),
            hands.get("position"),
            photographer.get("background"),
            analysis.get("scene"),
            analysis.get("subject"),
            analysis.get("environment"),
            " ".join(str(item) for item in analysis.get("visible_props") or []),
        )
        if value
    )
    evidence_lower = evidence.lower()
    is_city = any(word in evidence_lower for word in ("city", "street", "building", "glass facade", "urban"))
    is_night = any(word in evidence_lower for word in ("night", "evening", "neon", "street light"))
    local_geometry = analysis.get("_local_person_geometry")
    local_geometry = local_geometry if isinstance(local_geometry, dict) else {}
    people_count = int(
        local_geometry.get("people_count")
        or len(analysis.get("people_boxes") or [])
    )
    is_group = people_count >= 2
    is_graduation = any(word in evidence_lower for word in ("graduation", "academic gown", "mortarboard", "graduation cap"))
    visible_props_text = " ".join(
        str(item).lower() for item in analysis.get("visible_props") or []
    )
    has_phone = any(
        word in visible_props_text for word in ("phone", "smartphone", "mobile")
    ) and not is_group

    atmosphere = str(why.get("atmosphere") or "The real setting gives the photo an authentic sense of place.")
    if is_city and is_night:
        atmosphere = "City lights and reflections create a candid street-photography story."
    elif is_city:
        atmosphere = "The real city setting becomes part of the portrait's story."

    relationship = str(why.get("relationship") or "The subject is the visual center while the environment carries the story.")
    if is_city:
        relationship = "The subject remains central while the city adds a lived-in narrative background."

    composition = str(why.get("composition") or "The frame makes the subject clear while preserving environmental depth.")
    if is_city:
        composition = "A slightly angled half-body frame emphasizes expression and preserves urban depth."

    prop_role = str(why.get("prop_role") or "A simple hand action reduces the posed feeling.")
    if has_phone:
        prop_role = "The phone gives the hands a natural task and makes the moment feel candid."

    gaze_direction = str(gaze.get("direction") or "Look naturally toward the photographer")
    if any(word in gaze_direction.lower() for word in ("camera", "photographer", "look back")):
        gaze_direction = "Glance back as if you just noticed"

    head_direction = str(body.get("head_direction") or "Keep the head relaxed")
    if any(word in head_direction.lower() for word in ("camera", "photographer", "turn")):
        head_direction = "Turn gently toward the photographer"

    body_rotation = str(body.get("body_rotation") or "Keep the body relaxed")
    if any(word in body_rotation.lower() for word in ("side", "angle", "turn")):
        body_rotation = "Stay side-on; avoid a square stance"

    hand_title = str(hands.get("object") or "Hands")
    hand_direction = str(hands.get("position") or "Keep both hands relaxed")
    no_prop_labels = {
        "",
        "none",
        "no prop",
        "no props",
        "no visible prop",
        "nothing",
    }
    if hand_title.strip().lower() in no_prop_labels:
        hand_title = "Hands"
    elif hand_title.strip().lower() in {"phone", "smartphone", "mobile"} and not has_phone:
        hand_title = "Hands"
    if has_phone:
        hand_title = "Phone"
        hand_direction = "Hold it naturally; do not present it"

    angle = str(photographer.get("angle") or "Keep the camera level")
    if len(angle) > 46 or "id-photo" in angle.lower():
        angle = "Shoot slightly from the side, not straight on"

    height = str(photographer.get("height") or "Stay close to the subject's eye level")

    background = str(photographer.get("background") or "Preserve environmental depth and avoid clutter")
    if is_city:
        background = "Keep the glass reflections and urban depth"

    expression = str(gaze.get("expression") or "interact naturally").rstrip(".!?")
    summary = f"Stay relaxed and {expression[0].lower() + expression[1:] if expression else 'interact naturally'}."
    if has_phone:
        summary = "Stay relaxed, as if you were just caught after checking the phone."

    shoulder = str(body.get("shoulder") or "Lower and relax both shoulders")
    if "shoulder" in shoulder.lower() and len(shoulder) > 28:
        shoulder = "Drop both shoulders slightly"
    shooting_flow = (
        "Confirm distance and camera height",
        "Set the body, hands, and gaze",
        "Capture one safe frame",
        "Shoot a short burst for a natural moment",
    )
    if is_group:
        group_name = {
            2: "Two people",
            3: "Three people",
            4: "Four people",
        }.get(people_count, f"{people_count} people")
        atmosphere = str(why.get("atmosphere") or "The real setting gives the group portrait a stronger sense of occasion.")
        relationship = f"{group_name} stand close enough to read as one group while the setting explains the gathering."
        composition = f"{group_name} create a stable visual center with enough environmental context."
        prop_role = "Relax each person's arms and keep gestures from blocking one another."
        if is_graduation:
            atmosphere = "The architecture and banner make the graduation moment clear."
            relationship = f"{group_name} form the visual center while the entrance and banner tell the graduation story."
            composition = f"{group_name} create a stable row, with the building and banner completing the context."
            prop_role = "The gowns and graduation caps already communicate the theme; keep the hands relaxed."
        gaze_direction = "Everyone looks toward the photographer"
        head_direction = "Keep every head upright"
        shoulder = "Relax shoulders; step closer"
        body_rotation = "Stand close together in one row"
        hand_title = "Hands"
        hand_direction = "Relax arms; keep chests clear"
        summary = f"Settle the {group_name.lower()}, then relax into one shared smile."
        angle = "Keep the camera level so everyone stays clear"
        height = "Stay close to the center subject's eye level"
        background = "Preserve the setting and exclude unrelated bystanders"
        if is_graduation:
            background = "Keep the graduation banner and building entrance readable"
        shooting_flow = (
            "Check that every person is fully in frame",
            "Bring the group closer and align their gaze",
            "Capture one complete group frame",
            "Shoot a short burst for the shared smile",
        )

    return {
        "title": "AI Photography Guidance Card",
        "subtitle": "Turn a photo you love into an on-set plan you can follow",
        "why": {
            "atmosphere": atmosphere,
            "relationship": relationship,
            "composition": composition,
            "prop_role": prop_role,
        },
        "pose": {
            "gaze": gaze_direction,
            "head": head_direction,
            "shoulder": shoulder,
            "body": body_rotation,
            "hand_title": hand_title,
            "hands": hand_direction,
            "summary": summary,
        },
        "photographer": {
            "distance": str(photographer.get("distance") or "About 1.5 meters"),
            "angle": angle,
            "height": height,
            "background": background,
        },
        "shooting_flow": shooting_flow,
    }


def _draw_poster_header(draw: ImageDraw.ImageDraw, copy: dict[str, Any]) -> None:
    draw.text((55, 42), copy["title"], font=_font(48), fill=POSTER_INK)
    draw.text((55, 106), copy["subtitle"], font=_font(19), fill=POSTER_MUTED)
    draw.line((55, 150, 1545, 150), fill=POSTER_LINE, width=2)
    draw.text((1545, 50), "AMD RADEON · ROCm", font=_font(13), fill=POSTER_BLUE, anchor="ra")
    draw.text((1545, 79), "LOCAL VISION  ·  DETERMINISTIC CONTOUR RENDERING", font=_font(13), fill=POSTER_MUTED, anchor="ra")
    draw.text((1545, 108), "NO GENERATIVE IMAGE MODEL", font=_font(13), fill=POSTER_CLAY, anchor="ra")


def _paste_poster_photo(
    card: Image.Image,
    source: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """Place the real reference photo on a restrained offset paper shadow."""
    left, top, right, bottom = box
    size = (right - left, bottom - top)
    shadow = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (left + 8, top + 12, right + 8, bottom + 12),
        radius=18,
        fill=(46, 48, 44, 78),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=13))
    card.alpha_composite(shadow)
    photo = _rounded_thumbnail(source, size)
    card.alpha_composite(photo, (left, top))
    ImageDraw.Draw(card).rounded_rectangle(
        (left, top, right, bottom),
        radius=18,
        outline=(248, 245, 238, 255),
        width=4,
    )


def _draw_poster_reference(
    card: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    copy: dict[str, Any],
) -> None:
    _poster_section_label(draw, (55, 178), "", "Why This Photo Works", POSTER_BLUE)
    _paste_poster_photo(card, source, (55, 252, 520, 830))
    draw.text((55, 852), "REFERENCE", font=_font(13), fill=POSTER_BLUE)
    _multiline(
        draw,
        (145, 848),
        copy["why"]["atmosphere"],
        _font(17),
        POSTER_INK,
        375,
        max_lines=2,
        spacing=4,
    )

    why = copy["why"]
    entries = (
        ("Atmosphere", why["atmosphere"]),
        ("Relationship", why["relationship"]),
        ("Composition", why["composition"]),
        ("Prop", why["prop_role"]),
    )
    y = 260
    accents = (POSTER_CLAY, POSTER_SAGE, POSTER_BLUE, POSTER_GOLD)
    for (title, value), accent in zip(entries, accents):
        draw.ellipse((560, y + 3, 572, y + 15), fill=accent)
        draw.text((592, y - 5), title, font=_font(18), fill=POSTER_INK)
        _multiline(
            draw,
            (592, y + 31),
            value,
            _font(15),
            POSTER_MUTED,
            235,
            max_lines=3,
            spacing=5,
        )
        draw.line((592, y + 116, 830, y + 116), fill=POSTER_LINE, width=1)
        y += 140


def _poster_label_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    value: str,
    anchor: tuple[int, int],
    *,
    side: str,
) -> None:
    draw.rounded_rectangle(box, radius=12, fill=(45, 49, 45, 246))
    draw.text((box[0] + 14, box[1] + 10), title, font=_font(13), fill=POSTER_GOLD)
    _multiline(
        draw,
        (box[0] + 14, box[1] + 34),
        value,
        _font(15),
        (239, 235, 226, 255),
        box[2] - box[0] - 28,
        max_lines=2,
        spacing=3,
    )
    start = _label_start(box, side)
    _dashed_line(draw, start, anchor, POSTER_GOLD, width=2, dash=8)
    draw.ellipse(
        (anchor[0] - 4, anchor[1] - 4, anchor[0] + 4, anchor[1] + 4),
        fill=POSTER_GOLD,
    )


def _draw_poster_pose(
    card: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    people: list[list[int]],
    pose_json: dict[str, Any],
    copy: dict[str, Any],
    segmenter: Any | None,
) -> dict[str, Any]:
    draw.rounded_rectangle(
        (865, 178, 1545, 884),
        radius=16,
        fill=POSTER_STAGE,
    )
    _poster_section_label(
        draw,
        (900, 205),
        "",
        "How the Subject Stands and Moves",
        (214, 190, 150, 255),
    )
    draw.text(
        (900, 260),
        "Follow the labels. No photography jargon required.",
        font=_font(14),
        fill=(178, 181, 170, 255),
    )
    try:
        mask, details = _composite_masks(source, people, segmenter)
    except Exception as exc:
        mask = Image.new("L", source.size, 0)
        details = {"status": "unavailable", "people_matched": 0, "reason": f"{type(exc).__name__}: {exc}"}
    placed, silhouette_box = _place_silhouette(mask)
    detail_edges = _subject_detail_edges(source, mask, placed, silhouette_box)
    source_box = mask.getbbox()
    clip_bottom_y = silhouette_box[3] if source_box and source_box[3] >= mask.height - 2 else None
    anchor_mask = _composite_refined_outline(card, placed, detail_edges, clip_bottom_y=clip_bottom_y)
    draw = ImageDraw.Draw(card)

    left, top, right, bottom = silhouette_box
    width, height = max(1, right - left), max(1, bottom - top)
    pose = copy["pose"]
    labels = (
        ((885, 308, 1055, 392), "Gaze", pose["gaze"], (int(left + width * .52), int(top + height * .13)), "left"),
        ((1358, 300, 1525, 384), "Head", pose["head"], (int(left + width * .59), int(top + height * .15)), "right"),
        ((1360, 474, 1525, 546), "Shoulders", pose["shoulder"], (int(left + width * .72), int(top + height * .35)), "right"),
        ((885, 532, 1055, 616), "Body", pose["body"], (int(left + width * .28), int(top + height * .50)), "left"),
        ((885, 724, 1055, 816), pose["hand_title"], pose["hands"], (int(left + width * .34), int(top + height * .70)), "left"),
    )
    for box, title, value, nominal, side in labels:
        anchor = _snap_anchor_to_mask(anchor_mask, box, nominal, side)
        _poster_label_box(draw, box, title, value, anchor, side=side)

    draw.rounded_rectangle((1070, 820, 1438, 864), radius=12, fill=(73, 77, 70, 255))
    draw.text(
        (1254, 842),
        pose["summary"],
        font=_font(14),
        fill=(239, 235, 226, 255),
        anchor="mm",
    )
    return details


def _draw_poster_photographer(draw: ImageDraw.ImageDraw, copy: dict[str, Any]) -> None:
    photographer = copy["photographer"]
    draw.rounded_rectangle((55, 904, 1545, 1072), radius=16, fill=POSTER_SURFACE)
    draw.text((82, 926), "How the Photographer Shoots", font=_font(24), fill=POSTER_BLUE)

    entries = (
        ("Distance", photographer["distance"]),
        ("Angle", photographer["angle"]),
        ("Height", photographer["height"]),
        ("Background", photographer["background"]),
    )
    x_positions = (315, 600, 885, 1170)
    for x, (title, value) in zip(x_positions, entries):
        draw.text((x, 918), title, font=_font(13), fill=POSTER_BLUE)
        _multiline(
            draw,
            (x, 946),
            value,
            _font(15),
            POSTER_INK,
            235,
            max_lines=2,
            spacing=4,
        )

    draw.line((82, 994, 1518, 994), fill=POSTER_LINE, width=1)
    draw.text((82, 1015), "Shooting Flow", font=_font(20), fill=POSTER_CLAY)
    x_positions = (300, 565, 855, 1160)
    for index, (x, instruction) in enumerate(zip(x_positions, copy["shooting_flow"]), start=1):
        draw.ellipse((x, 1012, x + 28, 1040), fill=POSTER_SAGE)
        draw.text((x + 14, 1026), str(index), font=_font(13), fill=POSTER_SURFACE, anchor="mm")
        _multiline(
            draw,
            (x + 40, 1013),
            instruction,
            _font(14),
            POSTER_INK,
            220,
            max_lines=2,
            spacing=3,
        )


def render_pose_card(
    image_path: str | Path,
    analysis: dict[str, Any],
    plan: dict[str, Any],
    pose_json: dict[str, Any],
    output_path: str | Path,
    *,
    segmenter: Any | None = None,
) -> dict[str, Any]:
    """Render the same stable UI for every photo, using its real local mask."""
    started = time.perf_counter()
    source_path = Path(image_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    if max(source.size) > 1600:
        source.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

    card = Image.new("RGBA", CARD_SIZE, POSTER_BG)
    draw = ImageDraw.Draw(card)
    display_copy = _guidance_copy(pose_json, analysis=analysis)
    local_geometry = analysis.get("_local_person_geometry")
    local_geometry = local_geometry if isinstance(local_geometry, dict) else {}
    primary_boxes = local_geometry.get("person_boxes")
    if not isinstance(primary_boxes, list) or not primary_boxes:
        primary_boxes = list(analysis.get("people_boxes") or [])
    _draw_poster_header(draw, display_copy)
    _draw_poster_reference(card, draw, source, display_copy)
    details = _draw_poster_pose(
        card,
        draw,
        source,
        primary_boxes,
        pose_json,
        display_copy,
        segmenter,
    )
    _draw_poster_photographer(ImageDraw.Draw(card), display_copy)
    output = card.convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.save(destination, "PNG", optimize=False)
    return {
        "status": "generated",
        "renderer": "deterministic_pil_pose_card",
        "render_mode": "editorial_photography_execution_poster",
        "path": str(destination),
        "width": output.width,
        "height": output.height,
        "seconds": round(time.perf_counter() - started, 3),
        "pose_json": pose_json,
        "display_copy": display_copy,
        "pose_source": pose_json.get("source", "unknown"),
        "sections": ["why_beautiful", "photographer", "subject_pose"],
        "person_outline": details,
        "source_preserved": True,
        "source_reference_included": True,
        "source_pixels_in_output": True,
        "image_generation_model_used": False,
        "vlm_generated_image": False,
        "stable_layout": True,
        # Keep the public metadata contract stable for existing clients/tests.
        "layout_style": "editorial_morandi_poster",
        "palette": "morandi_dark",
        "label_anchor_mode": "real_mask_intersection",
        "subject_scale": 1.1,
        "detail_mode": "multiscale_face_hand_emphasis",
        "outline_style": "high_contrast_dual_vector_contour_with_multiscale_details",
    }
