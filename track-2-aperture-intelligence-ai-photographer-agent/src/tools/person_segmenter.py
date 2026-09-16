"""Local person-instance segmentation for clean coaching contours on ROCm."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Lock
from typing import Any

import torch
from PIL import Image


MODEL_NAME = "torchvision/maskrcnn_resnet50_fpn_v2-coco"
PERSON_LABEL = 1


def _require_local_checkpoint(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(
            f"Local Mask R-CNN checkpoint was not found: {path}. "
            "Core inference is offline-only; run "
            "scripts/download_person_segmenter.py before the demo."
        )
    return path


def _pixel_box(
    normalized: list[int], width: int, height: int
) -> tuple[float, float, float, float]:
    return tuple(
        value * (width if index % 2 == 0 else height) / 1000
        for index, value in enumerate(normalized)
    )  # type: ignore[return-value]


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(
        0.0, first[3] - first[1]
    )
    second_area = max(0.0, second[2] - second[0]) * max(
        0.0, second[3] - second[1]
    )
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _fallback_candidate_indices(
    candidates: list[dict[str, Any]],
    unused: set[int],
    limit: int,
) -> list[int]:
    """Pick bounded high-confidence people when VLM box coordinates drift.

    This recovery is used only after direct IoU matching fails. It does not
    alter Mask R-CNN output; it keeps the requested person count and selects
    the most confident remaining detections, using area only as a tie-breaker.
    """
    return sorted(
        unused,
        key=lambda index: (
            candidates[index]["score"],
            (candidates[index]["box"][2] - candidates[index]["box"][0])
            * (candidates[index]["box"][3] - candidates[index]["box"][1]),
        ),
        reverse=True,
    )[: max(0, limit)]


class PersonSegmenter:
    """Loads one official COCO Mask R-CNN and reuses it across requests."""

    def __init__(self, *, score_threshold: float = 0.70) -> None:
        if not torch.cuda.is_available() or torch.version.hip is None:
            raise RuntimeError("Person segmentation requires ROCm/HIP PyTorch.")
        from torchvision.models.detection import (
            MaskRCNN_ResNet50_FPN_V2_Weights,
            maskrcnn_resnet50_fpn_v2,
        )

        started = time.perf_counter()
        weights = MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT
        checkpoint = _require_local_checkpoint(weights_cache_path())
        self.model = maskrcnn_resnet50_fpn_v2(
            weights=None,
            weights_backbone=None,
        )
        try:
            state_dict = torch.load(
                checkpoint,
                map_location="cpu",
                weights_only=True,
            )
        except TypeError:
            state_dict = torch.load(checkpoint, map_location="cpu")
        self.model.load_state_dict(state_dict)
        self.model.eval().to("cuda")
        self.transforms = weights.transforms()
        self.score_threshold = score_threshold
        self.load_seconds = round(time.perf_counter() - started, 3)
        self.calls = 0

    @torch.inference_mode()
    def segment(
        self,
        image: Image.Image,
        primary_boxes: list[list[int]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        width, height = image.size
        tensor = self.transforms(image).to("cuda")
        torch.cuda.synchronize()
        inference_started = time.perf_counter()
        prediction = self.model([tensor])[0]
        torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - inference_started

        candidates: list[dict[str, Any]] = []
        labels = prediction["labels"].detach().cpu()
        scores = prediction["scores"].detach().cpu()
        boxes = prediction["boxes"].detach().cpu()
        masks = prediction["masks"].detach().cpu()
        for index, (label, score) in enumerate(zip(labels, scores)):
            if int(label) != PERSON_LABEL or float(score) < self.score_threshold:
                continue
            candidates.append(
                {
                    "score": float(score),
                    "box": tuple(float(value) for value in boxes[index].tolist()),
                    "mask": masks[index, 0],
                }
            )

        selected: list[dict[str, Any]] = []
        unused = set(range(len(candidates)))
        fallback_used = False
        for normalized in primary_boxes:
            target = _pixel_box(normalized, width, height)
            ranked = sorted(
                (
                    (_iou(target, candidates[index]["box"]), index)
                    for index in unused
                ),
                reverse=True,
            )
            if not ranked or ranked[0][0] < 0.08:
                continue
            _, match = ranked[0]
            unused.remove(match)
            selected.append(candidates[match])

        expected = min(len(primary_boxes), len(candidates))
        if primary_boxes and len(selected) < expected:
            fallback_used = True
            for match in _fallback_candidate_indices(
                candidates,
                unused,
                expected - len(selected),
            ):
                unused.remove(match)
                selected.append(candidates[match])

        if not primary_boxes:
            selected = sorted(
                candidates,
                key=lambda item: (
                    item["score"],
                    (item["box"][2] - item["box"][0])
                    * (item["box"][3] - item["box"][1]),
                ),
                reverse=True,
            )[:3]

        pil_masks: list[Image.Image] = []
        for item in selected:
            binary = (item["mask"] >= 0.5).to(torch.uint8).mul(255).numpy()
            pil_masks.append(Image.fromarray(binary, mode="L"))

        self.calls += 1
        return {
            "status": "generated" if pil_masks else "no_primary_person_mask",
            "masks": pil_masks,
            "model": MODEL_NAME,
            "detections": len(candidates),
            "people_matched": len(pil_masks),
            "match_mode": (
                "iou_with_detector_fallback" if fallback_used else "iou"
            ),
            "inference_seconds": round(inference_seconds, 3),
            "total_seconds": round(time.perf_counter() - started, 3),
            "model_load_seconds": self.load_seconds,
            "model_reused": self.calls > 1,
        }


_SHARED_SEGMENTER: PersonSegmenter | None = None
_SEGMENTER_LOCK = Lock()


def get_shared_person_segmenter() -> PersonSegmenter:
    global _SHARED_SEGMENTER
    if _SHARED_SEGMENTER is None:
        with _SEGMENTER_LOCK:
            if _SHARED_SEGMENTER is None:
                _SHARED_SEGMENTER = PersonSegmenter()
    return _SHARED_SEGMENTER


def weights_cache_path() -> Path:
    """Return the expected official checkpoint path for offline verification."""
    from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights

    filename = Path(MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT.url).name
    return Path(torch.hub.get_dir()) / "checkpoints" / filename
