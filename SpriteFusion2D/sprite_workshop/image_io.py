"""The only boundary between Pillow and the internal RGBA arrays.

No other module imports PIL.  Pillow is an optional dependency (``[workshop]``)
so the import failure is reported as a backend-unavailable error rather than an
ImportError traceback (BACKEND_CLI_PLAN.md 4.1, 10.1).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

from .errors import BackendUnavailableError, NotFoundError, OperationError
from .model import RgbaImage

_PILLOW_HINT = "install the workshop extra: pip install -e .[workshop]"


def _pillow():
    try:
        from PIL import Image  # noqa: PLC0415 - deliberate lazy import
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise BackendUnavailableError(
            "Pillow is required for image I/O", hint=_PILLOW_HINT
        ) from exc
    return Image


def load_rgba(path: str | os.PathLike[str]) -> RgbaImage:
    """Read any Pillow-readable image as canonical RGBA."""

    file_path = Path(path)
    if not file_path.is_file():
        raise NotFoundError("image file not found", path=str(file_path))

    image_module = _pillow()
    try:
        with image_module.open(file_path) as handle:
            converted = handle.convert("RGBA")
            array = np.array(converted, dtype=np.uint8)
    except OSError as exc:
        raise OperationError(
            "could not decode image", path=str(file_path), reason=str(exc)
        ) from exc

    return RgbaImage(array)


def save_rgba(
    image: RgbaImage, path: str | os.PathLike[str], *, normalize: bool = True
) -> Path:
    """Write RGBA to PNG.

    ``normalize`` zeroes the RGB of fully transparent pixels, which is the
    persistence rule from BACKEND_CLI_PLAN.md 5.1.  It is off only for source
    imports, which must keep their original bytes.
    """

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    payload = image.normalized() if normalize else image
    image_module = _pillow()
    surface = image_module.fromarray(payload.array, mode="RGBA")
    # A temp file plus atomic replace keeps a crashed write from leaving a
    # half-written PNG behind an otherwise valid manifest.  The name is unique
    # per write: a fixed "<name>.tmp" collides when the daemon and a CLI run
    # write the same target, and one writer then renames the other's partial
    # file into place.
    handle, temp_name = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        surface.save(temp_path, format="PNG", optimize=True)
        os.replace(temp_path, file_path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise OperationError(
            "could not write image", path=str(file_path), reason=str(exc)
        ) from exc
    return file_path


def pillow_available() -> bool:
    try:
        _pillow()
    except BackendUnavailableError:
        return False
    return True


def pillow_version() -> str | None:
    try:
        from PIL import __version__  # noqa: PLC0415
    except ImportError:  # pragma: no cover - depends on environment
        return None
    return __version__
