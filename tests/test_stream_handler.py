"""Turn-taking tests for the WebSocket stream handler.

The state machine decides when the user stopped talking. Getting it wrong produces
complaints that are hard to reproduce by hand ("it cut me off", "it never answered"),
so it is driven here with a scripted VAD instead of a microphone.

No model or network is needed: the handler's VAD is a plain callable returning a
probability, which the tests substitute.
"""

import base64
import io
import wave

import pytest

from audio.stream_handler import (
    EXIT_THRESHOLD,
    HANGOVER_MS,
    MIN_VOICED_MS,
    PREROLL_MS,
    TRIGGER_MS,
    SpeechState,
    StreamHandler,
)

SAMPLE_RATE = 16000
HOP = 512  # samples per chunk — one Silero frame
FRAME_MS = HOP / SAMPLE_RATE * 1000  # 32.0
CHUNK = b"\x01\x02" * HOP


def frames(ms: float) -> int:
    """Number of 32 ms chunks needed to cover `ms`."""
    return int(-(-ms // FRAME_MS))


def make_handler(**kwargs) -> tuple[StreamHandler, list[float]]:
    """Handler wired to a scripted VAD. The returned cell holds the current probability."""
    handler = StreamHandler(sample_rate=SAMPLE_RATE, **kwargs)
    cell = [0.0]
    handler._vad = lambda _chunk: cell[0]
    return handler, cell


def feed(handler, cell, count, prob) -> str | None:
    """Push `count` chunks at probability `prob`; return the first utterance emitted."""
    cell[0] = prob
    out = None
    for _ in range(count):
        result = handler.add_chunk(CHUNK)
        if result and out is None:
            out = result
    return out


def wav_samples(b64: str) -> int:
    with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        return wf.getnframes()


# ── server-side VAD ──────────────────────────────────────────────


def test_silence_never_produces_an_utterance():
    handler, script = make_handler()
    assert feed(handler, script, 300, 0.0) is None
    assert handler.state is SpeechState.SILENCE


def test_a_single_loud_frame_does_not_trigger():
    handler, script = make_handler()
    feed(handler, script, 1, 0.99)  # door slam, key press
    feed(handler, script, 60, 0.0)
    assert handler.state is SpeechState.SILENCE


def test_sustained_speech_opens_the_gate():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS) - 1, 0.9)
    assert handler.state is SpeechState.SILENCE
    feed(handler, script, 1, 0.9)
    assert handler.state is SpeechState.SPEAKING


def test_trigger_requires_consecutive_frames():
    handler, script = make_handler()
    for i in range(80):
        feed(handler, script, 1, 0.9 if i % 2 == 0 else 0.0)
    assert handler.state is SpeechState.SILENCE, "alternating noise must not open a turn"


def test_utterance_includes_preroll_before_the_trigger():
    handler, script = make_handler()
    feed(handler, script, 100, 0.0)
    speech = frames(TRIGGER_MS) + frames(600)
    feed(handler, script, speech, 0.9)

    b64 = feed(handler, script, frames(HANGOVER_MS) + 1, 0.0)
    assert b64, "hangover silence should close the utterance"

    got = wav_samples(b64)
    # Everything the gate saw as speech, plus pre-roll ahead of it and the hangover
    # behind it. Without pre-roll the first syllable would be missing.
    assert got > (speech + frames(HANGOVER_MS)) * HOP
    assert got <= (speech + frames(HANGOVER_MS) + frames(PREROLL_MS) + 2) * HOP


def test_intra_sentence_pause_does_not_split_the_turn():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS) + frames(600), 0.9)
    assert feed(handler, script, frames(400), 0.0) is None
    assert handler.state is SpeechState.SPEAKING, "a breath pause ended the turn"


def test_hysteresis_holds_the_turn_open():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS) + frames(600), 0.9)
    # Between the two thresholds: quiet, but not silence. An unvoiced consonant.
    mid = (EXIT_THRESHOLD + 0.5) / 2
    assert feed(handler, script, frames(2000), mid) is None
    assert handler.state is SpeechState.SPEAKING


def test_short_voiced_burst_is_discarded():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS), 0.9)  # a cough: enough to trigger
    assert handler.state is SpeechState.SPEAKING
    assert feed(handler, script, frames(HANGOVER_MS) + 1, 0.0) is None
    assert handler.state is SpeechState.SILENCE
    assert TRIGGER_MS < MIN_VOICED_MS, "the test only means something if it is below the floor"


def test_length_cap_flushes_unbroken_speech():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS), 0.9)
    b64 = feed(handler, script, frames(60_000), 0.99)
    assert b64, "speech that never pauses must still be flushed"
    assert wav_samples(b64) / SAMPLE_RATE < 21


def test_handler_ignores_audio_until_resume():
    handler, script = make_handler()
    feed(handler, script, frames(TRIGGER_MS) + frames(600), 0.9)
    assert feed(handler, script, frames(HANGOVER_MS) + 1, 0.0)
    assert handler.state is SpeechState.PROCESSING

    # STT + LLM + TTS take seconds; whatever the mic hears then is our own reply.
    assert feed(handler, script, 200, 0.99) is None
    assert handler.state is SpeechState.PROCESSING

    handler.resume()
    assert handler.state is SpeechState.SILENCE
    feed(handler, script, frames(TRIGGER_MS), 0.9)
    assert handler.state is SpeechState.SPEAKING


def test_consecutive_turns():
    handler, script = make_handler()
    for turn in range(3):
        feed(handler, script, frames(TRIGGER_MS) + frames(600), 0.9)
        assert feed(handler, script, frames(HANGOVER_MS) + 1, 0.0), f"turn {turn} lost"
        handler.resume()


# ── client-side VAD ──────────────────────────────────────────────


def test_client_vad_buffers_verbatim_until_eou():
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    # The browser already gated this audio, so no VAD should be constructed at all.
    handler._vad = pytest.fail

    for _ in range(20):
        assert handler.add_chunk(CHUNK) is None

    b64 = handler.end_of_utterance()
    assert b64
    assert wav_samples(b64) == 20 * HOP


def test_client_vad_accepts_a_single_frame_utterance():
    # The browser applies its own minimum-voicing rule; the server must not
    # second-guess it and silently drop a short but real answer like "yes".
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    handler.add_chunk(CHUNK)
    b64 = handler.end_of_utterance()
    assert b64 and wav_samples(b64) == HOP


def test_client_vad_eou_with_no_audio_is_harmless():
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    assert handler.end_of_utterance() is None
    assert handler.state is SpeechState.SILENCE


def test_client_vad_caps_what_a_client_can_buffer():
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    for _ in range(frames(60_000)):
        handler.add_chunk(CHUNK)
    b64 = handler.end_of_utterance()
    assert b64
    assert wav_samples(b64) / SAMPLE_RATE < 21, "a client must not be able to buffer forever"


def test_client_audio_is_dropped_while_replying():
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    handler.add_chunk(CHUNK)
    assert handler.end_of_utterance()
    assert handler.state is SpeechState.PROCESSING

    # The browser mutes its own mic during playback, but a slow or buggy client may
    # keep streaming. Buffering that would prepend our own voice to the next turn.
    for _ in range(50):
        handler.add_chunk(CHUNK)
    handler.resume()
    handler.add_chunk(CHUNK)
    assert wav_samples(handler.end_of_utterance()) == HOP


def test_server_vad_is_not_used_in_client_mode():
    handler = StreamHandler(sample_rate=SAMPLE_RATE, client_vad=True)
    handler._vad = pytest.fail
    handler.add_chunk(CHUNK)
    assert handler.end_of_utterance()
