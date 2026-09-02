"""Dependency-free structural validation for untrusted PNG/JPEG assets."""
from __future__ import annotations

import math
import struct
import zlib


MAX_IMAGE_WIDTH = 16_384
MAX_IMAGE_HEIGHT = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MAX_PNG_DECODE_BYTES = 128 * 1024 * 1024


class ImageValidationError(ValueError):
    """The byte sequence is not a bounded, structurally decodable image."""


def _validate_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_WIDTH
        or height > MAX_IMAGE_HEIGHT
    ):
        raise ImageValidationError("image dimensions exceed limits")
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageValidationError("image pixels exceed limit")


def _validate_png(data: bytes) -> tuple[str, str, int, int]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ImageValidationError("invalid PNG signature")
    offset = 8
    width = height = bit_depth = color_type = 0
    saw_ihdr = saw_idat = saw_iend = False
    compressed = bytearray()
    while offset < len(data):
        if len(data) - offset < 12:
            raise ImageValidationError("truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ImageValidationError("truncated PNG chunk")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise ImageValidationError("PNG chunk CRC mismatch")
        if not saw_ihdr:
            if kind != b"IHDR" or length != 13:
                raise ImageValidationError("PNG IHDR must be first")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filtering,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            _validate_dimensions(width, height)
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if bit_depth not in valid_depths.get(color_type, set()):
                raise ImageValidationError("invalid PNG color mode")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise ImageValidationError("unsupported PNG encoding")
            saw_ihdr = True
        elif kind == b"IHDR":
            raise ImageValidationError("duplicate PNG IHDR")
        if kind == b"IDAT":
            if not payload:
                raise ImageValidationError("empty PNG IDAT")
            saw_idat = True
            compressed.extend(payload)
        elif kind == b"IEND":
            if length != 0:
                raise ImageValidationError("invalid PNG IEND")
            saw_iend = True
            offset = end
            break
        offset = end
    if not (saw_ihdr and saw_idat and saw_iend) or offset != len(data):
        raise ImageValidationError("incomplete PNG structure")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = math.ceil(width * channels * bit_depth / 8)
    expected_size = (row_bytes + 1) * height
    if expected_size > MAX_PNG_DECODE_BYTES:
        raise ImageValidationError("PNG decoded size exceeds limit")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(compressed), expected_size + 1)
    except zlib.error as exc:
        raise ImageValidationError("PNG IDAT is not decodable") from exc
    if len(raw) > expected_size:
        raise ImageValidationError("PNG decoded size exceeds IHDR")
    if (
        not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or len(raw) != expected_size
    ):
        raise ImageValidationError("PNG decoded size does not match IHDR")
    stride = row_bytes + 1
    if any(raw[row * stride] > 4 for row in range(height)):
        raise ImageValidationError("invalid PNG row filter")
    return "image/png", ".png", width, height


_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _validate_jpeg(data: bytes) -> tuple[str, str, int, int]:
    if len(data) < 12 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ImageValidationError("invalid JPEG boundaries")
    offset = 2
    width = height = 0
    saw_sof = saw_sos = saw_eoi = False
    while offset < len(data):
        if data[offset] != 0xFF:
            if saw_sos:
                offset += 1
                continue
            raise ImageValidationError("invalid JPEG marker stream")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            raise ImageValidationError("truncated JPEG marker")
        marker = data[offset]
        offset += 1
        if marker == 0x00:
            if not saw_sos:
                raise ImageValidationError("unexpected JPEG stuffed byte")
            continue
        if marker == 0xD9:
            saw_eoi = True
            break
        if marker in {0xD8, 0x01, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(data):
            raise ImageValidationError("truncated JPEG segment")
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data):
            raise ImageValidationError("invalid JPEG segment length")
        payload = data[offset + 2 : offset + length]
        if marker in _JPEG_SOF_MARKERS:
            if len(payload) < 6:
                raise ImageValidationError("invalid JPEG SOF")
            height, width = struct.unpack_from(">HH", payload, 1)
            _validate_dimensions(width, height)
            saw_sof = True
        elif marker == 0xDA:
            saw_sos = True
        offset += length
    if not (saw_sof and saw_sos and saw_eoi):
        raise ImageValidationError("incomplete JPEG structure")
    return "image/jpeg", ".jpg", width, height


def validate_image_bytes(data: bytes) -> tuple[str, str, int, int]:
    """Return ``(media_type, extension, width, height)`` or raise safely."""
    if not isinstance(data, bytes):
        raise ImageValidationError("image payload must be bytes")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _validate_png(data)
    if data.startswith(b"\xff\xd8"):
        return _validate_jpeg(data)
    raise ImageValidationError("image is not PNG or JPEG")
