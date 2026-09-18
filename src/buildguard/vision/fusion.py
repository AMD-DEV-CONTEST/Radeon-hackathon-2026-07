"""Multi-model detection fusion."""

from buildguard.schemas.vision import Detection
from buildguard.vision.postprocessing import class_aware_nms


def fuse_detections(
    detector_results: list[list[Detection]], nms_iou: float
) -> list[Detection]:
    combined = [detection for result in detector_results for detection in result]
    return class_aware_nms(combined, nms_iou) if combined else []

