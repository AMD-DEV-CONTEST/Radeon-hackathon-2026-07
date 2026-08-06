from __future__ import annotations

import codecs
import hashlib
import json
import math
import shutil
import stat
import subprocess
import sys
import unicodedata
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Protocol, TypeVar
from zipfile import BadZipFile, ZipFile

import msoffcrypto
import pikepdf
from charset_normalizer import from_bytes
from PIL import Image, ImageOps, UnidentifiedImageError, __version__ as pillow_version

from ..exceptions import ValidationError
from .knowledge_formats import (
    KNOWLEDGE_FORMAT_REGISTRY,
    KnowledgeFormatCapability,
    KnowledgeFormatRegistry,
)
from .knowledge_pdf import PdfPageTextState, probe_pdf_pages
from .ocr.contracts import OcrService, normalize_runtime_descriptor

MAX_OCR_RESULT_BYTES = 64 * 1024 * 1024

MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_TEXT_LINE_CHARS = 1_000_000
MAX_IMAGE_PIXELS = 100_000_000
MAX_OOXML_PACKAGE_ENTRIES = 20_000
MAX_OOXML_ENTRY_BYTES = 128 * 1024 * 1024
MAX_OOXML_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_OOXML_COMPRESSION_RATIO = 200
MAX_OOXML_MEMBER_NAME_BYTES = 512
MAX_OOXML_MEMBER_DEPTH = 32
MAX_HASHABLE_IR_BYTES = 256 * 1024 * 1024
_CFB_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_IO_CHUNK_BYTES = 1024 * 1024
_PROCESS_TERMINATE_GRACE_SECONDS = 2.0
_LIBREOFFICE_TIMEOUT_SECONDS = 120
_OOXML_RATIO_CHECK_MIN_BYTES = 1024 * 1024
_TEXT_ENCODING_ALLOWLIST = frozenset(
    {"utf-8", "utf-16-le", "utf-16-be", "gb18030"}
)
_TEXT_FALLBACK_ENCODINGS = _TEXT_ENCODING_ALLOWLIST - {
    "utf-8",
    "utf-16-le",
    "utf-16-be",
}
_TEXT_MAX_CANDIDATE_CHAOS = 0.1
_TEXT_MIN_CANDIDATE_SEPARATION = 0.05
_ProviderT = TypeVar("_ProviderT")


@dataclass(frozen=True)
class _OoxmlPackageProfile:
    source_format: str
    display_name: str
    main_part: str


@dataclass(frozen=True)
class _OfficeConversionProfile:
    provider_id: str
    source_format: str
    source_display_name: str
    target_format: str
    libreoffice_filter: str
    target_package: _OoxmlPackageProfile


_DOCX_PACKAGE = _OoxmlPackageProfile("docx", "DOCX", "word/document.xml")
_PPTX_PACKAGE = _OoxmlPackageProfile("pptx", "PPTX", "ppt/presentation.xml")
_DOC_TO_DOCX = _OfficeConversionProfile(
    "doc-to-docx",
    "doc",
    "DOC",
    "docx",
    "docx:Office Open XML Text",
    _DOCX_PACKAGE,
)
_PPT_TO_PPTX = _OfficeConversionProfile(
    "ppt-to-pptx",
    "ppt",
    "PPT",
    "pptx",
    "pptx:Impress MS PowerPoint 2007 XML",
    _PPTX_PACKAGE,
)


@dataclass(frozen=True)
class FileProbeResult:
    source_path: Path
    source_format: str
    media_type: str | None
    size: int
    encrypted: bool
    facts: dict[str, Any]


@dataclass(frozen=True)
class NormalizedSource:
    path: Path
    source_format: str
    parser_format: str
    descriptor: dict[str, Any]


@dataclass(frozen=True)
class ParsePlanUnit:
    scope: str
    route_id: str
    reason: str
    page: int | None = None
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsePlan:
    source_format: str
    parser_format: str
    units: tuple[ParsePlanUnit, ...]
    merge_strategy: str
    policy_version: int = 1
    ocr_ready: bool = False


@dataclass(frozen=True)
class ParseResult:
    document: Any
    pipeline: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    projections: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _OcrBatchResult:
    succeeded_pages: tuple[int, ...]
    unavailable_pages: tuple[int, ...]
    item_count: int
    payload_hashes: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class FormatProbeFacts:
    detected_format: str
    encrypted: bool = False
    facts: dict[str, Any] = field(default_factory=dict)


class FormatProbeProvider(Protocol):
    provider_id: str

    def probe(
        self,
        source: Path,
        *,
        header: bytes,
        size: int,
        capability: KnowledgeFormatCapability,
    ) -> FormatProbeFacts: ...


class _TextProbeProvider:
    provider_id = "text"

    def probe(self, source, *, header, size, capability) -> FormatProbeFacts:
        facts: dict[str, Any] = {}
        _probe_text(header, facts, sample_is_complete=size <= len(header))
        return FormatProbeFacts("txt", facts=facts)


class _CfbOfficeProbeProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        source_format: str,
        normalized_format: str,
        office_kind: str,
    ) -> None:
        self.provider_id = provider_id
        self._source_format = source_format
        self._normalized_format = normalized_format
        self._office_kind = office_kind

    def probe(self, source, *, header, size, capability) -> FormatProbeFacts:
        if not header.startswith(_CFB_SIGNATURE):
            raise _format_mismatch()
        office_kind, encrypted = _inspect_office_file(source)
        if office_kind != self._office_kind:
            raise _format_mismatch()
        return FormatProbeFacts(
            self._source_format,
            encrypted=encrypted,
            facts={
                "container": "cfb",
                "office_kind": office_kind,
                "normalization_candidate": self._normalized_format,
            },
        )


class _OoxmlOfficeProbeProvider:
    def __init__(self, *, provider_id: str, profile: _OoxmlPackageProfile) -> None:
        self.provider_id = provider_id
        self._profile = profile

    def probe(self, source, *, header, size, capability) -> FormatProbeFacts:
        if header.startswith(_CFB_SIGNATURE):
            office_kind, encrypted = _inspect_office_file(source)
            if office_kind != "ooxml" or not encrypted:
                raise _ooxml_error(self._profile, "package_invalid", "container is invalid")
            return FormatProbeFacts(
                self._profile.source_format,
                encrypted=True,
                facts={"container": "cfb-encrypted-ooxml"},
            )
        if not header.startswith(b"PK\x03\x04"):
            raise _format_mismatch()
        facts = _verify_ooxml_package(source, self._profile)
        facts["container"] = "ooxml"
        return FormatProbeFacts(self._profile.source_format, facts=facts)


class _PdfProbeProvider:
    provider_id = "pdf"

    def probe(self, source, *, header, size, capability) -> FormatProbeFacts:
        if not header.startswith(b"%PDF-"):
            raise _format_mismatch()
        encrypted, facts = _probe_pdf(source)
        return FormatProbeFacts("pdf", encrypted=encrypted, facts=facts)


class _ImageProbeProvider:
    provider_id = "image"

    def probe(self, source, *, header, size, capability) -> FormatProbeFacts:
        expected = capability.source_format
        signature_matches = (
            expected == "png" and header.startswith(b"\x89PNG\r\n\x1a\n")
        ) or (
            expected == "jpeg" and header.startswith(b"\xff\xd8\xff")
        )
        if not signature_matches:
            raise _format_mismatch()
        return FormatProbeFacts(
            expected,
            facts=_probe_image(source, expected_format=expected),
        )


