"""Read the immutable RapidOCR target-server asset on explicit demand.

The AMD deployment controller transfers this script to an already acquired
target runtime.  Keeping the target program in bundled resources means the
desktop never imports RapidOCR, Torch, or any ROCm library merely to inspect a
deployment recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xenix.resources import package_resource_path


RAPIDOCR_SERVER_FILENAME = "rapidocr_kserve_server.py"
_RAPIDOCR_SERVER_RESOURCE = ("amd", "components", RAPIDOCR_SERVER_FILENAME)
_MAX_SERVER_SOURCE_BYTES = 2 * 1024 * 1024


class RapidOcrServerAssetError(RuntimeError):
    """The packaged target-side RapidOCR server cannot be read safely."""


@dataclass(frozen=True, slots=True)
class RapidOcrServerAsset:
    """One exact target-side file, without source contents in representations."""

    filename: str
    source: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.filename != RAPIDOCR_SERVER_FILENAME:
            raise RapidOcrServerAssetError("RapidOCR target asset filename is invalid.")
        if not isinstance(self.source, bytes) or not self.source or len(self.source) > _MAX_SERVER_SOURCE_BYTES:
            raise RapidOcrServerAssetError("RapidOCR target asset source is invalid.")

    def __repr__(self) -> str:
        return f"RapidOcrServerAsset(filename={self.filename!r}, source=<redacted>)"


def read_rapidocr_server_source() -> bytes:
    """Return the bundled standalone server bytes without target-side imports.

    This is intentionally a read-only, explicit resource operation.  It does
    not create target paths, start a process, inspect a GPU, or touch a token.
    """

    try:
        source = package_resource_path(*_RAPIDOCR_SERVER_RESOURCE).read_bytes()
    except OSError as exc:
        raise RapidOcrServerAssetError("RapidOCR target asset is unavailable.") from exc
    return RapidOcrServerAsset(RAPIDOCR_SERVER_FILENAME, source).source


def rapidocr_server_asset() -> RapidOcrServerAsset:
    """Return the fixed file identity and bytes placement must transfer."""

    return RapidOcrServerAsset(RAPIDOCR_SERVER_FILENAME, read_rapidocr_server_source())


__all__ = [
    "RAPIDOCR_SERVER_FILENAME",
    "RapidOcrServerAsset",
    "RapidOcrServerAssetError",
    "rapidocr_server_asset",
    "read_rapidocr_server_source",
]
