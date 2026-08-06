import cv2
import numpy as np

from colorgraph.vision import video_masks
from colorgraph.vision.video_masks import (
    _calculate_backward_flow,
    _propagate_mask,
    _unlink_with_retry,
)


def test_optical_flow_propagates_translated_mask() -> None:
    previous = np.zeros((80, 120), dtype=np.uint8)
    current = np.zeros_like(previous)
    cv2.rectangle(previous, (20, 25), (45, 50), 255, -1)
    cv2.rectangle(current, (24, 25), (49, 50), 255, -1)
    mask = (previous > 0).astype(np.float32)
    backward_flow = _calculate_backward_flow(previous, current)
    propagated = _propagate_mask(mask, backward_flow)
    source_center = propagated[37, 32]
    target_center = propagated[37, 45]
    assert target_center > 0.5
    assert target_center >= source_center


def test_locked_stale_mask_is_retried(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "000299.png"
    target.write_bytes(b"mask")
    original_unlink = video_masks.Path.unlink
    attempts = 0

    class SharingViolation(OSError):
        winerror = 32

    def flaky_unlink(path, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SharingViolation("file is in use")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(video_masks.Path, "unlink", flaky_unlink)
    monkeypatch.setattr(video_masks.time, "sleep", lambda _seconds: None)

    _unlink_with_retry(target)

    assert attempts == 3
    assert not target.exists()