class FileProbe:
    """Return authoritative byte/container facts without mutating the source."""

    def __init__(
        self,
        registry: KnowledgeFormatRegistry = KNOWLEDGE_FORMAT_REGISTRY,
        providers: tuple[FormatProbeProvider, ...] | None = None,
    ) -> None:
        self._registry = registry
        providers = providers or (
            _TextProbeProvider(),
            _CfbOfficeProbeProvider(
                provider_id="cfb-word",
                source_format="doc",
                normalized_format="docx",
                office_kind="doc",
            ),
            _OoxmlOfficeProbeProvider(
                provider_id="ooxml-word",
                profile=_DOCX_PACKAGE,
            ),
            _CfbOfficeProbeProvider(
                provider_id="cfb-presentation",
                source_format="ppt",
                normalized_format="pptx",
                office_kind="ppt",
            ),
            _OoxmlOfficeProbeProvider(
                provider_id="ooxml-presentation",
                profile=_PPTX_PACKAGE,
            ),
            _PdfProbeProvider(),
            _ImageProbeProvider(),
        )
        self._providers = _provider_map(
            providers,
            required_ids=registry.probe_provider_ids,
            kind="probe",
        )

    def probe(self, path: Path) -> FileProbeResult:
        source = path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError("Knowledge source must be an existing local file.")
        size = source.stat().st_size
        if size <= 0 or size > MAX_SOURCE_BYTES:
            raise ValidationError("Knowledge source size is outside the supported range.")
        suffix = source.suffix.casefold()
        capability = self._registry.capability_for_suffix(suffix)
        if capability is None:
            raise ValidationError(
                self._registry.supported_formats_message(),
                error_code="knowledge_format_unsupported",
            )
        header = _read_prefix(source, 64 * 1024)
        provider = self._providers[capability.probe_provider_id]
        result = provider.probe(
            source,
            header=header,
            size=size,
            capability=capability,
        )
        if result.detected_format != capability.source_format:
            raise _format_mismatch()

        facts: dict[str, Any] = {
            "signature": result.detected_format,
            "byte_size": size,
            "format_registry_version": self._registry.version,
            "probe_provider_id": provider.provider_id,
        }
        facts.update(result.facts)
        facts["encrypted"] = result.encrypted
        return FileProbeResult(
            source_path=source,
            source_format=result.detected_format,
            media_type=capability.media_type,
            size=size,
            encrypted=result.encrypted,
            facts=facts,
        )

    @property
    def supported_formats_message(self) -> str:
        return self._registry.supported_formats_message()


@dataclass(frozen=True)
class NormalizationRequest:
    probe: FileProbeResult
    capability: KnowledgeFormatCapability
    work_dir: Path
    password: str | None
    input_sha256: str


class FormatNormalizerProvider(Protocol):
    provider_id: str

    def normalize(self, request: NormalizationRequest) -> NormalizedSource: ...


class _TextNormalizerProvider:
    provider_id = "text"

    def normalize(self, request: NormalizationRequest) -> NormalizedSource:
        payload = _read_bytes(request.probe.source_path)
        decoded = _decode_text_payload(payload)
        text = _normalize_text(decoded.text)
        target = request.work_dir / "normalized.txt"
        _write_text(target, text)
        return NormalizedSource(
            target,
            request.capability.source_format,
            request.capability.parser_format,
            _normalization_descriptor(
                operation="decode_text",
                backend="python-codecs",
                package=_runtime_package("python", sys.version.split()[0]),
                options={
                    "decode_errors": "strict",
                    "allowed_encodings": sorted(_TEXT_ENCODING_ALLOWLIST),
                    "control_policy": "reject",
                },
                input_sha256=request.input_sha256,
                output_path=target,
                details={
                    "encoding": decoded.encoding,
                    "bom": decoded.bom,
                    "newline": {"input": decoded.newline, "output": "lf"},
                    "normalization": {
                        "bom_removed": decoded.bom != "none",
                        "newlines_normalized": decoded.newline not in {"lf", "none"},
                        "unicode_normalization": "preserved",
                    },
                },
            ),
        )


class _LegacyOfficeNormalizerProvider:
    def __init__(
        self,
        profile: _OfficeConversionProfile,
        executable: Path | None,
    ) -> None:
        self.provider_id = profile.provider_id
        self._profile = profile
        self._executable = executable

    def normalize(self, request: NormalizationRequest) -> NormalizedSource:
        source = _office_source(request)
        normalized = _convert_legacy_office_source(
            source,
            profile=self._profile,
            executable=self._executable,
            work_dir=request.work_dir,
        )
        return NormalizedSource(
            normalized,
            request.capability.source_format,
            request.capability.parser_format,
            _normalization_descriptor(
                operation="decrypt_and_convert" if request.probe.encrypted else "convert",
                backend=self.provider_id,
                package=_runtime_package("libreoffice", "runtime-resolved"),
                options={
                    "encrypted_input": request.probe.encrypted,
                    "headless": True,
                    "isolated_profile": True,
                    "source_format": self._profile.source_format,
                    "target_format": self._profile.target_format,
                },
                input_sha256=request.input_sha256,
                output_path=normalized,
            ),
        )


class _OoxmlNormalizerProvider:
    def __init__(self, *, provider_id: str, profile: _OoxmlPackageProfile) -> None:
        self.provider_id = provider_id
        self._profile = profile

    def normalize(self, request: NormalizationRequest) -> NormalizedSource:
        source = _office_source(request)
        package_facts = _verify_ooxml_package(
            source,
            self._profile,
        )
        return NormalizedSource(
            source,
            request.capability.source_format,
            request.capability.parser_format,
            _normalization_descriptor(
                operation="decrypt" if request.probe.encrypted else "identity",
                backend="msoffcrypto" if request.probe.encrypted else "ooxml-identity",
                package=(
                    _installed_package("msoffcrypto-tool")
                    if request.probe.encrypted
                    else _runtime_package("python-zipfile", sys.version.split()[0])
                ),
                options={
                    "encrypted_input": request.probe.encrypted,
                    "package_safety_verified": True,
                    "entry_count": package_facts["container_entry_count"],
                },
                input_sha256=request.input_sha256,
                output_path=source,
            ),
        )


class _PdfNormalizerProvider:
    provider_id = "pdf"

    def normalize(self, request: NormalizationRequest) -> NormalizedSource:
        source = request.probe.source_path
        if request.probe.encrypted:
            assert request.password is not None
            source = _decrypt_pdf(
                source,
                password=request.password,
                work_dir=request.work_dir,
            )
        return NormalizedSource(
            source,
            request.capability.source_format,
            request.capability.parser_format,
            _normalization_descriptor(
                operation="decrypt" if request.probe.encrypted else "identity",
                backend="pikepdf" if request.probe.encrypted else "pdf-identity",
                package=_installed_package("pikepdf"),
                options={"encrypted_input": request.probe.encrypted, "repair": False},
                input_sha256=request.input_sha256,
                output_path=source,
            ),
        )


