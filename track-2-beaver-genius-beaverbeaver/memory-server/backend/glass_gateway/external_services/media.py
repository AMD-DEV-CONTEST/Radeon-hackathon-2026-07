from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict, Field


IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
AUDIO_MEDIA_TYPES = frozenset(
    {
        "audio/wav",
        "audio/mpeg",
        "audio/ogg",
        "audio/flac",
        "audio/mp4",
    }
)
ALLOWED_MEDIA_TYPES = IMAGE_MEDIA_TYPES | AUDIO_MEDIA_TYPES

_SUFFIX_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
}
_MEDIA_TYPE_SUFFIXES = {
    media_type: suffix for suffix, media_type in _SUFFIX_MEDIA_TYPES.items()
}


class MediaContractError(ValueError):
    pass


class MediaTooLargeError(MediaContractError):
    pass


class UnsupportedMediaTypeError(MediaContractError):
    pass


class InvalidEncodedMediaError(MediaContractError):
    pass


class EncodedMedia(BaseModel):
    model_config = ConfigDict(frozen=True)

    media_type: str = Field(min_length=1)
    data_base64: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)


def encode_media(
    path: str | Path,
    *,
    max_bytes: int,
    allowed_media_types: frozenset[str] = ALLOWED_MEDIA_TYPES,
) -> EncodedMedia:
    source = Path(path)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    media_type = _SUFFIX_MEDIA_TYPES.get(source.suffix.lower())
    if media_type is None or media_type not in allowed_media_types:
        raise UnsupportedMediaTypeError(
            f"unsupported media type for suffix {source.suffix.lower() or '<none>'}"
        )

    size_bytes = source.stat().st_size
    if size_bytes <= 0:
        raise MediaContractError("media file is empty")
    if size_bytes > max_bytes:
        raise MediaTooLargeError(
            f"media size {size_bytes} bytes exceeds limit {max_bytes} bytes"
        )

    content = source.read_bytes()
    if len(content) != size_bytes:
        raise MediaContractError("media changed while it was being encoded")

    return EncodedMedia(
        media_type=media_type,
        data_base64=base64.b64encode(content).decode("ascii"),
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=size_bytes,
    )


def decode_media(
    media: EncodedMedia,
    *,
    max_bytes: int,
    allowed_media_types: frozenset[str] = ALLOWED_MEDIA_TYPES,
) -> bytes:
    if media.media_type not in allowed_media_types:
        raise UnsupportedMediaTypeError(f"unsupported media type {media.media_type}")
    if media.size_bytes > max_bytes:
        raise MediaTooLargeError(
            f"media size {media.size_bytes} bytes exceeds limit {max_bytes} bytes"
        )
    try:
        content = base64.b64decode(media.data_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidEncodedMediaError("media contains invalid Base64") from exc
    if len(content) != media.size_bytes:
        raise InvalidEncodedMediaError("decoded media size does not match declaration")
    if hashlib.sha256(content).hexdigest() != media.sha256:
        raise InvalidEncodedMediaError("decoded media checksum does not match declaration")
    return content


def authorization_headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


@contextmanager
def materialize_media(
    media: EncodedMedia,
    *,
    directory: str | Path,
    max_bytes: int,
    allowed_media_types: frozenset[str] = ALLOWED_MEDIA_TYPES,
    prefix: str = "beaver-media-",
) -> Iterator[Path]:
    content = decode_media(
        media,
        max_bytes=max_bytes,
        allowed_media_types=allowed_media_types,
    )
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    suffix = _MEDIA_TYPE_SUFFIXES.get(media.media_type, ".bin")
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=prefix,
        suffix=suffix,
        dir=root,
        delete=False,
    )
    path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        yield path
    finally:
        path.unlink(missing_ok=True)
