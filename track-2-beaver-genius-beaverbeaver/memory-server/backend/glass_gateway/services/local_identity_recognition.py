from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class FaceBackend(Protocol):
    def recognize(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class VoiceBackend(Protocol):
    def recognize(
        self,
        wav_path: str,
        sample_rate: int,
        transcript: str,
    ) -> list[dict[str, Any]]: ...


class LocalIdentityRecognizer:
    """Local face/voice recognizer with optional heavy model backends.

    The bridge can run without InsightFace/SpeechBrain installed. When those
    packages are available, the lazy backends emit embeddings that the
    IdentityCandidateAggregator clusters into candidates.
    """

    def __init__(
        self,
        *,
        face_backend: FaceBackend | None = None,
        voice_backend: VoiceBackend | None = None,
        enable_face: bool = True,
        enable_voice: bool = True,
    ) -> None:
        self.face_backend = face_backend if face_backend is not None else (
            LazyInsightFaceBackend() if enable_face else None
        )
        self.voice_backend = voice_backend if voice_backend is not None else (
            LazySpeechBrainVoiceBackend() if enable_voice else None
        )

    async def recognize_window(
        self,
        *,
        wav_path: str,
        transcript: str,
        images: list[dict[str, Any]],
        sample_rate: int,
        speech_present: bool | None = None,
        **_: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        visible_people: list[dict[str, Any]] = []
        audio_speakers: list[dict[str, Any]] = []
        if self.face_backend is not None and images:
            try:
                visible_people = self.face_backend.recognize(images)
            except Exception:
                visible_people = []
        if self.voice_backend is not None and wav_path and speech_present is True:
            try:
                audio_speakers = self.voice_backend.recognize(wav_path, sample_rate, transcript)
            except Exception:
                audio_speakers = []
        return {
            "visible_people": [
                item for item in visible_people if isinstance(item, dict)
            ],
            "audio_speakers": [
                item for item in audio_speakers if isinstance(item, dict)
            ],
        }


class LazyInsightFaceBackend:
    def __init__(self, *, model_name: str = "buffalo_l", det_size: tuple[int, int] = (640, 640)) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self._app = None

    def recognize(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        app, cv2 = self._load()
        people: list[dict[str, Any]] = []
        for image in images:
            path = _path_from_uri(str(image.get("uri") or ""))
            if not path:
                continue
            frame = cv2.imread(str(path))
            if frame is None:
                continue
            for index, face in enumerate(app.get(frame)):
                embedding = getattr(face, "normed_embedding", None)
                if embedding is None:
                    embedding = getattr(face, "embedding", None)
                vector = _vector(embedding)
                if not vector:
                    continue
                bbox = getattr(face, "bbox", None)
                people.append(
                    {
                        "name": "",
                        "confidence": float(getattr(face, "det_score", 0.0) or 0.0),
                        "source": "face",
                        "embedding": vector,
                        "evidence_id": image.get("id") or f"face-{index}",
                        "bbox": _vector(bbox),
                    }
                )
        return people

    def _load(self):
        if self._app is not None:
            return self._app
        import cv2  # type: ignore
        import onnxruntime as ort  # type: ignore
        from insightface.app import FaceAnalysis  # type: ignore

        available = set(ort.get_available_providers())
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in available
            else ["CPUExecutionProvider"]
        )
        app = FaceAnalysis(name=self.model_name, providers=providers)
        app.prepare(ctx_id=0, det_size=self.det_size)
        self._app = (app, cv2)
        return self._app


class LazySpeechBrainVoiceBackend:
    def __init__(
        self,
        *,
        model_source: str = "speechbrain/spkrec-ecapa-voxceleb",
        device: str = "cuda:0",
    ) -> None:
        self.model_source = model_source
        self.device = device
        self._classifier = None

    def recognize(self, wav_path: str, sample_rate: int, transcript: str) -> list[dict[str, Any]]:
        classifier = self._load()
        signal = classifier.load_audio(wav_path)
        embedding = classifier.encode_batch(signal).squeeze()
        vector = _vector(embedding)
        if not vector:
            return []
        return [
            {
                "name": "",
                "confidence": 0.7,
                "source": "voice",
                "embedding": vector,
                "evidence_id": "window-audio",
                "transcript_hint": transcript[:200],
                "sample_rate": sample_rate,
            }
        ]

    def _load(self):
        if self._classifier is not None:
            return self._classifier
        try:
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
        except Exception:
            from speechbrain.pretrained import EncoderClassifier  # type: ignore

        try:
            import torch  # type: ignore

            device = self.device if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        self._classifier = EncoderClassifier.from_hparams(
            source=self.model_source,
            run_opts={"device": device},
        )
        return self._classifier


def _path_from_uri(uri: str) -> Path | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(parsed.path)
    if parsed.scheme:
        return None
    return Path(uri)


def _vector(value: Any) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "detach"):
        value = value.detach().cpu().flatten().tolist()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        return []
    output: list[float] = []
    for item in value[:2048]:
        if isinstance(item, (int, float)):
            output.append(float(item))
    return output
