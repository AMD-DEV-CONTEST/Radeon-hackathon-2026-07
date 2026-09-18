"""Detection coordinate mapping and class-aware NMS."""

from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.vision.schemas import LetterboxTransform


def map_box_to_original(
    box: BoundingBox, transform: LetterboxTransform
) -> BoundingBox | None:
    x1 = max(0.0, (box.x1 - transform.pad_x) / transform.scale)
    y1 = max(0.0, (box.y1 - transform.pad_y) / transform.scale)
    x2 = min(
        float(transform.original_width),
        (box.x2 - transform.pad_x) / transform.scale,
    )
    y2 = min(
        float(transform.original_height),
        (box.y2 - transform.pad_y) / transform.scale,
    )
    if x2 <= x1 or y2 <= y1:
        return None
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def class_aware_nms(
    detections: list[Detection], iou_threshold: float
) -> list[Detection]:
    if not 0 < iou_threshold <= 1:
        raise ValueError("NMS IoU threshold must be within (0, 1]")
    kept: list[Detection] = []
    by_class: dict[str, list[Detection]] = {}
    for detection in detections:
        by_class.setdefault(detection.label, []).append(detection)
    for label in sorted(by_class):
        candidates = sorted(
            by_class[label],
            key=lambda item: (
                -item.confidence,
                item.bounding_box.x1,
                item.bounding_box.y1,
            ),
        )
        while candidates:
            selected = candidates.pop(0)
            kept.append(selected)
            candidates = [
                item
                for item in candidates
                if selected.bounding_box.iou(item.bounding_box) <= iou_threshold
            ]
    return sorted(
        kept,
        key=lambda item: (-item.confidence, item.label, item.bounding_box.x1),
    )

