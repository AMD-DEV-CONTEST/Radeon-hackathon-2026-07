"""Offline Silero VAD via ONNX runtime — zero network calls at runtime.

Usage:
    from audio.vad_onnx import SileroVAD
    vad = SileroVAD("models/silero_vad.onnx")
    vad.is_speech(pcm16_chunk)  # True/False

Model download (one-time):
    python scripts/download_silero_model.py
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Default ONNX model path (relative to project root)
DEFAULT_MODEL_PATH = Path(__file__).parent.parent / "models" / "silero_vad.onnx"

# Frame geometry, fixed by the model's 16 kHz graph.
#
# Silero consumes 576 samples per step: 64 samples carried over from the previous
# chunk plus 512 new ones. The 64 are not optional padding — the graph reflect-pads
# to 640 and takes four 256-wide STFT frames at hop 128, so a bare 512-sample input
# silently produces near-zero probabilities rather than failing.
HOP_SIZE = 512  # new samples per step, 32 ms at 16 kHz
CONTEXT_SIZE = 64  # samples carried over from the previous step
FRAME_SIZE = HOP_SIZE + CONTEXT_SIZE  # 576, what the model actually sees


class SileroVAD:
    """Offline Silero VAD using local ONNX model.

    No network calls — runs entirely on CPU via onnxruntime.
    """

    def __init__(self, model_path: str = "", sample_rate: int = 16000):
        path = model_path or str(DEFAULT_MODEL_PATH)

        try:
            import onnxruntime as ort

            self.session = ort.InferenceSession(
                path,
                providers=["CPUExecutionProvider"],
            )
        except ImportError:
            raise RuntimeError("onnxruntime not installed. Run: pip install onnxruntime")
        except Exception as e:
            raise RuntimeError(f"Cannot load Silero ONNX model at {path}: {e}") from e

        self.sample_rate = sample_rate
        self._input_name = self.session.get_inputs()[0].name
        self._state_name = self.session.get_inputs()[1].name
        self._sr_name = self.session.get_inputs()[2].name
        self.reset_states()

    def reset_states(self):
        """Reset LSTM state and carried context (call at start of new utterance)."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SIZE, dtype=np.float32)

    def speech_prob(self, pcm16_chunk: bytes) -> float:
        """Speech probability for one 512-sample PCM16 chunk.

        The 64 samples of context the model needs are carried internally, so callers
        feed plain consecutive 32 ms chunks. Chunks must be consecutive: a gap makes
        the carried context stale, so call reset_states() between utterances.

        Args:
            pcm16_chunk: Raw PCM16 bytes, at least 512 samples (1024 bytes).

        Returns:
            Speech probability in [0, 1], or 0.0 for a short chunk.
        """
        if len(pcm16_chunk) < HOP_SIZE * 2:
            return 0.0

        # PCM16 → float32 normalized [-1, 1]
        audio_int16 = np.frombuffer(pcm16_chunk[: HOP_SIZE * 2], dtype=np.int16)
        chunk = audio_int16.astype(np.float32) / 32768.0
        frame = np.concatenate([self._context, chunk])  # (576,)

        inputs = {
            self._input_name: np.expand_dims(frame, axis=0),
            self._state_name: self._state,
            self._sr_name: np.array(self.sample_rate, dtype=np.int64),
        }

        out, self._state = self.session.run(None, inputs)
        self._context = chunk[-CONTEXT_SIZE:]
        return float(out[0][0])

    def is_speech(self, pcm16_chunk: bytes, threshold: float = 0.5) -> bool:
        """Check if a PCM16 audio chunk contains speech.

        Args:
            pcm16_chunk: Raw PCM16 bytes (512 samples = 32ms at 16kHz).
            threshold: Speech probability threshold (0.0–1.0).

        Returns:
            True if speech detected.
        """
        return self.speech_prob(pcm16_chunk) > threshold

    def is_speech_long(self, pcm16_data: bytes, threshold: float = 0.5) -> bool:
        """Check a longer audio buffer by processing in 512-sample windows.

        Returns True if any window exceeds the threshold.
        """
        window_bytes = HOP_SIZE * 2
        num_windows = len(pcm16_data) // window_bytes

        self.reset_states()
        speech_windows = 0

        for i in range(num_windows):
            start = i * window_bytes
            chunk = pcm16_data[start : start + window_bytes]
            if self.is_speech(chunk, threshold):
                speech_windows += 1

        if num_windows == 0:
            return False
        return speech_windows / num_windows > 0.3  # 30%+ of windows must be speech

    def get_speech_timestamps(
        self,
        pcm16_data: bytes,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
    ) -> list[dict]:
        """Find speech segments in audio data.

        Returns list of {"start": float, "end": float} in seconds.
        """
        window_bytes = HOP_SIZE * 2
        num_windows = len(pcm16_data) // window_bytes
        speech_flags = []

        self.reset_states()
        for i in range(num_windows):
            start = i * window_bytes
            speech_flags.append(self.is_speech(pcm16_data[start : start + window_bytes], threshold))

        # Find contiguous speech segments
        segments = []
        in_speech = False
        segment_start = 0

        min_silence_windows = int(min_silence_duration_ms / 32)

        for i, is_sp in enumerate(speech_flags):
            if is_sp and not in_speech:
                segment_start = i
                in_speech = True
            elif not is_sp and in_speech:
                silence_count = 0
                for j in range(i, min(i + min_silence_windows, len(speech_flags))):
                    if not speech_flags[j]:
                        silence_count += 1
                if silence_count >= min_silence_windows:
                    duration = (i - segment_start) * 0.032
                    if duration >= min_speech_duration_ms / 1000:
                        segments.append(
                            {
                                "start": segment_start * 0.032,
                                "end": i * 0.032,
                            }
                        )
                    in_speech = False

        if in_speech:
            duration = (num_windows - segment_start) * 0.032
            if duration >= min_speech_duration_ms / 1000:
                segments.append(
                    {
                        "start": segment_start * 0.032,
                        "end": num_windows * 0.032,
                    }
                )

        return segments


# Factory function matching the old get_vad() interface
_vad_instance = None


def get_offline_vad(model_path: str = "") -> SileroVAD:
    """Get or create the offline Silero VAD instance."""
    global _vad_instance
    if _vad_instance is None:
        _vad_instance = SileroVAD(model_path)
        logger.info("Offline Silero VAD loaded (ONNX)")
    return _vad_instance
