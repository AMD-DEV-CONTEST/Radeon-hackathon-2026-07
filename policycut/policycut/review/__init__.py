"""Review preview: overlay video with boxes/labels burned in (no redaction)."""

__all__ = ["build_overlay"]


def __getattr__(name: str):
    if name == "build_overlay":
        from policycut.review.overlay import build_overlay

        return build_overlay
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
