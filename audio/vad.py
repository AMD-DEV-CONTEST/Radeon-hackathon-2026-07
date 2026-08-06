"""Voice Activity Detection (VAD).

Primary: Silero neural VAD (requires torch + silero-vad).
Fallback: RMS energy threshold.
"""

import logging

from utils.timing import timing

logger = logging.getLogger(__name__)

_silero_model = None


def get_vad():
    """Return a VAD function: (bytes, sample_rate) -> bool.

    Uses Silero if available, else RMS threshold.
    """
    global _silero_model

    # Try Silero
    if _silero_model is None:
        try:
            import torch

            model, _utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
            )
            _silero_model = model
            logger.info("Silero VAD loaded")
        except Exception as e:
            logger.warning("Silero VAD unavailable (%s), using RMS fallback", e)
            return _rms_is_speech

    if _silero_model is not None:
        return _silero_is_speech
    return _rms_is_speech


def _silero_is_speech(audio_data: bytes, sample_rate: int = 16000) -> bool:
    """Silero neural VAD check."""
    import torch

    try:
        # Convert raw PCM int16 → float32 tensor [-1, 1]
        samples = torch.frombuffer(bytearray(audio_data), dtype=torch.int16).float()
        if samples.numel() == 0:
            return False
        samples = samples / 32768.0

        # Silero expects shape (batch, samples) at 16kHz
        # Resample if needed (simple nearest-neighbor)
        if sample_rate != 16000 and samples.numel() > 0:
            scale = 16000 / sample_rate
            indices = (torch.arange(0, samples.numel(), scale)).long()
            indices = indices[indices < samples.numel()]
            samples = samples[indices]

        with torch.no_grad():
            speech_prob = _silero_model(samples.unsqueeze(0), 16000).item()
        return speech_prob > 0.5

    except Exception as e:
        logger.debug("Silero VAD error: %s, using RMS fallback", e)
        return _rms_is_speech(audio_data, sample_rate)


def _rms_is_speech(audio_data: bytes, _sample_rate: int = 16000) -> bool:
    """RMS energy threshold fallback."""
    import array
    import math

    try:
        samples = array.array("h", audio_data)
        if len(samples) == 0:
            return False
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        return rms > 300
    except Exception:
        return False


# Backward-compatible interface
@timing(name="vad_detect")
def is_speech(audio_data: bytes, sample_rate: int = 16000) -> bool:
    return get_vad()(audio_data, sample_rate)


def is_speech_file(filepath: str) -> bool:
    import wave

    try:
        with wave.open(filepath, "rb") as wf:
            return is_speech(wf.readframes(wf.getnframes()), wf.getframerate())
    except Exception as e:
        logger.warning("VAD file check failed: %s", e)
        return True
