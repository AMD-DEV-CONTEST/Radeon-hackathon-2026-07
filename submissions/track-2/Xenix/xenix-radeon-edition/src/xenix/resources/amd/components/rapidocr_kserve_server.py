"""Authenticated, loopback-only KServe V2 PNG-to-PAGE RapidOCR server.

This is a standalone target-runtime asset.  It deliberately imports only the
standard library until ``main`` initializes the certified RapidOCR Torch/ROCm
runtime, so packaging or reading the desktop-side AMD slice never imports an
accelerator dependency.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import ipaddress
import json
import math
import os
import re
import secrets
import signal
import socket
import stat
import struct
import threading
import xml.etree.ElementTree as element_tree
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit


MODEL_NAME = "rapidocr-ppocrv6"
MODEL_VERSION = "rapidocr-3.9.2-rocm721"
INPUT_NAME = "image"
OUTPUT_NAME = "page_xml"
PAGE_NAMESPACE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2024-07-15"
PAGE_SCHEMA_VERSION = "2024-07-15"
PROFILE_VERSION = "page-xml-text-regions-v1"

_TOKEN_FILE_ENVIRONMENT: Final = "XENIX_RUNTIME_BEARER_TOKEN_FILE"
_TOKEN_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{24,512}\Z")
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_PRIVATE_FILE_MODE: Final = 0o600
_MAX_TOKEN_FILE_BYTES: Final = 514

MAX_JSON_HEADER_BYTES = 64 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_DIMENSION = 20_000
MAX_DECODED_PIXELS = 100_000_000
MAX_DECODED_BYTES = 256 * 1024 * 1024
MAX_PNG_CHUNKS = 512
MAX_PAGE_XML_BYTES = 48 * 1024 * 1024
MAX_REGIONS = 20_000
MAX_POLYGON_POINTS = 64
MAX_REGION_TEXT_BYTES = 64 * 1024
MAX_PAGE_TEXT_BYTES = 16 * 1024 * 1024

DEFAULT_REQUEST_DEADLINE_SECONDS = 300.0
MAX_REQUEST_DEADLINE_SECONDS = 300.0
DEFAULT_SOCKET_TIMEOUT_SECONDS = 15.0
MAX_SOCKET_TIMEOUT_SECONDS = 60.0

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PNG_BIT_DEPTHS: Final = {
    0: frozenset((1, 2, 4, 8, 16)),
    2: frozenset((8, 16)),
    3: frozenset((1, 2, 4, 8)),
    4: frozenset((8, 16)),
    6: frozenset((8, 16)),
}
_PNG_CHANNELS: Final = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_FORBIDDEN_BACKEND_MODULES: Final = ("onnxruntime", "paddle", "openvino", "tensorrt")


class ServerConfigurationError(RuntimeError):
    """The fixed target-runtime launch contract is not satisfied."""


class RequestError(RuntimeError):
    """A bounded client request failure represented by one HTTP error shape."""

    status = HTTPStatus.BAD_REQUEST
    code = "request_invalid"


class AuthenticationError(RequestError):
    status = HTTPStatus.UNAUTHORIZED
    code = "authentication_required"


class UnknownEndpointError(RequestError):
    status = HTTPStatus.NOT_FOUND
    code = "endpoint_not_found"


class UnsupportedContentTypeError(RequestError):
    status = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    code = "content_type_unsupported"


class RequestTooLargeError(RequestError):
    status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    code = "request_too_large"


class RequestIoTimeoutError(RequestError):
    status = HTTPStatus.REQUEST_TIMEOUT
    code = "request_io_timeout"


class RequestDeadlineExceeded(RequestError):
    status = HTTPStatus.GATEWAY_TIMEOUT
    code = "request_deadline_exceeded"


class BackendUnavailableError(RequestError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "backend_unavailable"


def _require_target_platform() -> None:
    if (
        os.name != "posix"
        or not hasattr(signal, "setitimer")
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "geteuid")
    ):
        raise ServerConfigurationError("The RapidOCR target requires POSIX protected handoff support.")


def _read_runtime_bearer_token() -> str:
    """Read exactly one protected token file named by the launch environment."""

    raw_path = os.environ.get(_TOKEN_FILE_ENVIRONMENT)
    if (
        not raw_path
        or len(raw_path) > 4_096
        or "\x00" in raw_path
        or "\r" in raw_path
        or "\n" in raw_path
    ):
        raise ServerConfigurationError("Runtime bearer-token handoff is unavailable.")
    try:
        path = Path(raw_path)
    except (TypeError, ValueError) as exc:
        raise ServerConfigurationError("Runtime bearer-token handoff is invalid.") from exc
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        directory_stat = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.geteuid()
            or stat.S_IMODE(directory_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
        ):
            raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
        before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if not _is_private_token_file(before):
            raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        after = os.fstat(file_fd)
        if not _is_private_token_file(after) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
        payload = os.read(file_fd, _MAX_TOKEN_FILE_BYTES)
        if os.read(file_fd, 1):
            raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
    except ServerConfigurationError:
        raise
    except (OSError, ValueError) as exc:
        raise ServerConfigurationError("Runtime bearer-token handoff is unavailable.") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)

    if len(payload) < 25 or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
    try:
        token = payload[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ServerConfigurationError("Runtime bearer-token handoff is invalid.") from exc
    if not _TOKEN_PATTERN.fullmatch(token):
        raise ServerConfigurationError("Runtime bearer-token handoff is invalid.")
    return token


def _is_private_token_file(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == _PRIVATE_FILE_MODE
    )


def _validated_model_root(value: Path) -> Path:
    try:
        root = Path(value)
    except (TypeError, ValueError) as exc:
        raise ServerConfigurationError("RapidOCR model root is invalid.") from exc
    if not root.is_absolute() or not root.is_dir():
        raise ServerConfigurationError("RapidOCR model root is unavailable.")
    required = (
        "PP-OCRv6_det_small.pth",
        "ch_ptocr_mobile_v2.0_cls_mobile.pth",
        "PP-OCRv6_rec_small.pth",
        "ppocrv6_dict.txt",
        "FZYTK.TTF",
    )
    if any(not (root / name).is_file() for name in required):
        raise ServerConfigurationError("RapidOCR model assets are unavailable.")
    return root


def _parse_loopback_host(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "%" in value:
        raise argparse.ArgumentTypeError("host must be a numeric loopback address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("host must be a numeric loopback address") from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("host must be a numeric loopback address")
    return str(address)


def _parse_port(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise argparse.ArgumentTypeError("port must be an integer")
    port = int(value)
    if not 1_024 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def _parse_request_deadline(value: str) -> float:
    return _parse_bounded_seconds(
        value,
        minimum=1.0,
        maximum=MAX_REQUEST_DEADLINE_SECONDS,
        label="request deadline",
    )


def _parse_socket_timeout(value: str) -> float:
    return _parse_bounded_seconds(
        value,
        minimum=1.0,
        maximum=MAX_SOCKET_TIMEOUT_SECONDS,
        label="socket timeout",
    )


def _parse_bounded_seconds(value: str, *, minimum: float, maximum: float, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label} is outside the supported bound")
    return parsed


def _reject_fallback_backends() -> None:
    for module_name in _FORBIDDEN_BACKEND_MODULES:
        try:
            present = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            raise ServerConfigurationError("RapidOCR backend inspection failed.") from exc
        if present:
            raise ServerConfigurationError("RapidOCR fallback backend is present in the target runtime.")


def _load_target_runtime() -> tuple[Any, Any, Any]:
    """Load only the certified Torch/ROCm implementation, never a fallback."""

    _reject_fallback_backends()
    try:
        rapidocr_version = importlib.metadata.version("rapidocr")
        import torch
        from rapidocr import EngineType, RapidOCR
    except (ImportError, ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as exc:
        raise ServerConfigurationError("RapidOCR Torch/ROCm runtime is unavailable.") from exc
    if rapidocr_version != "3.9.2":
        raise ServerConfigurationError("RapidOCR runtime version is not certified.")
    if not getattr(torch.version, "hip", None) or not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise ServerConfigurationError("ROCm device zero is unavailable.")
    return torch, EngineType, RapidOCR


class RapidOcrBackend:
    """One fully-attested RapidOCR Torch/ROCm backend with no fallback branch."""

    def __init__(self, model_root: Path) -> None:
        torch, engine_type, rapid_ocr = _load_target_runtime()
        self._torch = torch
        self._engine_type = engine_type
        self._engine = rapid_ocr(
            params={
                "Global.model_root_dir": str(model_root),
                "Global.font_path": str(model_root / "FZYTK.TTF"),
                "EngineConfig.torch.use_cuda": True,
                "EngineConfig.torch.cuda_ep_cfg.device_id": 0,
                "Det.engine_type": engine_type.TORCH,
                "Det.model_path": str(model_root / "PP-OCRv6_det_small.pth"),
                "Cls.engine_type": engine_type.TORCH,
                "Cls.model_path": str(model_root / "ch_ptocr_mobile_v2.0_cls_mobile.pth"),
                "Rec.engine_type": engine_type.TORCH,
                "Rec.model_path": str(model_root / "PP-OCRv6_rec_small.pth"),
                "Rec.rec_keys_path": str(model_root / "ppocrv6_dict.txt"),
            }
        )
        self._stage_predictors = self._attest_stage_configuration()

    def infer(self, image: bytes, *, width: int, height: int) -> bytes:
        observed_devices: dict[str, list[str]] = {name: [] for name, _predictor in self._stage_predictors}
        handles: list[Any] = []
        try:
            for stage, predictor in self._stage_predictors:
                handles.append(
                    predictor.register_forward_pre_hook(
                        self._input_device_hook(stage, observed_devices),
                    )
                )
            result = self._engine(image)
            self._torch.cuda.synchronize(0)
        except RequestDeadlineExceeded:
            raise
        except Exception as exc:
            raise BackendUnavailableError() from exc
        finally:
            for handle in handles:
                try:
                    handle.remove()
                except Exception:
                    pass
        if any(not devices or any(not device.startswith("cuda") for device in devices) for devices in observed_devices.values()):
            raise BackendUnavailableError()
        regions = self._normalize_result(result, width=width, height=height)
        return _render_page(width, height, regions)

    def _attest_stage_configuration(self) -> tuple[tuple[str, Any], ...]:
        sessions = (
            ("det", getattr(self._engine, "text_det", None)),
            ("cls", getattr(self._engine, "text_cls", None)),
            ("rec", getattr(self._engine, "text_rec", None)),
        )
        predictors: list[tuple[str, Any]] = []
        for stage, owner in sessions:
            session = getattr(owner, "session", None)
            if getattr(getattr(session, "device", None), "type", None) != "cuda":
                raise ServerConfigurationError("RapidOCR stage did not bind to ROCm.")
            predictor = getattr(session, "predictor", None)
            parameters = getattr(predictor, "parameters", None)
            try:
                parameter = next(parameters())
            except (AttributeError, StopIteration, TypeError) as exc:
                raise ServerConfigurationError("RapidOCR stage cannot attest Torch parameters.") from exc
            if getattr(getattr(parameter, "device", None), "type", None) != "cuda":
                raise ServerConfigurationError("RapidOCR stage parameters did not bind to ROCm.")
            configured = getattr(getattr(self._engine, "cfg", None), stage.capitalize(), None)
            if getattr(configured, "engine_type", None) is not self._engine_type.TORCH:
                raise ServerConfigurationError("RapidOCR stage engine is not Torch.")
            predictors.append((stage, predictor))
        return tuple(predictors)

    def _input_device_hook(self, stage: str, observed: dict[str, list[str]]):
        def record(_module: Any, inputs: tuple[Any, ...]) -> None:
            tensors = tuple(_iter_tensors(inputs, self._torch))
            if not tensors:
                raise BackendUnavailableError()
            devices = [str(tensor.device) for tensor in tensors]
            if any(getattr(tensor.device, "type", None) != "cuda" for tensor in tensors):
                raise BackendUnavailableError()
            observed[stage].extend(devices)

        return record

    @staticmethod
    def _normalize_result(
        result: Any,
        *,
        width: int,
        height: int,
    ) -> tuple[tuple[tuple[tuple[int, int], ...], str, float], ...]:
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or texts is None or scores is None:
            if boxes is None and texts is None and scores is None:
                return ()
            raise BackendUnavailableError()

        regions: list[tuple[tuple[tuple[int, int], ...], str, float]] = []
        total_text_bytes = 0
        try:
            triples = zip(boxes, texts, scores, strict=True)
            for box, text, confidence in triples:
                normalized_text = _safe_xml_text(str(text).strip())
                if not normalized_text:
                    continue
                encoded_text = normalized_text.encode("utf-8")
                if len(encoded_text) > MAX_REGION_TEXT_BYTES:
                    raise BackendUnavailableError()
                total_text_bytes += len(encoded_text)
                if total_text_bytes > MAX_PAGE_TEXT_BYTES or len(regions) >= MAX_REGIONS:
                    raise BackendUnavailableError()
                polygon = _normalize_polygon(box, width=width, height=height)
                normalized_confidence = float(confidence)
                if not math.isfinite(normalized_confidence) or not 0.0 <= normalized_confidence <= 1.0:
                    raise BackendUnavailableError()
                regions.append((polygon, normalized_text, normalized_confidence))
        except BackendUnavailableError:
            raise
        except (TypeError, ValueError, UnicodeError) as exc:
            raise BackendUnavailableError() from exc
        return tuple(regions)


def _iter_tensors(value: Any, torch: Any) -> Iterator[Any]:
    if isinstance(value, torch.Tensor):
        yield value
    elif isinstance(value, tuple | list):
        for item in value:
            yield from _iter_tensors(item, torch)


def _normalize_polygon(value: Any, *, width: int, height: int) -> tuple[tuple[int, int], ...]:
    try:
        points = tuple(value)
    except TypeError as exc:
        raise BackendUnavailableError() from exc
    if not 3 <= len(points) <= MAX_POLYGON_POINTS:
        raise BackendUnavailableError()
    polygon: list[tuple[int, int]] = []
    try:
        for point in points:
            x = min(width, max(0, _round_pixel(float(point[0]))))
            y = min(height, max(0, _round_pixel(float(point[1]))))
            polygon.append((x, y))
    except (IndexError, TypeError, ValueError) as exc:
        raise BackendUnavailableError() from exc
    normalized = tuple(polygon)
    if len(set(normalized)) < 3:
        raise BackendUnavailableError()
    return normalized


def _round_pixel(value: float) -> int:
    if not math.isfinite(value):
        raise BackendUnavailableError()
    return math.floor(value + 0.5)


def _safe_xml_text(value: str) -> str:
    return "".join(character for character in value if _is_xml_character(character)).strip()


def _is_xml_character(character: str) -> bool:
    value = ord(character)
    return value in {0x09, 0x0A, 0x0D} or 0x20 <= value <= 0xD7FF or 0xE000 <= value <= 0xFFFD or 0x10000 <= value <= 0x10FFFF


def _render_page(
    width: int,
    height: int,
    regions: tuple[tuple[tuple[tuple[int, int], ...], str, float], ...],
) -> bytes:
    element_tree.register_namespace("", PAGE_NAMESPACE)
    qualified = lambda name: f"{{{PAGE_NAMESPACE}}}{name}"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    root = element_tree.Element(qualified("PcGts"), {"pcGtsId": "pcgts_1"})
    metadata = element_tree.SubElement(root, qualified("Metadata"))
    element_tree.SubElement(metadata, qualified("Creator")).text = "Xenix RapidOCR Torch ROCm"
    element_tree.SubElement(metadata, qualified("Created")).text = now
    element_tree.SubElement(metadata, qualified("LastChange")).text = now
    page = element_tree.SubElement(
        root,
        qualified("Page"),
        {
            "imageFilename": "request.png",
            "imageWidth": str(width),
            "imageHeight": str(height),
        },
    )
    group = None
    if regions:
        reading_order = element_tree.SubElement(page, qualified("ReadingOrder"))
        group = element_tree.SubElement(reading_order, qualified("OrderedGroup"), {"id": "reading_order_1"})
    for index, (polygon, text, confidence) in enumerate(regions):
        region_id = f"region_{index + 1}"
        assert group is not None
        element_tree.SubElement(
            group,
            qualified("RegionRefIndexed"),
            {"index": str(index), "regionRef": region_id},
        )
        text_region = element_tree.SubElement(page, qualified("TextRegion"), {"id": region_id, "type": "other"})
        element_tree.SubElement(
            text_region,
            qualified("Coords"),
            {"points": " ".join(f"{x},{y}" for x, y in polygon)},
        )
        text_equiv = element_tree.SubElement(
            text_region,
            qualified("TextEquiv"),
            {"index": "1", "conf": f"{confidence:.6f}".rstrip("0").rstrip(".")},
        )
        element_tree.SubElement(text_equiv, qualified("Unicode")).text = text
    element_tree.indent(root, space="  ")
    try:
        rendered = element_tree.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    except (TypeError, ValueError, UnicodeError) as exc:
        raise BackendUnavailableError() from exc
    if not rendered or len(rendered) > MAX_PAGE_XML_BYTES:
        raise BackendUnavailableError()
    return rendered


def _validate_png(image: bytes) -> tuple[int, int]:
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise RequestTooLargeError()
    if len(image) < 33 or not image.startswith(_PNG_SIGNATURE):
        raise RequestError()

    offset = len(_PNG_SIGNATURE)
    chunk_count = 0
    width: int | None = None
    height: int | None = None
    color_type: int | None = None
    bit_depth: int | None = None
    seen_palette = False
    seen_idat = False
    idat_closed = False
    idat_chunks: list[bytes] = []
    while offset < len(image):
        if len(image) - offset < 12:
            raise RequestError()
        chunk_count += 1
        if chunk_count > MAX_PNG_CHUNKS:
            raise RequestError()
        chunk_length = struct.unpack(">I", image[offset : offset + 4])[0]
        chunk_type = image[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        crc_end = data_end + 4
        if data_end < data_start or crc_end > len(image) or not _is_png_chunk_name(chunk_type):
            raise RequestError()
        chunk = image[data_start:data_end]
        expected_crc = struct.unpack(">I", image[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise RequestError()
        offset = crc_end

        if chunk_type == b"IHDR":
            if width is not None or chunk_count != 1 or chunk_length != 13:
                raise RequestError()
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if (
                not 10 <= width <= MAX_IMAGE_DIMENSION
                or not 10 <= height <= MAX_IMAGE_DIMENSION
                or width * height > MAX_DECODED_PIXELS
                or color_type not in _PNG_BIT_DEPTHS
                or bit_depth not in _PNG_BIT_DEPTHS[color_type]
                or compression != 0
                or filter_method != 0
                or interlace not in {0, 1}
                or _estimated_png_bytes(width, height, color_type, bit_depth) > MAX_DECODED_BYTES
            ):
                raise RequestTooLargeError()
        elif chunk_type == b"PLTE":
            if width is None or seen_idat or seen_palette or color_type in {0, 4} or chunk_length == 0 or chunk_length > 768 or chunk_length % 3:
                raise RequestError()
            seen_palette = True
        elif chunk_type == b"IDAT":
            if width is None or idat_closed:
                raise RequestError()
            seen_idat = True
            idat_chunks.append(chunk)
        elif chunk_type == b"IEND":
            if width is None or not seen_idat or chunk_length != 0 or offset != len(image):
                raise RequestError()
            if color_type == 3 and not seen_palette:
                raise RequestError()
            _inflate_png(idat_chunks)
            assert width is not None and height is not None
            return width, height
        else:
            if seen_idat:
                idat_closed = True
            if chunk_type in {b"acTL", b"fcTL", b"fdAT"}:
                raise RequestError()
            if _is_critical_png_chunk(chunk_type):
                raise RequestError()
    raise RequestError()


def _is_png_chunk_name(value: bytes) -> bool:
    return len(value) == 4 and all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in value)


def _is_critical_png_chunk(value: bytes) -> bool:
    return bool(value and 65 <= value[0] <= 90)


def _estimated_png_bytes(width: int, height: int, color_type: int, bit_depth: int) -> int:
    bits_per_row = width * _PNG_CHANNELS[color_type] * bit_depth
    return ((bits_per_row + 7) // 8 + 8) * height


def _inflate_png(chunks: list[bytes]) -> None:
    inflater = zlib.decompressobj()
    decoded_bytes = 0
    try:
        for chunk in chunks:
            if inflater.eof:
                raise RequestError()
            pending = chunk
            while pending:
                remaining = MAX_DECODED_BYTES - decoded_bytes
                decoded = inflater.decompress(pending, remaining + 1)
                decoded_bytes += len(decoded)
                if decoded_bytes > MAX_DECODED_BYTES:
                    raise RequestTooLargeError()
                pending = inflater.unconsumed_tail
                if inflater.eof and (pending or inflater.unused_data):
                    raise RequestError()
                if pending and not decoded:
                    raise RequestError()
        remaining = MAX_DECODED_BYTES - decoded_bytes
        tail = inflater.flush(remaining + 1)
    except RequestError:
        raise
    except zlib.error as exc:
        raise RequestError() from exc
    decoded_bytes += len(tail)
    if decoded_bytes <= 0 or decoded_bytes > MAX_DECODED_BYTES or not inflater.eof or inflater.unused_data:
        raise RequestError()


@contextmanager
def _request_deadline(seconds: float) -> Iterator[None]:
    """Interrupt the single target request and retire the process after a timeout."""

    if threading.current_thread() is not threading.main_thread():
        raise ServerConfigurationError("RapidOCR request handling must remain single-threaded.")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)
    if previous_timer != (0.0, 0.0):
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        raise ServerConfigurationError("RapidOCR request deadline already has a timer owner.")

    def expire(_signal_number: int, _frame: Any) -> None:
        raise RequestDeadlineExceeded()

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


class OcrHttpServer(HTTPServer):
    """One serial, loopback-only server; timeout retirement avoids reused GPU state."""

    allow_reuse_address = False
    request_queue_size = 1

    def __init__(
        self,
        host: str,
        port: int,
        *,
        backend: RapidOcrBackend,
        bearer_token: str,
        request_deadline_seconds: float,
        socket_timeout_seconds: float,
    ) -> None:
        self.address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.backend = backend
        self._bearer_token = bearer_token
        self.request_deadline_seconds = request_deadline_seconds
        self.socket_timeout_seconds = socket_timeout_seconds
        self._retiring_after_deadline = False
        self._retirement_lock = threading.Lock()
        super().__init__((host, port), OcrHandler, bind_and_activate=False)
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        self.server_bind()
        self.server_activate()
        bound_host = str(self.server_address[0])
        if not ipaddress.ip_address(bound_host).is_loopback:
            self.server_close()
            raise ServerConfigurationError("RapidOCR server did not bind to loopback.")

    @property
    def retiring_after_deadline(self) -> bool:
        with self._retirement_lock:
            return self._retiring_after_deadline

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        request, client_address = super().get_request()
        request.settimeout(self.socket_timeout_seconds)
        return request, client_address

    def verify_request(self, request: socket.socket, client_address: tuple[str, int]) -> bool:
        _ = request
        try:
            return ipaddress.ip_address(client_address[0]).is_loopback
        except ValueError:
            return False

    def authorization_matches(self, value: str) -> bool:
        return secrets.compare_digest(value, self._bearer_token)

    def retire_after_deadline(self) -> None:
        with self._retirement_lock:
            if self._retiring_after_deadline:
                return
            self._retiring_after_deadline = True
        threading.Thread(target=self.shutdown, name="rapidocr-timeout-retire", daemon=True).start()


class OcrHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "XenixRapidOcrKServe/1"
    sys_version = ""

    def do_GET(self) -> None:
        try:
            server = self._typed_server()
            self._require_authorization(server)
            path = self._request_path()
            if path == "/v2":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "name": "xenix-rapidocr-rocm",
                        "version": MODEL_VERSION,
                        "extensions": ["binary_tensor_data"],
                    },
                )
                return
            if path == "/v2/health/live":
                self._send_empty(HTTPStatus.SERVICE_UNAVAILABLE if server.retiring_after_deadline else HTTPStatus.OK)
                return
            if path == "/v2/health/ready":
                self._send_empty(HTTPStatus.SERVICE_UNAVAILABLE if server.retiring_after_deadline else HTTPStatus.OK)
                return
            if path == f"/v2/models/{MODEL_NAME}":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "name": MODEL_NAME,
                        "versions": [MODEL_VERSION],
                        "platform": "pytorch_rocm",
                        "inputs": [{"name": INPUT_NAME, "datatype": "BYTES", "shape": [1]}],
                        "outputs": [{"name": OUTPUT_NAME, "datatype": "BYTES", "shape": [1]}],
                    },
                )
                return
            if path == f"/v2/models/{MODEL_NAME}/ready":
                self._send_empty(HTTPStatus.SERVICE_UNAVAILABLE if server.retiring_after_deadline else HTTPStatus.OK)
                return
            raise UnknownEndpointError()
        except RequestError as exc:
            self._send_error(exc)

    def do_POST(self) -> None:
        server: OcrHttpServer | None = None
        try:
            server = self._typed_server()
            self._require_authorization(server)
            if self._request_path() != f"/v2/models/{MODEL_NAME}/infer":
                raise UnknownEndpointError()
            if server.retiring_after_deadline:
                raise BackendUnavailableError()
            with _request_deadline(server.request_deadline_seconds):
                header, image, width, height = self._read_inference_request()
                page_xml = server.backend.infer(image, width=width, height=height)
            self._send_inference_response(header, page_xml)
        except RequestDeadlineExceeded as exc:
            if server is not None:
                server.retire_after_deadline()
            self._send_error(exc)
        except (socket.timeout, TimeoutError):
            self._send_error(RequestIoTimeoutError())
        except RequestError as exc:
            self._send_error(exc)

    def do_HEAD(self) -> None:
        try:
            server = self._typed_server()
            self._require_authorization(server)
            raise UnknownEndpointError()
        except RequestError as exc:
            self._send_error(exc)

    def _typed_server(self) -> OcrHttpServer:
        server = self.server
        if not isinstance(server, OcrHttpServer):
            raise BackendUnavailableError()
        return server

    def _require_authorization(self, server: OcrHttpServer) -> None:
        values = self.headers.get_all("Authorization")
        if values is None or len(values) != 1:
            raise AuthenticationError()
        value = values[0]
        if not value.startswith("Bearer ") or len(value) > 520:
            raise AuthenticationError()
        if not server.authorization_matches(value[7:]):
            raise AuthenticationError()

    def _request_path(self) -> str:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            raise UnknownEndpointError()
        return parsed.path.rstrip("/") or "/"

    def _read_inference_request(self) -> tuple[dict[str, Any], bytes, int, int]:
        if self.headers.get_content_type() != "application/octet-stream":
            raise UnsupportedContentTypeError()
        if self.headers.get_all("Transfer-Encoding") is not None or self.headers.get_all("Expect") is not None:
            raise RequestError()
        total_length = self._integer_header("Content-Length")
        header_length = self._integer_header("Inference-Header-Content-Length")
        if not 1 <= header_length <= MAX_JSON_HEADER_BYTES or total_length <= header_length:
            raise RequestError()
        if total_length > MAX_JSON_HEADER_BYTES + MAX_IMAGE_BYTES + 4:
            raise RequestTooLargeError()
        body = self._read_exact(total_length)
        try:
            header = json.loads(
                body[:header_length].decode("utf-8"),
                parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise RequestError() from exc
        if not isinstance(header, dict):
            raise RequestError()
        self._validate_request_id(header)
        binary = body[header_length:]
        image = self._unpack_image_tensor(header, binary)
        self._validate_requested_output(header)
        width, height = _validate_png(image)
        return header, image, width, height

    def _integer_header(self, name: str) -> int:
        values = self.headers.get_all(name)
        if values is None or len(values) != 1:
            raise RequestError()
        value = values[0]
        if not value or not value.isascii() or not value.isdecimal():
            raise RequestError()
        try:
            return int(value)
        except ValueError as exc:
            raise RequestError() from exc

    def _read_exact(self, length: int) -> bytes:
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError) as exc:
            raise RequestIoTimeoutError() from exc
        if len(body) != length:
            raise RequestError()
        return body

    @staticmethod
    def _validate_request_id(header: dict[str, Any]) -> None:
        request_id = header.get("id")
        if request_id is not None and (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 160
            or not request_id.isascii()
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for character in request_id)
        ):
            raise RequestError()

    @staticmethod
    def _unpack_image_tensor(header: dict[str, Any], binary: bytes) -> bytes:
        inputs = header.get("inputs")
        if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
            raise RequestError()
        tensor = inputs[0]
        if (
            tensor.get("name") != INPUT_NAME
            or tensor.get("datatype") != "BYTES"
            or tensor.get("shape") != [1]
            or "data" in tensor
        ):
            raise RequestError()
        parameters = tensor.get("parameters")
        if (
            not isinstance(parameters, dict)
            or parameters.get("content_type") != "image/png"
            or not isinstance(parameters.get("binary_data_size"), int)
            or isinstance(parameters.get("binary_data_size"), bool)
            or parameters["binary_data_size"] != len(binary)
            or len(binary) < 4
        ):
            raise RequestError()
        image_size = struct.unpack("<I", binary[:4])[0]
        image = binary[4:]
        if image_size != len(image):
            raise RequestError()
        return image

    @staticmethod
    def _validate_requested_output(header: dict[str, Any]) -> None:
        outputs = header.get("outputs")
        if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
            raise RequestError()
        output = outputs[0]
        parameters = output.get("parameters")
        if output.get("name") != OUTPUT_NAME or not isinstance(parameters, dict) or parameters.get("binary_data") is not True:
            raise RequestError()
        if "datatype" in output and output["datatype"] != "BYTES":
            raise RequestError()
        if "shape" in output and output["shape"] != [1]:
            raise RequestError()

    def _send_inference_response(self, request_header: dict[str, Any], page_xml: bytes) -> None:
        if not page_xml or len(page_xml) > MAX_PAGE_XML_BYTES:
            raise BackendUnavailableError()
        binary = struct.pack("<I", len(page_xml)) + page_xml
        response: dict[str, Any] = {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "outputs": [
                {
                    "name": OUTPUT_NAME,
                    "shape": [1],
                    "datatype": "BYTES",
                    "parameters": {
                        "binary_data_size": len(binary),
                        "content_type": "application/xml",
                        "schema_version": PAGE_SCHEMA_VERSION,
                        "profile": PROFILE_VERSION,
                        "coordinate_quantization": "round-half-up-clamped",
                    },
                }
            ],
        }
        request_id = request_header.get("id")
        if request_id is not None:
            response["id"] = request_id
        self._send_binary_response(response, binary)

    def _send_binary_response(self, header: dict[str, Any], binary: bytes) -> None:
        header_bytes = _json_bytes(header)
        body = header_bytes + binary
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Inference-Header-Content-Length", str(len(header_bytes)))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, status: HTTPStatus, value: object) -> None:
        body = _json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, error: RequestError) -> None:
        self.close_connection = True
        try:
            body = _json_bytes({"error": error.code})
            self.send_response(error.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if isinstance(error, AuthenticationError):
                self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
            return

    def log_message(self, message_format: str, *args: object) -> None:
        _ = message_format, args


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=_parse_loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=_parse_port, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument(
        "--request-deadline-seconds",
        type=_parse_request_deadline,
        default=DEFAULT_REQUEST_DEADLINE_SECONDS,
    )
    parser.add_argument(
        "--socket-timeout-seconds",
        type=_parse_socket_timeout,
        default=DEFAULT_SOCKET_TIMEOUT_SECONDS,
    )
    args = parser.parse_args()

    server: OcrHttpServer | None = None
    try:
        _require_target_platform()
        bearer_token = _read_runtime_bearer_token()
        backend = RapidOcrBackend(_validated_model_root(args.model_root))
        server = OcrHttpServer(
            args.host,
            args.port,
            backend=backend,
            bearer_token=bearer_token,
            request_deadline_seconds=args.request_deadline_seconds,
            socket_timeout_seconds=args.socket_timeout_seconds,
        )
    except (OSError, ServerConfigurationError):
        return 2

    try:
        print("READY", flush=True)
        server.serve_forever(poll_interval=0.25)
        return 1 if server.retiring_after_deadline else 0
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
