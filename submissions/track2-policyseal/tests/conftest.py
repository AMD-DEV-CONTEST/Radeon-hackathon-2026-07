from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from policyseal.documents.docx import DocxAdapter
from policyseal.documents.pdf import PdfAdapter
from policyseal.documents.preflight import PreflightService
from policyseal.documents.residual import ResidualScanner
from policyseal.documents.xlsx import XlsxAdapter
from policyseal.policy.loader import load_policy_pack
from policyseal.policy.schema import PolicyPack
from policyseal.security.key_store import MasterKeyStore
from policyseal.security.pseudonyms import Pseudonymizer


@pytest.fixture
def hero_xlsx() -> Path:
    return Path("demo_data/sources/supplier-matrix-hero.xlsx")


@pytest.fixture
def hero_docx() -> Path:
    return Path("demo_data/sources/security-incident-hero.docx")


@pytest.fixture
def hero_pdf() -> Path:
    return Path("demo_data/sources/reference-contract-hero.pdf")


@pytest.fixture
def embedded_pdf() -> Path:
    return Path("demo_data/sources/edges/pdf-embedded-attachment.pdf")


@pytest.fixture
def scanned_pdf() -> Path:
    return Path("demo_data/sources/edges/pdf-image-only.pdf")


@pytest.fixture
def preflight_service() -> PreflightService:
    return PreflightService()


@pytest.fixture
def residual_scanner(tmp_path: Path) -> ResidualScanner:
    return ResidualScanner(MasterKeyStore(tmp_path / "secrets" / "master.key"))


@pytest.fixture
def policy_pack() -> PolicyPack:
    return load_policy_pack(Path("policies/v1"))


@pytest.fixture
def xlsx_adapter(
    preflight_service: PreflightService,
    residual_scanner: ResidualScanner,
) -> XlsxAdapter:
    return XlsxAdapter(preflight_service, residual_scanner)


@pytest.fixture
def pseudonymizer(tmp_path: Path) -> Pseudonymizer:
    return Pseudonymizer(MasterKeyStore(tmp_path / "secrets" / "master.key"))


@pytest.fixture
def docx_adapter(
    preflight_service: PreflightService,
    residual_scanner: ResidualScanner,
    pseudonymizer: Pseudonymizer,
) -> DocxAdapter:
    return DocxAdapter(preflight_service, residual_scanner, pseudonymizer)


@pytest.fixture
def pdf_adapter(
    preflight_service: PreflightService,
    residual_scanner: ResidualScanner,
) -> PdfAdapter:
    return PdfAdapter(preflight_service, residual_scanner)


@pytest.fixture
def output_with_token(tmp_path: Path) -> Path:
    path = tmp_path / "unsafe-output.docx"
    document = Document()
    document.add_paragraph("Residual token ps_demo_token_7f4b2e91 must block this output.")
    document.save(path)
    return path
