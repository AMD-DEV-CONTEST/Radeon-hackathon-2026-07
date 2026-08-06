"""Strict KServe V2 Binary Tensor PAGE OCR client.

The client is an ordinary OCR provider.  It has no knowledge of AMD, SSH,
installation lifecycle, or managed provider settings; a parent supplies an
ephemeral loopback binding through :class:`OcrSpawnSpec`.
"""

from __future__ import annotations

import json
import math
import struct
import urllib.error
import urllib.request
import xml.etree.ElementTree as element_tree
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .contracts import OcrFailure, OcrRuntimeDescriptor, OcrSpawnSpec

_PAGE_NAMESPACE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2024-07-15"
_INPUT_NAME = "image"
_OUTPUT_NAME = "page_xml"
_MAX_HEADER_BYTES = 64 * 1024
_DEFAULT_MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_DEFAULT_MAX_PIXELS = 100_000_000
_DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_XML_BYTES = 48 * 1024 * 1024
_DEFAULT_MAX_XML_DEPTH = 64
_DEFAULT_MAX_XML_NODES = 100_000
_DEFAULT_MAX_REGIONS = 20_000
_DEFAULT_MAX_POINTS = 64


@dataclass(frozen=True, slots=True)
class KServeV2OcrService(AbstractContextManager["KServeV2OcrService"]):
    """One ordinary KServe V2 PAGE OCR client bound to a transient loopback URL."""

    _endpoint: str = field(repr=False)
    _bearer_token: str = field(repr=False)
    _model_name: str
    _descriptor: OcrRuntimeDescriptor
    _timeout_seconds: int
    _limits: dict[str, int]

    @classmethod
    def from_spawn_spec(cls, spawn_spec: OcrSpawnSpec) -> KServeV2OcrService:
        if spawn_spec.kind != "kserve_v2" or spawn_spec.runtime_descriptor is None:
            raise OcrFailure("OCR provider binding is unavailable.", error_code="knowledge_ocr_provider_unavailable")
        endpoint = spawn_spec.endpoint or ""
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise OcrFailure("OCR provider binding is unavailable.", error_code="knowledge_ocr_binding_invalid")
        return cls(
            _endpoint=endpoint.rstrip("/"),
            _bearer_token=spawn_spec.bearer_token or "",
            _model_name=spawn_spec.model_name or "",
            _descriptor=spawn_spec.runtime_descriptor,
            _timeout_seconds=spawn_spec.timeout_seconds,
            _limits=dict(spawn_spec.request_limits),
        )

    def __enter__(self) -> KServeV2OcrService:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """The binding is parent-owned; the child has no remote cleanup authority."""

    def is_ready(self) -> bool:
        return True

    def runtime_descriptor(self) -> OcrRuntimeDescriptor:
        return self._descriptor

    def open_session(self, *, allowed_root: Path, log_path: Path) -> KServeV2OcrService:
        _ = allowed_root, log_path
        return self

    def recognize(
        self,
        image_path: Path,
        *,
        output_path: Path,
        timeout: int = 300,
    ) -> dict[str, object]:
        image = _read_png(image_path, limits=self._limits)
        request_timeout = min(max(1, timeout), self._timeout_seconds)
        page_xml = self._infer(image, timeout_seconds=request_timeout)
        result = _parse_page(page_xml, limits=self._limits)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except (OSError, UnicodeError) as exc:
            raise OcrFailure("OCR result could not be staged.", error_code="knowledge_ocr_result_stage_failed") from exc
        return result

    def _infer(self, image: bytes, *, timeout_seconds: int) -> bytes:
        packed_image = struct.pack("<I", len(image)) + image
        request_id = uuid4().hex
        header = {
            "id": request_id,
            "inputs": [
                {
                    "name": _INPUT_NAME,
                    "datatype": "BYTES",
                    "shape": [1],
                    "parameters": {
                        "binary_data_size": len(packed_image),
                        "content_type": "image/png",
                    },
                }
            ],
            "outputs": [{"name": _OUTPUT_NAME, "parameters": {"binary_data": True}}],
        }
        try:
            header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise OcrFailure(
                "OCR request could not be constructed.", error_code="knowledge_ocr_request_invalid"
            ) from exc
        request = urllib.request.Request(
            f"{self._endpoint}/v2/models/{self._model_name}/infer",
            data=header_bytes + packed_image,
            headers={
                "Content-Type": "application/octet-stream",
                "Inference-Header-Content-Length": str(len(header_bytes)),
                "Authorization": f"Bearer {self._bearer_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.headers.get_content_type() != "application/octet-stream":
                    raise OcrFailure(
                        "OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid"
                    )
                raw = response.read(_limit(self._limits, "max_response_bytes", _DEFAULT_MAX_RESPONSE_BYTES) + 1)
                raw_header_length = response.headers.get("Inference-Header-Content-Length")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            try:
                exc.close()
            except OSError:
                pass
            code = (
                "knowledge_ocr_authentication_failed" if status in {401, 403} else "knowledge_ocr_provider_http_error"
            )
            raise OcrFailure("OCR provider rejected the request.", error_code=code, retryable=status >= 500) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OcrFailure(
                "OCR provider is unavailable.", error_code="knowledge_ocr_provider_unavailable", retryable=True
            ) from exc
        if len(raw) > _limit(self._limits, "max_response_bytes", _DEFAULT_MAX_RESPONSE_BYTES):
            raise OcrFailure(
                "OCR provider response exceeds the configured bound.", error_code="knowledge_ocr_response_too_large"
            )
        try:
            header_length = int(raw_header_length)
        except (TypeError, ValueError) as exc:
            raise OcrFailure(
                "OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid"
            ) from exc
        if not 2 <= header_length <= _MAX_HEADER_BYTES or header_length >= len(raw):
            raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")
        header = _json_object(raw[:header_length])
        binary = raw[header_length:]
        _validate_response_header(header, request_id=request_id, model_name=self._model_name, binary=binary)
        if len(binary) < 4:
            raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")
        element_size = struct.unpack("<I", binary[:4])[0]
        page_xml = binary[4:]
        if element_size != len(page_xml):
            raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")
        if not page_xml or len(page_xml) > _limit(self._limits, "max_xml_bytes", _DEFAULT_MAX_XML_BYTES):
            raise OcrFailure(
                "OCR provider response exceeds the configured bound.", error_code="knowledge_ocr_response_too_large"
            )
        return page_xml


def _read_png(path: Path, *, limits: dict[str, int]) -> bytes:
    max_bytes = _limit(limits, "max_compressed_bytes", _DEFAULT_MAX_COMPRESSED_BYTES)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OcrFailure("OCR input is unavailable.", error_code="knowledge_ocr_input_unavailable") from exc
    if not raw or len(raw) > max_bytes:
        raise OcrFailure("OCR input exceeds the configured bound.", error_code="knowledge_ocr_input_too_large")
    if len(raw) < 24 or not raw.startswith(b"\x89PNG\r\n\x1a\n") or raw[12:16] != b"IHDR":
        raise OcrFailure("OCR input must be a PNG image.", error_code="knowledge_ocr_input_invalid")
    width, height = struct.unpack(">II", raw[16:24])
    if not width or not height or width * height > _limit(limits, "max_decoded_pixels", _DEFAULT_MAX_PIXELS):
        raise OcrFailure("OCR input exceeds the configured bound.", error_code="knowledge_ocr_input_too_large")
    return raw


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise OcrFailure(
            "OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")
    return value


def _validate_response_header(header: dict[str, Any], *, request_id: str, model_name: str, binary: bytes) -> None:
    outputs = header.get("outputs")
    if (
        header.get("id") != request_id
        or header.get("model_name") != model_name
        or not isinstance(outputs, list)
        or len(outputs) != 1
        or not isinstance(outputs[0], dict)
    ):
        raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")
    output = outputs[0]
    parameters = output.get("parameters")
    if (
        output.get("name") != _OUTPUT_NAME
        or output.get("datatype") != "BYTES"
        or output.get("shape") != [1]
        or not isinstance(parameters, dict)
        or parameters.get("binary_data_size") != len(binary)
        or parameters.get("content_type") != "application/xml"
        or parameters.get("schema_version") != "2024-07-15"
        or parameters.get("profile") != "page-xml-text-regions-v1"
        or parameters.get("coordinate_quantization") != "round-half-up-clamped"
    ):
        raise OcrFailure("OCR provider returned an invalid response.", error_code="knowledge_ocr_protocol_invalid")


def _parse_page(page_xml: bytes, *, limits: dict[str, int]) -> dict[str, object]:
    upper = page_xml[:16_384].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise OcrFailure("OCR provider returned an unsafe XML response.", error_code="knowledge_ocr_xml_invalid")
    try:
        root = element_tree.fromstring(page_xml)
    except element_tree.ParseError as exc:
        raise OcrFailure("OCR provider returned invalid PAGE XML.", error_code="knowledge_ocr_xml_invalid") from exc
    _validate_xml_bounds(root, limits=limits)
    q = lambda name: f"{{{_PAGE_NAMESPACE}}}{name}"
    if root.tag != q("PcGts"):
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    pages = root.findall(f"./{q('Page')}")
    if len(pages) != 1:
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    page = pages[0]
    try:
        width = int(page.attrib["imageWidth"])
        height = int(page.attrib["imageHeight"])
    except (KeyError, ValueError) as exc:
        raise OcrFailure(
            "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
        ) from exc
    if width < 1 or height < 1:
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    regions = page.findall(f"./{q('TextRegion')}")
    if len(regions) > _limit(limits, "max_regions", _DEFAULT_MAX_REGIONS):
        raise OcrFailure(
            "OCR provider response exceeds the configured bound.", error_code="knowledge_ocr_response_too_large"
        )
    refs = page.findall(f"./{q('ReadingOrder')}/{q('OrderedGroup')}/{q('RegionRefIndexed')}")
    if len(refs) != len(regions):
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    region_ids = [region.attrib.get("id") for region in regions]
    if any(not identifier for identifier in region_ids):
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    if [reference.attrib.get("regionRef") for reference in refs] != region_ids or [
        reference.attrib.get("index") for reference in refs
    ] != [str(index) for index in range(len(refs))]:
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    normalized_regions: list[dict[str, object]] = []
    for region in regions:
        if region.attrib.get("type") != "other":
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            )
        coords = region.find(f"./{q('Coords')}")
        text_equiv = region.find(f"./{q('TextEquiv')}")
        unicode_text = text_equiv.find(f"./{q('Unicode')}") if text_equiv is not None else None
        if (
            coords is None
            or text_equiv is None
            or text_equiv.attrib.get("index") != "1"
            or unicode_text is None
            or unicode_text.text is None
        ):
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            )
        try:
            confidence = float(text_equiv.attrib["conf"])
        except (KeyError, ValueError) as exc:
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            ) from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            )
        polygon = _parse_points(coords.attrib.get("points"), width=width, height=height, limits=limits)
        normalized_regions.append(
            {"id": region.attrib["id"], "text": unicode_text.text, "confidence": confidence, "polygon": polygon}
        )
    return {
        "protocol": "page-2024-07-15",
        "pages": [{"width": width, "height": height, "regions": normalized_regions}],
    }


