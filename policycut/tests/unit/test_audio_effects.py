"""Tests for the pure-numpy audio redaction effects.

Contract (CONTRACTS.md sections 7/10): mute writes zeros, beep is a 1 kHz sine
at -12 dBFS, both with 10 ms linear fades at each end, and mute wins where
events overlap. Multichannel audio is processed on every channel.

The numpy effect function lives in the media/audio layer; its exact name is
not pinned by CONTRACTS.md, so a small adapter locates it.
"""

from __future__ import annotations

import importlib
import inspect
import math

import numpy as np
import pytest

from policycut.core.models import RedactionEvent

SR = 16000
MODULES = [
    "policycut.media.render",
    "policycut.audio.effects",
    "policycut.media.audio_effects",
    "policycut.media.audio",
    "policycut.audio.render",
]
FN_NAMES = [
    "apply_audio_effects",
    "apply_audio_events",
    "apply_audio_redactions",
    "apply_effects",
    "process_audio_events",
    "process_audio",
    "render_audio",
]


def _find_effect_fn():
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for fn_name in FN_NAMES:
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                return fn
    pytest.fail(
        f"no audio effect function found; searched {FN_NAMES} in {MODULES}"
    )


def apply_effects(samples: np.ndarray, sr: int, events: list) -> np.ndarray:
    """Signature-tolerant invocation: binds args by parameter name."""
    fn = _find_effect_fn()
    sig = inspect.signature(fn)
    kwargs = {}
    for name, param in sig.parameters.items():
        low = name.lower()
        if any(k in low for k in ("sample", "audio", "data", "wave", "pcm", "signal")) and "rate" not in low:
            kwargs[name] = samples
        elif low in ("sr", "fs", "rate") or "rate" in low:
            kwargs[name] = sr
        elif "event" in low:
            kwargs[name] = events
        elif param.default is inspect.Parameter.empty:
            # unknown required parameter: give positionally-sane defaults
            kwargs[name] = None
    out = fn(**kwargs)
    if out is None:  # in-place implementations return None
        out = samples
    return np.asarray(out)


def _sine(duration_s: float, freq: float = 440.0, amp: float = 0.8, channels: int = 1) -> np.ndarray:
    t = np.arange(int(duration_s * SR)) / SR
    mono = (amp * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    if channels == 1:
        return mono
    return np.stack([mono] * channels, axis=-1)


def _event(category: str, start: float, end: float, action_type: str) -> RedactionEvent:
    return RedactionEvent(
        id=f"e_{abs(hash((category, start, end))) % 10**10:010d}",
        kind="audio",
        category=category,
        status="confirmed",
        source="auto",
        start_s=start,
        end_s=end,
        action={"type": action_type},
    )


def _slice(samples: np.ndarray, t0: float, t1: float) -> np.ndarray:
    seg = samples[int(t0 * SR): int(t1 * SR)]
    return seg


class TestMute:
    def test_mute_interior_is_zero(self):
        audio = _sine(1.0)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "mute")])
        interior = _slice(out, 0.25, 0.55)  # beyond the 10 ms fades
        assert np.max(np.abs(interior)) == pytest.approx(0.0, abs=1e-6)

    def test_outside_untouched(self):
        audio = _sine(1.0)
        out = apply_effects(audio.copy(), SR, [_event("phone", 0.4, 0.6, "mute")])
        before = _slice(out, 0.0, 0.35)
        ref = _slice(audio, 0.0, 0.35)
        np.testing.assert_allclose(before, ref, atol=1e-4)

    def test_output_same_length(self):
        audio = _sine(1.0)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.4, "mute")])
        assert out.shape[0] == audio.shape[0]


class TestBeep:
    def test_beep_level_minus_12_dbfs(self):
        audio = _sine(1.0)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "beep")])
        interior = _slice(out, 0.3, 0.5)
        peak = float(np.max(np.abs(interior)))
        target = 10 ** (-12 / 20)  # ~0.2512 peak amplitude
        assert peak == pytest.approx(target, rel=0.15), f"beep peak {peak} vs -12dBFS {target}"

    def test_beep_is_roughly_1khz(self):
        audio = np.zeros(SR, dtype=np.float32)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.8, "beep")])
        interior = _slice(out, 0.3, 0.7)
        assert np.max(np.abs(interior)) > 0.05, "beep must produce audible signal"
        # zero crossings of a 1 kHz sine over 0.4 s ~= 800
        crossings = int(np.sum(np.abs(np.diff(np.signbit(interior.flatten()[: int(0.4 * SR)])))))
        assert 600 <= crossings <= 1000, f"expected ~800 zero-crossings for 1 kHz, got {crossings}"


