"""Read the immutable OpenAI-proxy target asset on explicit demand.

The AMD deployment controller transfers this standalone script to an already
acquired target runtime.  Keeping it in bundled resources means the desktop
does not need the target package layout after PyInstaller extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xenix.resources import package_resource_path


OPENAI_PROXY_FILENAME = "openai_proxy.py"
_OPENAI_PROXY_RESOURCE = ("amd", "components", OPENAI_PROXY_FILENAME)
_MAX_PROXY_SOURCE_BYTES = 2 * 1024 * 1024


class OpenAIProxyAssetError(RuntimeError):
    """The packaged target-side OpenAI proxy cannot be read safely."""


@dataclass(frozen=True, slots=True)
class OpenAIProxyAsset:
    """One exact target-side file, without source contents in representations."""

    filename: str
    source: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.filename != OPENAI_PROXY_FILENAME:
            raise OpenAIProxyAssetError("OpenAI proxy target asset filename is invalid.")
        if not isinstance(self.source, bytes) or not self.source or len(self.source) > _MAX_PROXY_SOURCE_BYTES:
            raise OpenAIProxyAssetError("OpenAI proxy target asset source is invalid.")

    def __repr__(self) -> str:
        return f"OpenAIProxyAsset(filename={self.filename!r}, source=<redacted>)"


def read_openai_proxy_source() -> bytes:
    """Return the bundled standalone proxy bytes without target-side imports.

    This is intentionally a read-only, explicit resource operation.  It does
    not create target paths, start a process, inspect a GPU, or touch a token.
    """

    try:
        source = package_resource_path(*_OPENAI_PROXY_RESOURCE).read_bytes()
    except OSError as exc:
        raise OpenAIProxyAssetError("OpenAI proxy target asset is unavailable.") from exc
    return OpenAIProxyAsset(OPENAI_PROXY_FILENAME, source).source


def openai_proxy_asset() -> OpenAIProxyAsset:
    """Return the fixed file identity and bytes placement must transfer."""

    return OpenAIProxyAsset(OPENAI_PROXY_FILENAME, read_openai_proxy_source())


__all__ = [
    "OPENAI_PROXY_FILENAME",
    "OpenAIProxyAsset",
    "OpenAIProxyAssetError",
    "openai_proxy_asset",
    "read_openai_proxy_source",
]
