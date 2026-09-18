"""Optional PDF adapter that never makes the core report path unavailable."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class PdfExportResult(StrictSchema):
    available: bool
    path: Path | None = None
    reason: str | None = Field(default=None, max_length=2000)


class OptionalPdfExporter:
    """Use WeasyPrint only when it was installed explicitly by the operator."""

    def export(self, html_path: Path, target: Path) -> PdfExportResult:
        try:
            from weasyprint import HTML  # type: ignore
        except ImportError:
            return PdfExportResult(
                available=False,
                reason="Optional PDF support is unavailable; install a compatible PDF extra.",
            )
        destination = target.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            HTML(filename=str(html_path.resolve())).write_pdf(str(destination))
        except Exception as exc:
            return PdfExportResult(
                available=False,
                reason=f"Optional PDF export failed without affecting other formats: {exc}",
            )
        return PdfExportResult(available=True, path=destination)
