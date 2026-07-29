"""Local image → text parsing (OCR + optional caption). Private / offline friendly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


@dataclass
class ImageParseResult:
    path: str
    backend: str
    width: int = 0
    height: int = 0
    text: str = ""
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        parts = [
            f"图片: {Path(self.path).name}",
            f"尺寸: {self.width}×{self.height}" if self.width else "尺寸: 未知",
            f"解析引擎: {self.backend}",
        ]
        if self.notes:
            parts.append("说明: " + "；".join(self.notes))
        body = self.text.strip() or "（未识别到文字）"
        parts.append("")
        parts.append("【识别文本】")
        parts.append(body)
        return "\n".join(parts)


def is_image_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _open_image(path: Path) -> tuple[Any, int, int]:
    from PIL import Image

    # Mitigate decompression bombs
    Image.MAX_IMAGE_PIXELS = 25_000_000
    img = Image.open(path)
    img.load()
    img = img.convert("RGB")
    if img.width * img.height > 25_000_000:
        raise ValueError("image too large")
    return img, img.width, img.height


def _ocr_rapidocr(path: Path) -> tuple[str, list[str]] | None:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    try:
        engine = RapidOCR()
        result, _ = engine(str(path))
        if not result:
            return "", []
        lines = [str(item[1]).strip() for item in result if item and len(item) > 1 and str(item[1]).strip()]
        return "\n".join(lines), lines
    except Exception:
        return None


def _ocr_pytesseract(img: Any) -> tuple[str, list[str]] | None:
    try:
        import pytesseract
    except Exception:
        return None
    try:
        # Prefer Chinese+English when available
        try:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        except Exception:
            text = pytesseract.image_to_string(img)
        text = (text or "").strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return text, lines
    except Exception:
        return None


def _caption_blip(path: Path) -> str | None:
    """Optional local caption — only if TRANSFORMERS_VISION=1 to avoid slow boot."""
    import os

    if os.getenv("TRANSFORMERS_VISION", "").lower() not in {"1", "true", "yes"}:
        return None
    try:
        from transformers import pipeline
    except Exception:
        return None
    try:
        pipe = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
        out = pipe(str(path))
        if isinstance(out, list) and out:
            return str(out[0].get("generated_text") or "").strip() or None
        return None
    except Exception:
        return None


def parse_image(path: Path | str) -> ImageParseResult:
    path = Path(path)
    if not path.exists():
        return ImageParseResult(path=str(path), backend="none", text="", notes=["文件不存在"])
    if not is_image_path(path):
        return ImageParseResult(path=str(path), backend="none", text="", notes=["不是支持的图片格式"])

    notes: list[str] = []
    try:
        img, w, h = _open_image(path)
    except Exception as exc:  # noqa: BLE001
        return ImageParseResult(path=str(path), backend="none", notes=[f"无法打开图片: {exc}"])

    text, lines, backend = "", [], "metadata_only"

    rapid = _ocr_rapidocr(path)
    if rapid is not None:
        text, lines = rapid
        backend = "rapidocr"
    else:
        tess = _ocr_pytesseract(img)
        if tess is not None:
            text, lines = tess
            backend = "pytesseract"
        else:
            notes.append("未安装 OCR（建议: pip install rapidocr-onnxruntime Pillow）")

    caption = _caption_blip(path)
    if caption:
        notes.append(f"画面描述: {caption}")
        if not text:
            text = caption
            lines = [caption]
            backend = f"{backend}+blip" if backend != "metadata_only" else "blip"

    # Light cleanup
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ImageParseResult(
        path=str(path),
        backend=backend,
        width=w,
        height=h,
        text=text,
        lines=lines,
        notes=notes,
    )


def parse_image_to_text(path: Path | str) -> str:
    return parse_image(path).as_text()
