"""Unit tests for src.core.base_model — Strategy interface contract.

No real model loading, no GPU. We just verify the contract.
"""
import pytest

from src.core.base_model import BaseModel, GenerationRequest, GenerationResult


def test_generation_request_defaults_are_sensible():
    """GenerationRequest should provide working defaults so callers only set what they need."""
    req = GenerationRequest(prompt="a cat")
    assert req.prompt == "a cat"
    assert req.negative_prompt == ""
    assert req.height == 1024 and req.width == 1024
    assert req.num_inference_steps == 30
    assert req.guidance_scale == 7.5
    assert req.init_image is None
    assert req.style_image is None
    assert req.mask_image is None
    assert req.extra == {}


def test_subclass_must_implement_abstract_methods():
    """A subclass that forgets generate() / load() must fail to instantiate."""

    class BadModel(BaseModel):
        pass

    with pytest.raises(TypeError):
        BadModel(model_id="x")  # type: ignore[abstract]


def test_concrete_subclass_lifecycle():
    """A valid subclass should report is_loaded=False until load(), then False again after unload()."""

    class FakeModel(BaseModel):
        def load(self) -> None:
            self._loaded = True

        def generate(self, request):
            return GenerationResult(
                images=[], seed=0, duration_seconds=0.0, model_id=self.model_id
            )

    m = FakeModel(model_id="fake")
    assert m.is_loaded is False
    m.load()
    assert m.is_loaded is True
    m.unload()
    assert m.is_loaded is False


def test_generation_result_default_extra_is_empty_dict():
    """GenerationResult.extra should default to {} (not None) to avoid KeyError pitfalls."""
    r = GenerationResult(images=[], seed=0, duration_seconds=0.0, model_id="m")
    assert r.extra == {}
