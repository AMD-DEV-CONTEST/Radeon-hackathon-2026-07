"""
Textovid — Comic Layout Engine v2
Assembles generated panel images into polished 4K comic pages with
speech bubbles, narration boxes, SFX text, title page, and comic borders.
"""

import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from typing import List, Tuple, Optional
import config


# ── Font handling ───────────────────────────────────────────────────────

_font_cache = {}

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _font_cache:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold
            else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    _font_cache[key] = ImageFont.truetype(path, size)
                    return _font_cache[key]
                except Exception:
                    continue
        _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# ════════════════════════════════════════════════════════════════════════
#   TITLE PAGE GENERATOR
# ════════════════════════════════════════════════════════════════════════

def create_title_page(
    title: str,
    synopsis: str = "",
    characters: list = None,
    cover_image: Image.Image = None,
) -> Image.Image:
    """Generate a professional comic book title/cover page."""
    W = config.COMIC_PAGE_W
    H = config.COMIC_PAGE_H
    margin = config.PAGE_MARGIN

    page = Image.new("RGB", (W, H), (10, 10, 25))
    draw = ImageDraw.Draw(page)

    # ── Background: cover image if available ────────────────────────────
    if cover_image:
        # Resize to fill, crop to cover
        img_ratio = cover_image.width / cover_image.height
        page_ratio = W / H
        if img_ratio > page_ratio:
            new_w = int(cover_image.height * page_ratio)
            cover_image = cover_image.crop((
                (cover_image.width - new_w) // 2, 0,
                (cover_image.width + new_w) // 2, cover_image.height,
            ))
        else:
            new_h = int(cover_image.width / page_ratio)
            cover_image = cover_image.crop((
                0, (cover_image.height - new_h) // 2,
                cover_image.width, (cover_image.height + new_h) // 2,
            ))
        cover_image = cover_image.resize((W, H), Image.LANCZOS)

        # Darken overlay for text readability
        enhancer = ImageEnhance.Brightness(cover_image)
        cover_image = enhancer.enhance(0.35)
        page = cover_image

        # Add gradient overlay from bottom
        overlay = Image.new("RGBA", (W, H), (10, 10, 25, 200))
        for y in range(H):
            alpha = int(200 * max(0, (y - H * 0.3) / (H * 0.7)))
            for x in range(W):
                overlay.putpixel((x, y), (10, 10, 25, min(alpha, 220)))
        # Simpler gradient: dark bottom
        gradient = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        grad_draw = ImageDraw.Draw(gradient)
        for y in range(H):
            frac = max(0, (y - H * 0.3) / (H * 0.7))
            alpha = int(220 * frac)
            grad_draw.line([(0, y), (W, y)], fill=(10, 10, 25, alpha))
        page = Image.alpha_composite(page.convert("RGBA"), gradient).convert("RGB")
        draw = ImageDraw.Draw(page)

    # ── Title ───────────────────────────────────────────────────────────
    title_upper = title.upper()
    title_font = _get_font(72, bold=True)

    # Word wrap title
    words = title_upper.split()
    title_lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=title_font)
        if bbox[2] - bbox[0] > W - margin * 4:
            title_lines.append(current)
            current = word
        else:
            current = test
    if current:
        title_lines.append(current)

    # Draw title with glow effect
    title_y = H // 2 - len(title_lines) * 40
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2

        # Glow (multiple offsets with decreasing opacity simulation)
        glow_color = (0, 180, 200)
        for dx in [-3, -2, -1, 0, 1, 2, 3]:
            for dy in [-3, -2, -1, 0, 1, 2, 3]:
                draw.text((x + dx, title_y + dy), line, fill=glow_color, font=title_font)
        # Main text
        draw.text((x, title_y), line, fill=(255, 255, 255), font=title_font)
        title_y += 84

    # ── Subtitle / tagline ──────────────────────────────────────────────
    if synopsis:
        sub_font = _get_font(24, bold=False)
        # Truncate synopsis
        sub_text = synopsis[:120] + "..." if len(synopsis) > 120 else synopsis
        bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
        stw = bbox[2] - bbox[0]
        draw.text(((W - stw) // 2, title_y + 20), sub_text, fill=(180, 180, 210), font=sub_font)

    # ── "TEXTOVID" branding ─────────────────────────────────────────────
    brand_font = _get_font(20, bold=True)
    brand_text = "G E N E R A T E D   B Y   T E X T O V I D"
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    btw = bbox[2] - bbox[0]
    brand_y = H - margin - 40
    draw.text(((W - btw) // 2, brand_y), brand_text, fill=(0, 200, 220), font=brand_font)

    # ── Bottom line ─────────────────────────────────────────────────────
    line_y = brand_y - 15
    draw.line([(margin + 60, line_y), (W - margin - 60, line_y)],
              fill=(0, 200, 220), width=2)

    return page


# ════════════════════════════════════════════════════════════════════════
#   SPEECH BUBBLES
# ════════════════════════════════════════════════════════════════════════

def draw_speech_bubble(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int,
    text: str,
    speaker: str = "",
    max_width: int = None,
    font_size: int = None,
    tail_direction: str = "top-left",
    fill_color: str = "#FFFFFF",
    border_color: str = "#111111",
    border_width: int = 3,
):
    """Draw a comic speech bubble with text and optional tail."""
    fs = font_size or config.BUBBLE_FONT_SIZE
    mw = max_width or config.BUBBLE_MAX_WIDTH
    font = _get_font(fs, bold=True)

    # Word wrap
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > mw:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)
    if not lines:
        return

    # Add speaker label
    if speaker:
        lines.insert(0, speaker)
        lines.insert(1, "")

    # Calculate bubble size
    padding = config.BUBBLE_PADDING
    line_height = fs + 6
    text_h = len(lines) * line_height
    text_w = max(draw.textbbox((0, 0), ln, font=font)[2] for ln in lines if ln) if lines else 100

    bw = text_w + padding * 2 + 14
    bh = text_h + padding * 2 + 10

    # Position
    x1 = max(cx - bw // 2, 8)
    y1 = max(cy - bh // 2, 8)
    x2 = x1 + bw
    y2 = y1 + bh

    # Draw rounded rectangle
    r = 18
    draw.rounded_rectangle(
        [x1, y1, x2, y2], radius=r,
        fill=fill_color, outline=border_color, width=border_width,
    )

    # Tail
    tail_size = 20
    if "left" in tail_direction:
        tx = x1 + 25
    else:
        tx = x2 - 25
    if "top" in tail_direction:
        ty = y2
        points = [(tx, ty), (tx - tail_size, ty + tail_size * 1.8), (tx + tail_size, ty)]
    else:
        ty = y1
        points = [(tx, ty), (tx - tail_size, ty - tail_size * 1.8), (tx + tail_size, ty)]
    draw.polygon(points, fill=fill_color, outline=border_color)

    # Text
    text_x = x1 + padding + 7
    text_y = y1 + padding + 2
    for i, line in enumerate(lines):
        if line == "":
            text_y += line_height // 2
            continue
        if i == 0 and speaker:
            draw.text((text_x, text_y), line, fill="#333333", font=_get_font(fs - 8, bold=True))
        else:
            draw.text((text_x, text_y), line, fill="#111111", font=font)
        text_y += line_height


# ── Narration Box ───────────────────────────────────────────────────────

def draw_narration_box(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    text: str,
    page_width: int,
    font_size: int = None,
):
    """Draw a rectangular narration/caption box at the top of a panel."""
    if not text.strip():
        return
    fs = font_size or config.NARRATION_FONT_SIZE
    font = _get_font(fs, bold=False)
    padding = 12

    words = text.split()
    lines = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > page_width - padding * 2 - 24:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)

    box_h = len(lines) * (fs + 4) + padding * 2
    box_w = page_width - 24

    # Semi-transparent yellow background
    draw.rounded_rectangle(
        [x, y, x + box_w, y + box_h],
        radius=6, fill="#FFFDE7", outline="#444444", width=2,
    )
    ty = y + padding
    for line in lines:
        draw.text((x + padding + 2, ty), line, fill="#222222", font=font)
        ty += fs + 4


# ── SFX Text ────────────────────────────────────────────────────────────

def draw_sfx(
    draw: ImageDraw.ImageDraw,
    text: str,
    panel_x: int, panel_y: int,
    panel_w: int, panel_h: int,
):
    """Draw large, stylized sound-effect text on a panel."""
    if not text.strip():
        return
    font = _get_font(config.SFX_FONT_SIZE, bold=True)
    tx = panel_x + panel_w - len(text) * 22 - 24
    ty = panel_y + 18

    # Outline
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx == 0 and dy == 0:
                continue
            draw.text((tx + dx, ty + dy), text, fill="#000000", font=font)
    # Main text
    draw.text((tx, ty), text, fill="#FFD600", font=font)
    # Highlight
    draw.text((tx - 1, ty - 1), text, fill="#FFF176", font=font)


# ════════════════════════════════════════════════════════════════════════
#   PAGE COMPOSITION
# ════════════════════════════════════════════════════════════════════════

def compose_comic_page(
    page_panels: List[Tuple],
    page_number: int,
    total_pages: int,
    comic_title: str = "Textovid Comic",
    layout: Optional[list] = None,
) -> Image.Image:
    """
    Assemble multiple panel images into a single comic page.
    page_panels: [(panel_dict, PIL.Image), ...]
    layout: list of rows, each row is list of float weights summing to 1.0
    """
    W = config.COMIC_PAGE_W
    H = config.COMIC_PAGE_H
    margin = config.PAGE_MARGIN
    gap = config.PANEL_GAP

    page = Image.new("RGB", (W, H), config.PAGE_BG_COLOR)
    draw = ImageDraw.Draw(page)

    # ── Page border ─────────────────────────────────────────────────────
    draw.rectangle(
        [margin - 5, margin - 5, W - margin + 5, H - margin + 5],
        outline="#1a1a2e", width=7,
    )

    # ── Header bar ──────────────────────────────────────────────────────
    header_font = _get_font(28, bold=True)
    page_font   = _get_font(16, bold=False)
    title_text = comic_title.upper()
    bbox = draw.textbbox((0, 0), title_text, font=header_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, 10), title_text, fill="#1a1a2e", font=header_font)
    page_label = f"— Page {page_number} / {total_pages} —"
    pl_bbox = draw.textbbox((0, 0), page_label, font=page_font)
    plw = pl_bbox[2] - pl_bbox[0]
    draw.text(((W - plw) // 2, 44), page_label, fill="#666666", font=page_font)

    top_offset = 70

    # ── Calculate layout ────────────────────────────────────────────────
    n = len(page_panels)
    if layout is None:
        layout = [[0.5, 0.5], [0.5, 0.5]] if n == 4 else \
                 [[1.0 / n] * n] if n <= 3 else \
                 [[0.34, 0.33, 0.33]] * ((n + 2) // 3)

    num_rows = len(layout)
    available_h = H - top_offset - margin
    available_w = W - margin * 2
    row_h = (available_h - gap * (num_rows - 1)) / num_rows

    # ── Place panels ────────────────────────────────────────────────────
    panel_idx = 0
    for row_i, row_weights in enumerate(layout):
        y = top_offset + row_i * (row_h + gap)
        row_w_total = available_w - gap * (len(row_weights) - 1)

        for col_i, weight in enumerate(row_weights):
            if panel_idx >= n:
                break

            pw = int(row_w_total * weight)
            ph = int(row_h)
            x = margin + col_i * (pw + gap)

            panel_dict, panel_img = page_panels[panel_idx]

            # Resize panel image to fit
            panel_img_resized = panel_img.resize((pw, ph), Image.LANCZOS)

            # Panel border
            draw.rectangle(
                [x - 1, y - 1, x + pw + 1, y + ph + 1],
                outline=config.PANEL_BORDER_COLOR, width=config.PANEL_BORDER_W,
            )

            page.paste(panel_img_resized, (x, y))

            # ── Narration box ───────────────────────────────────────────
            narration = panel_dict.get("narration", "")
            if narration:
                draw_narration_box(draw, x + 5, y + 5, narration, pw)

            # ── SFX ─────────────────────────────────────────────────────
            sfx = panel_dict.get("sfx", "")
            if sfx:
                draw_sfx(draw, sfx, x, y, pw, ph)

            # ── Speech bubbles ──────────────────────────────────────────
            dialogue_list = panel_dict.get("dialogue", [])
            if dialogue_list:
                bubble_area_top = y + ph * 0.5
                bubble_area_bottom = y + ph - 24
                bubble_area_h = bubble_area_bottom - bubble_area_top
                num_bubbles = len(dialogue_list)
                for bi, d in enumerate(dialogue_list):
                    speaker = d.get("speaker", "")
                    text = d.get("text", "")
                    if not text:
                        continue
                    by = bubble_area_top + (bubble_area_h / (num_bubbles + 1)) * (bi + 1)
                    bx = x + pw * 0.5
                    tail_dir = "top-left" if bi % 2 == 0 else "top-right"
                    draw_speech_bubble(
                        draw, int(bx), int(by), text,
                        speaker=speaker, tail_direction=tail_dir,
                    )

            panel_idx += 1

    return page


# ════════════════════════════════════════════════════════════════════════
#   FULL COMIC ASSEMBLY
# ════════════════════════════════════════════════════════════════════════

def assemble_full_comic(
    script: dict,
    panel_images: List[Tuple],
    progress_callback=None,
) -> Tuple[List[Image.Image], dict]:
    """
    Compose all pages from a script and generated images.
    Includes a title page as page 1.
    Returns: (list_of_page_images, metadata_dict)
    """
    pages = script.get("pages", [])
    title = script.get("title", "Textovid Comic")
    synopsis = script.get("synopsis", "")
    characters = script.get("characters", [])
    total_pages = len(pages)
    output_pages = []

    # ── Title page (uses first generated image as cover) ────────────────
    if config.TITLE_PAGE_ENABLED and panel_images:
        if progress_callback:
            progress_callback(0.80, "Generating title page...")
        cover_img = panel_images[0][1]  # first panel image
        title_page = create_title_page(
            title=title,
            synopsis=synopsis,
            characters=characters,
            cover_image=cover_img,
        )
        output_pages.append(title_page)

    # ── Group images by page ────────────────────────────────────────────
    page_image_map = {}
    panel_counter = 0
    for page_idx, page in enumerate(pages):
        page_panels = []
        for panel in page.get("panels", []):
            if panel_counter < len(panel_images):
                _, img, _, _ = panel_images[panel_counter]
                page_panels.append((panel, img))
                panel_counter += 1
        if page_panels:
            page_image_map[page_idx] = page_panels

    # ── Generate layouts per page ───────────────────────────────────────
    from uniqueness import randomize_panel_layout
    for page_idx in range(total_pages):
        if progress_callback:
            frac = 0.82 + 0.13 * (page_idx / max(total_pages, 1))
            progress_callback(frac, f"Composing page {page_idx + 1}/{total_pages}...")

        pp = page_image_map.get(page_idx, [])
        if not pp:
            continue

        n_panels = len(pp)
        layout = randomize_panel_layout(n_panels)

        page_img = compose_comic_page(
            page_panels=pp,
            page_number=page_idx + 1,
            total_pages=total_pages,
            comic_title=title,
            layout=layout,
        )
        output_pages.append(page_img)

    # ── Metadata ────────────────────────────────────────────────────────
    total_gen_time = sum(p[2] for p in panel_images) if panel_images else 0
    total_panels = sum(len(p.get("panels", [])) for p in pages)
    has_title = 1 if config.TITLE_PAGE_ENABLED and panel_images else 0

    metadata = {
        "title": title,
        "synopsis": synopsis,
        "total_pages": len(output_pages),
        "content_pages": total_pages,
        "total_panels": total_panels,
        "has_title_page": bool(has_title),
        "total_gen_time": round(total_gen_time, 2),
        "avg_time_per_panel": round(total_gen_time / max(total_panels, 1), 2),
        "page_size": f"{config.COMIC_PAGE_W}x{config.COMIC_PAGE_H}",
    }

    return output_pages, metadata