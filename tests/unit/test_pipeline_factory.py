"""Unit tests for src.core.pipeline_factory."""
import pytest

from src.core.base_model import BaseModel, GenerationRequest, GenerationResult
from src.core import pipeline_factory as factory


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot the registry around each test so decorator registrations don't leak."""
    original = dict(factory._REGISTRY)
    yield
    factory._REGISTRY.clear()
    factory._REGISTRY.update(original)


def test_unknown_key_raises_with_helpful_message():
    """create_model('nope') should tell the user what's available."""
    with pytest.raises(KeyError) as ei:
        factory.create_model("nope")
    msg = str(ei.value)
    assert "Unknown model" in msg
    assert "Registered" in msg


def test_register_and_create():
    """register_model decorator should make a class available via create_model."""

    @factory.register_model("fake_test_model")
    class FakeModel(BaseModel):
        def load(self) -> None:
            self._loaded = True

        def generate(self, request):
            return GenerationResult(
                images=[], seed=0, duration_seconds=0.0, model_id=self.model_id
            )

    assert "fake_test_model" in factory.available_models()
    instance = factory.create_model("fake_test_model", model_id="fake_test_model")
    assert isinstance(instance, FakeModel)
    assert instance.model_id == "fake_test_model"
    assert instance.model_key == "fake_test_model"  # type: ignore[attr-defined]


def test_register_overwrite_warns(caplog):
    """Re-registering a key should overwrite and emit a warning (no silent shadowing)."""

    @factory.register_model("dup_key")
    class A(BaseModel):
        def load(self) -> None: ...
        def generate(self, request): ...

    with caplog.at_level("WARNING"):
        factory.register_model("dup_key")(type("B", (BaseModel,), {
            "load": lambda self: None,
            "generate": lambda self, r: None,
        }))
    assert any("overwriting" in r.message for r in caplog.records)
