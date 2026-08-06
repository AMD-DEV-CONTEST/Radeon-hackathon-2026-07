"""图片原子操作与按平台组合。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 支持 iPhone HEIC/HEIF 照片（装了 pillow-heif 才生效，没装就跳过）
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

from content_studio.config import ImageConfig

XHS_COVER_SIZE = (1242, 1656)        # 3:4
WECHAT_COVER_SIZE = (900, 383)       # 2.35:1
WECHAT_ARTICLE_MAX_W = 900


def load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _fit_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _contain(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    target_ratio = target_w / target_h
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = target_w
        new_h = int(target_w / src_ratio)
    else:
        new_h = target_h
        new_w = int(target_h * src_ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def to_cover_3_4(img: Image.Image, strategy: str = "crop") -> Image.Image:
    target_w, target_h = XHS_COVER_SIZE
    if strategy == "pad":
        scaled = _contain(img, target_w, target_h)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(scaled, ((target_w - scaled.width) // 2, (target_h - scaled.height) // 2))
        return canvas
    target_ratio = target_w / target_h
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)


def add_watermark(img: Image.Image, text: str, position: str = "br", opacity: int = 128) -> Image.Image:
    if not text:
        return img
    layer = img.convert("RGBA")
    overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _fit_font(max(24, layer.height // 30))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = layer.height // 40
    pos = {
        "br": (layer.width - tw - margin, layer.height - th - margin),
        "bl": (margin, layer.height - th - margin),
        "tr": (layer.width - tw - margin, margin),
        "tl": (margin, margin),
    }[position]
    draw.text(pos, text, fill=(255, 255, 255, opacity), font=font,
              stroke_width=2, stroke_fill=(0, 0, 0, int(opacity * 0.6)))
    return Image.alpha_composite(layer, overlay).convert("RGB")


def add_title_overlay(img: Image.Image, title: str) -> Image.Image:
    if not title:
        return img
    layer = img.convert("RGBA")
    overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _fit_font(layer.height // 9)
    margin = layer.width // 15
    bbox = draw.textbbox((0, 0), title, font=font)
    th = bbox[3] - bbox[1]
    y = layer.height // 2 - th // 2
    draw.rectangle([0, y - margin, layer.width, y + th + margin], fill=(0, 0, 0, 140))
    draw.text((margin, y), title, fill=(255, 255, 255, 255), font=font)
    return Image.alpha_composite(layer, overlay).convert("RGB")


def stitch_grid(imgs: list[Image.Image], cols: int = 2) -> Image.Image:
    if not imgs:
        raise ValueError("无图可拼")
    rows = (len(imgs) + cols - 1) // cols
    cell_w = min(i.width for i in imgs)
    cell_h = min(i.height for i in imgs)
    canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), (255, 255, 255))
    for idx, im in enumerate(imgs):
        r, c = divmod(idx, cols)
        canvas.paste(im.resize((cell_w, cell_h), Image.LANCZOS), (c * cell_w, r * cell_h))
    return canvas


def to_wechat_cover(img: Image.Image) -> Image.Image:
    tw, th = WECHAT_COVER_SIZE
    target_ratio = tw / th
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((tw, th), Image.LANCZOS)


def resize_for_article(img: Image.Image, max_w: int = WECHAT_ARTICLE_MAX_W) -> Image.Image:
    if img.width > max_w:
        new_h = int(img.height * max_w / img.width)
        img = img.resize((max_w, new_h), Image.LANCZOS)
    return img


def save_jpeg(img: Image.Image, path: str | Path, quality: int = 85) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=quality)
    return path


def build_xhs_images(images: list[Image.Image], cfg: ImageConfig, cover_text: str = "") -> list[Image.Image]:
    if not images:
        return []
    base = [to_cover_3_4(im, cfg.crop_strategy) for im in images]
    if cfg.collage and len(base) >= 2:
        cover = to_cover_3_4(stitch_grid(base, cols=2), "pad")
        if cover_text:
            cover = add_title_overlay(cover, cover_text)
        cover = add_watermark(cover, cfg.watermark_text)
        return [cover]
    cover = base[0]
    if cover_text:
        cover = add_title_overlay(cover, cover_text)
    cover = add_watermark(cover, cfg.watermark_text)
    rest = [add_watermark(im, cfg.watermark_text) for im in base[1:]]
    return [cover] + rest


def build_wechat_images(images: list[Image.Image], cfg: ImageConfig) -> list[Image.Image]:
    if not images:
        return []
    cover = to_wechat_cover(images[0])
    body = [resize_for_article(im) for im in images[1:]]
    return [cover] + body
