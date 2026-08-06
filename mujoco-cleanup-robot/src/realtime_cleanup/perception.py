"""ROCm YOLOE RGB-D perception with explicit unknown-object handling."""

from __future__ import annotations

import math
import time

import cv2
import numpy as np
import torch

from realtime_cleanup.provenance import ModelArtifact
from realtime_cleanup.telemetry import TraceWriter, array_sha256, gpu_identity
from realtime_cleanup.types import Detection, SensorPacket


KNOWN_LABELS = {
    "can": "can",
    "tin can": "can",
    "soda can": "can",
    "bottle": "bottle",
    "plastic bottle": "bottle",
    "carton": "carton",
    "cardboard box": "carton",
    "cup": "cup",
    "mug": "cup",
    "orange": "orange",
    "orange fruit": "orange",
    "banana": "banana",
    "yellow banana": "banana",
    "paper": "paper",
    "sheet of paper": "paper",
    "snack bag": "snack_bag",
    "chip bag": "snack_bag",
    "toy": "toy",
}


class YOLOEPerception:
    def __init__(
        self,
        artifact: ModelArtifact,
        trace: TraceWriter,
        *,
        device_index: int = 0,
        confidence: float = 0.05,
        image_size: int = 640,
    ) -> None:
        from ultralytics import YOLO, YOLOE

        self.artifact = artifact
        self.trace = trace
        self.device_index = device_index
        self.confidence = confidence
        self.image_size = image_size
        self.gpu = gpu_identity(device_index)
        self.last_inference_ms = float("nan")
        model_type = YOLO if artifact.architecture.endswith("-Detect") else YOLOE
        self.model = model_type(str(artifact.path))

    @staticmethod
    def _mask_at_image_size(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        if mask.shape == shape:
            return mask > 0.5
        return cv2.resize(
            mask.astype(np.float32),
            (shape[1], shape[0]),
            interpolation=cv2.INTER_NEAREST,
        ) > 0.5

    @staticmethod
    def _project(
        depth_m: np.ndarray,
        mask: np.ndarray,
        bbox: tuple[int, int, int, int],
        fovy_degrees: float,
    ) -> tuple[np.ndarray, tuple[float, float]] | None:
        height, width = depth_m.shape
        x1, y1, x2, y2 = bbox
        valid = mask & np.isfinite(depth_m) & (depth_m > 0.04) & (depth_m < 5.0)
        ys, xs = np.nonzero(valid)
        if len(xs) < 8:
            crop = depth_m[max(0, y1) : min(height, y2), max(0, x1) : min(width, x2)]
            values = crop[np.isfinite(crop) & (crop > 0.04) & (crop < 5.0)]
            if values.size < 8:
                return None
            u = 0.5 * (x1 + x2)
            v = 0.5 * (y1 + y2)
            depth = float(np.median(values))
        else:
            u = float(np.median(xs))
            v = float(np.median(ys))
            depth = float(np.median(depth_m[valid]))
        focal = height / (2.0 * math.tan(math.radians(fovy_degrees) / 2.0))
        center = np.array(
            [
                (u - (width - 1) / 2.0) * depth / focal,
                (v - (height - 1) / 2.0) * depth / focal,
                depth,
            ],
            dtype=np.float32,
        )
        physical_width = max(0, x2 - x1) * depth / focal
        physical_height = max(0, y2 - y1) * depth / focal
        return center, (float(physical_width), float(physical_height))

    @staticmethod
    def _canonical_label(source_label: str, physical_size: tuple[float, float]) -> tuple[str, bool]:
        normalized = source_label.lower().replace("_", " ").strip()
        if normalized in KNOWN_LABELS:
            return KNOWN_LABELS[normalized], False
        width, height = physical_size
        graspable = 0.01 <= width <= 0.22 and 0.01 <= height <= 0.30
        return ("unknown_graspable" if graspable else "unknown_ungraspable"), True

    def infer(self, packet: SensorPacket) -> list[Detection]:
        torch.cuda.synchronize(self.device_index)
        start = time.perf_counter_ns()
        result = self.model.predict(
            packet.head_rgb[:, :, ::-1],
            device=self.device_index,
            imgsz=self.image_size,
            conf=self.confidence,
            verbose=False,
        )[0]
        torch.cuda.synchronize(self.device_index)
        inference_ms = (time.perf_counter_ns() - start) / 1_000_000.0
        self.last_inference_ms = inference_ms

        if result.boxes is None:
            boxes = np.empty((0, 4), dtype=np.float32)
            scores = np.empty((0,), dtype=np.float32)
            class_ids = np.empty((0,), dtype=np.int64)
        else:
            boxes = result.boxes.xyxy.detach().float().cpu().numpy()
            scores = result.boxes.conf.detach().float().cpu().numpy()
            class_ids = result.boxes.cls.detach().long().cpu().numpy()
        masks = (
            result.masks.data.detach().float().cpu().numpy()
            if result.masks is not None
            else np.zeros((len(boxes), *packet.head_depth_m.shape), dtype=np.float32)
        )

        trace_id = self.trace.write(
            kind="perception",
            model={**self.artifact.trace_metadata(), "device": self.gpu},
            inputs={
                "frame_id": packet.frame_id,
                "rgb_sha256": array_sha256(packet.head_rgb),
                "depth_sha256": array_sha256(packet.head_depth_m),
            },
            outputs={
                "detections": len(boxes),
                "class_ids": class_ids.tolist(),
                "scores": scores.tolist(),
            },
            timing={"inference_ms": inference_ms},
            raw_arrays={
                "boxes_xyxy": boxes,
                "scores": scores,
                "class_ids": class_ids,
                "masks": masks.astype(np.float16),
            },
        )

        detections: list[Detection] = []
        names = result.names
        for index, (box, score, class_id) in enumerate(
            zip(boxes, scores, class_ids, strict=False)
        ):
            bbox = tuple(int(round(value)) for value in box)
            mask = self._mask_at_image_size(masks[index], packet.head_depth_m.shape)
            projected = self._project(
                packet.head_depth_m,
                mask,
                bbox,
                packet.head_fovy_degrees,
            )
            if projected is None:
                continue
            center, physical_size = projected
            if not (
                0.01 <= physical_size[0] <= 0.22
                and 0.01 <= physical_size[1] <= 0.30
            ):
                continue
            source_label = str(names.get(int(class_id), int(class_id)))
            label, unknown = self._canonical_label(source_label, physical_size)
            if label == "unknown_ungraspable":
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
                    unknown=unknown,
                    trace_id=trace_id,
                )
            )
        return sorted(detections, key=lambda item: item.confidence, reverse=True)
