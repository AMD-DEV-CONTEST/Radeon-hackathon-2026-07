from __future__ import annotations

from pathlib import Path


def convert_document(source_path: Path, *, source_format: str):
    if source_format not in {"docx", "pptx", "pdf"}:
        raise ValueError("Unsupported Docling source format.")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = None
    if source_format == "pdf":
        options = {
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=PdfPipelineOptions(do_ocr=False),
            )
        }
    result = DocumentConverter(format_options=options).convert(source_path)
    status = str(getattr(result.status, "value", result.status)).lower()
    if status not in {"success", "partial_success"}:
        raise RuntimeError("Docling conversion failed.")
    return result.document


__all__ = ["convert_document"]
