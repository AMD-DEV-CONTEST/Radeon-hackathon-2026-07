"""Audio redaction effects (pure numpy): mute and 1 kHz beep with 10 ms fades.

apply_audio_effects(samples, sr, events) -> np.ndarray

- samples: float32 array of shape (n_samples, n_channels); a 1-D mono array
  is accepted and returned in the same shape.
- mute zeroes the region; beep replaces it with a 1 kHz sine at -12 dBFS on
  all channels; both cross-fade with the original over 10 ms at each boundary.
- Mute wins overlaps (mutes are applied after beeps).
"""

from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

BEEP_FREQ_HZ = 1000.0
BEEP_DBFS = -12.0
BEEP_AMPLITUDE = 10.0 ** (BEEP_DBFS / 20.0)  # ~0.2512 peak
FADE_S = 0.010  # 10 ms linear fades


def _field(event, name, default=None):
    """Read a field from a RedactionEvent, pydantic model, or plain dict."""
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _effect_type(event) -> str | None:
    action = _field(event, "action") or {}
    if isinstance(action, dict):
        return action.get("type")
    return getattr(action, "type", None)


def _sample_range(event, sr: int, n: int) -> tuple[int, int] | None:
    start_s = _field(event, "start_s")
    end_s = _field(event, "end_s")
    if start_s is None or end_s is None:
        return None
    i0 = max(0, int(round(float(start_s) * sr)))
    i1 = min(n, int(round(float(end_s) * sr)))
    if i1 <= i0:
        return None
    return i0, i1


def _effect_weight(length: int, sr: int) -> np.ndarray:
    """Blend weight of the effect over the region: 0->1 fade-in over 10 ms,
    1 in the middle, 1->0 fade-out over 10 ms."""
    weight = np.ones(length, dtype=np.float32)
    fade = min(max(1, int(round(FADE_S * sr))), length // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
        weight[:fade] = ramp
        weight[length - fade:] = ramp[::-1]
    return weight


def _beep_wave(i0: int, i1: int, sr: int) -> np.ndarray:
    """1 kHz sine at -12 dBFS, phase-locked to absolute sample index so
    overlapping/adjacent beeps stay continuous."""
    t = np.arange(i0, i1, dtype=np.float64) / float(sr)
    return (BEEP_AMPLITUDE * np.sin(2.0 * math.pi * BEEP_FREQ_HZ * t)).astype(np.float32)


def apply_audio_effects(samples: np.ndarray, sr: int, events) -> np.ndarray:
    """Apply mute/beep audio events to a float32 sample buffer.

    Only events whose action type is "mute" or "beep" are applied (visual or
    unknown events are ignored). Returns a new array; the input is untouched.
    """
    out = np.array(samples, dtype=np.float32, copy=True)
    was_mono = out.ndim == 1
    if was_mono:
        out = out[:, np.newaxis]
    if out.ndim != 2:
        raise ValueError(f"samples must be 1-D or (n, ch); got shape {samples.shape}")
    n = out.shape[0]
    if n == 0 or sr <= 0:
        return out[:, 0] if was_mono else out

    beeps = []
    mutes = []
    for event in events or []:
        kind = _field(event, "kind", "audio")
        if kind not in (None, "audio"):
            continue
        effect = _effect_type(event)
        if effect == "beep":
            beeps.append(event)
        elif effect == "mute":
            mutes.append(event)

    # Beeps first, then mutes, so mute wins any overlap.
    for event in beeps:
        rng = _sample_range(event, sr, n)
        if rng is None:
            continue
        i0, i1 = rng
        weight = _effect_weight(i1 - i0, sr)[:, np.newaxis]
        beep = _beep_wave(i0, i1, sr)[:, np.newaxis]  # same signal on all channels
        out[i0:i1] = out[i0:i1] * (1.0 - weight) + beep * weight

    for event in mutes:
        rng = _sample_range(event, sr, n)
        if rng is None:
            continue
        i0, i1 = rng
        weight = _effect_weight(i1 - i0, sr)[:, np.newaxis]
        out[i0:i1] = out[i0:i1] * (1.0 - weight)

    logger.debug("applied audio effects: %d beep, %d mute over %d samples",
                 len(beeps), len(mutes), n)
    return out[:, 0] if was_mono else out
