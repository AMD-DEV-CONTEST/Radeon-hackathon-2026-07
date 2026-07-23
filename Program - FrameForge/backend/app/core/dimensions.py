"""
Dimension/frame-count snapping -- same math as the LTX Motion Studio
SmartDimensionSnap ComfyUI node, ported to a plain function.
"""


def _nearest_valid(value: float, step: int, offset: int) -> int:
    if value < offset + step:
        return offset + step
    n = round((value - offset) / step)
    n = max(n, 1)
    return step * n + offset


def snap_dimensions(
    pipeline_config: dict,
    requested_width: int,
    requested_height: int,
    requested_seconds: float,
    frame_rate: int,
) -> dict:
    """
    Returns {width, height, frame_count, actual_seconds, adjustment_note}.
    Clamps to the hardware tier's resolution ceiling, then snaps width/
    height to 32n+1 and frame count to 8n+1, exactly as LTX-2.3 requires.
    """
    notes = []

    ceiling = pipeline_config.get("max_short_side", 768)
    short_side = min(requested_width, requested_height)
    if short_side > ceiling:
        scale = ceiling / short_side
        requested_width = int(requested_width * scale)
        requested_height = int(requested_height * scale)
        notes.append(
            f"Scaled down to fit {pipeline_config.get('tier_name', 'your GPU tier')} "
            f"(short side capped at {ceiling}px)."
        )

    snapped_w = _nearest_valid(requested_width, 32, 1)
    snapped_h = _nearest_valid(requested_height, 32, 1)
    if snapped_w != requested_width or snapped_h != requested_height:
        notes.append(
            f"Resolution adjusted {requested_width}x{requested_height} -> "
            f"{snapped_w}x{snapped_h} (LTX-2.3 requires 32n+1 dimensions)."
        )

    raw_frame_count = max(int(round(requested_seconds * frame_rate)), 9)
    snapped_frames = _nearest_valid(raw_frame_count, 8, 1)
    if snapped_frames != raw_frame_count:
        notes.append(
            f"Frame count adjusted {raw_frame_count} -> {snapped_frames} "
            f"(LTX-2.3 requires 8n+1 total frames)."
        )

    actual_seconds = round(snapped_frames / frame_rate, 2)
    if abs(actual_seconds - requested_seconds) > 0.05:
        notes.append(f"Actual clip length will be ~{actual_seconds}s at {frame_rate}fps.")

    return {
        "width": snapped_w,
        "height": snapped_h,
        "frame_count": snapped_frames,
        "actual_seconds": actual_seconds,
        "adjustment_note": " ".join(notes) if notes else "No adjustments needed -- inputs were already valid.",
    }
