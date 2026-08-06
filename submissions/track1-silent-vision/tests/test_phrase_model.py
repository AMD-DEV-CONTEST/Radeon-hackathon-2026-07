import pytest

from command.model import build_fixed_phrase_model, count_trainable_parameters


def test_phrase_model_shape_and_parameter_cap():
    torch = pytest.importorskip("torch")
    model = build_fixed_phrase_model(num_classes=2)
    logits, embedding = model(torch.rand(3, 12, 96, 96))
    assert logits.shape == (3, 2)
    assert embedding.shape == (3, 64)
    assert torch.allclose(embedding.norm(dim=1), torch.ones(3), atol=1e-5)
    assert count_trainable_parameters(model) < 150_000


def test_phrase_model_builder_rejects_first_head_over_parameter_cap():
    with pytest.raises(ValueError, match="parameter cap"):
        build_fixed_phrase_model(num_classes=1_598)


def test_phrase_model_largest_compliant_head_is_under_parameter_cap():
    pytest.importorskip("torch")
    largest_valid_model = build_fixed_phrase_model(num_classes=1_597)
    assert count_trainable_parameters(largest_valid_model) < 150_000


def test_phrase_model_uses_temporal_order():
    torch = pytest.importorskip("torch")
    torch.manual_seed(17)
    model = build_fixed_phrase_model(num_classes=2).eval()
    frames = torch.rand(1, 10, 96, 96)
    forward_logits, _ = model(frames)
    reverse_logits, _ = model(frames.flip(1))
    assert not torch.allclose(forward_logits, reverse_logits)


@pytest.mark.parametrize("shape", [(10, 96, 96), (1, 10, 95, 96), (1, 10, 96, 95)])
def test_phrase_model_rejects_invalid_frame_shape(shape):
    torch = pytest.importorskip("torch")
    model = build_fixed_phrase_model(num_classes=2)
    with pytest.raises(ValueError, match=r"\[B, T, 96, 96\]"):
        model(torch.rand(shape))
