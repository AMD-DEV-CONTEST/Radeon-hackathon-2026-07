"""WebSocket audio streaming handler: turns a PCM stream into complete utterances.

Two modes, chosen by the client at connection time:

  client_vad=True   The browser ran Silero on WebGPU and only sends audio it already
                    believes is speech, closing each turn with an explicit end-of-
                    utterance signal. Silence never leaves the browser.
  client_vad=False  Fallback for browsers without WebGPU: every chunk arrives and the
                    VAD runs here.

Both paths produce the same thing — a WAV of one utterance — so the rest of the
pipeline does not care which ran.

State machine (server-VAD mode):
  SILENCE  → SPEAKING    (TRIGGER_MS of sustained speech)
  SPEAKING → PROCESSING  (HANGOVER_MS of trailing silence, or the length cap)
  PROCESSING → SILENCE   (caller calls resume() once it has replied)
"""

import base64
import io
import logging
import wave
from collections import deque
from enum import Enum, auto

logger = logging.getLogger(__name__)

# Turn-taking geometry. These mirror frontend/webgpu/vad/utterance-gate.js so a
# session behaves identically whether the VAD ran in the browser or here.
SPEECH_THRESHOLD = 0.5  # probability needed to call a frame speech
EXIT_THRESHOLD = 0.35  # lower bar to stay in speech — hysteresis
TRIGGER_MS = 160  # sustained speech that opens an utterance
HANGOVER_MS = 700  # trailing silence that closes it
PREROLL_MS = 320  # audio kept from before the trigger
MIN_VOICED_MS = 300  # utterances with less real voice than this are noise
MAX_UTTERANCE_MS = 20_000  # hard cap, also bounds what a client can make us buffer

BYTES_PER_SAMPLE = 2  # int16 mono


class SpeechState(Enum):
    SILENCE = auto()
    SPEAKING = auto()
    PROCESSING = auto()


