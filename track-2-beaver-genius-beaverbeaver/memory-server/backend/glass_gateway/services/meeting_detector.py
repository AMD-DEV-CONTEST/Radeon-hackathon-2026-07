from dataclasses import dataclass
from math import sqrt
import struct


@dataclass(frozen=True)
class DetectorEvent:
    kind: str
    at_ms: int


class MeetingDetector:
    def __init__(
        self,
        sample_rate: int,
        speech_rms: int,
        start_speech_ms: int,
        end_silence_ms: int,
    ) -> None:
        self.sample_rate = sample_rate
        self.speech_rms = speech_rms
        self.start_speech_ms = start_speech_ms
        self.end_silence_ms = end_silence_ms
        self.speech_ms = 0
        self.silence_ms = 0
        self.active = False

    def ingest(self, captured_at_ms: int, pcm: bytes) -> list[DetectorEvent]:
        values = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
        duration_ms = round(len(values) * 1000 / self.sample_rate)
        rms = sqrt(sum(value * value for value in values) / max(1, len(values)))
        speech = rms >= self.speech_rms
        events: list[DetectorEvent] = []

        if not self.active:
            self.speech_ms = self.speech_ms + duration_ms if speech else 0
            if self.speech_ms >= self.start_speech_ms:
                self.active = True
                self.silence_ms = 0
                events.append(DetectorEvent("speech.started", captured_at_ms))
        else:
            self.silence_ms = 0 if speech else self.silence_ms + duration_ms
            if self.silence_ms >= self.end_silence_ms:
                self.active = False
                self.speech_ms = 0
                events.append(DetectorEvent("speech.ended", captured_at_ms))

        return events
