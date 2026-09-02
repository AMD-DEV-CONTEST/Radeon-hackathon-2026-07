"""Media handling: probing (ffprobe), normalization and final rendering.

Only ``probe`` symbols are imported eagerly (stdlib-only); ``normalize`` and
``render`` are exposed lazily so importing this package never pulls in numpy
or OpenCV unnecessarily.
"""
from policycut.media.probe import (
    MediaCancelled,
    MediaError,
    ffmpeg_path,
    ffprobe_path,
    have_ffmpeg,
    probe_media,
    probe_raw,
)

__all__ = [
    "MediaCancelled",
    "MediaError",
    "ffmpeg_path",
    "ffprobe_path",
    "have_ffmpeg",
    "probe_media",
    "probe_raw",
    "normalize_video",
    "render_video",
    "write_srt",
]

_LAZY = {
    "normalize_video": ("policycut.media.normalize", "normalize_video"),
    "render_video": ("policycut.media.render", "render_video"),
    "write_srt": ("policycut.media.render", "write_srt"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module_name, attr = _LAZY[name]
        return getattr(importlib.import_module(module_name), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
