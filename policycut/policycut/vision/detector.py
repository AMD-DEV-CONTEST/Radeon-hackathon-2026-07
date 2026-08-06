"""Keyframe visual detection.

GroundingDINO (zero-shot, via transformers) provides open-vocabulary detection
for all visual categories; YuNet (cv2.FaceDetectorYN) adds a fast, reliable
face detector that always runs when faces are targeted.

Heavy dependencies (torch, transformers) are imported lazily inside methods
and every failure is recorded as a warning instead of crashing. cv2 is also
imported lazily so this module can be imported on any machine.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DINO_BATCH_SIZE = 4
YUNET_SCORE_THRESHOLD = 0.6
YUNET_NMS_THRESHOLD = 0.3
DEFAULT_YUNET_PATH = "models/face_detection_yunet_2023mar.onnx"

# Default DINO prompts per category (contract section 3).
DEFAULT_PROMPTS: dict[str, list[str]] = {
    "face": ["human face"],
    "license_plate": ["license plate", "vehicle registration plate"],
    "id_document": ["identity card", "passport", "driver's license"],
    "screen": ["computer monitor", "laptop screen", "smartphone screen", "tablet screen"],
}


@dataclass
class Detection:
    """A single keyframe detection.

    box is (x, y, w, h) normalized to 0..1 relative to the frame.
    source is "dino" or "yunet".
    """

    t: float
    category: str
    box: tuple[float, float, float, float]
    score: float
    source: str


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _normalize_box(x1: float, y1: float, x2: float, y2: float, width: int, height: int
                   ) -> Optional[tuple[float, float, float, float]]:
    """Convert absolute xyxy to normalized xywh, clamped to the frame."""
    if width <= 0 or height <= 0:
        return None
    nx1 = _clamp01(x1 / width)
    ny1 = _clamp01(y1 / height)
    nx2 = _clamp01(x2 / width)
    ny2 = _clamp01(y2 / height)
    w = nx2 - nx1
    h = ny2 - ny1
    if w <= 1e-4 or h <= 1e-4:
        return None
    return (nx1, ny1, w, h)


def iou_xywh(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """IoU of two (x, y, w, h) boxes (any consistent unit)."""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = ix2 - ix1, iy2 - iy1
    if iw <= 0.0 or ih <= 0.0:
        return 0.0
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def nms_detections(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    """Greedy NMS applied per category per timestamp."""
    groups: dict[tuple[str, int], list[Detection]] = {}
    for det in detections:
        key = (det.category, int(round(det.t * 1000)))
        groups.setdefault(key, []).append(det)
    kept: list[Detection] = []
    for group in groups.values():
        group.sort(key=lambda d: d.score, reverse=True)
        chosen: list[Detection] = []
        for det in group:
            if all(iou_xywh(det.box, c.box) <= iou_threshold for c in chosen):
                chosen.append(det)
        kept.extend(chosen)
    kept.sort(key=lambda d: (d.t, d.category, -d.score))
    return kept


def _report(progress_cb: Optional[Callable], fraction: float, message: str = "") -> None:
    """Call a progress callback tolerating both cb(frac, msg) and cb(frac)."""
    if progress_cb is None:
        return
    fraction = max(0.0, min(1.0, fraction))
    try:
        progress_cb(fraction, message)
    except TypeError:
        try:
            progress_cb(fraction)
        except Exception:
            logger.debug("progress callback failed", exc_info=True)
    except Exception:
        logger.debug("progress callback failed", exc_info=True)


class VisualDetector:
    """Lazy-loading wrapper around GroundingDINO and YuNet."""

    def __init__(self, settings: Any):
        self.settings = settings
        self.warnings: list[str] = []
        self._dino: Optional[tuple] = None  # (processor, model, device, fp16)
        self._dino_failed = False
        self._yunet = None
        self._yunet_failed = False
        self._yunet_size: Optional[tuple[int, int]] = None

    # ------------------------------------------------------------------ DINO

    def _load_dino(self) -> Optional[tuple]:
        if self._dino is not None or self._dino_failed:
            return self._dino
        try:
            import torch  # noqa: F401
            from transformers import (  # type: ignore
                AutoModelForZeroShotObjectDetection,
                AutoProcessor,
            )

            try:
                from policycut.core.device import get_device
                device = get_device()
            except Exception:
                device = "cuda" if torch.cuda.is_available() else "cpu"

            if getattr(self.settings, "require_rocm", False) and device != "cuda":
                raise RuntimeError(
                    "POLICYCUT_REQUIRE_ROCM=1 but no ROCm/CUDA device is available "
                    "for GroundingDINO"
                )

            model_id = self.settings.dino_model
            processor = AutoProcessor.from_pretrained(model_id)
            model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id)
            # Keep weights fp32 and use autocast for the forward pass:
            # DINO's text branch mixes dtypes, so a blanket .half() breaks
            # ("expected scalar type Half but found Float"). Autocast gives
            # fp16 math on ROCm with fp32 master weights.
            fp16 = device == "cuda"
            model = model.to(device)
            model.eval()
            self._dino = (processor, model, device, fp16)
            logger.info("GroundingDINO %s loaded on %s (fp16=%s)", model_id, device, fp16)
        except Exception as exc:
            self._dino_failed = True
            if getattr(self.settings, "require_rocm", False) and isinstance(exc, RuntimeError):
                raise
            msg = f"grounding_dino_unavailable: {exc}"
            self.warnings.append(msg)
            logger.warning("GroundingDINO unavailable, DINO detection skipped: %s", exc)
        return self._dino

    @staticmethod
    def build_text_prompt(prompts_by_category: dict[str, list[str]]
                          ) -> tuple[str, dict[str, str]]:
        """Build the DINO text prompt and a phrase -> category map.

        Prompt format: lowercase phrases joined by ". " with a trailing ".".
        """
        phrase_to_category: dict[str, str] = {}
        ordered: list[str] = []
        for category, phrases in prompts_by_category.items():
            for phrase in phrases:
                p = str(phrase).strip().lower()
                if not p:
                    continue
                if p not in phrase_to_category:
                    phrase_to_category[p] = category
                    ordered.append(p)
        text = ". ".join(ordered) + "." if ordered else ""
        return text, phrase_to_category

    @staticmethod
    def _match_category(label: str, phrase_to_category: dict[str, str]) -> Optional[str]:
        """Map a predicted phrase back to a policy category."""
        lab = str(label).strip().lower()
        if not lab:
            return None
        if lab in phrase_to_category:
            return phrase_to_category[lab]
        for phrase, category in phrase_to_category.items():
            if phrase in lab or lab in phrase:
                return category
        # Token-overlap fallback (DINO sometimes returns partial/merged phrases).
        lab_tokens = set(lab.replace(".", " ").split())
        best_cat, best_score = None, 0.0
        for phrase, category in phrase_to_category.items():
            p_tokens = set(phrase.split())
            if not p_tokens or not lab_tokens:
                continue
            overlap = len(lab_tokens & p_tokens) / len(lab_tokens | p_tokens)
            if overlap > best_score:
                best_cat, best_score = category, overlap
        return best_cat if best_score >= 0.25 else None

    def detect_dino_batch(self, frames_bgr: list, timestamps: list[float],
                          prompts_by_category: dict[str, list[str]]) -> list[Detection]:
        """Run GroundingDINO on a batch of BGR frames."""
        if not frames_bgr or not prompts_by_category:
            return []
        bundle = self._load_dino()
        if bundle is None:
            return []
        processor, model, device, fp16 = bundle
        detections: list[Detection] = []
        try:
            import numpy as np
            import torch

            text, phrase_to_category = self.build_text_prompt(prompts_by_category)
            if not text:
                return []
            images = [np.ascontiguousarray(f[:, :, ::-1]) for f in frames_bgr]  # BGR -> RGB
            inputs = processor(
                images=images,
                text=[text] * len(images),
                return_tensors="pt",
                padding=True,
            )
            inputs = inputs.to(device)
            with torch.no_grad():
                if fp16:
                    with torch.autocast(device_type="cuda", dtype=torch.float16):
                        outputs = model(**inputs)
                else:
                    outputs = model(**inputs)
            target_sizes = [(f.shape[0], f.shape[1]) for f in frames_bgr]
            box_thr = float(getattr(self.settings, "box_threshold", 0.25))
            text_thr = float(getattr(self.settings, "text_threshold", 0.20))
            try:
                results = processor.post_process_grounded_object_detection(
                    outputs,
                    input_ids=inputs["input_ids"],
                    threshold=box_thr,
                    text_threshold=text_thr,
                    target_sizes=target_sizes,
                )
            except TypeError:
                # Older transformers signature uses box_threshold.
                results = processor.post_process_grounded_object_detection(
                    outputs,
                    inputs["input_ids"],
                    box_threshold=box_thr,
                    text_threshold=text_thr,
                    target_sizes=target_sizes,
                )
            for i, result in enumerate(results):
                t = timestamps[i]
                height, width = target_sizes[i]
                scores = result.get("scores")
                boxes = result.get("boxes")
                labels = result.get("text_labels", result.get("labels", []))
                if scores is None or boxes is None:
                    continue
                for score, box, label in zip(scores, boxes, labels):
                    category = self._match_category(str(label), phrase_to_category)
                    if category is None:
                        continue
                    vals = [float(v) for v in box.tolist()]
                    norm = _normalize_box(vals[0], vals[1], vals[2], vals[3], width, height)
                    if norm is None:
                        continue
                    detections.append(
                        Detection(
                            t=round(float(t), 3),
                            category=category,
                            box=norm,
                            score=float(score),
                            source="dino",
                        )
                    )
        except Exception as exc:
            msg = f"dino_batch_failed: {exc}"
            if msg not in self.warnings:
                self.warnings.append(msg)
            logger.warning("GroundingDINO batch failed at t~%.2fs: %s",
                           timestamps[0] if timestamps else -1.0, exc)
        return detections

    # ----------------------------------------------------------------- YuNet

    @staticmethod
    def yunet_model_path() -> Path:
        return Path(os.environ.get("POLICYCUT_YUNET") or DEFAULT_YUNET_PATH)

    def _load_yunet(self, frame_size: tuple[int, int]):
        """frame_size is (width, height)."""
        if self._yunet_failed:
            return None
        try:
            import cv2
        except Exception as exc:
            self._yunet_failed = True
            self.warnings.append(f"yunet_unavailable: {exc}")
            logger.warning("OpenCV unavailable for YuNet: %s", exc)
            return None
        if self._yunet is None:
            model_path = self.yunet_model_path()
            if not model_path.is_file():
                self._yunet_failed = True
                msg = f"yunet_model_missing: {model_path.name}"
                self.warnings.append(msg)
                logger.warning(
                    "YuNet model not found at %s (set POLICYCUT_YUNET); "
                    "face detection uses GroundingDINO only", model_path
                )
                return None
            try:
                self._yunet = cv2.FaceDetectorYN.create(
                    str(model_path), "", frame_size,
                    YUNET_SCORE_THRESHOLD, YUNET_NMS_THRESHOLD, 5000,
                )
                self._yunet_size = frame_size
            except Exception as exc:
                self._yunet_failed = True
                self.warnings.append(f"yunet_load_failed: {exc}")
                logger.warning("YuNet failed to load: %s", exc)
                return None
        elif frame_size != self._yunet_size:
            self._yunet.setInputSize(frame_size)
            self._yunet_size = frame_size
        return self._yunet

    def detect_faces(self, frame_bgr, t: float) -> list[Detection]:
        """Run YuNet face detection on one BGR frame."""
        height, width = frame_bgr.shape[:2]
        detector = self._load_yunet((width, height))
        if detector is None:
            return []
        detections: list[Detection] = []
        try:
            _, faces = detector.detect(frame_bgr)
            if faces is None:
                return []
            for face in faces:
                x, y, bw, bh = float(face[0]), float(face[1]), float(face[2]), float(face[3])
                score = float(face[-1])
                norm = _normalize_box(x, y, x + bw, y + bh, width, height)
                if norm is None:
                    continue
                detections.append(
                    Detection(
                        t=round(float(t), 3),
                        category="face",
                        box=norm,
                        score=score,
                        source="yunet",
                    )
                )
        except Exception as exc:
            msg = f"yunet_detect_failed: {exc}"
            if msg not in self.warnings:
                self.warnings.append(msg)
            logger.warning("YuNet detection failed at t=%.2fs: %s", t, exc)
        return detections


# --------------------------------------------------------------------- runner

def _prompts_from_policy(policy: Any) -> dict[str, list[str]]:
    """Extract {category: [prompt, ...]} from a PolicySpec (or dict-like)."""
    prompts: dict[str, list[str]] = {}
    targets = getattr(policy, "visual_targets", None)
    if targets is None and isinstance(policy, dict):
        targets = policy.get("visual_targets")
    for target in targets or []:
        if isinstance(target, dict):
            category = target.get("category")
            phrases = target.get("prompts") or []
        else:
            category = getattr(target, "category", None)
            phrases = list(getattr(target, "prompts", None) or [])
        if not category:
            continue
        phrases = [str(p).strip().lower() for p in phrases if str(p).strip()]
        if not phrases:
            phrases = list(DEFAULT_PROMPTS.get(category, [category.replace("_", " ")]))
        prompts.setdefault(category, [])
        for p in phrases:
            if p not in prompts[category]:
                prompts[category].append(p)
    return prompts


def run_detection(proxy_path, policy, settings, progress_cb: Optional[Callable] = None,
                  cancel_event=None) -> list[Detection]:
    """Sample proxy video keyframes and detect all policy visual targets.

    - GroundingDINO samples at settings.dino_interval_s (batched, batch size 4).
    - YuNet samples at settings.yunet_interval_s when faces are targeted.
    - Results are merged and NMS'd per category per timestamp.
    """
    prompts_by_category = _prompts_from_policy(policy)
    if not prompts_by_category:
        logger.info("No visual targets in policy; skipping visual detection")
        return []

    try:
        import cv2
    except Exception as exc:
        logger.warning("OpenCV unavailable; visual detection skipped: %s", exc)
        return []

    capture = cv2.VideoCapture(str(proxy_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open proxy video: {proxy_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    if fps <= 0.0 or fps != fps:  # NaN guard
        fps = 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    detector = VisualDetector(settings)
    face_targeted = "face" in prompts_by_category
    dino_interval = float(getattr(settings, "dino_interval_s", 0.5))
    yunet_interval = float(getattr(settings, "yunet_interval_s", 0.25))
    nms_iou = float(getattr(settings, "nms_iou", 0.50))

    detections: list[Detection] = []
    batch_frames: list = []
    batch_times: list[float] = []
    next_dino_t = 0.0
    next_yunet_t = 0.0
    epsilon = 1.0 / (2.0 * fps)
    frame_idx = 0
    cancelled = False

    def flush_batch() -> None:
        if not batch_frames:
            return
        detections.extend(
            detector.detect_dino_batch(batch_frames, batch_times, prompts_by_category)
        )
        batch_frames.clear()
        batch_times.clear()

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            t = frame_idx / fps

            if t + epsilon >= next_dino_t:
                while next_dino_t <= t + epsilon:
                    next_dino_t += dino_interval
                batch_frames.append(frame.copy())
                batch_times.append(t)
                if len(batch_frames) >= DINO_BATCH_SIZE:
                    flush_batch()
                    if frame_count > 0:
                        _report(progress_cb, frame_idx / frame_count,
                                f"Detecting visual targets ({t:.1f}s)")

            if face_targeted and t + epsilon >= next_yunet_t:
                while next_yunet_t <= t + epsilon:
                    next_yunet_t += yunet_interval
                detections.extend(detector.detect_faces(frame, t))

            if frame_count > 0 and frame_idx % 60 == 0:
                _report(progress_cb, frame_idx / frame_count,
                        f"Scanning frames ({t:.1f}s)")
            frame_idx += 1

        if not cancelled:
            flush_batch()
    finally:
        capture.release()

    merged = nms_detections(detections, nms_iou)
    _report(progress_cb, 1.0, f"Visual detection done: {len(merged)} detections")
    logger.info(
        "run_detection: %d raw -> %d after NMS (%d frames sampled, cancelled=%s, warnings=%s)",
        len(detections), len(merged), frame_idx, cancelled, detector.warnings,
    )
    return merged