class TestFades:
    def test_fade_in_ramp(self):
        # beep into silence: the first 5 ms of the beep must be attenuated
        audio = np.zeros(SR, dtype=np.float32)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "beep")])
        interior_peak = float(np.max(np.abs(_slice(out, 0.3, 0.5))))
        first_half_fade = _slice(out, 0.2, 0.205)  # first 5 ms of a 10 ms fade
        fade_peak = float(np.max(np.abs(first_half_fade)))
        assert fade_peak <= 0.65 * interior_peak, (
            f"10ms fade-in missing: first-5ms peak {fade_peak} vs interior {interior_peak}"
        )

    def test_fade_out_ramp(self):
        audio = np.zeros(SR, dtype=np.float32)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "beep")])
        interior_peak = float(np.max(np.abs(_slice(out, 0.3, 0.5))))
        last_half_fade = _slice(out, 0.595, 0.6)
        fade_peak = float(np.max(np.abs(last_half_fade)))
        assert fade_peak <= 0.65 * interior_peak

    def test_no_hard_discontinuity_at_mute_boundary(self):
        audio = _sine(1.0, amp=0.9)
        out = apply_effects(audio, SR, [_event("phone", 0.3, 0.6, "mute")])
        flat = out.reshape(out.shape[0], -1)[:, 0]
        # max sample-to-sample jump around the boundary must stay well below
        # an instantaneous 0.9 step (440 Hz at 16 kHz moves ~0.155/sample max)
        region = flat[int(0.29 * SR): int(0.32 * SR)]
        max_jump = float(np.max(np.abs(np.diff(region))))
        assert max_jump < 0.5, f"hard click at mute start (jump {max_jump})"


class TestOverlap:
    def test_mute_wins_over_beep(self):
        audio = _sine(1.0)
        events = [
            _event("phone", 0.2, 0.8, "beep"),
            _event("email", 0.4, 0.6, "mute"),
        ]
        out = apply_effects(audio, SR, events)
        muted = _slice(out, 0.45, 0.55)
        assert np.max(np.abs(muted)) == pytest.approx(0.0, abs=1e-6), "mute must win overlaps"
        beeped = _slice(out, 0.25, 0.35)
        assert np.max(np.abs(beeped)) > 0.05, "beep must still apply outside the mute span"

    def test_order_independence(self):
        audio = _sine(1.0)
        ev_a = [_event("phone", 0.2, 0.8, "beep"), _event("email", 0.4, 0.6, "mute")]
        ev_b = list(reversed(ev_a))
        out_a = apply_effects(audio.copy(), SR, ev_a)
        out_b = apply_effects(audio.copy(), SR, ev_b)
        muted_a = _slice(out_a, 0.45, 0.55)
        muted_b = _slice(out_b, 0.45, 0.55)
        assert np.max(np.abs(muted_a)) == pytest.approx(0.0, abs=1e-6)
        assert np.max(np.abs(muted_b)) == pytest.approx(0.0, abs=1e-6)


class TestMultichannel:
    def test_stereo_shape_preserved(self):
        audio = _sine(1.0, channels=2)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "mute")])
        assert out.shape == audio.shape

    def test_all_channels_muted(self):
        audio = _sine(1.0, channels=2)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "mute")])
        interior = out[int(0.25 * SR): int(0.55 * SR)]
        assert np.max(np.abs(interior)) == pytest.approx(0.0, abs=1e-6)

    def test_all_channels_beeped(self):
        audio = _sine(1.0, channels=2)
        out = apply_effects(audio, SR, [_event("phone", 0.2, 0.6, "beep")])
        interior = out[int(0.3 * SR): int(0.5 * SR)]
        for ch in range(interior.shape[-1]):
            assert np.max(np.abs(interior[..., ch])) > 0.05
