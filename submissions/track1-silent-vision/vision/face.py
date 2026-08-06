import warnings
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from backend.config import Settings

MOUTH_LANDMARK_IDS = (
    61,
    146,
    91,
    181,
    84,
    17,
    314,
    405,
    321,
    375,
    291,
    78,
    95,
    88,
    178,
    87,
    14,
    317,
    402,
    318,
    324,
    308,
)


@dataclass(frozen=True)
class FaceDetectionResult:
    face_detected: bool
    landmarks: list[tuple[float, float]]
    face_count: int


class FaceDetectorProtocol(Protocol):
    def detect(self, image_rgb: np.ndarray) -> FaceDetectionResult:
        raise NotImplementedError


class FaceDetector:
    def __init__(self) -> None:
        warnings.filterwarnings(
            "ignore",
            message=r"SymbolDatabase.GetPrototype\(\) is deprecated.*",
            category=UserWarning,
            module=r"google\.protobuf\.symbol_database",
        )
        face_mesh = _import_face_mesh_module()

        self._mesh = face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=2,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def detect(self, image_rgb: np.ndarray) -> FaceDetectionResult:
        result = self._mesh.process(image_rgb)
        faces = result.multi_face_landmarks or []
        if len(faces) != 1:
            return FaceDetectionResult(face_detected=False, landmarks=[], face_count=len(faces))
        landmarks = []
        for index in MOUTH_LANDMARK_IDS:
            point = faces[0].landmark[index]
            landmarks.append((float(point.x), float(point.y)))
        return FaceDetectionResult(face_detected=True, landmarks=landmarks, face_count=1)


class FakeFaceDetector:
    def detect(self, image_rgb: np.ndarray) -> FaceDetectionResult:
        return FaceDetectionResult(
            face_detected=True,
            face_count=1,
            landmarks=[(0.45, 0.55), (0.55, 0.55), (0.50, 0.62), (0.50, 0.50)],
        )


def create_face_detector(settings: Settings) -> FaceDetectorProtocol:
    if settings.command_backend == "fake":
        return FakeFaceDetector()
    return FaceDetector()


def _import_face_mesh_module():
    import mediapipe as mp

    solutions = getattr(mp, "solutions", None)
    if solutions is not None:
        return solutions.face_mesh

    from mediapipe.python.solutions import face_mesh

    return face_mesh
