from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pypdfium2
from pypdfium2 import raw as pdfium_c

from ..exceptions import ValidationError


class PdfPageTextState(StrEnum):
    CREDIBLE = "credible"
    SUSPECT = "suspect"
    ABSENT = "absent"


@dataclass(frozen=True)
class PdfPageEvidence:
    """Bounded page facts used by routing; never a content authority."""

    page: int
    text_state: PdfPageTextState
    reasons: tuple[str, ...]
    extracted_characters: int
    alphanumeric_characters: int
    suspicious_characters: int
    image_coverage: float
    image_objects: int
    text_objects: int
    unembedded_nonstandard_fonts: int
    rotation: int

    def to_payload(self) -> dict[str, object]:
        return {
            "text_state": self.text_state.value,
            "reasons": list(self.reasons),
            "extracted_characters": self.extracted_characters,
            "alphanumeric_characters": self.alphanumeric_characters,
            "suspicious_characters": self.suspicious_characters,
            "image_coverage": round(self.image_coverage, 4),
            "image_objects": self.image_objects,
            "text_objects": self.text_objects,
            "unembedded_nonstandard_fonts": self.unembedded_nonstandard_fonts,
            "rotation": self.rotation,
        }


def classify_pdf_page_text(
    *,
    extracted_characters: int,
    alphanumeric_characters: int,
    suspicious_characters: int,
    image_coverage: float,
    unembedded_nonstandard_fonts: int,
) -> tuple[PdfPageTextState, tuple[str, ...]]:
    """Classify text evidence without pretending to solve layout semantics."""

    if alphanumeric_characters < 8:
        return PdfPageTextState.ABSENT, ("useful_text_absent",)

    reasons: list[str] = []
    if suspicious_characters:
        reasons.append("suspicious_unicode")
    if unembedded_nonstandard_fonts:
        reasons.append("unembedded_nonstandard_font")
    useful_ratio = alphanumeric_characters / max(1, extracted_characters)
    if useful_ratio < 0.35:
        reasons.append("low_useful_character_ratio")
    if image_coverage >= 0.65 and alphanumeric_characters < 64:
        reasons.append("image_dominant_sparse_text_layer")
    if reasons:
        return PdfPageTextState.SUSPECT, tuple(reasons)
    return PdfPageTextState.CREDIBLE, ("native_text_credible",)


def probe_pdf_pages(path: Path) -> tuple[PdfPageEvidence, ...]:
    try:
        document = pypdfium2.PdfDocument(path)
    except Exception as exc:
        raise ValidationError(
            "The PDF page inventory could not be read.",
            error_code="knowledge_pdf_page_probe_failed",
        ) from exc
    try:
        return tuple(_probe_page(document[index], page=index + 1) for index in range(len(document)))
    finally:
        document.close()


def _probe_page(page_object, *, page: int) -> PdfPageEvidence:
    text_page = None
    try:
        text_page = page_object.get_textpage()
        text = text_page.get_text_range().strip()
        extracted_characters = len(text)
        alphanumeric_characters = sum(character.isalnum() for character in text)
        suspicious_characters = sum(_suspicious_character(character) for character in text)
        text_objects, unembedded_fonts = _font_evidence(page_object, text_page)
        image_objects, image_coverage = _image_evidence(page_object)
        state, reasons = classify_pdf_page_text(
            extracted_characters=extracted_characters,
            alphanumeric_characters=alphanumeric_characters,
            suspicious_characters=suspicious_characters,
            image_coverage=image_coverage,
            unembedded_nonstandard_fonts=unembedded_fonts,
        )
        return PdfPageEvidence(
            page=page,
            text_state=state,
            reasons=reasons,
            extracted_characters=extracted_characters,
            alphanumeric_characters=alphanumeric_characters,
            suspicious_characters=suspicious_characters,
            image_coverage=image_coverage,
            image_objects=image_objects,
            text_objects=text_objects,
            unembedded_nonstandard_fonts=unembedded_fonts,
            rotation=int(page_object.get_rotation()),
        )
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(
            "The PDF page evidence could not be inspected.",
            error_code="knowledge_pdf_page_probe_failed",
        ) from exc
    finally:
        if text_page is not None:
            text_page.close()
        page_object.close()


def _font_evidence(page, text_page) -> tuple[int, int]:
    text_objects = 0
    unembedded_nonstandard = 0
    for item in page.get_objects(
        filter=[pdfium_c.FPDF_PAGEOBJ_TEXT],
        textpage=text_page,
    ):
        text_objects += 1
        try:
            font = item.get_font()
            base_name = font.get_base_name(errors="replace")
            if not font.is_embedded and base_name not in font.STANDARD_FONTS:
                unembedded_nonstandard += 1
        except Exception:
            unembedded_nonstandard += 1
    return text_objects, unembedded_nonstandard


def _image_evidence(page) -> tuple[int, float]:
    width, height = page.get_size()
    page_area = max(0.0, float(width) * float(height))
    covered_area = 0.0
    image_objects = 0
    for item in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
        image_objects += 1
        try:
            left, bottom, right, top = item.get_bounds()
        except Exception:
            continue
        object_width = max(0.0, min(float(width), right) - max(0.0, left))
        object_height = max(0.0, min(float(height), top) - max(0.0, bottom))
        covered_area += object_width * object_height
    coverage = min(1.0, covered_area / page_area) if page_area else 0.0
    return image_objects, coverage if math.isfinite(coverage) else 0.0


def _suspicious_character(character: str) -> bool:
    if character == "\ufffd":
        return True
    category = unicodedata.category(character)
    return category in {"Co", "Cs"} or (
        category == "Cc" and character not in {"\t", "\n", "\r"}
    )


__all__ = [
    "PdfPageEvidence",
    "PdfPageTextState",
    "classify_pdf_page_text",
    "probe_pdf_pages",
]
