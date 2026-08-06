"""YOLO11 plus real-time depth components for TidyBot target perception."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import torch

from realtime_cleanup.perception import YOLOEPerception
from realtime_cleanup.provenance import sha256_file
from realtime_cleanup.telemetry import TraceWriter, array_sha256, gpu_identity
from realtime_cleanup.types import Detection, TidyBotSensorPacket


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_YOLO11 = (
    PROJECT_ROOT
    / "runs"
    / "detect"
    / "outputs"
    / "detector"
    / "livingroom_v2"
    / "weights"
    / "best.pt"
)


def _install_rocm_nms_fallback() -> str:
    """Use Ultralytics' equivalent Torch NMS when ROCm torchvision lacks its op."""

    if torch.version.hip is None:
        return "torchvision.ops.nms"
    import torchvision
    from ultralytics.utils.nms import TorchNMS

    try:
        boxes = torch.tensor([[0.0, 0.0, 1.0, 1.0]], device="cuda")
        torchvision.ops.nms(boxes, torch.ones(1, device="cuda"), 0.5)
        return "torchvision.ops.nms"
    except NotImplementedError:
        torchvision.ops.nms = TorchNMS.nms
        return "ultralytics.TorchNMS.nms-rocm-fallback"


def detection_goal_view(
    workspace_rgb: np.ndarray,
    detection: Detection,
    *,
    output_size: tuple[int, int] = (256, 256),
    context_scale: float = 1.35,
) -> np.ndarray:
    """Create a policy goal image from a sensor detector box only."""

    if context_scale < 1.0:
        raise ValueError("context_scale must be at least one")
    height, width = workspace_rgb.shape[:2]
    x1, y1, x2, y2 = detection.bbox_xyxy
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    side = max(4.0, max(x2 - x1, y2 - y1) * context_scale)
    left = max(0, int(round(center_x - side / 2.0)))
    right = min(width, int(round(center_x + side / 2.0)))
    top = max(0, int(round(center_y - side / 2.0)))
    bottom = min(height, int(round(center_y + side / 2.0)))
    crop = workspace_rgb[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("detection does not overlap the workspace image")
    return cv2.resize(crop, output_size, interpolation=cv2.INTER_AREA)


class YOLO11DepthPerception:
    """Fixed-class detector whose masks come only from measured depth."""

    def __init__(
        self,
        trace: TraceWriter,
        *,
        weights: Path = DEFAULT_YOLO11,
        device_index: int = 0,
        confidence: float = 0.20,
        image_size: int = 640,
    ) -> None:
        from ultralytics import YOLO

        self.nms_backend = _install_rocm_nms_fallback()
        self.weights = Path(weights)
        if not self.weights.is_file():
            raise FileNotFoundError(self.weights)
        self.trace = trace
        self.device_index = device_index
        self.confidence = confidence
        self.image_size = image_size
        self.gpu = gpu_identity(device_index)
        self.sha256 = sha256_file(self.weights)
        self.model = YOLO(str(self.weights))
        self.last_inference_ms = float("nan")

    @staticmethod
    def _depth_component(
        depth_m: np.ndarray,
        bbox: tuple[int, int, int, int],
    ) -> np.ndarray | None:
        """Select a coherent near-depth component inside a detector box."""

        height, width = depth_m.shape
        x1, y1, x2, y2 = bbox
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        if x2 - x1 < 3 or y2 - y1 < 3:
            return None
        crop = depth_m[y1:y2, x1:x2]
        valid = np.isfinite(crop) & (crop > 0.04) & (crop < 5.0)
        values = crop[valid]
        if values.size < 16:
            return None
        near = float(np.percentile(values, 25))
        band = max(0.06, 0.10 * near)
        candidate = valid & (crop <= near + band)
        kernel = np.ones((3, 3), dtype=np.uint8)
        candidate = cv2.morphologyEx(
            candidate.astype(np.uint8),
            cv2.MORPH_OPEN,
            kernel,
        )
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=8)
        if count <= 1:
            return None
        center = ((y2 - y1) // 2, (x2 - x1) // 2)
        center_label = int(labels[center])
        if center_label == 0:
            center_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        if int(stats[center_label, cv2.CC_STAT_AREA]) < 12:
            return None
        mask = np.zeros_like(depth_m, dtype=bool)
        mask[y1:y2, x1:x2] = labels == center_label
        return mask

    def infer(self, packet: TidyBotSensorPacket) -> list[Detection]:
        torch.cuda.synchronize(self.device_index)
        started = time.perf_counter_ns()
        result = self.model.predict(
            packet.workspace_rgb[:, :, ::-1],
            device=self.device_index,
            imgsz=self.image_size,
            conf=self.confidence,
            verbose=False,
        )[0]
        torch.cuda.synchronize(self.device_index)
        inference_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        self.last_inference_ms = inference_ms
        if result.boxes is None:
            boxes = np.empty((0, 4), dtype=np.float32)
            scores = np.empty((0,), dtype=np.float32)
            class_ids = np.empty((0,), dtype=np.int64)
        else:
            boxes = result.boxes.xyxy.detach().float().cpu().numpy()
            scores = result.boxes.conf.detach().float().cpu().numpy()
            class_ids = result.boxes.cls.detach().long().cpu().numpy()

        trace_id = self.trace.write(
            kind="tidybot_perception",
            model={
                "architecture": "YOLO11s-Detect+DepthComponents",
                "path": str(self.weights),
                "sha256": self.sha256,
                "device": self.gpu,
                "nms_backend": self.nms_backend,
            },
            inputs={
                "frame_id": packet.frame_id,
                "rgb_sha256": array_sha256(packet.workspace_rgb),
                "depth_sha256": array_sha256(packet.workspace_depth_m),
            },
            outputs={
                "boxes": len(boxes),
                "scores": scores.tolist(),
                "class_ids": class_ids.tolist(),
            },
            timing={"inference_ms": inference_ms},
            raw_arrays={
                "boxes_xyxy": boxes,
                "scores": scores,
                "class_ids": class_ids,
            },
        )

        names = result.names
        detections = []
        for box, score, class_id in zip(boxes, scores, class_ids, strict=False):
            bbox = tuple(int(round(value)) for value in box)
            mask = self._depth_component(packet.workspace_depth_m, bbox)
            if mask is None:
                continue
            projected = YOLOEPerception._project(
                packet.workspace_depth_m,
                mask,
                bbox,
                packet.workspace_fovy_degrees,
            )
            if projected is None:
                continue
            center, physical_size = projected
            source_label = str(names.get(int(class_id), int(class_id)))
            label, unknown = YOLOEPerception._canonical_label(source_label, physical_size)
            if unknown:
                continue
            detections.append(
                Detection(
                    label=label,
                    source_label=source_label,
                    confidence=float(score),
                    bbox_xyxy=bbox,
                    mask=mask,
                    center_camera_m=center,
                    physical_size_m=physical_size,
                    unknown=False,
                    trace_id=trace_id,
                )
            )
        return sorted(detections, key=lambda item: item.confidence, reverse=True)