class _ImageNormalizerProvider:
    provider_id = "image"

    def normalize(self, request: NormalizationRequest) -> NormalizedSource:
        target = request.work_dir / "normalized-image.png"
        try:
            with Image.open(request.probe.source_path) as image:
                normalized = ImageOps.exif_transpose(image)
                if normalized.mode not in {"RGB", "RGBA", "L"}:
                    normalized = normalized.convert("RGB")
                normalized.save(target, format="PNG")
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError("The image could not be normalized.") from exc
        return NormalizedSource(
            target,
            request.capability.source_format,
            request.capability.parser_format,
            _normalization_descriptor(
                operation="normalize_image",
                backend="pillow-image",
                package=_runtime_package("Pillow", pillow_version),
                options={
                    "orientation": "exif_transposed",
                    "pixel_encoding": "png",
                    "source_format": request.capability.source_format,
                },
                input_sha256=request.input_sha256,
                output_path=target,
            ),
        )


class FormatNormalizer:
    """Dispatch normalization through one registered capability provider."""

    def __init__(
        self,
        executable: Path | None = None,
        *,
        registry: KnowledgeFormatRegistry = KNOWLEDGE_FORMAT_REGISTRY,
        providers: tuple[FormatNormalizerProvider, ...] | None = None,
    ) -> None:
        self._registry = registry
        providers = providers or (
            _TextNormalizerProvider(),
            _LegacyOfficeNormalizerProvider(_DOC_TO_DOCX, executable),
            _OoxmlNormalizerProvider(provider_id="docx", profile=_DOCX_PACKAGE),
            _LegacyOfficeNormalizerProvider(_PPT_TO_PPTX, executable),
            _OoxmlNormalizerProvider(provider_id="pptx", profile=_PPTX_PACKAGE),
            _PdfNormalizerProvider(),
            _ImageNormalizerProvider(),
        )
        self._providers = _provider_map(
            providers,
            required_ids=registry.normalizer_provider_ids,
            kind="normalizer",
        )

    def normalize(
        self,
        probe: FileProbeResult,
        *,
        work_dir: Path,
        password: str | None = None,
    ) -> NormalizedSource:
        capability = self._registry.capability_for_format(probe.source_format)
        if capability is None:
            raise ValidationError("No Knowledge normalizer is registered for this format.")
        if probe.encrypted and not password:
            raise ValidationError(
                "A password is required to import this encrypted document.",
                error_code="knowledge_password_required",
                retryable=True,
            )
        request = NormalizationRequest(
            probe=probe,
            capability=capability,
            work_dir=work_dir,
            password=password,
            input_sha256=_sha256_file_bounded(
                probe.source_path,
                max_bytes=MAX_SOURCE_BYTES,
            ),
        )
        return self._providers[capability.normalizer_provider_id].normalize(request)


def _office_source(request: NormalizationRequest) -> Path:
    if not request.probe.encrypted:
        return request.probe.source_path
    assert request.password is not None
    target = request.work_dir / f"decrypted.{request.probe.source_format}"
    try:
        with request.probe.source_path.open("rb") as stream:
            office = msoffcrypto.OfficeFile(stream)
            office.load_key(password=request.password)
            with target.open("wb") as output:
                office.decrypt(output)
    except Exception as exc:
        raise ValidationError(
            "The document password was not accepted.",
            error_code="knowledge_password_invalid",
            retryable=True,
        ) from exc
    return target


def _decrypt_pdf(
    source: Path,
    *,
    password: str,
    work_dir: Path,
) -> Path:
    target = work_dir / "decrypted.pdf"
    try:
        with pikepdf.Pdf.open(source, password=password) as document:
            document.save(target)
    except (pikepdf.PasswordError, pikepdf.PdfError) as exc:
        raise ValidationError(
            "The document password was not accepted.",
            error_code="knowledge_password_invalid",
            retryable=True,
        ) from exc
    return target