class StreamHandler:
    """Accumulates streamed PCM and emits one WAV per detected utterance."""

    def __init__(self, sample_rate: int = 16000, client_vad: bool = False):
        self.sample_rate = sample_rate
        self.client_vad = client_vad
        self.state = SpeechState.SILENCE
        self.speech_buffer: list[bytes] = []
        self._buffered_bytes = 0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._voiced_ms = 0.0
        self._preroll: deque[bytes] = deque()
        self._preroll_bytes = 0
        self._vad = None
        self._vad_reset = None

    # ── VAD ──────────────────────────────────────────────────────

    def _get_vad(self):
        """Return a callable (bytes) -> speech probability.

        Each connection gets its own Silero session: the model is stateful (LSTM plus
        a 64-sample context carry), so sharing one across concurrent sessions would
        interleave two conversations into a single hidden state.
        """
        if self._vad is None:
            try:
                from audio.vad_onnx import SileroVAD

                model = SileroVAD(sample_rate=self.sample_rate)
                self._vad = model.speech_prob
                self._vad_reset = model.reset_states
            except Exception as e:
                # No ONNX model on disk, or onnxruntime missing. The legacy VAD only
                # answers yes/no, so hysteresis collapses to a single threshold.
                logger.warning("Offline VAD unavailable (%s), using audio.vad", e)
                from audio.vad import get_vad

                legacy = get_vad()
                self._vad = lambda chunk: 1.0 if legacy(chunk, self.sample_rate) else 0.0
                self._vad_reset = lambda: None
        return self._vad

    # ── ingest ───────────────────────────────────────────────────

    def _chunk_ms(self, chunk: bytes) -> float:
        return len(chunk) / BYTES_PER_SAMPLE / self.sample_rate * 1000

    def add_chunk(self, audio_chunk: bytes) -> str | None:
        """Process an incoming audio chunk.

        Args:
            audio_chunk: Raw PCM audio bytes (int16 mono at self.sample_rate).

        Returns:
            None (still listening) or a base64-encoded WAV string (utterance complete).
        """
        if self.state == SpeechState.PROCESSING:
            return None  # we are mid-reply; whatever arrives now is our own voice

        if self.client_vad:
            return self._append_client_audio(audio_chunk)

        chunk_ms = self._chunk_ms(audio_chunk)
        prob = self._get_vad()(audio_chunk)

        if self.state == SpeechState.SILENCE:
            self._push_preroll(audio_chunk)
            if prob >= SPEECH_THRESHOLD:
                self._speech_ms += chunk_ms
            else:
                self._speech_ms = 0.0

            if self._speech_ms >= TRIGGER_MS:
                # Start from the pre-roll, not from this chunk: by now the first
                # syllable is already TRIGGER_MS in the past.
                self.state = SpeechState.SPEAKING
                self.speech_buffer = list(self._preroll)
                self._buffered_bytes = self._preroll_bytes
                self._preroll.clear()
                self._preroll_bytes = 0
                self._voiced_ms = self._speech_ms
                self._speech_ms = 0.0
                self._silence_ms = 0.0
                logger.debug("Speech started")

        elif self.state == SpeechState.SPEAKING:
            self.speech_buffer.append(audio_chunk)
            self._buffered_bytes += len(audio_chunk)

            if prob >= EXIT_THRESHOLD:
                self._silence_ms = 0.0
                self._voiced_ms += chunk_ms
            else:
                self._silence_ms += chunk_ms
                if self._silence_ms >= HANGOVER_MS:
                    return self._finalize_utterance("silence")

            if self._buffered_ms() >= MAX_UTTERANCE_MS:
                return self._finalize_utterance("max-length")

        return None

    def _push_preroll(self, chunk: bytes) -> None:
        limit = int(PREROLL_MS / 1000 * self.sample_rate) * BYTES_PER_SAMPLE
        self._preroll.append(chunk)
        self._preroll_bytes += len(chunk)
        while self._preroll_bytes > limit and len(self._preroll) > 1:
            self._preroll_bytes -= len(self._preroll.popleft())

    def _append_client_audio(self, chunk: bytes) -> None:
        """Buffer pre-gated audio from a browser that ran the VAD itself."""
        cap = int(MAX_UTTERANCE_MS / 1000 * self.sample_rate) * BYTES_PER_SAMPLE
        if self._buffered_bytes >= cap:
            logger.warning("Client utterance exceeded %d ms, dropping tail", MAX_UTTERANCE_MS)
            return None
        self.speech_buffer.append(chunk)
        self._buffered_bytes += len(chunk)
        return None

    def end_of_utterance(self) -> str | None:
        """Client signalled the turn is over. Returns the WAV, or None if too short."""
        if not self.client_vad:
            return None
        return self._finalize_utterance("client")

    def resume(self) -> None:
        """Re-open the gate after the caller has finished replying."""
        self._reset()

    # ── output ───────────────────────────────────────────────────

    def _buffered_ms(self) -> float:
        return self._buffered_bytes / BYTES_PER_SAMPLE / self.sample_rate * 1000

    def _finalize_utterance(self, reason: str = "silence") -> str | None:
        """Pack buffered speech into a base64-encoded WAV string."""
        duration_ms = self._buffered_ms()
        voiced_ms = self._voiced_ms
        chunks = self.speech_buffer

        if not chunks:
            self._reset()
            return None

        # In client-VAD mode the browser already applied the voicing test, so its word
        # is good enough; here we only guard against a stray trigger.
        if not self.client_vad and voiced_ms < MIN_VOICED_MS:
            logger.debug(
                "Discarded %.0f ms utterance with only %.0f ms voiced", duration_ms, voiced_ms
            )
            self._reset()
            return None

        self.state = SpeechState.PROCESSING
        logger.info("Utterance complete: %.1fs (%s)", duration_ms / 1000, reason)

        wav_bytes = self._pack_wav(chunks)
        b64_data = base64.b64encode(wav_bytes).decode("utf-8")

        # Deliberately keep state == PROCESSING: the caller is about to spend seconds
        # in STT/LLM/TTS and anything arriving in the meantime is echo, not a new turn.
        self.speech_buffer = []
        self._buffered_bytes = 0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._voiced_ms = 0.0
        self._preroll.clear()
        self._preroll_bytes = 0
        return b64_data

    def _pack_wav(self, chunks: list[bytes]) -> bytes:
        """Pack raw PCM chunks into a WAV file."""
        raw_data = b"".join(chunks)
        buf = io.BytesIO()

        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(self.sample_rate)
            wf.writeframes(raw_data)

        return buf.getvalue()

    def _reset(self):
        self.state = SpeechState.SILENCE
        self.speech_buffer = []
        self._buffered_bytes = 0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._voiced_ms = 0.0
        self._preroll.clear()
        self._preroll_bytes = 0
        # A gap in the stream makes the carried 64-sample context stale.
        if self._vad_reset is not None:
            self._vad_reset()


