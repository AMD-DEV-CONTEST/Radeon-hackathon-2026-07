from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import torch
from PIL import Image

from colorgraph.agent.scene_understanding import LocalSceneAnalyzer
from colorgraph.vision.model_lifecycle import (
    ContentTensorCache,
    ModelCacheKey,
    ModelLifecycleCache,
    TorchModelResource,
    clear_inference_caches,
    torch_model_state_sha256,
)


def _key(name: str) -> ModelCacheKey:
    return ModelCacheKey(
        family="test",
        model_id=name,
        device="cpu",
        dtype="float32",
    )


def test_model_lifecycle_cache_evicts_idle_lru_and_preserves_active_lease() -> None:
    unloaded: list[str] = []
    cache = ModelLifecycleCache[str](
        maximum_entries=1,
        maximum_estimated_bytes=10,
    )
    first = cache.acquire(
        _key("first"),
        loader=lambda: "first",
        estimate_bytes=lambda _: 8,
        unload=unloaded.append,
    )
    assert first.__enter__() == "first"
    second = cache.acquire(
        _key("second"),
        loader=lambda: "second",
        estimate_bytes=lambda _: 8,
        unload=unloaded.append,
    )
    assert second.__enter__() == "second"
    assert cache.stats()["entries"] == 2

    second.close()
    assert unloaded == ["second"]
    assert cache.stats()["entries"] == 1
    first.close()
    assert cache.release_idle() == 1
    assert unloaded == ["second", "first"]
    assert cache.stats()["entries"] == 0


def test_model_lifecycle_cache_enforces_byte_budget_and_reports_release_reason() -> None:
    unloaded: list[str] = []
    cache = ModelLifecycleCache[str](
        maximum_entries=3,
        maximum_estimated_bytes=10,
    )
    with cache.acquire(
        _key("first"),
        loader=lambda: "first",
        estimate_bytes=lambda _: 6,
        unload=unloaded.append,
    ):
        pass
    with cache.acquire(
        _key("second"),
        loader=lambda: "second",
        estimate_bytes=lambda _: 6,
        unload=unloaded.append,
    ):
        assert unloaded == ["first"]

    assert cache.stats()["evictions"] == 1
    assert cache.release_idle() == 1
    assert unloaded == ["first", "second"]
    assert cache.stats()["releases"] == 1


def test_content_tensor_cache_is_bounded_and_returns_isolated_values() -> None:
    cache = ContentTensorCache(maximum_entries=1)
    original = torch.tensor([1.0, 2.0])
    cache.put("first", original)
    restored = cache.get("first")
    assert restored is not None
    restored[0] = 99
    assert cache.get("first").tolist() == [1.0, 2.0]

    cache.put("second", torch.tensor([3.0]))

    assert cache.get("first") is None
    assert cache.get("second").tolist() == [3.0]
    assert cache.stats()["evictions"] == 1


def test_torch_model_state_hash_is_stable_and_changes_with_loaded_weights() -> None:
    first = torch.nn.Linear(3, 2)
    second = torch.nn.Linear(3, 2)
    first.register_buffer("revision_marker", torch.tensor(1, dtype=torch.int64))
    second.register_buffer("revision_marker", torch.tensor(1, dtype=torch.int64))
    second.load_state_dict(first.state_dict())

    initial = torch_model_state_sha256(first)

    assert initial == torch_model_state_sha256(first)
    assert initial == torch_model_state_sha256(second)
    with torch.no_grad():
        second.weight[0, 0] += 1
    assert initial != torch_model_state_sha256(second)


class _FakeBackend:
    def __init__(self) -> None:
        self.torch_device = torch.device("cpu")
        self.info = SimpleNamespace(runtime="cpu")
        self.empty_cache_calls = 0

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


class _FakeProcessor:
    def __init__(self) -> None:
        self.image_batches = 0
        self.text_batches = 0

    def __call__(
        self,
        *,
        images=None,
        text=None,
        return_tensors: str,
        padding: bool = False,
    ):
        assert return_tensors == "pt"
        if images is not None:
            self.image_batches += 1
            values = []
            for image in images:
                rgb = torch.tensor(image.resize((1, 1)).getpixel((0, 0))).float()
                values.append(rgb)
            return {"pixel_values": torch.stack(values)}
        assert text is not None
        self.text_batches += 1
        return {
            "input_ids": torch.arange(len(text), dtype=torch.float32).view(-1, 1)
        }


class _FakeModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(_commit_hash="fake-revision")
        self.logit_scale = torch.tensor(0.0)
        self.image_calls = 0
        self.text_calls = 0

    def parameters(self):
        return iter(())

    def buffers(self):
        return iter(())

    def to(self, *args, **kwargs):
        return self

    def get_image_features(self, *, pixel_values: torch.Tensor) -> torch.Tensor:
        self.image_calls += 1
        return pixel_values + 1

    def get_text_features(self, *, input_ids: torch.Tensor) -> torch.Tensor:
        self.text_calls += 1
        index = input_ids[:, 0].long() % 3
        return torch.nn.functional.one_hot(index, num_classes=3).float() + 0.1


def test_scene_analyzer_caches_text_and_content_addressed_image_embeddings(
    tmp_path,
    monkeypatch,
) -> None:
    clear_inference_caches()
    backend = _FakeBackend()
    processor = _FakeProcessor()
    model = _FakeModel()
    analyzer = LocalSceneAnalyzer(backend, model_id="fake/cache-test")
    monkeypatch.setattr(
        analyzer,
        "_load_resource",
        lambda: TorchModelResource(processor=processor, model=model),
    )
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (20, 40, 80)).save(frame)

    first = analyzer.embed_images([frame])
    second = analyzer.embed_images([frame])
    analyzer.analyze(frame)
    analyzer.analyze(frame)

    assert torch.equal(first, second)
    assert model.image_calls == 1
    assert processor.image_batches == 1
    assert model.text_calls == 4
    assert processor.text_batches == 4

    Image.new("RGB", (8, 8), (80, 40, 20)).save(frame)
    changed = analyzer.embed_images([frame])

    assert model.image_calls == 2
    assert not torch.equal(first, changed)
    assert analyzer.release_model() == 1
    assert backend.empty_cache_calls == 1