def _validate_xml_bounds(root: element_tree.Element, *, limits: dict[str, int]) -> None:
    maximum_depth = _limit(limits, "max_xml_depth", _DEFAULT_MAX_XML_DEPTH)
    maximum_nodes = _limit(limits, "max_xml_nodes", _DEFAULT_MAX_XML_NODES)
    stack: list[tuple[element_tree.Element, int]] = [(root, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > maximum_nodes or depth > maximum_depth:
            raise OcrFailure(
                "OCR provider response exceeds the configured bound.", error_code="knowledge_ocr_response_too_large"
            )
        stack.extend((child, depth + 1) for child in node)


def _parse_points(value: str | None, *, width: int, height: int, limits: dict[str, int]) -> list[list[int]]:
    if not value:
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    tokens = value.split()
    if len(tokens) < 3 or len(tokens) > _limit(limits, "max_points", _DEFAULT_MAX_POINTS):
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    points: list[list[int]] = []
    for token in tokens:
        try:
            x_text, y_text = token.split(",", maxsplit=1)
            x, y = int(x_text), int(y_text)
        except ValueError as exc:
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            ) from exc
        if not 0 <= x <= width or not 0 <= y <= height:
            raise OcrFailure(
                "OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid"
            )
        points.append([x, y])
    if len({tuple(point) for point in points}) < 3:
        raise OcrFailure("OCR provider returned an incompatible PAGE profile.", error_code="knowledge_ocr_page_invalid")
    return points


def _limit(limits: dict[str, int], name: str, default: int) -> int:
    value = limits.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return default
    return min(value, default * 16)


__all__ = ["KServeV2OcrService"]