def _convert_legacy_office_source(
    source: Path,
    *,
    profile: _OfficeConversionProfile,
    executable: Path | None,
    work_dir: Path,
) -> Path:
    executable = executable or _find_libreoffice()
    if executable is None:
        raise ValidationError(
            f"Importing legacy {profile.source_display_name} requires LibreOffice.",
            error_code=f"knowledge_{profile.source_format}_converter_unavailable",
            retryable=True,
        )
    libreoffice_profile = work_dir / "libreoffice-profile"
    local_source = work_dir / f"source.{profile.source_format}"
    if source.resolve() != local_source.resolve():
        shutil.copyfile(source, local_source)
    command = [
        str(executable),
        "--headless",
        f"-env:UserInstallation={libreoffice_profile.resolve().as_uri()}",
        "--convert-to",
        profile.libreoffice_filter,
        "--outdir",
        str(work_dir),
        str(local_source),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=str(work_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_no_console_process_kwargs(),
        )
    except OSError:
        raise ValidationError(
            "LibreOffice could not normalize the legacy "
            f"{profile.source_display_name} document.",
            error_code=f"knowledge_{profile.source_format}_conversion_failed",
            retryable=True,
        ) from None
    returncode = _wait_for_process(
        process,
        timeout_seconds=_LIBREOFFICE_TIMEOUT_SECONDS,
        timeout_error=ValidationError(
            "LibreOffice could not normalize the legacy "
            f"{profile.source_display_name} document.",
            error_code=f"knowledge_{profile.source_format}_conversion_failed",
            retryable=True,
        ),
    )
    output = work_dir / f"source.{profile.target_format}"
    if returncode != 0 or not output.is_file():
        raise ValidationError(
            "LibreOffice could not normalize the legacy "
            f"{profile.source_display_name} document.",
            error_code=f"knowledge_{profile.source_format}_conversion_failed",
            retryable=True,
        )
    _verify_ooxml_package(
        output,
        profile.target_package,
    )
    return output


class ParserRouteProvider(Protocol):
    provider_id: str

    def plan(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan: ...


class ParserRouter:
    """Select explainable parse routes through an extensible provider registry."""

    def __init__(
        self,
        providers: tuple[ParserRouteProvider, ...] | None = None,
        *,
        registry: KnowledgeFormatRegistry = KNOWLEDGE_FORMAT_REGISTRY,
    ) -> None:
        self._registry = registry
        providers = providers or (
            _TextRouteProvider(),
            _DoclingOfficeRouteProvider(
                provider_id="docx",
                parser_format="docx",
                route_id="docling-docx",
            ),
            _DoclingOfficeRouteProvider(
                provider_id="pptx",
                parser_format="pptx",
                route_id="docling-pptx",
            ),
            _PdfRouteProvider(),
            _ImageRouteProvider(),
        )
        self._providers = _provider_map(
            providers,
            required_ids=registry.route_provider_ids,
            kind="parser route",
        )

    @property
    def registered_provider_ids(self) -> frozenset[str]:
        return frozenset(self._providers)

    def route(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan:
        capability = self._registry.capability_for_format(normalized.source_format)
        if capability is None or capability.parser_format != normalized.parser_format:
            raise ValidationError("No Knowledge parser route is registered for this format.")
        provider = self._providers[capability.route_provider_id]
        return provider.plan(normalized, ocr_ready=ocr_ready)


@dataclass(frozen=True)
class ParserExecutionContext:
    normalized: NormalizedSource
    plan: ParsePlan
    work_dir: Path
    ocr_executor: Any


@dataclass(frozen=True)
class ParsedContent:
    document: Any
    warnings: tuple[str, ...] = ()
    projections: tuple[dict[str, Any], ...] = ()
    ocr_projection_count: int = 0
    ocr_attempted_count: int = 0
    ocr_succeeded_count: int = 0
    ocr_unavailable_count: int = 0
    ocr_payload_hashes: tuple[tuple[int, str], ...] = ()


class DocumentParserProvider(Protocol):
    provider_id: str
    uses_docling: bool
    backend: str

    def parse(self, context: ParserExecutionContext) -> ParsedContent: ...


class ParseExecutor:
    def __init__(
        self,
        ocr_service: OcrService | None = None,
        *,
        registry: KnowledgeFormatRegistry = KNOWLEDGE_FORMAT_REGISTRY,
        providers: tuple[DocumentParserProvider, ...] | None = None,
    ) -> None:
        self._ocr = ocr_service
        self._registry = registry
        providers = providers or (
            _TextParserProvider(),
            _DoclingOfficeParserProvider(
                provider_id="docx",
                source_format="docx",
            ),
            _DoclingOfficeParserProvider(
                provider_id="pptx",
                source_format="pptx",
            ),
            _PdfParserProvider(),
            _ImageParserProvider(),
        )
        self._providers = _provider_map(
            providers,
            required_ids=registry.parser_provider_ids,
            kind="document parser",
        )

    @property
    def ocr_ready(self) -> bool:
        if self._ocr is None:
            return False
        readiness = getattr(self._ocr, "is_ready", None)
        return bool(readiness()) if callable(readiness) else True

    def parse(
        self,
        normalized: NormalizedSource,
        plan: ParsePlan,
        *,
        probe: FileProbeResult,
        work_dir: Path,
    ) -> ParseResult:
        ocr_ready = plan.ocr_ready
        capability = self._registry.capability_for_format(normalized.source_format)
        if (
            capability is None
            or capability.parser_format != normalized.parser_format
            or plan.parser_format != normalized.parser_format
        ):
            raise ValidationError("The selected Knowledge parse plan is invalid.")
        provider = self._providers[capability.parser_provider_id]
        parser_input_sha256 = _sha256_file_bounded(
            normalized.path,
            max_bytes=MAX_SOURCE_BYTES,
        )
        needs_ocr = any(unit.route_id.startswith("ocr-") for unit in plan.units)
        ocr_runtime_descriptor: dict[str, object] | None = None
        with ExitStack() as stack:
            ocr_executor: Any = self._ocr
            if needs_ocr:
                assert self._ocr is not None
                open_session = getattr(self._ocr, "open_session", None)
                if callable(open_session):
                    ocr_executor = stack.enter_context(
                        open_session(
                            allowed_root=work_dir,
                            log_path=work_dir / "ocr.log",
                        )
                    )
                ocr_runtime_descriptor = _ocr_runtime_payload(ocr_executor)
            content = provider.parse(
                ParserExecutionContext(
                    normalized=normalized,
                    plan=plan,
                    work_dir=work_dir,
                    ocr_executor=ocr_executor,
                )
            )
        parser_output_sha256 = _docling_document_sha256(content.document)
        ocr_status = _ocr_status(
            projection_count=content.ocr_projection_count,
            succeeded_count=content.ocr_succeeded_count,
            unavailable_count=content.ocr_unavailable_count,
        )
        return ParseResult(
            document=content.document,
            pipeline={
                "probe": dict(probe.facts),
                "normalizer": dict(normalized.descriptor),
                "router": {
                    "policy_version": plan.policy_version,
                    "merge_strategy": plan.merge_strategy,
                    "units": [
                        {
                            "scope": unit.scope,
                            "route_id": unit.route_id,
                            "reason": unit.reason,
                            **({"page": unit.page} if unit.page is not None else {}),
                            **({"evidence": unit.evidence} if unit.evidence else {}),
                        }
                        for unit in plan.units
                    ],
                },
                "parser": {
                    "content_ir": "DoclingDocument",
                    "version": 2,
                    "package": _installed_package(
                        "docling" if provider.uses_docling else "docling-core"
                    ),
                    "backend": provider.backend,
                    "options": {
                        "merge_strategy": plan.merge_strategy,
                        "parser_format": normalized.parser_format,
                    },
                    "status": "succeeded",
                    "input_sha256": parser_input_sha256,
                    "output_sha256": parser_output_sha256,
                },
                "ocr": {
                    "service": str((ocr_runtime_descriptor or {}).get("engine", "not-selected")),
                    "package": _runtime_package(
                        str((ocr_runtime_descriptor or {}).get("engine", "not-selected")),
                        str((ocr_runtime_descriptor or {}).get("engine_version", "runtime-resolved")),
                    ),
                    "backend": "provider-session" if needs_ocr else "not-requested",
                    "options": {
                        "page_scoped": normalized.parser_format == "pdf",
                        "projection": "text",
                        "protocol": str((ocr_runtime_descriptor or {}).get("protocol", "none")),
                    },
                    "status": ocr_status,
                    "ready": ocr_ready,
                    "input_sha256": parser_input_sha256,
                    "output_sha256": _combined_projection_sha256(
                        content.ocr_payload_hashes
                    ),
                    "projection_count": content.ocr_projection_count,
                    "attempted_count": content.ocr_attempted_count,
                    "succeeded_count": content.ocr_succeeded_count,
                    "unavailable_count": content.ocr_unavailable_count,
                    **(
                        {"runtime": ocr_runtime_descriptor}
                        if ocr_runtime_descriptor is not None
                        else {}
                    ),
                },
            },
            warnings=list(content.warnings),
            projections=list(content.projections),
        )


class _TextRouteProvider:
    provider_id = "text"

    def plan(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan:
        return ParsePlan(
            "txt",
            "txt",
            (ParsePlanUnit("document", "xenix-text", "decoded_text"),),
            "document",
            ocr_ready=ocr_ready,
        )


class _DoclingOfficeRouteProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        parser_format: str,
        route_id: str,
    ) -> None:
        self.provider_id = provider_id
        self._parser_format = parser_format
        self._route_id = route_id

    def plan(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan:
        return ParsePlan(
            normalized.source_format,
            self._parser_format,
            (ParsePlanUnit("document", self._route_id, "validated_ooxml"),),
            "document",
            ocr_ready=ocr_ready,
        )


class _PdfRouteProvider:
    provider_id = "pdf"

    def plan(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan:
        units: list[ParsePlanUnit] = []
        for evidence in probe_pdf_pages(normalized.path):
            payload = evidence.to_payload()
            if evidence.text_state is PdfPageTextState.CREDIBLE:
                route_id = "docling-pdf-native"
                reason = "native_text_credible"
            elif ocr_ready:
                route_id = (
                    "ocr-page"
                    if evidence.text_state is PdfPageTextState.ABSENT
                    else "ocr-hybrid-page"
                )
                reason = f"native_text_{evidence.text_state.value}"
            else:
                route_id = "text-projection-unavailable"
                reason = f"ocr_unavailable_for_{evidence.text_state.value}_text"
            units.append(ParsePlanUnit("page", route_id, reason, evidence.page, payload))
        return ParsePlan(
            "pdf",
            "pdf",
            tuple(units),
            "docling-document-plus-page-projections",
            policy_version=2,
            ocr_ready=ocr_ready,
        )


class _ImageRouteProvider:
    provider_id = "image"

    def plan(self, normalized: NormalizedSource, *, ocr_ready: bool) -> ParsePlan:
        units = [ParsePlanUnit("image", "docling-image-shell", "image_content_ir")]
        units.append(
            ParsePlanUnit(
                "image",
                "ocr-image" if ocr_ready else "text-projection-unavailable",
                "ocr_ready" if ocr_ready else "ocr_unavailable",
            )
        )
        return ParsePlan(
            normalized.source_format,
            "image",
            tuple(units),
            "image-with-optional-text-projection",
            ocr_ready=ocr_ready,
        )


class _TextParserProvider:
    provider_id = "text"
    uses_docling = False
    backend = "xenix-txt-adapter"

    def parse(self, context: ParserExecutionContext) -> ParsedContent:
        return ParsedContent(
            _plain_text_docling_document(context.normalized.path)
        )


class _DoclingOfficeParserProvider:
    uses_docling = True
    backend = "docling"

    def __init__(self, *, provider_id: str, source_format: str) -> None:
        self.provider_id = provider_id
        self._source_format = source_format

    def parse(self, context: ParserExecutionContext) -> ParsedContent:
        return ParsedContent(
            _docling_convert(
                context.normalized.path,
                source_format=self._source_format,
                work_dir=context.work_dir,
            )
        )


class _PdfParserProvider:
    provider_id = "pdf"
    uses_docling = True
    backend = "docling"

    def parse(self, context: ParserExecutionContext) -> ParsedContent:
        document = _docling_convert(
            context.normalized.path,
            source_format="pdf",
            work_dir=context.work_dir,
        )
        ocr_pages = [
            unit.page - 1
            for unit in context.plan.units
            if unit.route_id in {"ocr-page", "ocr-hybrid-page"}
            and unit.page
        ]
        unavailable_pages = [
            unit.page
            for unit in context.plan.units
            if unit.route_id == "text-projection-unavailable" and unit.page
        ]
        projection_count = len(ocr_pages) + len(unavailable_pages)
        warnings: list[str] = []
        projections: list[dict[str, Any]] = []
        succeeded_count = 0
        payload_hashes: tuple[tuple[int, str], ...] = ()
        if ocr_pages:
            page_result = _append_ocr_pages(
                document,
                pdf_path=context.normalized.path,
                page_indexes=ocr_pages,
                work_dir=context.work_dir,
                ocr_service=context.ocr_executor,
            )
            succeeded_count = len(page_result.succeeded_pages)
            unavailable_pages.extend(page_result.unavailable_pages)
            payload_hashes = page_result.payload_hashes
            if page_result.succeeded_pages:
                projections.append(
                    {
                        "kind": "ocr_text",
                        "status": "ready",
                        "pages": list(page_result.succeeded_pages),
                        "items": page_result.item_count,
                    }
                )
        unavailable_pages = sorted(set(unavailable_pages))
        if unavailable_pages:
            warnings.append("ocr_projection_unavailable")
            projections.append(
                {
                    "kind": "ocr_text",
                    "status": "unavailable",
                    "pages": unavailable_pages,
                }
            )
        return ParsedContent(
            document,
            warnings=tuple(warnings),
            projections=tuple(projections),
            ocr_projection_count=projection_count,
            ocr_attempted_count=len(ocr_pages),
            ocr_succeeded_count=succeeded_count,
            ocr_unavailable_count=len(unavailable_pages),
            ocr_payload_hashes=payload_hashes,
        )


class _ImageParserProvider:
    provider_id = "image"
    uses_docling = False
    backend = "xenix-image-adapter"

    def parse(self, context: ParserExecutionContext) -> ParsedContent:
        document = _image_docling_document(context.normalized.path)
        if not context.plan.ocr_ready:
            return ParsedContent(
                document,
                warnings=("ocr_projection_unavailable",),
                projections=({"kind": "ocr_text", "status": "unavailable"},),
                ocr_projection_count=1,
                ocr_unavailable_count=1,
            )
        staged_image = context.work_dir / "ocr-image.png"
        try:
            with Image.open(context.normalized.path) as source:
                ImageOps.exif_transpose(source).convert("RGB").save(staged_image, format="PNG")
                image_width, image_height = source.size
        except (OSError, ValueError) as exc:
            raise ValidationError(
                "The image could not be prepared for OCR.",
                error_code="knowledge_ocr_input_invalid",
            ) from exc
        payload = _recognize_projection(
            context.ocr_executor,
            staged_image,
            output_path=context.work_dir / "image-ocr.json",
        )
        if payload is None:
            raise ValidationError(
                "OCR provider returned no result.",
                error_code="knowledge_ocr_response_invalid",
            )
        count = _append_ocr_text(
            document,
            payload,
            page_no=1,
            coordinate_scale=1.0,
            maximum_width=float(image_width),
            maximum_height=float(image_height),
        )
        payload_hash = _bounded_json_sha256(
            payload,
            label="OCR result",
            max_bytes=MAX_OCR_RESULT_BYTES,
        )
        return ParsedContent(
            document,
            projections=({"kind": "ocr_text", "status": "ready", "items": count},),
            ocr_projection_count=1,
            ocr_attempted_count=1,
            ocr_succeeded_count=1,
            ocr_payload_hashes=((1, payload_hash),),
        )


def _wait_for_process(
    process: Any,
    *,
    timeout_seconds: float,
    timeout_error: Exception,
) -> int:
    try:
        return int(process.wait(timeout=timeout_seconds))
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        raise timeout_error from None
    except BaseException:
        _terminate_process(process)
        raise


def _terminate_process(process: Any) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=_PROCESS_TERMINATE_GRACE_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=_PROCESS_TERMINATE_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _no_console_process_kwargs() -> dict[str, int]:
    if sys.platform != "win32":
        return {}
    return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}


def _read_bytes(path: Path) -> bytes:
    blocks: list[bytes] = []
    with path.open("rb") as source:
        while True:
            block = source.read(_IO_CHUNK_BYTES)
            if not block:
                break
            blocks.append(block)
    return b"".join(blocks)


def _read_text(path: Path) -> str:
    return _read_bytes(path).decode("utf-8")


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for start in range(0, len(text), _IO_CHUNK_BYTES):
            target.write(text[start : start + _IO_CHUNK_BYTES])


def _sha256_file_bounded(
    path: Path,
    *,
    max_bytes: int,
) -> str:
    size = path.stat().st_size
    if size < 0 or size > max_bytes:
        raise ValidationError("Knowledge pipeline hash input exceeds the supported limit.")
    digest = hashlib.sha256()
    consumed = 0
    with path.open("rb") as source:
        while True:
            block = source.read(_IO_CHUNK_BYTES)
            if not block:
                break
            consumed += len(block)
            if consumed > max_bytes:
                raise ValidationError(
                    "Knowledge pipeline hash input exceeds the supported limit."
                )
            digest.update(block)
    return digest.hexdigest()


def _normalization_descriptor(
    *,
    operation: str,
    backend: str,
    package: dict[str, str],
    options: dict[str, Any],
    input_sha256: str,
    output_path: Path,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_sha256 = _sha256_file_bounded(
        output_path,
        max_bytes=MAX_SOURCE_BYTES,
    )
    return {
        "operation": operation,
        "version": 2,
        "package": package,
        "backend": backend,
        "options": dict(options),
        "status": "succeeded",
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        **dict(details or {}),
    }


def _runtime_package(name: str, version: str) -> dict[str, str]:
    return {"name": name, "version": version}


def _installed_package(distribution: str) -> dict[str, str]:
    try:
        installed_version = package_version(distribution)
    except PackageNotFoundError:
        installed_version = "unknown"
    return _runtime_package(distribution, installed_version)


def _bounded_json_sha256(
    value: Any,
    *,
    label: str,
    max_bytes: int = MAX_HASHABLE_IR_BYTES,
) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise ValidationError(f"{label} cannot be hashed safely.") from exc
    if len(payload) > max_bytes:
        raise ValidationError(f"{label} exceeds the supported hash limit.")
    return hashlib.sha256(payload).hexdigest()


def _docling_document_sha256(document: Any) -> str:
    try:
        exported = document.export_to_dict()
    except Exception as exc:
        raise ValidationError("Docling content cannot be hashed safely.") from exc
    return _bounded_json_sha256(
        _redact_path_values_for_hash(exported),
        label="Docling content",
    )


def _redact_path_values_for_hash(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(item_key): _redact_path_values_for_hash(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_path_values_for_hash(item, key=key) for item in value]
    if isinstance(value, str) and key in {"path", "uri"}:
        candidate = Path(value)
        if candidate.is_absolute() or "://" in value or value.startswith(("~", "\\\\")):
            return "<redacted-path>"
    return value


def _combined_projection_sha256(payload_hashes: Iterable[tuple[int, str]]) -> str | None:
    ordered = [
        {"ordinal": ordinal, "sha256": payload_sha256}
        for ordinal, payload_sha256 in payload_hashes
    ]
    if not ordered:
        return None
    return _bounded_json_sha256(ordered, label="OCR projection hashes", max_bytes=64 * 1024)


def _ocr_status(
    *,
    projection_count: int,
    succeeded_count: int,
    unavailable_count: int,
) -> str:
    if projection_count == 0:
        return "not_requested"
    if unavailable_count and succeeded_count:
        return "partial"
    if unavailable_count:
        return "unavailable"
    return "succeeded"


def _normalize_text(
    raw_text: str,
) -> str:
    _reject_unsafe_text_controls(raw_text)
    pieces: list[str] = []
    pending_cr = ""
    current_line_chars = 0
    for start in range(0, len(raw_text), _IO_CHUNK_BYTES):
        chunk = pending_cr + raw_text[start : start + _IO_CHUNK_BYTES]
        if chunk.endswith("\r"):
            chunk, pending_cr = chunk[:-1], "\r"
        else:
            pending_cr = ""
        chunk = chunk.replace("\r\n", "\n").replace("\r", "\n")
        lines = chunk.split("\n")
        if len(lines) == 1:
            current_line_chars += len(lines[0])
        else:
            if current_line_chars + len(lines[0]) > MAX_TEXT_LINE_CHARS:
                raise ValidationError(
                    "TXT contains a line longer than the supported limit.",
                    error_code="knowledge_text_line_too_long",
                )
            if any(len(line) > MAX_TEXT_LINE_CHARS for line in lines[1:-1]):
                raise ValidationError(
                    "TXT contains a line longer than the supported limit.",
                    error_code="knowledge_text_line_too_long",
                )
            current_line_chars = len(lines[-1])
        if current_line_chars > MAX_TEXT_LINE_CHARS:
            raise ValidationError(
                "TXT contains a line longer than the supported limit.",
                error_code="knowledge_text_line_too_long",
            )
        pieces.append(chunk)
    if pending_cr:
        pieces.append("\n")
    return "".join(pieces)


def _recognize_projection(
    ocr_service: Any,
    image_path: Path,
    *,
    output_path: Path,
) -> Any:
    """Provider/protocol failures propagate so the parent publishes no partial document."""

    return ocr_service.recognize(image_path, output_path=output_path)


def _ocr_runtime_payload(value: object) -> dict[str, object] | None:
    descriptor = normalize_runtime_descriptor(value)
    return descriptor.to_payload() if descriptor is not None else None


@dataclass(frozen=True)
class _DecodedText:
    text: str
    encoding: str
    bom: str
    newline: str
    selection: str


def _provider_map(
    providers: Iterable[_ProviderT],
    *,
    required_ids: tuple[str, ...],
    kind: str,
) -> dict[str, _ProviderT]:
    by_id: dict[str, _ProviderT] = {}
    for provider in providers:
        provider_id = getattr(provider, "provider_id", None)
        if (
            not isinstance(provider_id, str)
            or not provider_id
            or provider_id != provider_id.strip().casefold()
        ):
            raise ValueError(
                f"Knowledge {kind} provider IDs must be normalized strings."
            )
        if provider_id in by_id:
            raise ValueError(f"Knowledge {kind} provider IDs must be unique.")
        by_id[provider_id] = provider
    missing = [provider_id for provider_id in required_ids if provider_id not in by_id]
    if missing:
        raise ValueError(
            f"Knowledge {kind} providers are missing: {', '.join(missing)}"
        )
    unused = sorted(set(by_id) - set(required_ids))
    if unused:
        raise ValueError(
            f"Knowledge {kind} providers have no format capability: "
            + ", ".join(unused)
        )
    return by_id


def _format_mismatch() -> ValidationError:
    return ValidationError(
        "The selected file signature does not match its extension.",
        error_code="knowledge_format_mismatch",
    )


def _probe_text(
    payload: bytes,
    facts: dict[str, Any],
    *,
    sample_is_complete: bool,
) -> None:
    decoded = _decode_text_payload(
        payload,
        allow_truncated_tail=not sample_is_complete,
    )
    facts["encoding_candidate"] = decoded.encoding
    facts["encoding_selection"] = decoded.selection
    facts["bom"] = decoded.bom != "none"
    facts["bom_kind"] = decoded.bom
    facts["newline"] = decoded.newline
    facts["control_character_count"] = 0


def _decode_text_payload(
    payload: bytes,
    *,
    allow_truncated_tail: bool = False,
) -> _DecodedText:
    if not payload:
        raise ValidationError(
            "TXT contains no decodable text.",
            error_code="knowledge_text_encoding_unknown",
        )
    bom_encoding, bom_size = _text_bom(payload)
    if bom_encoding in {"utf-32-le", "utf-32-be"}:
        raise ValidationError(
            "TXT encoding is outside the supported allowlist.",
            error_code="knowledge_text_encoding_unknown",
        )
    if bom_encoding is not None:
        text = _strict_decode_text(
            payload[bom_size:],
            encoding=bom_encoding,
            allow_truncated_tail=allow_truncated_tail,
        )
        selection = "bom"
        encoding = bom_encoding
    else:
        try:
            text = _strict_decode_text(
                payload,
                encoding="utf-8",
                allow_truncated_tail=allow_truncated_tail,
            )
            encoding = "utf-8"
            selection = "strict_utf8"
        except ValidationError:
            matches = tuple(from_bytes(payload))
            best = matches[0] if matches else None
            candidate = _canonical_encoding_name(
                str(best.encoding) if best is not None and best.encoding else ""
            )
            best_chaos = float(best.chaos) if best is not None else 1.0
            ambiguous = any(
                _canonical_encoding_name(str(other.encoding or "")) != candidate
                and float(other.chaos) - best_chaos < _TEXT_MIN_CANDIDATE_SEPARATION
                for other in matches[1:]
            )
            if (
            candidate not in _TEXT_FALLBACK_ENCODINGS
                or best_chaos > _TEXT_MAX_CANDIDATE_CHAOS
                or ambiguous
            ):
                raise ValidationError(
                    "TXT encoding could not be determined with sufficient confidence.",
                    error_code="knowledge_text_encoding_unknown",
                ) from None
            encoding = candidate
            selection = "bounded_charset_candidate"
            text = _strict_decode_text(
                payload,
                encoding=encoding,
                allow_truncated_tail=allow_truncated_tail,
            )
    _reject_unsafe_text_controls(text)
    if not text and not allow_truncated_tail:
        raise ValidationError(
            "TXT contains no decodable text.",
            error_code="knowledge_text_encoding_unknown",
        )
    return _DecodedText(
        text=text,
        encoding=encoding,
        bom=encoding if bom_encoding is not None else "none",
        newline=_newline_style(text),
        selection=selection,
    )


def _text_bom(payload: bytes) -> tuple[str | None, int]:
    markers = (
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xfe\xff", "utf-16-be"),
        (b"\xff\xfe", "utf-16-le"),
    )
    for marker, encoding in markers:
        if payload.startswith(marker):
            return encoding, len(marker)
    return None, 0


def _strict_decode_text(
    payload: bytes,
    *,
    encoding: str,
    allow_truncated_tail: bool,
) -> str:
    try:
        return payload.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        truncated_tail = (
            allow_truncated_tail
            and exc.end == len(payload)
            and ("unexpected end" in exc.reason or "truncated" in exc.reason)
        )
        if truncated_tail:
            return payload[: exc.start].decode(encoding, errors="strict")
        raise ValidationError(
            "TXT bytes are invalid for the selected encoding.",
            error_code="knowledge_text_encoding_invalid",
        ) from None


def _canonical_encoding_name(raw: str) -> str:
    if not raw:
        return ""
    try:
        return codecs.lookup(raw).name.replace("_", "-")
    except LookupError:
        return ""


def _reject_unsafe_text_controls(text: str) -> None:
    if "\ufffd" in text or any(
        unicodedata.category(character) in {"Cc", "Cs"}
        and character not in {"\t", "\n", "\r"}
        for character in text
    ):
        raise ValidationError(
            "TXT contains unsupported control or binary characters.",
            error_code="knowledge_text_controls_invalid",
        )


def _newline_style(text: str) -> str:
    crlf_count = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    styles = [
        name
        for name, count in (
            ("crlf", crlf_count),
            ("cr", without_crlf.count("\r")),
            ("lf", without_crlf.count("\n")),
        )
        if count
    ]
    if not styles:
        return "none"
    return styles[0] if len(styles) == 1 else "mixed"


def _probe_pdf(path: Path) -> tuple[bool, dict[str, Any]]:
    try:
        with pikepdf.Pdf.open(path) as document:
            warnings = [str(item)[:96] for item in document.check_pdf_syntax()[:16]]
            return False, {"page_count": len(document.pages), "syntax_warning_count": len(warnings)}
    except pikepdf.PasswordError:
        return True, {"page_count": None, "syntax_warning_count": 0}
    except pikepdf.PdfError as exc:
        raise ValidationError(
            "The selected PDF is structurally invalid.",
            error_code="knowledge_pdf_invalid",
        ) from exc


def _probe_image(path: Path, *, expected_format: str) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            actual = str(image.format or "").casefold()
            if actual == "jpg":
                actual = "jpeg"
            if actual != expected_format:
                raise ValidationError("The image container does not match its extension.")
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValidationError("The image dimensions exceed the supported range.")
            image.verify()
        return {"width": width, "height": height, "pixels": width * height}
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("The selected image is invalid.") from exc


def _inspect_office_file(path: Path) -> tuple[str | None, bool]:
    try:
        with path.open("rb") as stream:
            office = msoffcrypto.OfficeFile(stream)
            office_kind = {
                "Doc97File": "doc",
                "Ppt97File": "ppt",
                "OOXMLFile": "ooxml",
            }.get(type(office).__name__)
            return office_kind, bool(office.is_encrypted())
    except Exception:
        return None, False


def _ooxml_error(
    profile: _OoxmlPackageProfile,
    category: str,
    detail: str,
) -> ValidationError:
    return ValidationError(
        f"The selected {profile.display_name} {detail}.",
        error_code=f"knowledge_{profile.source_format}_{category}",
    )


def _verify_ooxml_package(
    path: Path,
    profile: _OoxmlPackageProfile,
) -> dict[str, int]:
    try:
        with ZipFile(path) as package:
            entries = package.infolist()
            if len(entries) > MAX_OOXML_PACKAGE_ENTRIES:
                raise _ooxml_error(
                    profile,
                    "entry_limit",
                    "contains too many package entries",
                )
            names: set[str] = set()
            casefold_names: set[str] = set()
            expanded_bytes = 0
            maximum_ratio = 1
            for entry in entries:
                _validate_ooxml_member_path(
                    entry.filename,
                    profile=profile,
                    is_directory=entry.is_dir(),
                )
                folded = entry.filename.casefold()
                if entry.filename in names or folded in casefold_names:
                    raise _ooxml_error(
                        profile,
                        "entries_ambiguous",
                        "contains ambiguous package entries",
                    )
                names.add(entry.filename)
                casefold_names.add(folded)
                if entry.flag_bits & 0x1:
                    raise _ooxml_error(
                        profile,
                        "entry_encrypted",
                        "contains encrypted package entries",
                    )
                mode = (entry.external_attr >> 16) & 0xFFFF
                if mode and stat.S_ISLNK(mode):
                    raise _ooxml_error(
                        profile,
                        "entry_unsafe",
                        "contains an unsafe package entry",
                    )
                if entry.file_size < 0 or entry.compress_size < 0:
                    raise _ooxml_error(
                        profile,
                        "size_invalid",
                        "has invalid package sizes",
                    )
                if entry.file_size > MAX_OOXML_ENTRY_BYTES:
                    raise _ooxml_error(
                        profile,
                        "entry_too_large",
                        "package entry is too large",
                    )
                expanded_bytes += entry.file_size
                if expanded_bytes > MAX_OOXML_EXPANDED_BYTES:
                    raise _ooxml_error(
                        profile,
                        "expansion_limit",
                        "expands beyond the supported limit",
                    )
                ratio = (
                    entry.file_size
                    if entry.compress_size == 0
                    else (entry.file_size + entry.compress_size - 1) // entry.compress_size
                )
                maximum_ratio = max(maximum_ratio, ratio)
                if (
                    entry.file_size >= _OOXML_RATIO_CHECK_MIN_BYTES
                    and ratio > MAX_OOXML_COMPRESSION_RATIO
                ):
                    raise _ooxml_error(
                        profile,
                        "compression_ratio",
                        "compression ratio is unsafe",
                    )
            if profile.main_part not in names or "[Content_Types].xml" not in names:
                raise _ooxml_error(
                    profile,
                    "package_invalid",
                    "has the wrong Office package type",
                )
    except (BadZipFile, OSError) as exc:
        raise _ooxml_error(
            profile,
            "package_invalid",
            "is not a valid Office package",
        ) from exc
    return {
        "container_entry_count": len(entries),
        "container_expanded_bytes": expanded_bytes,
        "container_max_compression_ratio": maximum_ratio,
    }


def _validate_ooxml_member_path(
    name: str,
    *,
    profile: _OoxmlPackageProfile,
    is_directory: bool,
) -> None:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or len(name.encode("utf-8")) > MAX_OOXML_MEMBER_NAME_BYTES
    ):
        raise _ooxml_error(
            profile,
            "path_unsafe",
            "contains an unsafe package path",
        )
    normalized = name[:-1] if is_directory and name.endswith("/") else name
    raw_parts = normalized.split("/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or relative.is_absolute()
        or len(raw_parts) > MAX_OOXML_MEMBER_DEPTH
        or any(part in {"", ".", ".."} or ":" in part for part in raw_parts)
    ):
        raise _ooxml_error(
            profile,
            "path_unsafe",
            "contains an unsafe package path",
        )


def _read_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as stream:
        return stream.read(size)


def _find_libreoffice() -> Path | None:
    command = shutil.which("soffice") or shutil.which("libreoffice")
    candidates = (
        Path(command) if command else None,
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    )
    return next((candidate for candidate in candidates if candidate is not None and candidate.is_file()), None)


def _plain_text_docling_document(path: Path):
    from docling_core.types.doc import DocItemLabel, DoclingDocument

    text = _read_text(path)
    document = DoclingDocument(name=path.stem)
    for paragraph in (part.strip() for part in text.split("\n\n")):
        if paragraph:
            document.add_text(DocItemLabel.TEXT, paragraph)
    return document


def _image_docling_document(path: Path):
    from docling_core.types.doc import DoclingDocument

    document = DoclingDocument(name=path.stem)
    document.add_picture()
    return document


def _docling_convert(
    path: Path,
    *,
    source_format: str,
    work_dir: Path,
):
    from .knowledge_docling import convert_document

    _ = work_dir
    try:
        document = convert_document(path, source_format=source_format)
    except Exception as exc:
        raise ValidationError(
            "Docling could not parse the document.",
            error_code="knowledge_docling_conversion_failed",
            error_details={"diagnostic_code": _docling_diagnostic_code(exc)},
            retryable=True,
        ) from exc
    return document


def _docling_diagnostic_code(exc: Exception) -> str:
    if isinstance(exc, MemoryError):
        return "docling_memory_error"
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "docling_dependency_error"
    if isinstance(exc, OSError):
        return "docling_runtime_error"
    return "docling_conversion_error"


def _append_ocr_pages(
    document: Any,
    *,
    pdf_path: Path,
    page_indexes: list[int],
    work_dir: Path,
    ocr_service: OcrService,
) -> _OcrBatchResult:
    import pypdfium2

    succeeded_pages: list[int] = []
    unavailable_pages: list[int] = []
    payload_hashes: list[tuple[int, str]] = []
    item_count = 0
    pdf = pypdfium2.PdfDocument(pdf_path)
    try:
        for page_index in page_indexes:
            page = pdf[page_index]
            try:
                image_path = work_dir / f"ocr-page-{page_index + 1}.png"
                render_scale = 2.0
                page_width = float(page.get_width())
                page_height = float(page.get_height())
                page.render(scale=render_scale).to_pil().save(image_path)
            finally:
                page.close()
            output_path = work_dir / f"ocr-page-{page_index + 1}.json"
            payload = _recognize_projection(
                ocr_service,
                image_path,
                output_path=output_path,
            )
            page_number = page_index + 1
            if payload is None:
                raise ValidationError(
                    "OCR provider returned no result.",
                    error_code="knowledge_ocr_response_invalid",
                )
            item_count += _append_ocr_text(
                document,
                payload,
                page_no=page_number,
                coordinate_scale=render_scale,
                maximum_width=page_width,
                maximum_height=page_height,
            )
            succeeded_pages.append(page_number)
            payload_hashes.append(
                (
                    page_number,
                    _bounded_json_sha256(
                        payload,
                        label="OCR result",
                        max_bytes=MAX_OCR_RESULT_BYTES,
                    ),
                )
            )
    finally:
        pdf.close()
    return _OcrBatchResult(
        succeeded_pages=tuple(succeeded_pages),
        unavailable_pages=tuple(unavailable_pages),
        item_count=item_count,
        payload_hashes=tuple(payload_hashes),
    )


def _append_ocr_text(
    document: Any,
    payload: Any,
    *,
    page_no: int,
    coordinate_scale: float,
    maximum_width: float,
    maximum_height: float,
) -> int:
    from docling_core.types.doc import BoundingBox, DocItemLabel, ProvenanceItem

    count = 0
    for text, bbox in _ocr_text_boxes(payload):
        clean = text.strip()
        if not clean:
            continue
        document.add_text(
            DocItemLabel.TEXT,
            clean,
            prov=ProvenanceItem(
                page_no=page_no,
                bbox=BoundingBox(
                    l=_inverse_clamped_coordinate(bbox[0], coordinate_scale, maximum_width),
                    t=_inverse_clamped_coordinate(bbox[1], coordinate_scale, maximum_height),
                    r=_inverse_clamped_coordinate(bbox[2], coordinate_scale, maximum_width),
                    b=_inverse_clamped_coordinate(bbox[3], coordinate_scale, maximum_height),
                ),
                charspan=(0, len(clean)),
            ),
        )
        count += 1
    return count


def _ocr_text_boxes(payload: Any) -> list[tuple[str, tuple[float, float, float, float]]]:
    matches: list[tuple[str, tuple[float, float, float, float]]] = []
    if isinstance(payload, dict):
        regions = payload.get("regions")
        if isinstance(regions, list):
            for region in regions:
                if not isinstance(region, dict):
                    continue
                matches.append(
                    (
                        str(region.get("text", "")),
                        _polygon_bbox(region.get("polygon")),
                    )
                )
            return matches
        texts = payload.get("rec_texts")
        polygons = payload.get("rec_polys") or payload.get("dt_polys") or []
        if isinstance(texts, list):
            for index, raw_text in enumerate(texts):
                polygon = polygons[index] if isinstance(polygons, list) and index < len(polygons) else None
                matches.append((str(raw_text), _polygon_bbox(polygon)))
        for value in payload.values():
            matches.extend(_ocr_text_boxes(value))
    elif isinstance(payload, list):
        for value in payload:
            matches.extend(_ocr_text_boxes(value))
    return matches


def _polygon_bbox(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, list):
        points = [point for point in value if isinstance(point, list) and len(point) >= 2]
        if points:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            return min(xs), min(ys), max(xs), max(ys)
    return 0.0, 0.0, 0.0, 0.0


def _inverse_clamped_coordinate(value: float, scale: float, maximum: float) -> float:
    if not math.isfinite(value) or not math.isfinite(scale) or scale <= 0 or maximum < 0:
        raise ValidationError("OCR provider returned an invalid coordinate.", error_code="knowledge_ocr_result_invalid")
    inverted = value / scale
    quantized = math.floor(inverted + 0.5)
    return float(min(maximum, max(0, quantized)))
