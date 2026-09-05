"""Vision pipeline: YOLOv8 object detection + EasyOCR label reading.

Inference runs through ONNX Runtime. On AMD the ROCm execution provider
accelerates the detection model and the CRAFT text detector; if the EP is
unavailable we transparently fall back to CPU (logged for the benchmark and
optimization sections).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from config import CONFIG
from utils import MedGlassError

LOG = logging.getLogger("medglass.video")

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class Detection:
    kind: str                # medication | other COCO class
    bbox: tuple[int, int, int, int]
    confidence: float
    ocr_text: str | None = None


@dataclass
class FrameResult:
    detections: list[Detection] = field(default_factory=list)
    processed_ms: float = 0.0
    ocr_ms: float = 0.0
    metadata: dict = field(default_factory=dict)


# YOLOv8 COCO class names; we only care about the medication-like subset.
_COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]

# COCO index -> our medication categories (objects OCR is run on).
_MED_LIKE = {39: "bottle", 40: "wine glass", 73: "book", 76: "clock"}


def _nms(x1, y1, x2, y2, scores, iou_thr: float = 0.45):
    """Greedy non-max suppression. Accepts 1-D float arrays, returns indices."""
    import numpy as _np
    x1 = _np.asarray(x1, dtype=_np.float64)
    y1 = _np.asarray(y1, dtype=_np.float64)
    x2 = _np.asarray(x2, dtype=_np.float64)
    y2 = _np.asarray(y2, dtype=_np.float64)
    scores = _np.asarray(scores, dtype=_np.float64)
    if x1.size == 0:
        return []
    order = _np.argsort(-scores)
    keep = []
    areas = (x2 - x1) * (y2 - y1)
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = _np.maximum(x1[i], x1[order[1:]])
        yy1 = _np.maximum(y1[i], y1[order[1:]])
        xx2 = _np.minimum(x2[i], x2[order[1:]])
        yy2 = _np.minimum(y2[i], y2[order[1:]])
        w = _np.maximum(0.0, xx2 - xx1)
        h = _np.maximum(0.0, yy2 - yy1)
        inter = w * h
        union = areas[i] + areas[order[1:]] - inter
        iou = inter / _np.maximum(union, 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


class VideoProcessor:
    """Orchestrates detection -> OCR per frame."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or CONFIG
        self._detector = None
        self._ocr = None
        self._detector_loaded = False
        self._ocr_loaded = False

    # -- lazy model loading (memory budget friendly) ------------------------

    @property
    def detector(self):
        """ONNX Runtime session for YOLOv8n-seg, or None (no model)."""
        if not self._detector_loaded:
            self._detector = self._load_detector()
            self._detector_loaded = True
        return self._detector

    @property
    def ocr(self):
        if not self._ocr_loaded:
            self._ocr = self._load_ocr()
            self._ocr_loaded = True
        return self._ocr

    def _load_detector(self):
        from pathlib import Path
        if not Path(self.cfg["yolo_model"]).exists():
            LOG.warning("YOLO ONNX model missing -> detection disabled")
            return None
        try:
            import onnxruntime as ort
        except ImportError as exc:
            LOG.warning("onnxruntime not installed -> detection disabled")
            return None
        providers = []
        if self.cfg["yolo_rocm"]:
            providers.append("ROCMExecutionProvider")
        providers.append("CPUExecutionProvider")
        try:
            session = ort.InferenceSession(self.cfg["yolo_model"],
                                           providers=providers)
            active = session.get_providers()
            LOG.info("YOLO ONNX providers: %s", active)
            return session
        except Exception as exc:
            raise MedGlassError(f"failed to load YOLO ONNX model: {exc}")

    def _load_ocr(self):
        try:
            import easyocr
        except ImportError:
            LOG.warning("easyocr not installed -> OCR disabled "
                        "(medication labels won't be read)")
            return None
        reader = easyocr.Reader(self.cfg["ocr_languages"],
                                gpu=self.cfg["ocr_rocm"])
        LOG.info("EasyOCR loaded (gpu=%s)", self.cfg["ocr_rocm"])
        return reader

    # -- public API ---------------------------------------------------------

    def process_frame(self, frame: np.ndarray) -> FrameResult:
        """Detect medication-like objects and read their labels with OCR."""
        t0 = time.perf_counter()
        result = FrameResult()
        if frame is None:
            return result
        h, w = frame.shape[:2]

        dets = self._detect(frame)
        for det in dets:
            if det.kind == "medication":
                det.ocr_text = self._read_label(frame, det.bbox)
            result.detections.append(det)

        result.processed_ms = round((time.perf_counter() - t0) * 1000, 2)
        result.metadata["frame_shape"] = [h, w]
        return result

    # -- detection ----------------------------------------------------------

    def _detect(self, frame: np.ndarray) -> list[Detection]:
        session = self.detector
        if session is None:
            return []
        inp, ratio, pad = self._preprocess(frame)
        out = session.run(None, {session.get_inputs()[0].name: inp})
        return self._postprocess(out, ratio, pad, frame.shape[:2])

    def _preprocess(self, frame: np.ndarray):
        # Resize keeping aspect ratio into 640x640 with gray padding.
        size = 640
        h, w = frame.shape[:2]
        ratio = size / max(h, w)
        nw, nh = int(w * ratio), int(h * ratio)
        resized = cv2.resize(frame, (nw, nh))
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        pad_x = (size - nw) // 2
        pad_y = (size - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        inp = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        return inp, ratio, (pad_x, pad_y)

    def _postprocess(self, outputs, ratio, pad, shape):
        dets: list[Detection] = []
        px, py = pad
        out0 = outputs[0]

        # Standard Ultralytics YOLOv8 export (opset>=11, simplify off):
        #   out0: (1, 116, 8400) -> xywh(4) + cls_scores(80) + mask_coeffs(32)
        if out0.ndim == 3 and out0.shape[1] > 6:
            data = out0[0].T                        # (8400, 116)
            n_cls = len(_COCO_CLASSES)
            xywh = data[:, :4]
            cls_scores = data[:, 4:4 + n_cls]
            scores = cls_scores.max(axis=1)
            classes = cls_scores.argmax(axis=1)
            cx, cy, w, h = xywh[:, 0], xywh[:, 1], xywh[:, 2], xywh[:, 3]
            x1 = (cx - w / 2 - px) / ratio
            y1 = (cy - h / 2 - py) / ratio
            x2 = (cx + w / 2 - px) / ratio
            y2 = (cy + h / 2 - py) / ratio
        # Legacy 4-output export: [boxes(1,4,N), masks(1,32,N), scores, classes]
        elif len(outputs) >= 2 and outputs[0].shape[1] == 4:
            boxes = outputs[0][0]                  # (4, N)
            n = boxes.shape[1]
            scores = (outputs[2][0] if len(outputs) > 2
                      else np.zeros(n, dtype=np.float32))
            classes = (outputs[3][0] if len(outputs) > 3
                       else np.zeros(n, dtype=np.int64))
            x1 = (boxes[0] - px) / ratio
            y1 = (boxes[1] - py) / ratio
            x2 = (boxes[2] - px) / ratio
            y2 = (boxes[3] - py) / ratio
        else:
            LOG.warning("unexpected YOLO output layout: %s",
                        [o.shape for o in outputs])
            return dets

        keep = _nms(x1, y1, x2, y2, scores, iou_thr=0.45)
        for i in keep:
            score = float(scores[i])
            if score < self.cfg["yolo_conf"]:
                continue
            dets.append(self._classify(
                bbox=(x1[i], y1[i], x2[i], y2[i]),
                score=score, cls=int(classes[i])))
        return dets

    def _classify(self, bbox, score: float, cls: int) -> Detection:
        name = _COCO_CLASSES[cls] if cls < len(_COCO_CLASSES) else "unknown"
        if cls in _MED_LIKE:
            return Detection(kind="medication",
                             bbox=tuple(int(v) for v in bbox),
                             confidence=round(score, 3))
        # Other objects are not medication and are ignored (not sensitive).
        LOG.debug("ignored class %s", name)
        return Detection(kind=name, bbox=tuple(int(v) for v in bbox),
                         confidence=round(score, 3))

    # -- OCR ----------------------------------------------------------------

    def _read_label(self, frame: np.ndarray, bbox) -> str:
        if self.ocr is None:
            return ""
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return ""
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return ""
        try:
            result = self.ocr.readtext(roi)
            return " ".join(t for _, t, _ in result)
        except Exception as exc:  # pragma: no cover
            LOG.warning("OCR failed on ROI: %s", exc)
            return ""
