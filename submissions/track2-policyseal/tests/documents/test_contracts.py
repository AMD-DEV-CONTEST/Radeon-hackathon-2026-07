from __future__ import annotations

from pathlib import Path

from policyseal.documents.preflight import PreflightDisposition, PreflightService
from policyseal.documents.residual import ResidualScanner


def test_unsupported_embedded_content_never_passes(
    preflight_service: PreflightService,
    embedded_pdf: Path,
) -> None:
    result = preflight_service.inspect(embedded_pdf)

    assert result.disposition is PreflightDisposition.BLOCK
    assert any(finding.code == "pdf_embedded_file" for finding in result.findings)


def test_image_only_pdf_never_silently_enters_text_pipeline(
    preflight_service: PreflightService,
    scanned_pdf: Path,
) -> None:
    result = preflight_service.inspect(scanned_pdf)

    assert result.blocked
    assert any(finding.code == "pdf_unextractable_page" for finding in result.findings)


def test_residual_credential_match_blocks_output(
    residual_scanner: ResidualScanner,
    output_with_token: Path,
) -> None:
    result = residual_scanner.scan(output_with_token)

    assert result.safe is False
    assert result.waivable is False
    assert result.findings[0].category.value == "credential_secret"


def test_residual_evidence_never_contains_the_raw_match(
    residual_scanner: ResidualScanner,
    output_with_token: Path,
) -> None:
    result = residual_scanner.scan(output_with_token)
    serialized = repr(result)

    assert "ps_demo_token_7f4b2e91" not in serialized
    assert len(result.findings[0].value_hmac) == 64


def test_corrupt_supported_file_is_processing_failure(
    preflight_service: PreflightService,
) -> None:
    result = preflight_service.inspect(Path("demo_data/sources/edges/docx-corrupt.docx"))

    assert result.disposition is PreflightDisposition.PROCESSING_FAILED


def test_unknown_extension_fails_closed(
    preflight_service: PreflightService,
    tmp_path: Path,
) -> None:
    path = tmp_path / "fixture.txt"
    path.write_text("synthetic", encoding="utf-8")

    result = preflight_service.inspect(path)

    assert result.disposition is PreflightDisposition.BLOCK
