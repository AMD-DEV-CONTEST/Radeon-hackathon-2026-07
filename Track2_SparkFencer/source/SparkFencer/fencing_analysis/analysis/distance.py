import numpy as np


def analyze_distance(timeline, downsample_hz=10):
    """Distance statistics + a downsampled series for events.json / charts."""
    dist = timeline.distance_smooth
    valid = ~np.isnan(dist)
    if not valid.any():
        return {"available": False}

    step = max(1, int(round(timeline.fps / downsample_hz)))
    series = [
        {"t": round(float(timeline.t[i]), 3), "d": round(float(dist[i]), 3)}
        for i in range(0, timeline.n_frames, step)
        if not np.isnan(dist[i])
    ]

    closing = timeline.closing_speed[valid]
    closing = closing[~np.isnan(closing)]

    return {
        "available": True,
        "mean_m": round(float(np.nanmean(dist)), 3),
        "min_m": round(float(np.nanmin(dist)), 3),
        "max_m": round(float(np.nanmax(dist)), 3),
        "std_m": round(float(np.nanstd(dist)), 3),
        "max_closing_speed_ms": round(float(closing.max()), 3) if len(closing) else None,
        "series": series,
    }
