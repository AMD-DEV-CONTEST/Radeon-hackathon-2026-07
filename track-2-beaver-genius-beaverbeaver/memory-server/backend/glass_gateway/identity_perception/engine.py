from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable

from .contracts import StaleModelRevisionError


class InsightFaceIdentityEngine:
    """CUDA-side face detector/recognizer using the frozen MVP-11A contract."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        model_root: str | Path,
        allowed_media_root: str | Path,
        app_factory: Callable[[dict[str, Any], Path], Any] | None = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.model_root = Path(model_root).expanduser().resolve()
        self.allowed_media_root = Path(allowed_media_root).expanduser().resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.config_version = str(self.config["config_id"])
        self.model_revision = model_revision_from_config(self.config)
        self._app_factory = app_factory
        self._app: Any = None
        self._cv2: Any = None
        self._providers_by_model: dict[str, list[str]] = {}
        self._loaded_at_ms: int | None = None
        self._lock = threading.RLock()

    def recognize(
        self,
        *,
        image_path: str,
        media_type: str,
        expected_model_revision: str,
        expected_config_version: str,
    ) -> dict[str, Any]:
        with self._lock:
            return self._recognize_serialized(
                image_path=image_path,
                media_type=media_type,
                expected_model_revision=expected_model_revision,
                expected_config_version=expected_config_version,
            )

    def _recognize_serialized(
        self,
        *,
        image_path: str,
        media_type: str,
        expected_model_revision: str,
        expected_config_version: str,
    ) -> dict[str, Any]:
        if expected_model_revision != self.model_revision:
            raise StaleModelRevisionError(
                f"model revision mismatch: {expected_model_revision} != {self.model_revision}"
            )
        if expected_config_version != self.config_version:
            raise StaleModelRevisionError(
                f"config version mismatch: {expected_config_version} != {self.config_version}"
            )
        if media_type not in {"image/jpeg", "image/jpg", "image/png"}:
            raise ValueError(f"unsupported face image media type: {media_type}")
        path = Path(image_path).expanduser().resolve()
        if not path.is_relative_to(self.allowed_media_root):
            raise PermissionError("face image path is outside the controlled media root")
        if not path.is_file():
            raise FileNotFoundError(path)
        app, cv2 = self._load()
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError("failed to decode face image")
        started = time.perf_counter()
        faces = app.get(frame)
        latency_ms = (time.perf_counter() - started) * 1000.0
        height, width = frame.shape[:2]
        observations = [
            self._observation(face, frame, index=index, width=width, height=height)
            for index, face in enumerate(faces)
        ]
        observations.sort(
            key=lambda item: (
                item["bbox_xyxy"][0],
                item["bbox_xyxy"][1],
                -item["quality"]["face_area_pixels"],
            )
        )
        for index, item in enumerate(observations):
            item["face_index"] = index
        return {
            "status": "ready" if observations else "ready_no_face",
            "model_id": str(self.config["model"]["pack"]),
            "model_revision": self.model_revision,
            "config_version": self.config_version,
            "input_width": width,
            "input_height": height,
            "latency_ms": round(latency_ms, 3),
            "observations": observations,
            "device": "cuda:0",
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "loaded": self._app is not None,
            "model_id": str(self.config["model"]["pack"]),
            "model_revision": self.model_revision,
            "config_version": self.config_version,
            "providers_by_model": dict(self._providers_by_model),
            "loaded_at_ms": self._loaded_at_ms,
            "allowed_media_root": str(self.allowed_media_root),
        }

    def _load(self) -> tuple[Any, Any]:
        if self._app is not None:
            return self._app, self._cv2
        import cv2

        if self._app_factory is not None:
            app = self._app_factory(self.config, self.model_root)
        else:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis

            providers = list(self.config["model"]["providers_required"])
            missing = [
                provider
                for provider in providers
                if provider not in set(ort.get_available_providers())
            ]
            if missing:
                raise RuntimeError(f"required ONNX providers missing: {missing}")
            _verify_model_hashes(self.config, self.model_root)
            app = FaceAnalysis(
                name=str(self.config["model"]["pack"]),
                root=str(self.model_root),
                allowed_modules=["detection", "recognition"],
                providers=providers,
            )
            app.prepare(
                ctx_id=0,
                det_size=tuple(self.config["model"]["detector_input_size"]),
                det_thresh=float(self.config["model"]["detection_threshold"]),
            )
        providers_by_model: dict[str, list[str]] = {}
        for name, model in getattr(app, "models", {}).items():
            session = getattr(model, "session", None)
            if session is not None:
                providers_by_model[str(name)] = list(session.get_providers())
        if self._app_factory is None and any(
            "CUDAExecutionProvider" not in providers
            for providers in providers_by_model.values()
        ):
            raise RuntimeError("identity model silently missed CUDAExecutionProvider")
        self._app = app
        self._cv2 = cv2
        self._providers_by_model = providers_by_model
        self._loaded_at_ms = int(time.time() * 1000)
        return app, cv2

    def _observation(
        self,
        face: Any,
        frame: Any,
        *,
        index: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        cv2 = self._cv2
        raw_bbox = [float(value) for value in face.bbox.tolist()]
        x1 = max(0.0, min(float(width - 1), raw_bbox[0]))
        y1 = max(0.0, min(float(height - 1), raw_bbox[1]))
        x2 = max(x1 + 1.0, min(float(width), raw_bbox[2]))
        y2 = max(y1 + 1.0, min(float(height), raw_bbox[3]))
        bbox = [x1, y1, x2, y2]
        ix1, iy1 = max(0, int(x1)), max(0, int(y1))
        ix2, iy2 = min(width, int(math.ceil(x2))), min(height, int(math.ceil(y2)))
        crop = frame[iy1:iy2, ix1:ix2]
        blur = 0.0
        if crop.size:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        frame_area = max(1, width * height)
        detection_score = float(getattr(face, "det_score", 0.0) or 0.0)
        landmarks = getattr(face, "kps", None)
        five_landmarks = landmarks is not None and len(landmarks) == 5
        pitch, yaw, roll = _face_pose(face, landmarks)
        quality = self.config["quality"]
        reasons: list[str] = []
        if detection_score < float(quality["min_detection_score"]):
            reasons.append("low_detection_score")
        if area < float(quality["min_face_area_pixels"]):
            reasons.append("face_too_small_pixels")
        if area / frame_area < float(quality["min_face_frame_ratio"]):
            reasons.append("face_too_small_ratio")
        if blur < float(quality["min_laplacian_variance"]):
            reasons.append("blurred")
        if bool(quality["require_five_landmarks"]) and not five_landmarks:
            reasons.append("missing_landmarks")
        max_yaw = quality.get("max_abs_yaw_degrees")
        if yaw is not None and max_yaw is not None and abs(yaw) > float(max_yaw):
            reasons.append("extreme_yaw")
        embedding_value = getattr(face, "normed_embedding", None)
        if embedding_value is None:
            embedding_value = getattr(face, "embedding", None)
        embedding = (
            [float(value) for value in embedding_value.tolist()]
            if embedding_value is not None
            else []
        )
        if not embedding:
            raise RuntimeError("InsightFace returned a face without embedding")
        return {
            "face_index": index,
            "bbox_xyxy": bbox,
            "detection_score": detection_score,
            "quality": {
                "eligible_for_match": not reasons,
                "reason_codes": reasons,
                "face_area_pixels": round(area, 3),
                "face_frame_ratio": round(area / frame_area, 9),
                "laplacian_variance": round(blur, 3),
                "five_landmarks_available": five_landmarks,
                "pitch_degrees": round(pitch, 3) if pitch is not None else None,
                "yaw_degrees": round(yaw, 3) if yaw is not None else None,
                "roll_degrees": round(roll, 3) if roll is not None else None,
                "pose_bucket": _pose_bucket(yaw),
            },
            "embedding": embedding,
        }


def _face_pose(face: Any, landmarks: Any) -> tuple[float | None, float | None, float | None]:
    pose = getattr(face, "pose", None)
    if pose is not None:
        values = pose.tolist() if hasattr(pose, "tolist") else pose
        if isinstance(values, (list, tuple)) and len(values) >= 3:
            return float(values[0]), float(values[1]), float(values[2])
    if landmarks is None:
        return None, None, None
    values = landmarks.tolist() if hasattr(landmarks, "tolist") else landmarks
    if not isinstance(values, (list, tuple)) or len(values) != 5:
        return None, None, None
    try:
        left_eye, right_eye, nose = values[0], values[1], values[2]
        eye_distance = math.dist(
            (float(left_eye[0]), float(left_eye[1])),
            (float(right_eye[0]), float(right_eye[1])),
        )
        if eye_distance <= 1e-6:
            return None, None, None
        eye_mid_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
        yaw = max(-90.0, min(90.0, (float(nose[0]) - eye_mid_x) / eye_distance * 90.0))
        roll = math.degrees(
            math.atan2(
                float(right_eye[1]) - float(left_eye[1]),
                float(right_eye[0]) - float(left_eye[0]),
            )
        )
        return None, yaw, roll
    except (IndexError, TypeError, ValueError):
        return None, None, None


def _pose_bucket(yaw: float | None) -> str:
    if yaw is None:
        return "unknown"
    if yaw <= -20.0:
        return "left_profile"
    if yaw >= 20.0:
        return "right_profile"
    return "frontal"


def model_revision_from_config(config_or_path: dict[str, Any] | str | Path) -> str:
    """Return the worker contract revision without loading CUDA/model weights."""

    config = (
        config_or_path
        if isinstance(config_or_path, dict)
        else json.loads(Path(config_or_path).read_text(encoding="utf-8"))
    )
    model = config["model"]
    payload = "\n".join(
        (
            str(model["pack"]),
            str(model["detector_sha256"]),
            str(model["recognizer_sha256"]),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_model_hashes(config: dict[str, Any], model_root: Path) -> None:
    pack_dir = model_root / "models" / str(config["model"]["pack"])
    expected = {
        "det_10g.onnx": str(config["model"]["detector_sha256"]),
        "w600k_r50.onnx": str(config["model"]["recognizer_sha256"]),
    }
    for filename, expected_sha256 in expected.items():
        path = pack_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError(f"identity model hash mismatch: {filename}")
