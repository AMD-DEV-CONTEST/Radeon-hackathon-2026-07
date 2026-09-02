import torch

from colorgraph.grading.color import apply_cdl, apply_tone_curve


def test_identity_cdl_preserves_pixels() -> None:
    image = torch.rand((2, 3, 8, 8))
    assert torch.allclose(apply_cdl(image), image)


def test_tone_curve_can_reduce_highlights_without_crushing_shadows() -> None:
    image = torch.tensor([[[[0.1, 0.9]], [[0.1, 0.9]], [[0.1, 0.9]]]])
    output = apply_tone_curve(image, highlights=-0.5)
    assert output[0, 0, 0, 1] < image[0, 0, 0, 1]
    assert torch.allclose(output[..., 0], image[..., 0], atol=0.01)
