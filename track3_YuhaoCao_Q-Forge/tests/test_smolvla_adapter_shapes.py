import pytest
import torch

from smolvla_qvgm_rlinf.models.smolvla_rlinf_policy import SmolVLARLinfPolicy


def test_last_rgb_view_uint8_conversion():
    images = torch.zeros(2, 3, 32, 24, 3, dtype=torch.uint8)
    result = SmolVLARLinfPolicy._last_rgb_view(images, name="images")
    assert result.shape == (2, 3, 32, 24)
    assert result.dtype == torch.float32


def test_last_rgb_view_rejects_invalid_shape():
    with pytest.raises(ValueError, match="must be"):
        SmolVLARLinfPolicy._last_rgb_view(torch.zeros(32, 32, 3), name="images")
