import numpy as np

from backend.config import Settings
from vision.face import FakeFaceDetector, create_face_detector
from vision.mouth import crop_mouth


def test_crop_mouth_returns_normalized_box_and_96_image():
    image = np.full((200, 300, 3), 128, dtype=np.uint8)
    landmarks = [(0.45, 0.55), (0.55, 0.55), (0.50, 0.62), (0.50, 0.50)]
    result = crop_mouth(image, landmarks, mouth_size=96)
    assert result.image.shape == (96, 96)
    assert result.image.dtype == np.uint8
    assert 0.0 <= result.box.x <= 1.0
    assert 0.0 <= result.box.y <= 1.0
    assert result.box.width > 0
    assert result.box.height > 0


def test_crop_mouth_uses_tighter_mouth_centered_roi():
    image = np.full((200, 300, 3), 128, dtype=np.uint8)
    landmarks = [(0.45, 0.55), (0.55, 0.55), (0.50, 0.62), (0.50, 0.50)]

    result = crop_mouth(image, landmarks, mouth_size=96)

    assert result.box.width < 0.24
    assert result.box.height < 0.31
    assert result.box.y > 0.40


def test_fake_face_detector_returns_one_face():
    detector = FakeFaceDetector()
    result = detector.detect(np.full((200, 300, 3), 128, dtype=np.uint8))
    assert result.face_detected is True
    assert result.face_count == 1
    assert len(result.landmarks) >= 4


def test_create_face_detector_uses_fake_backend_by_default():
    detector = create_face_detector(Settings(command_backend="fake"))
    assert isinstance(detector, FakeFaceDetector)
