from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from autoflow.pdf_tools import PDFTextConverter


def test_pdf_to_txt_conversion_and_verification(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "output"
    source.mkdir()
    pdf = source / "report.pdf"
    canvas = Canvas(str(pdf))
    canvas.drawString(72, 760, "AutoFlow PDF conversion works")
    canvas.save()

    result = PDFTextConverter().convert(source, destination)
    assert result["converted"] == 1
    assert result["failed"] == 0
    assert "AutoFlow PDF conversion works" in (destination / "report.txt").read_text(encoding="utf-8")


def test_existing_txt_is_not_overwritten(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    canvas = Canvas(str(pdf))
    canvas.drawString(72, 760, "existing output check")
    canvas.save()
    output = tmp_path / "output"
    output.mkdir()
    txt = output / "sample.txt"
    txt.write_text("keep", encoding="utf-8")

    result = PDFTextConverter().convert(pdf, output)
    assert result["skipped"] == 1
    assert txt.read_text(encoding="utf-8") == "keep"
