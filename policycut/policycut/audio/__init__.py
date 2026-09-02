"""Audio analysis and redaction subpackage for PolicyCut.

Modules
-------
transcribe : Whisper (transformers pipeline) transcription with word timestamps.
spoken     : Pure-python normalization of spoken digits / emails ("zero"->"0", "at"->"@").
pii        : Regex + spoken-form (+ optional presidio) PII detection -> audio RedactionEvents.
effects    : Pure-numpy mute/beep application with 10 ms fades.

This package intentionally performs no imports at package level: heavy ML
dependencies (torch, transformers, presidio) are imported lazily inside
functions of the submodules.
"""

__all__ = ["transcribe", "spoken", "pii", "effects"]
