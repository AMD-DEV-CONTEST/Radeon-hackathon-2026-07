import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))

from rocm_pipeline import (
    VALIDATED_MODEL_ID,
    VALIDATED_MODEL_REVISION,
    RocmCampaignPipeline,
    RocmPipelineConfig,
    RocmPipelineError,
)


def test_configuration_defaults_to_validated_sdxl(monkeypatch):
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_REVISION", raising=False)
    config = RocmPipelineConfig.from_environment()
    assert config.model_id == VALIDATED_MODEL_ID
    assert config.model_revision == VALIDATED_MODEL_REVISION


def test_real_pipeline_never_generates_before_loading(tmp_path):
    config = RocmPipelineConfig(
        model_id="local-test-model",
        model_revision=None,
        model_cache_dir=tmp_path,
        output_dir=tmp_path / "outputs",
        device="cuda",
        dtype="float16",
        local_files_only=True,
        ip_adapter_model_id=None,
        controlnet_model_id=None,
    )
    pipeline = RocmCampaignPipeline(config)
    image = tmp_path / "input.png"
    image.write_bytes(b"test")
    with pytest.raises(RocmPipelineError, match=r"load_model\(\)"):
        pipeline.generate_ad_image(image, {}, "Instagram Square")


class FakeGenerator:
    def __init__(self, device):
        self.device = device

    def manual_seed(self, seed):
        self.seed = seed
        return self


class FakeCuda:
    def reset_peak_memory_stats(self):
        pass

    def synchronize(self):
        pass

    def max_memory_allocated(self, index):
        return 123

    def max_memory_reserved(self, index):
        return 456

    def get_device_name(self, index):
        return "AMD Radeon Test Device"


class FakePipeline:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(images=[Image.new("RGB", (768, 768), "red")])


def test_validated_generation_path_is_testable_without_weights(tmp_path):
    config = RocmPipelineConfig(
        model_id=VALIDATED_MODEL_ID,
        model_revision=VALIDATED_MODEL_REVISION,
        model_cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "outputs",
        device="cuda",
        dtype="float16",
        local_files_only=True,
        ip_adapter_model_id=None,
        controlnet_model_id=None,
    )
    fake_pipeline = FakePipeline()
    fake_torch = SimpleNamespace(
        cuda=FakeCuda(),
        Generator=FakeGenerator,
        __version__="2.9.1-test",
        version=SimpleNamespace(hip="7.2-test"),
    )
    pipeline = RocmCampaignPipeline(config, torch_module=fake_torch)
    pipeline._pipeline = fake_pipeline

    image = tmp_path / "input.png"
    Image.new("RGB", (256, 256), "blue").save(image)
    result = pipeline.generate_ad_image(image, {}, "Instagram Square")

    assert result["mode"] == "rocm"
    assert result["model_revision"] == VALIDATED_MODEL_REVISION
    assert result["product_preservation_validated"] is False
    assert result["peak_allocated_gpu_memory_bytes"] == 123
    assert Path(result["image_path"]).is_file()
    assert fake_pipeline.kwargs["num_inference_steps"] == 15
