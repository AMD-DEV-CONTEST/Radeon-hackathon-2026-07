"""Smoke tests for the backend pipeline."""
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
from PIL import Image

from inference.pipeline import AnalysisPipeline
from models.classifier import RADDINOHead
from models.vision_encoder import RADDINOVisionEncoder

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore


def _create_temporary_head() -> str:
    """Create a random RAD-DINO classification head for testing."""
    encoder = RADDINOVisionEncoder(device="cpu")
    head = RADDINOHead(encoder.hidden_size, 8)
    path = os.path.join(tempfile.gettempdir(), f"test_classifier_head_{uuid.uuid4().hex}.pt")
    torch.save({"head": head.state_dict()}, path)
    return path


if pytest is not None:
    @pytest.fixture(scope="session")
    def classifier_head_path():
        path = _create_temporary_head()
        os.environ["CLASSIFIER_HEAD"] = path
        yield path
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def test_pipeline():
    """Default pipeline uses TorchXRayVision for real predictions."""
    # Ensure no CLASSIFIER_HEAD so we exercise the default TorchXRayVision backend.
    old_head = os.environ.pop("CLASSIFIER_HEAD", None)
    try:
        device = "cuda" if os.environ.get("FORCE_CUDA", "0") == "1" else "cpu"
        pipeline = AnalysisPipeline(device=device)
        img = Image.new("RGB", (512, 512), color=(128, 128, 128))
        result = pipeline.analyze(img)
        assert result.image_id
        assert len(result.findings) > 0
        assert "FINDINGS" in result.report.upper() or "IMPRESSION" in result.report.upper()
        assert result.mask is not None
        print("Findings:", [(f.label, f.confidence) for f in result.findings])
        print("Report:\n", result.report)
        print("Mask shape:", result.mask.shape)

        answer = pipeline.chat(result.report, result.findings, "Why did you mention cardiomegaly?")
        print("Chat:", answer)
    finally:
        if old_head is not None:
            os.environ["CLASSIFIER_HEAD"] = old_head


def test_raddino_pipeline(classifier_head_path=None):
    """Test the RAD-DINO backend when a head checkpoint is provided."""
    if classifier_head_path is None:
        classifier_head_path = _create_temporary_head()
        os.environ["CLASSIFIER_HEAD"] = classifier_head_path
        cleanup = True
    else:
        cleanup = False

    try:
        device = "cuda" if os.environ.get("FORCE_CUDA", "0") == "1" else "cpu"
        pipeline = AnalysisPipeline(device=device)
        img = Image.new("RGB", (512, 512), color=(128, 128, 128))
        result = pipeline.analyze(img)
        assert len(result.findings) > 0
        assert result.mask is not None
    finally:
        if cleanup:
            os.remove(classifier_head_path)
            os.environ.pop("CLASSIFIER_HEAD", None)


def test_benchmark():
    device = "cpu"
    pipeline = AnalysisPipeline(device=device)
    benchmarks = pipeline.benchmark_report("Explain findings", max_tokens=32)
    print("Benchmarks:", benchmarks)


def test_generate_report():
    device = "cpu"
    pipeline = AnalysisPipeline(device=device)
    structured = {
        "modality": "Chest X-ray",
        "findings": [
            {"name": "cardiomegaly", "confidence": 0.96},
            {"name": "pleural_effusion", "confidence": 0.91},
        ],
    }
    report_result = pipeline.generate_report(structured)
    assert report_result.report
    assert "FINDINGS" in report_result.report.upper() or "IMPRESSION" in report_result.report.upper()


def test_gradcam_pipeline():
    """Test the Grad-CAM evidence path with TorchXRayVision backend."""
    old_head = os.environ.pop("CLASSIFIER_HEAD", None)
    try:
        device = "cuda" if os.environ.get("FORCE_CUDA", "0") == "1" else "cpu"
        pipeline = AnalysisPipeline(device=device)
        img = Image.new("RGB", (512, 512), color=(128, 128, 128))
        result = pipeline.analyze(img, evidence_type="gradcam")
        assert result.mask is not None
        # Grad-CAM is now computed for every predicted pathology class.
        assert len(result.localization_maps) >= 1
        for loc in result.localization_maps:
            assert loc.heatmap is not None
            assert loc.heatmap.shape == (512, 512)
    finally:
        if old_head is not None:
            os.environ["CLASSIFIER_HEAD"] = old_head


if __name__ == "__main__":
    test_pipeline()
    test_gradcam_pipeline()
    test_benchmark()
    test_generate_report()
    # Also run RAD-DINO backend smoke test.
    path = _create_temporary_head()
    os.environ["CLASSIFIER_HEAD"] = path
    try:
        test_raddino_pipeline(path)
    finally:
        os.remove(path)
        os.environ.pop("CLASSIFIER_HEAD", None)