def process_turn_text(
    text: str,
    date: str | None = None,
    session_id: str | None = None,
    lang: str = "zh",
) -> dict:
    """Run one transcribed turn through the diary agent: Agent → Graph → TTS.

    Returns {"text": str, "answer": str, "audio_b64": str|None}.

    ``text`` is already speech-to-text (the WS path may transcribe client-side,
    or ``process_utterance`` does it server-side). The diary agent records the
    turn into the graph for ``date`` (defaults to today) and returns a spoken
    reply, which Kokoro renders to audio.
    """
    import os
    import tempfile

    from diary import runtime
    from tts.kokoro_tts import synthesize

    if not text or not text.strip():
        return {"text": "", "answer": "", "audio_b64": None}

    if date is None:
        date = runtime.today_iso()

    agent, ctx = runtime.get_or_create_diary_agent(session_id)
    answer = agent.process_turn(ctx, date, text, lang=lang)

    if not answer:
        # Agent recorded the turn but had nothing to say (e.g. a bare fact).
        return {"text": text, "answer": "", "audio_b64": None}

    tts_lang = "zh" if sum(1 for c in answer if "\u4e00" <= c <= "\u9fff") > len(answer) * 0.3 else "en"

    with tempfile.TemporaryDirectory() as tmpdir:
        tts_path = os.path.join(tmpdir, "output")
        audio_path = synthesize(answer, tts_path, lang=tts_lang)

        audio_b64 = None
        if audio_path and os.path.exists(audio_path):
            with open(audio_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {"text": text, "answer": answer, "audio_b64": audio_b64}


def process_utterance(
    audio_b64: str,
    date: str | None = None,
    session_id: str | None = None,
    lang: str = "zh",
) -> dict:
    """Process a complete utterance: STT → DiaryAgent → TTS.

    Returns {"text": str, "answer": str, "audio_b64": str|None}.
    """
    import base64 as _b64
    import os
    import tempfile

    # Pick STT backend. Default is the local offline Whisper model; only fall
    # back to the cloud Qwen Omni STT when explicitly requested (DIARY_STT=cloud)
    # and a key is present.
    from config.settings import QWEN_API_KEY
    stt_mode = os.getenv("DIARY_STT", "local").lower()
    if stt_mode == "cloud" and QWEN_API_KEY:
        from audio.stt_client import transcribe
    else:
        try:
            from audio.stt_local import transcribe
        except Exception:
            from audio.stt_client import transcribe  # reports [未配置 API key]

    # Decode WAV
    wav_bytes = _b64.b64decode(audio_b64)

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "utterance.wav")
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        # STT. Anything the recogniser returns bracketed ("[…]") is a failure
        # sentinel (no API key, missing file, decode error) — never feed it to
        # the diary agent as if it were the user's words.
        text = transcribe(wav_path)
        if text.startswith("["):
            logger.warning("STT failed/disabled: %s", text)
            return {"text": "", "answer": text, "audio_b64": None}

        logger.info("STT: %s", text)

        return process_turn_text(text, date=date, session_id=session_id, lang=lang)
